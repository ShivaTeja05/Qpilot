"""Run one qPCR study end to end: an RDML file in; results, Decision Cards and the grid out.

This is the one place where the qPCR plugin meets the domain-agnostic core:

1. curves (LinRegPCR on every plate) -> log2 quantities -> geNorm -> the decision space
   (:class:`qpilot.qpcr.space.QpcrSpace`);
2. ``core.robustness`` evaluates every cell of the space (186 analyses on the demo) and
   summarises each gene: primary conclusion, how often it holds, which choices flip it;
3. ``core.decisions`` turns the analysis choices into ranked Decision Cards and applies the
   escalation rule (a choice that can flip a conclusion is a human decision); the reference-set
   card then gains the flip count by normaliser-set size and the control-gene group-effect check
   (:func:`qpilot.qpcr.refgenes.group_effect`);
4. ``qpcr.confidence_checks`` and ``core.confidence`` grade every gene;
5. every number that prose may cite is registered as a fact (``core.facts``) under the id
   convention ``f_<metric>_<slug>_<context>``, e.g. ``f_fc_odc1_hmbs``.

A study runs from :class:`StudySettings`; :meth:`StudySettings.from_design` turns a confirmed
:class:`~qpilot.schemas_studio.StudyDesign` into settings. ``StudySettings()`` is the demo
analysis, and so is the demo preset (:func:`qpilot.qpcr.designs.vermeulen_design`). Any other
design may take its groups from a sample sheet (no ``cut`` dimension), average technical
replicates per biological unit, exclude or re-type wells, offer several amplification-call
rules (the ``amp_call`` dimension, screened before it enters the grid) and adds the Studio facts:
the usual route to Prism (:mod:`qpilot.qpcr.routes`) and the amp_call screening result.

Deterministic: the same file and settings give byte-identical output, which ``qpilot rerun``
relies on. No model is called and nothing touches the network.
"""

from __future__ import annotations

import hashlib
import re
import statistics
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from qpilot.core import robustness
from qpilot.core.confidence import grade
from qpilot.core.decisions import CardSpec, OptionSpec, build_cards, card_impact
from qpilot.core.facts import FactRegistry, slug
from qpilot.core.store import atomic_write, dump_json
from qpilot.qpcr.amp_call import (
    DEFAULT_AMP_CALLS,
    METHOD_CARD_PATH,
    RECOMMENDED,
    RULES,
    AmpScreen,
    apply_rule,
    screen_amp_call,
)
from qpilot.qpcr.confidence_checks import START_LEVEL, checks_for, mde_fold, upgrade_rule
from qpilot.qpcr.contrast import DEFAULT_RULE, ConclusionRule
from qpilot.qpcr.curves import DEMO_EXPERIMENT, REFERENCE_TARGETS, CurveSettings, analyse_study
from qpilot.qpcr.design import DEMO_GROUP_VAR, DEMO_MARKER, GroupSpec, design_summary
from qpilot.qpcr.designs import (
    HEADLINE_GENES,
    DesignError,
    check_design,
    design_curves,
    design_units,
    is_legacy_design,
    study_key,
    unit_groups,
)
from qpilot.qpcr.quant import EXCLUDED, Undetermined, excluded_cells, log2_matrix
from qpilot.qpcr.refgenes import RefGroupEffect, genorm, group_effect
from qpilot.qpcr.routes import ROUTES, RouteResult, compare_routes
from qpilot.qpcr.space import DEFAULT_CUTS, DEFAULT_UNDETERMINED, QpcrSpace
from qpilot.schemas import (
    Autonomy,
    DecisionCard,
    DesignSummary,
    Fact,
    GeneRobustness,
    GenormResult,
    Grade,
    StudyResult,
)
from qpilot.schemas_studio import StudyDesign

