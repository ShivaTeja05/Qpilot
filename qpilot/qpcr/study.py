"""Run one qPCR study end to end: an RDML file in; results, Decision Cards and the grid out.

This is the one place where the qPCR plugin meets the domain-agnostic core:

1. curves (LinRegPCR on every plate) -> log2 quantities -> geNorm -> the decision space
   (:class:`qpilot.qpcr.space.QpcrSpace`);
2. ``core.robustness`` evaluates every cell of the space (186 analyses on the demo) and
   summarises each gene: primary conclusion, how often it holds, which choices flip it;
3. ``core.decisions`` turns the three analysis choices into ranked Decision Cards and applies the
   escalation rule (a choice that can flip a conclusion is a human decision);
4. ``qpcr.confidence_checks`` and ``core.confidence`` grade every gene;
5. every number that prose may cite is registered as a fact (``core.facts``) under the id
   convention ``f_<metric>_<slug>_<context>``, e.g. ``f_fc_odc1_hmbs``.

Deterministic: the same file and settings give byte-identical output, which ``qpilot rerun``
relies on. No model is called and nothing touches the network.
"""

from __future__ import annotations

import hashlib
import re
import statistics
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from qpilot.core import robustness
from qpilot.core.confidence import grade
from qpilot.core.decisions import CardSpec, OptionSpec, build_cards, card_impact
from qpilot.core.facts import FactRegistry, slug
from qpilot.core.store import atomic_write, dump_json
from qpilot.qpcr.confidence_checks import START_LEVEL, checks_for, mde_fold, upgrade_rule
from qpilot.qpcr.contrast import DEFAULT_RULE, ConclusionRule
from qpilot.qpcr.curves import DEMO_EXPERIMENT, REFERENCE_TARGETS, CurveSettings, analyse_study
from qpilot.qpcr.design import DEMO_GROUP_VAR, DEMO_MARKER, GroupSpec, design_summary
from qpilot.qpcr.quant import Undetermined, log2_matrix
from qpilot.qpcr.refgenes import genorm
from qpilot.qpcr.space import DEFAULT_CUTS, DEFAULT_UNDETERMINED, QpcrSpace
from qpilot.schemas import (
    Autonomy,
    DecisionCard,
    Fact,
    GeneRobustness,
    GenormResult,
    Grade,
    StudyResult,
)

HEADLINE_GENES: tuple[str, ...] = ("ODC1", "BIRC5", "NTRK1", "NM23A")
HOLDS_LOW = 0.80  # "holds in fewer than 80 %" is counted in f_n_hold_lt_80
FC_FMT = "{:.2g}"
TIMES = "×"
_NUMBER_WORDS = {2: "two", 3: "three", 4: "four", 5: "five", 6: "six", 7: "seven", 8: "eight"}


@dataclass(frozen=True)
class StudySettings:
    """Every choice that shapes a study's output; the defaults reproduce the demo analysis."""

    experiment_id: str = DEMO_EXPERIMENT
    candidates: tuple[str, ...] = REFERENCE_TARGETS
    marker: str = DEMO_MARKER
    group_var: str = DEMO_GROUP_VAR
    cut: float = 0.15
    cuts: tuple[float, ...] = DEFAULT_CUTS
    undetermined: tuple[Undetermined, ...] = DEFAULT_UNDETERMINED
    headline: tuple[str, ...] = HEADLINE_GENES
    rule: ConclusionRule = DEFAULT_RULE
    curves: CurveSettings = field(default_factory=CurveSettings)
    autonomy: Autonomy = "suggest"

    @property
    def marker_label(self) -> str:
        """The marker gene's name without its assay suffix: ``MYCN(4)`` -> ``MYCN``."""
        return re.sub(r"\(.*\)$", "", self.marker).strip() or self.marker


def run_study(
    rdml_path: str | Path,
    settings: StudySettings | None = None,
    *,
    cache_dir: str | Path | None = None,
) -> tuple[StudyResult, list[DecisionCard], pd.DataFrame]:
    """Analyse one RDML file.

    Args:
        rdml_path: The instrument export (RDML 1.0–1.4, plain or zipped).
        settings: Analysis choices; defaults reproduce the demo analysis.
        cache_dir: Curve-cache directory (default ``$QPILOT_CACHE_DIR`` or ``~/.cache/qpilot``).

    Returns:
        ``(result, cards, grid)``: the study result with confidence grades and facts, the ranked
        Decision Cards, and the robustness grid (one row per analysis x gene).
    """
    settings = settings or StudySettings()
    path = Path(rdml_path)
    curves = analyse_study(
        path, settings.experiment_id, settings.candidates, settings.curves, cache_dir=cache_dir
    )
    return study_from_curves(curves, _sha256(path), settings)