HOLDS_LOW = 0.80  # "holds in fewer than 80 %" is counted in f_n_hold_lt_80
FC_FMT = "{:.2g}"
COUNT_FMT = "{:,}"  # 24576 -> 24,576
TIMES = "×"
_NUMBER_WORDS = {2: "two", 3: "three", 4: "four", 5: "five", 6: "six", 7: "seven", 8: "eight"}
NOT_RECOMMENDED_NOTE = (
    "MIQE recommends normalising to more than one validated reference gene; a single gene is "
    "what a ΔΔCt spreadsheet does"
)
GENORM_NOTE = (
    "geNorm M ranks stability across all samples; it cannot show whether a control gene differs "
    "between the groups. The pairwise ratios below check that."
)
GROUPS_NOTE = "groups from the confirmed design"
AMP_CALL_TITLE = "Which curves count as amplified"
_REFSET_EXTRA_FACTS = (
    "f_n_flipped_refset_min3",
    "f_n_flipped_refset_single_only",
    "f_ref_pair_top",
    "f_ref_ratio_top",
    "f_ref_ratio_top_p",
    "f_n_ref_pairs_flagged",
    "f_n_ref_pairs",
    "f_ref_flag_fold",
)


class NGuardError(ValueError):
    """A comparison group has fewer than two biological units, so no p-value can be given."""


@dataclass(frozen=True)
class StudySettings:
    """Every choice that shapes a study's output; the defaults reproduce the demo analysis.

    ``design`` is the confirmed design for anything but the legacy demo analysis (``None``
    then); ``amp_calls`` are the options of the amplification-call dimension, primary first
    (one option: no dimension); ``studio_facts`` adds the Studio facts (the routes to Prism and
    the amp_call screening), which the legacy output does not carry.
    """

    experiment_id: str | None = DEMO_EXPERIMENT
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
    amp_calls: tuple[str, ...] = DEFAULT_AMP_CALLS
    design: StudyDesign | None = None
    studio_facts: bool = False

    @property
    def marker_label(self) -> str:
        """The marker gene's name without its assay suffix: ``MYCN(4)`` -> ``MYCN``."""
        return re.sub(r"\(.*\)$", "", self.marker).strip() or self.marker

    @property
    def groups_mode(self) -> bool:
        """True when the groups come from the design (no marker gene, no ``cut`` dimension)."""
        return self.design is not None and self.design.mode == "groups"

    @classmethod
    def from_design(cls, design: StudyDesign) -> StudySettings:
        """Settings that run a confirmed design.

        The demo preset (:func:`qpilot.qpcr.designs.vermeulen_design`) gives exactly
        ``StudySettings()``, so its output is the legacy output byte for byte. Any other design
        is carried in ``design`` and switches the Studio facts on. Control-gene candidates are
        ``reference_candidates``, or (when that is empty) the targets whose role is ``ref``,
        sorted by name.

        Raises:
            DesignError: The design breaks a rule :func:`qpilot.qpcr.designs.check_design`
                checks.
        """
        check_design(design)
        legacy = is_legacy_design(design)
        candidates = tuple(design.reference_candidates) or tuple(
            sorted(t for t, target in design.targets.items() if target.role == "ref")
        )
        values: dict = {
            "experiment_id": design.experiment_id,
            "candidates": candidates,
            "headline": tuple(design.headline),
            "amp_calls": tuple(design.amp_calls),
            "design": None if legacy else design,
            "studio_facts": not legacy,
        }
        if design.mode == "marker_split" and design.marker_split is not None:
            split = design.marker_split
            values.update(
                marker=split.marker, group_var=split.group_var, cut=split.cut, cuts=split.cuts
            )
        return cls(**values)


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


@dataclass(frozen=True)
class _Inputs:
    """The per-well table as the design says, and the matrices the space is built from."""

    table: pd.DataFrame  # design applied, before any amplification rule
    primary_table: pd.DataFrame  # ... under the primary amplification rule
    units: dict[str, str] | None
    matrix: pd.DataFrame
    alternatives: dict[str, pd.DataFrame]
    excluded: pd.DataFrame | None
    not_amplified: dict[str, int]  # study wells without a value, per amplification rule


def _inputs(curves: pd.DataFrame, settings: StudySettings) -> _Inputs:
    design = settings.design
    if design is None and settings.amp_calls == DEFAULT_AMP_CALLS:  # the legacy path, untouched
        matrix = log2_matrix(curves)
        return _Inputs(curves, curves, None, matrix, {}, None, {})
    table = design_curves(curves, design) if design is not None else curves
    units = (design_units(design) or None) if design is not None else None
    calls = dict(design.well_calls) if design is not None else {}
    tables = {rule_id: apply_rule(table, rule_id, calls) for rule_id in settings.amp_calls}
    primary, *others = settings.amp_calls
    has_exclusions = EXCLUDED in table.columns
    return _Inputs(
        table=table,
        primary_table=tables[primary],
        units=units,
        matrix=log2_matrix(tables[primary], units),
        alternatives={rule_id: log2_matrix(tables[rule_id], units) for rule_id in others},
        excluded=excluded_cells(table, units) if has_exclusions else None,
        not_amplified={rule_id: _counts(t)["n_undetermined"] for rule_id, t in tables.items()},
    )


def _counts(table: pd.DataFrame) -> dict[str, int]:
    """Undetermined and total study wells (wells a person excluded are not counted)."""
    unknown = table[table["sample_type"] == "unkn"]
    if EXCLUDED in unknown.columns:
        unknown = unknown[~unknown[EXCLUDED].astype(bool)]
    return {"n_undetermined": int(unknown["n0"].isna().sum()), "n_unknown_wells": len(unknown)}


def _stability(matrix: pd.DataFrame, candidates: tuple[str, ...]) -> GenormResult:
    """Control-gene stability: geNorm for three or more candidates; no ranking with fewer.

    With two candidates M is the SD of their log2 ratio (the same for both); with one it is
    undefined. Either way every candidate is used and no V is reported.
    """
    if len(candidates) >= 3:
        return genorm(matrix, candidates)
    m: dict[str, float] = {}
    if len(candidates) == 2:
        a, b = candidates
        sd = float((matrix[a] - matrix[b]).dropna().std(ddof=1))
        m = {a: sd, b: sd}
    return GenormResult(M_initial=m, order=list(candidates), V={}, recommended=candidates)


def _design_groups(
    design: StudyDesign, curves: pd.DataFrame, matrix: pd.DataFrame
) -> tuple[tuple[frozenset[str], frozenset[str]], tuple[str, str]]:
    """The compared units of a groups design, measured for every gene."""
    comparison = design.comparison
    names = (comparison.group_a, comparison.group_b)
    by_unit = unit_groups(design)
    compared = {s for s, d in design.samples.items() if d.group in names}
    absent = sorted(compared - set(curves["sample"]))
    if absent:
        raise DesignError(f"samples of the comparison groups not in the data: {absent[:5]}")
    present = set(matrix.index)
    group_a, group_b = (
        frozenset(u for u, g in by_unit.items() if g == name and u in present) for name in names
    )
    return (group_a, group_b), names


def _n_guard(groups: tuple[frozenset[str], frozenset[str]], labels: tuple[str, str]) -> None:
    """Refuse a comparison with fewer than two biological units in a group (never wells)."""
    pairs = zip(labels, groups, strict=True)
    short = [f"{label} has {len(units)}" for label, units in pairs if len(units) < 2]
    if short:
        raise NGuardError(
            "the p-value is withheld because a group has fewer than two biological units "
            f"({'; '.join(short)}); every group needs at least two"
        )