def study_from_curves(
    curves: pd.DataFrame, input_sha256: str, settings: StudySettings | None = None
) -> tuple[StudyResult, list[DecisionCard], pd.DataFrame]:
    """Everything after curve analysis, on the per-well table (see :func:`run_study`)."""
    settings = settings or StudySettings()
    matrix = log2_matrix(curves)
    stability = genorm(matrix, settings.candidates)
    space = QpcrSpace(
        matrix,
        stability,
        GroupSpec(settings.marker, settings.cut, settings.candidates, settings.group_var),
        candidates=settings.candidates,
        cuts=settings.cuts,
        undetermined=settings.undetermined,
        rule=settings.rule,
    )
    high, rest = space.groups(settings.cut)
    grid = robustness.run_grid(space)
    summary = robustness.summary(grid, space)
    fragility = robustness.fragility(grid, space)
    unknown = curves[curves["sample_type"] == "unkn"]
    base = StudyResult(
        study_id=input_sha256[:12],
        input_sha256=input_sha256,
        n_plates=int(curves["run_id"].nunique()),
        n_reactions=len(curves),
        n_samples=len(matrix),
        design=design_summary(high, rest, space.design),
        genorm=stability,
        contrasts=space.evaluate(space.primary),
        robustness=summary,
        efficiency=_efficiency(curves),
        conclusion_rule=settings.rule.as_dict(),
    )
    confidence = {gene: _grade(gene, base, fragility) for gene in space.items}
    headline = [gene for gene in settings.headline if gene in space.items]
    counts = {"n_undetermined": int(unknown["n0"].isna().sum()), "n_unknown_wells": len(unknown)}
    specs = _card_specs(space, stability, summary, settings, headline, counts)
    cards = build_cards(space, summary, specs, headline, settings.autonomy)
    facts = _facts(base, confidence, cards, space, settings, headline, counts)
    result = base.model_copy(update={"confidence": confidence, "facts": facts.as_dict()})
    return result, cards, grid


def write_outputs(
    result: StudyResult, cards: list[DecisionCard], grid: pd.DataFrame, out_dir: str | Path
) -> dict[str, Path]:
    """Write ``results.json``, ``cards.json``, ``facts.json`` and ``grid.csv`` atomically."""
    directory = Path(out_dir)
    directory.mkdir(parents=True, exist_ok=True)
    texts = {
        "results.json": dump_json(result.model_dump(mode="json")),
        "cards.json": dump_json([card.model_dump(mode="json") for card in cards]),
        "facts.json": dump_json(
            {fid: f.model_dump(mode="json") for fid, f in result.facts.items()}
        ),
        "grid.csv": robustness.to_csv_frame(grid).to_csv(
            index=False, float_format="%.10g", lineterminator="\n"
        ),
    }
    paths = {}
    for name, text in texts.items():
        paths[name] = directory / name
        atomic_write(paths[name], text)
    return paths


# ---------- pieces ----------


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 16), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _efficiency(curves: pd.DataFrame) -> dict[str, float]:
    """Each gene's mean PCR efficiency (median over its plates)."""
    per_gene = curves.dropna(subset=["eff_target"]).groupby("target")["eff_target"].median()
    return {str(gene): float(value) for gene, value in per_gene.sort_index().items()}


def _grade(gene: str, result: StudyResult, fragility: dict[str, int]) -> Grade:
    checks = checks_for(gene, result, fragility)
    holds = result.robustness[gene].holds
    return grade(
        START_LEVEL,
        checks,
        upgrade_rule(result.contrasts[gene], holds),
        min_flip_changes=int(fragility[gene]),
    )


def _pct(cut: float) -> int:
    return round(cut * 100)


def _refs_label(refs: tuple[str, ...], candidates: tuple[str, ...]) -> str:
    if refs == candidates:
        return f"Recommended set (all {_NUMBER_WORDS.get(len(refs), str(len(refs)))})"
    return f"Recommended set ({', '.join(refs)})"