def study_from_curves(
    curves: pd.DataFrame, input_sha256: str, settings: StudySettings | None = None
) -> tuple[StudyResult, list[DecisionCard], pd.DataFrame]:
    """Everything after curve analysis, on the per-well table (see :func:`run_study`).

    Raises:
        NGuardError: A comparison group has fewer than two biological units.
        DesignError: The design does not fit the data (unknown wells or samples).
    """
    settings = settings or StudySettings()
    if not settings.candidates:
        raise DesignError("no control genes: set reference_candidates or mark targets as ref")
    inputs = _inputs(curves, settings)
    matrix = inputs.matrix
    stability = _stability(matrix, settings.candidates)
    groups = labels = None
    if settings.groups_mode:
        groups, labels = _design_groups(settings.design, curves, matrix)
        _n_guard(groups, labels)
    spec = None
    if groups is None:
        spec = GroupSpec(settings.marker, settings.cut, settings.candidates, settings.group_var)
    options = dict(
        candidates=settings.candidates,
        cuts=settings.cuts,
        undetermined=settings.undetermined,
        rule=settings.rule,
        groups=groups,
        amp_call=settings.amp_calls[0],
        excluded=inputs.excluded,
        group_labels=labels,
    )
    space = QpcrSpace(matrix, stability, spec, amp_alternatives=inputs.alternatives, **options)
    screen = None
    if inputs.alternatives:
        dims = space.dimensions["amp_call"]
        screen = screen_amp_call(space.evaluate, space.primary, dims, space.items)
        if not screen.admitted:  # the choice changes nothing that matters: no axis in the grid
            space = QpcrSpace(matrix, stability, spec, **options)
    high, rest = space.groups(settings.cut)
    if groups is None:
        _n_guard((high, rest), (settings.group_var, "rest"))
    grid = robustness.run_grid(space)
    summary = robustness.summary(grid, space)
    fragility = robustness.fragility(grid, space)
    counts = _counts(inputs.primary_table)
    base = StudyResult(
        study_id=study_key(input_sha256, settings.design)[:12],
        input_sha256=input_sha256,
        n_plates=int(curves["run_id"].nunique()),
        n_reactions=len(curves),
        n_samples=len(matrix),
        design=_summary_of_design(high, rest, space, labels),
        genorm=stability,
        contrasts=space.evaluate(space.primary),
        robustness=summary,
        efficiency=_efficiency(curves),
        conclusion_rule=settings.rule.as_dict(),
    )
    confidence = {gene: _grade(gene, base, fragility) for gene in space.items}
    headline = [gene for gene in settings.headline if gene in space.items]
    specs = _card_specs(space, stability, summary, settings, headline, counts)
    if "amp_call" in space.dimensions:
        specs.append(_amp_call_spec(space, grid, summary, headline, inputs.not_amplified))
    cards = build_cards(space, summary, specs, headline, settings.autonomy, grid=grid)
    ref_flips = refset_flip_counts(grid, space, summary)
    ref_effect = group_effect(matrix, settings.candidates, high, rest)
    cards = [_refset_extras(card, ref_flips, ref_effect) for card in cards]
    routes = None
    if settings.studio_facts:
        primary = {gene: summary[gene].conclusion for gene in space.items}
        calls = settings.design.well_calls if settings.design is not None else None
        routes = compare_routes(
            inputs.table,
            inputs.units,
            list(matrix.index),
            high,
            rest,
            space.primary["refs"],
            primary,
            settings.rule,
            calls,
        )
    extras = _Extras(
        withheld=space.withheld,
        screen=screen if settings.studio_facts else None,
        routes=routes,
        groups=labels,
    )
    facts = _facts(base, confidence, cards, space, settings, headline, counts, extras)
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


def _summary_of_design(
    high: frozenset[str],
    rest: frozenset[str],
    space: QpcrSpace,
    labels: tuple[str, str] | None,
) -> DesignSummary:
    """The design record: expression-defined groups, or the confirmed design's two groups.

    With groups from a design there is no cut-off; ``cut`` is 0 there and is not an option.
    """
    if space.design is not None:
        return design_summary(high, rest, space.design)
    return DesignSummary(
        group_var=f"{labels[0]} vs {labels[1]}",
        cut=0.0,
        n_hi=len(high),
        n_lo=len(rest),
        note=GROUPS_NOTE,
        refs_primary=tuple(space.primary["refs"]),
    )


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
    if len(refs) == 1:
        return f"{refs[0]} (the only control gene)"
    if refs == candidates:
        return f"Recommended set (all {_NUMBER_WORDS.get(len(refs), str(len(refs)))})"
    return f"Recommended set ({', '.join(refs)})"


def _ref_options(
    space: QpcrSpace, stability: GenormResult, candidates: tuple[str, ...]
) -> list[tuple[OptionSpec, str]]:
    """(option, fact context) for the reference-set card, recommended first.

    Single-gene options keep their ids (``<gene>_alone``); the card's evidence lists them under
    ``not_recommended`` with the MIQE note instead of changing their labels.
    """
    recommended = tuple(space.primary["refs"])
    label = _refs_label(recommended, candidates)
    options = [(OptionSpec(id="recommended", label=label, value=recommended), "recommended")]
    top2 = tuple(gene for gene in candidates if gene in stability.order[:2])
    top3 = tuple(gene for gene in candidates if gene in stability.order[:3])
    if top3 not in (recommended, top2):
        label = f"Top three by stability ({', '.join(stability.order[:3])})"
        options.append((OptionSpec(id="top3", label=label, value=top3), "top3"))
    if top2 != recommended:
        label = f"Top two by stability ({', '.join(stability.order[:2])})"
        options.append((OptionSpec(id="top2", label=label, value=top2), "top2"))
    for gene in candidates:
        if (gene,) != recommended:
            option = OptionSpec(id=f"{slug(gene)}_alone", label=f"{gene} alone", value=(gene,))
            options.append((option, slug(gene)))
    return options


def _only_varying(grid: pd.DataFrame, space: QpcrSpace, dimension: str) -> pd.DataFrame:
    """Grid rows where every dimension except ``dimension`` is at its primary option."""
    rows = grid
    for name in space.dimensions:
        if name != dimension:
            idx = space.dimensions[name].index(space.primary[name])
            rows = rows[rows[f"{name}{robustness.IDX_SUFFIX}"] == idx]
    return rows


def refset_flip_counts(
    grid: pd.DataFrame, space: QpcrSpace, summary: dict[str, GeneRobustness]
) -> dict[str, int]:
    """How many genes the control-gene choice flips, by the size of the sets compared.

    Uses the grid rows where every other choice is at its primary option, so only the
    control-gene set varies. A gene counts when some subset gives a conclusion different from
    its primary one:

    * ``n_flipped_refs_all``: over every subset (equals the card's ``n_genes_flipped``);
    * ``n_flipped_refs_min3``: over subsets of three or more control genes only, i.e. between
      sets a careful analyst could defend;
    * ``n_flipped_refs_single_only``: flips over all subsets but not over subsets of two or more,
      i.e. only a single control gene (what a ΔΔCt spreadsheet does) changes it.
    """
    rows = _only_varying(grid, space, "refs")
    primary = rows["item"].map({gene: s.conclusion for gene, s in summary.items()})
    changed = rows["conclusion"] != primary
    size = rows["refs"].map(len)

    def flipped(min_size: int) -> set[str]:
        return set(rows.loc[changed & (size >= min_size), "item"])

    flipped_all = flipped(1)
    return {
        "n_flipped_refs_all": len(flipped_all),
        "n_flipped_refs_min3": len(flipped(3)),
        "n_flipped_refs_single_only": len(flipped_all - flipped(2)),
    }


def amp_flip_counts(
    grid: pd.DataFrame, space: QpcrSpace, summary: dict[str, GeneRobustness]
) -> dict[str, int]:
    """Per amplification rule, how many genes change their conclusion when only it changes."""
    rows = _only_varying(grid, space, "amp_call")
    primary = rows["item"].map({gene: s.conclusion for gene, s in summary.items()})
    changed = rows[rows["conclusion"] != primary]
    return {
        rule_id: int(changed.loc[changed["amp_call"] == rule_id, "item"].nunique())
        for rule_id in space.dimensions["amp_call"]
    }