def _ref_options(
    space: QpcrSpace, stability: GenormResult, candidates: tuple[str, ...]
) -> list[tuple[OptionSpec, str]]:
    """(option, fact context) for the reference-set card, recommended first."""
    recommended = tuple(space.primary["refs"])
    label = _refs_label(recommended, candidates)
    options = [(OptionSpec(id="recommended", label=label, value=recommended), "recommended")]
    top2 = tuple(gene for gene in candidates if gene in stability.order[:2])
    if top2 != recommended:
        label = f"Top two by stability ({', '.join(stability.order[:2])})"
        options.append((OptionSpec(id="top2", label=label, value=top2), "top2"))
    for gene in candidates:
        if (gene,) != recommended:
            option = OptionSpec(id=f"{slug(gene)}_alone", label=f"{gene} alone", value=(gene,))
            options.append((option, slug(gene)))
    return options


def _card_specs(
    space: QpcrSpace,
    stability: GenormResult,
    summary: dict[str, GeneRobustness],
    settings: StudySettings,
    headline: Sequence[str],
    counts: dict[str, int],
) -> list[CardSpec]:
    """The three cards the qPCR plugin asks the core to build (the core adds impact and rank)."""

    def option_facts(contexts: list[str]) -> list[str]:
        return [f"f_fc_{slug(gene)}_{ctx}" for ctx in contexts for gene in headline]

    ref_options = _ref_options(space, stability, settings.candidates)
    lead = [slug(headline[0])] if headline else []
    refset_facts = ["f_order_1", "f_m_1", "f_worst_ref"]
    refset_facts += [f"f_fc_{s}_{ctx}" for s in lead for ctx in ("recommended", "worst")]
    refset_facts += ["f_n_flipped_refset", "f_n_genes"]
    refset_facts += option_facts([ctx for _, ctx in ref_options])

    cut_ids = [f"cut_{_pct(cut)}" for cut in settings.cuts]
    undetermined_flips = card_impact(summary, "undetermined")["flips"]
    return [
        CardSpec(
            card_id="card_refset",
            kind="reference_set",
            dimension="refs",
            options=[option for option, _ in ref_options],
            recommended="recommended",
            rationale_template="refset_v1",
            evidence={
                "genorm_M": stability.M_initial,
                "genorm_order": stability.order,
                "genorm_V": stability.V,
                "cutoff_M": stability.cutoff_M,
                "cutoff_V": stability.cutoff_V,
            },
            facts=list(dict.fromkeys(refset_facts)),
        ),
        CardSpec(
            card_id="card_cutoff",
            kind="group_cutoff",
            dimension="cut",
            options=[
                OptionSpec(
                    id=cid,
                    label=f"Top {_pct(cut)} % by {settings.marker_label} expression",
                    value=cut,
                )
                for cid, cut in zip(cut_ids, settings.cuts, strict=True)
            ],
            recommended=f"cut_{_pct(settings.cut)}",
            rationale_template="cutoff_v1",
            evidence={
                "cuts": list(settings.cuts),
                "n_hi_by_cut": {
                    cid: len(space.groups(cut)[0])
                    for cid, cut in zip(cut_ids, settings.cuts, strict=True)
                },
            },
            facts=["f_n_flipped_cutoff", "f_n_genes", *option_facts(cut_ids)],
        ),
        CardSpec(
            card_id="card_undetermined",
            kind="undetermined",
            dimension="undetermined",
            options=[
                OptionSpec(id="drop", label="Drop empty wells", value="drop"),
                OptionSpec(id="cap", label="Count empty wells as very low (cap)", value="cap"),
            ],
            recommended="drop",
            rationale_template="undetermined_v1" if undetermined_flips else "undetermined_auto_v1",
            evidence=dict(counts),
            facts=[
                "f_n_flipped_undetermined",
                "f_n_undetermined",
                "f_n_unknown_wells",
                "f_pct_undetermined",
                *option_facts(["drop", "cap"]),
            ],
        ),
    ]