def _refset_extras(
    card: DecisionCard, flips: dict[str, int], effect: RefGroupEffect
) -> DecisionCard:
    """Add the flip count by set size, the group-effect check and the MIQE note to card 1."""
    if card.id != "card_refset":
        return card
    extra = [f for f in _REFSET_EXTRA_FACTS if effect.top is not None or "_top" not in f]
    impact = {
        **card.impact,
        "n_genes_flipped_min3": flips["n_flipped_refs_min3"],
        "n_genes_flipped_single_only": flips["n_flipped_refs_single_only"],
    }
    evidence = {
        **card.evidence,
        "ref_group_effect": effect.as_dict(),
        "genorm_validated": False,
        "genorm_note": GENORM_NOTE,
        "not_recommended": [o.id for o in card.options if o.id.endswith("_alone")],
        "not_recommended_note": NOT_RECOMMENDED_NOTE,
    }
    facts = list(dict.fromkeys([*card.facts, *extra]))
    return card.model_copy(update={"impact": impact, "evidence": evidence, "facts": facts})


def _option_facts(headline: Sequence[str], contexts: list[str]) -> list[str]:
    return [f"f_fc_{slug(gene)}_{ctx}" for ctx in contexts for gene in headline]


def _card_specs(
    space: QpcrSpace,
    stability: GenormResult,
    summary: dict[str, GeneRobustness],
    settings: StudySettings,
    headline: Sequence[str],
    counts: dict[str, int],
) -> list[CardSpec]:
    """The cards the qPCR plugin asks the core to build (the core adds impact and rank).

    The cut-off card exists only when the groups are defined from the data.
    """

    def option_facts(contexts: list[str]) -> list[str]:
        return _option_facts(headline, contexts)

    ref_options = _ref_options(space, stability, settings.candidates)
    lead = [slug(headline[0])] if headline else []
    refset_facts = ["f_order_1", "f_m_1", "f_worst_ref"]
    contexts = ("recommended", "worst")
    if len(settings.candidates) == 1:  # one candidate: no M and no "worst gene alone" option
        refset_facts.remove("f_m_1")
        contexts = ("recommended",)
    refset_facts += [f"f_fc_{s}_{ctx}" for s in lead for ctx in contexts]
    refset_facts += ["f_n_flipped_refset", "f_n_genes"]
    refset_facts += option_facts([ctx for _, ctx in ref_options])

    cut_ids = [f"cut_{_pct(cut)}" for cut in settings.cuts]
    undetermined_flips = card_impact(summary, "undetermined")["flips"]
    specs = [
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
    ]
    if "cut" in space.dimensions:
        specs.append(
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
            )
        )
    specs.append(
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
        )
    )
    return specs


def _amp_call_spec(
    space: QpcrSpace,
    grid: pd.DataFrame,
    summary: dict[str, GeneRobustness],
    headline: Sequence[str],
    not_amplified: Mapping[str, int],
) -> CardSpec:
    """The "Which curves count as amplified" card (only when the dimension is in the grid).

    The recommended option is the primary rule (``linregpcr`` unless a person chose another).
    """
    options = list(space.dimensions["amp_call"])
    flips = amp_flip_counts(grid, space, summary)
    slugs = [slug(rule_id) for rule_id in options]
    return CardSpec(
        card_id="card_amp_call",
        kind="amp_call",
        dimension="amp_call",
        options=[OptionSpec(id=r, label=RULES[r].label, value=r) for r in options],
        recommended=space.primary["amp_call"],
        rationale_template="ampcall_v1",
        evidence={
            "title": AMP_CALL_TITLE,
            "rules": {r: RULES[r].model_dump(mode="json", exclude_none=True) for r in options},
            "recommended_rule": RECOMMENDED,
            "n_flipped_by_rule": flips,
            "n_not_amplified_by_rule": {r: int(not_amplified[r]) for r in options},
            "method_card": METHOD_CARD_PATH,
        },
        facts=[
            "f_n_flipped_amp_call",
            "f_n_genes",
            "f_amp_primary",
            *[f"f_amp_label_{s}" for s in slugs],
            *[f"f_n_flipped_amp_{s}" for s in slugs],
            *[f"f_n_undetermined_amp_{s}" for s in slugs],
            *_option_facts(headline, options),
        ],
    )


@dataclass(frozen=True)
class _Extras:
    """Facts beyond the legacy set: withheld genes, the Studio facts, the design's groups."""

    withheld: Mapping[str, str]
    screen: AmpScreen | None
    routes: Mapping[str, RouteResult] | None
    groups: tuple[str, str] | None


def _facts(
    result: StudyResult,
    confidence: dict[str, Grade],
    cards: list[DecisionCard],
    space: QpcrSpace,
    settings: StudySettings,
    headline: Sequence[str],
    counts: dict[str, int],
    extras: _Extras,
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
        **({"f_n_flipped_cutoff": len(flipped["cut"])} if "cut" in flipped else {}),
        "f_n_flipped_undetermined": len(flipped["undetermined"]),
        **({"f_n_flipped_amp_call": len(flipped["amp_call"])} if "amp_call" in flipped else {}),
        "f_n_hold_lt_80": sum(result.robustness[gene].holds < HOLDS_LOW for gene in items),
        **{f"f_{key}": value for key, value in counts.items()},
    }
    large_counts = {"f_n_reactions", "f_n_unknown_wells"}
    for fid, value in study.items():
        add(fid, int(value), COUNT_FMT if fid in large_counts else "{}", path="study")
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
        if ref in stability.M_initial:
            m = float(stability.M_initial[ref])
            add(f"f_m_{i}", m, "{:.2f}", "", f"genorm.M_initial.{ref}")
    for ref, value in stability.M_initial.items():
        add(f"f_m_{slug(ref)}", float(value), "{:.2f}", "", f"genorm.M_initial.{ref}")
    for key, value in stability.V.items():  # "V2/3" -> f_v_2_3
        add(f"f_v_{slug(key[1:])}", float(value), "{:.2f}", "", f"genorm.V.{key}")
    add("f_worst_ref", stability.order[-1], path="genorm.order[-1]")
    if stability.V:
        add("f_genorm_v_min", float(min(stability.V.values())), "{:.2f}", "", "genorm.V")

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
        if card.id == "card_refset" and "ref_group_effect" in card.evidence:
            _refset_facts(add, card)
        if card.id == "card_amp_call":
            _amp_call_facts(add, card)
    worst = slug(stability.order[-1])
    for gene in headline:
        source = f"f_fc_{slug(gene)}_{worst}"
        if source in registry:
            path = f"cards.card_refset.{worst}_alone.{gene}.fc"
            add(f"f_fc_{slug(gene)}_worst", registry.get(source).value, FC_FMT, TIMES, path)
    _extra_facts(add, extras, settings)
    return registry