def _facts(
    result: StudyResult,
    confidence: dict[str, Grade],
    cards: list[DecisionCard],
    space: QpcrSpace,
    settings: StudySettings,
    headline: Sequence[str],
    counts: dict[str, int],
) -> FactRegistry:
    """Every number that prose may cite, under the id convention in the module docstring."""
    registry = FactRegistry()

    def add(fid: str, value: float | int | str, fmt: str = "{}", unit: str = "", path: str = ""):
        if fid in registry:  # the same number reached by two routes, e.g. a card's primary option
            if registry.get(fid).value != value:
                raise ValueError(f"fact {fid} has two different values")
            return
        registry.add(Fact(id=fid, value=value, fmt=fmt, unit=unit, path=path))

    items = space.items
    flipped = {dim: robustness.flipped_by(result.robustness, dim) for dim in space.dimensions}
    study = {
        "f_n_plates": result.n_plates,
        "f_n_reactions": result.n_reactions,
        "f_n_samples": result.n_samples,
        "f_n_hi": result.design.n_hi,
        "f_n_lo": result.design.n_lo,
        "f_n_cells": robustness.n_cells(space),
        "f_n_genes": len(items),
        "f_n_flipped_refset": len(flipped["refs"]),
        "f_n_flipped_cutoff": len(flipped["cut"]),
        "f_n_flipped_undetermined": len(flipped["undetermined"]),
        "f_n_hold_lt_80": sum(result.robustness[gene].holds < HOLDS_LOW for gene in items),
        **{f"f_{key}": value for key, value in counts.items()},
    }
    for fid, value in study.items():
        add(fid, int(value), path="study")
    share = counts["n_undetermined"] / counts["n_unknown_wells"] if counts["n_unknown_wells"] else 0
    add("f_pct_undetermined", 100 * share, "{:.1f}", "%", "study")
    if result.efficiency:
        median = statistics.median(result.efficiency.values())
        add("f_eff_median", float(median), "{:.2f}", "", "efficiency")
    for gene, value in result.efficiency.items():
        add(f"f_eff_{slug(gene)}", value, "{:.2f}", "", f"efficiency.{gene}")

    stability = result.genorm
    for i, ref in enumerate(stability.order, start=1):
        add(f"f_order_{i}", ref, path=f"genorm.order[{i - 1}]")
        add(f"f_m_{i}", float(stability.M_initial[ref]), "{:.2f}", "", f"genorm.M_initial.{ref}")
    for ref, value in stability.M_initial.items():
        add(f"f_m_{slug(ref)}", float(value), "{:.2f}", "", f"genorm.M_initial.{ref}")
    for key, value in stability.V.items():  # "V2/3" -> f_v_2_3
        add(f"f_v_{slug(key[1:])}", float(value), "{:.2f}", "", f"genorm.V.{key}")
    add("f_worst_ref", stability.order[-1], path="genorm.order[-1]")

    for gene in items:
        s, contrast, graded = slug(gene), result.contrasts[gene], confidence[gene]
        add(f"f_fc_{s}_recommended", contrast.fc, FC_FMT, TIMES, f"contrasts.{gene}.fc")
        add(f"f_ci_lo_{s}_recommended", contrast.ci[0], FC_FMT, TIMES, f"contrasts.{gene}.ci[0]")
        add(f"f_ci_hi_{s}_recommended", contrast.ci[1], FC_FMT, TIMES, f"contrasts.{gene}.ci[1]")
        add(f"f_p_{s}_recommended", contrast.p, "{:.2g}", "", f"contrasts.{gene}.p")
        add(f"f_holds_{s}", result.robustness[gene].holds, "{:.0%}", "", f"robustness.{gene}.holds")
        add(f"f_level_{s}", graded.level, path=f"confidence.{gene}.level")
        flips = int(graded.min_flip_changes or 0)
        add(f"f_min_flip_{s}", flips, path=f"confidence.{gene}.min_flip_changes")
        add(f"f_mde_fold_{s}", mde_fold(contrast), FC_FMT, TIMES, f"confidence.{gene}.mde")

    for card in cards:
        for option in card.options:
            context = option.id.removesuffix("_alone")
            for gene, contrast in option.per_gene.items():
                path = f"cards.{card.id}.{option.id}.{gene}.fc"
                add(f"f_fc_{slug(gene)}_{context}", contrast.fc, FC_FMT, TIMES, path)
        for option_id, n_hi in card.evidence.get("n_hi_by_cut", {}).items():
            add(f"f_n_hi_{option_id}", int(n_hi), path=f"cards.{card.id}.evidence.n_hi_by_cut")
    worst = slug(stability.order[-1])
    for gene in headline:
        source = f"f_fc_{slug(gene)}_{worst}"
        if source in registry:
            path = f"cards.card_refset.{worst}_alone.{gene}.fc"
            add(f"f_fc_{slug(gene)}_worst", registry.get(source).value, FC_FMT, TIMES, path)
    return registry