def _refset_facts(add: Callable[..., None], card: DecisionCard) -> None:
    """Facts for the reference-set card's flip count by set size and its group-effect check.

    Values are read from the card itself, so a fact always equals what ``cards.json`` shows.
    """
    root = f"cards.{card.id}"
    for key, fid in (
        ("n_genes_flipped_min3", "f_n_flipped_refset_min3"),
        ("n_genes_flipped_single_only", "f_n_flipped_refset_single_only"),
    ):
        add(fid, int(card.impact[key]), path=f"{root}.impact.{key}")
    effect = card.evidence["ref_group_effect"]
    base = f"{root}.evidence.ref_group_effect"
    pairs = effect["pairs"]
    for pair in pairs:  # f_ref_ratio_hmbs_ubc_2 (+ _p): the shift of HMBS:UBC(2), high vs rest
        a, b = pair["genes"]
        fid, path = f"f_ref_ratio_{slug(a)}_{slug(b)}", f"{base}.pairs.{pair['label']}"
        add(fid, float(pair["fold"]), FC_FMT, TIMES, f"{path}.fold")
        add(f"{fid}_p", float(pair["p"]), "{:.2g}", "", f"{path}.p")
    if pairs:
        top, path = pairs[0], f"{base}.pairs.{pairs[0]['label']}"
        add("f_ref_pair_top", str(top["label"]), path=f"{path}.label")
        add("f_ref_ratio_top", float(top["fold"]), FC_FMT, TIMES, f"{path}.fold")
        add("f_ref_ratio_top_p", float(top["p"]), "{:.2g}", "", f"{path}.p")
    add("f_n_ref_pairs", len(pairs), path=f"{base}.pairs")
    add("f_n_ref_pairs_flagged", len(effect["flagged"]), path=f"{base}.flagged")
    add("f_ref_flag_fold", float(effect["flag_fold"]), FC_FMT, TIMES, f"{base}.flag_fold")


def _amp_call_facts(add: Callable[..., None], card: DecisionCard) -> None:
    """Facts for the amplification-call card, read from the card itself."""
    root = f"cards.{card.id}.evidence"
    evidence = card.evidence
    add("f_amp_primary", RULES[card.recommended].label, path=f"{root}.rules.{card.recommended}")
    for option in card.options:
        s = slug(option.id)
        add(f"f_amp_label_{s}", option.label, path=f"{root}.rules.{option.id}.label")
        flips = int(evidence["n_flipped_by_rule"][option.id])
        add(f"f_n_flipped_amp_{s}", flips, path=f"{root}.n_flipped_by_rule.{option.id}")
        wells = int(evidence["n_not_amplified_by_rule"][option.id])
        path = f"{root}.n_not_amplified_by_rule.{option.id}"
        add(f"f_n_undetermined_amp_{s}", wells, COUNT_FMT, path=path)


def _extra_facts(add: Callable[..., None], extras: _Extras, settings: StudySettings) -> None:
    """Withheld genes, the design's group names and the Studio facts (routes, screening).

    None of these exist in the legacy demo output: a withheld gene cannot occur there, and the
    Studio facts are added only when the settings ask for them.
    """
    if extras.withheld or settings.studio_facts:
        add("f_n_withheld", len(extras.withheld), path="withheld")
        for gene, reason in extras.withheld.items():
            add(f"f_withheld_{slug(gene)}", reason, path=f"withheld.{gene}")
    if extras.groups is not None:
        add("f_group_a", extras.groups[0], path="design.comparison.group_a")
        add("f_group_b", extras.groups[1], path="design.comparison.group_b")
    if extras.routes is not None:
        for route in ROUTES:
            found = extras.routes[route]
            add(f"f_n_differ_route_{route}", found.n_differ, path=f"routes.{route}.differ")
            genes = ", ".join(found.differ) or "none"
            add(f"f_genes_differ_route_{route}", genes, path=f"routes.{route}.differ")
    if extras.screen is not None:
        screen = extras.screen
        verdict = "admitted" if screen.admitted else "not admitted"
        add("f_screen_amp_call", verdict, path="screen.amp_call.admitted")
        add("f_screen_amp_min_log2fc", screen.min_log2fc, "{:g}", path="screen.amp_call.min_log2fc")
        for rule in screen.rules:
            s, path = slug(rule.rule_id), f"screen.amp_call.{rule.rule_id}"
            add(f"f_screen_amp_flips_{s}", rule.n_flipped, path=f"{path}.flipped")
            delta = rule.max_delta_log2fc
            add(f"f_screen_amp_dlog2fc_{s}", delta, "{:.2f}", path=f"{path}.max_delta_log2fc")
