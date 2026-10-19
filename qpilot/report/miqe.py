"""The MIQE 2.0 table: each item answered from the record, or left to the scientist.

The item list is ``packs/miqe2_items.yaml`` (its hash goes into the report). Each item names a
resolver here; a resolver reads the record (results, facts, design, versions, the RDML file's
metadata) and returns a :class:`Fill` ("Yes" with fact-bound text, or "No" with a rationale the
record supports), a :class:`Hint` (the item stays with the scientist, with what the record does
hold), or :data:`NA`. An item is "filled" only when its answer is bound to facts in the record;
items only a person can attest are never answered. The headline is a count, "items filled
from the record: N of M", never a score and never a claim about the whole checklist.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path

import yaml

from qpilot.report.context import Ctx
from qpilot.report.model import Miqe, MiqeRow
from qpilot.report.text import tok

PACK = Path(__file__).resolve().parents[2] / "packs" / "miqe2_items.yaml"


@dataclass
class Fill:
    """The record answers the item: "Yes" with the value, or "No" with the rationale."""

    answer: str
    tokens: str
    sources: list[str] = field(default_factory=list)


@dataclass
class Hint:
    """The item stays with the scientist; ``tokens`` says what the record does hold."""

    tokens: str
    sources: list[str] = field(default_factory=list)


@dataclass
class NotApplicable:
    """The item does not apply to this study (the reason in words)."""

    tokens: str


Outcome = Fill | Hint | NotApplicable | None


class MiqeCtx:
    """The report context plus the RDML metadata, read once and only when an item needs it."""

    def __init__(self, ctx: Ctx) -> None:
        self.ctx = ctx

    @cached_property
    def rdml(self):  # noqa: ANN201 - RdmlMeta | None
        """Metadata of the record's ``input.rdml``, or None when absent or unreadable."""
        from qpilot.io.rdml_io import RdmlLoadError
        from qpilot.report.rdml_meta import read_meta

        view = self.ctx.view
        if not view.has("input.rdml"):
            return None
        try:
            return read_meta(view.root / "input.rdml")
        except (RdmlLoadError, OSError, ValueError):
            view.problems.append("input.rdml: its metadata could not be read")
            return None

    def n(self, name: str, value: int, path: str) -> str:
        """A derived count token."""
        return self.ctx.count(name, value, path)

    @cached_property
    def roles(self) -> dict[str, int]:
        """Samples per declared role in the confirmed design (``study_design.json``)."""
        samples = self.ctx.view.study_design.get("samples")
        out: dict[str, int] = {}
        if isinstance(samples, dict):
            for entry in samples.values():
                role = entry.get("role") if isinstance(entry, dict) else None
                if isinstance(role, str):
                    out[role] = out.get(role, 0) + 1
        return out


NO_RDML = "the record does not include its RDML file"


# ---------- resolvers (RDML metadata) ----------


def _rdml_count(m: MiqeCtx, attr: str, what: str, name: str) -> Outcome:
    meta = m.rdml
    if meta is None:
        return Hint(NO_RDML + ".")
    have = getattr(meta, attr)
    if not have:
        return None
    path = f"input.rdml:target.{what}"
    total = m.n("rdml_n_targets", meta.n_targets, "input.rdml:target")
    return Fill("Yes", f"In the RDML file for {m.n(name, have, path)} of {total} targets.", [path])


def rdml_xref(m: MiqeCtx) -> Outcome:
    """1.2: database cross-references of the targets."""
    return _rdml_count(m, "n_targets_with_xref", "xRef", "rdml_n_xref")


def rdml_amplicon(m: MiqeCtx) -> Outcome:
    """1.4: amplicon sequences (unmasked) in the file."""
    out = _rdml_count(m, "n_targets_with_amplicon", "sequences.amplicon", "rdml_n_amplicon")
    if out is None and m.rdml is not None and m.rdml.n_targets:
        return Hint("The RDML file holds amplicon entries, but their sequences are masked.")
    return out


def rdml_primers(m: MiqeCtx) -> Outcome:
    """1.5: primer/probe sequences or commercial assay ids (footnote c)."""
    meta = m.rdml
    if meta is None:
        return Hint(NO_RDML + ".")
    if meta.n_targets_with_primers or meta.n_targets_with_assay:
        path = "input.rdml:target.sequences|commercialAssay"
        total = m.n("rdml_n_targets", meta.n_targets, "input.rdml:target")
        seq = m.n("rdml_n_primers", meta.n_targets_with_primers, path)
        assay = m.n("rdml_n_assays", meta.n_targets_with_assay, path)
        return Fill(
            "Yes",
            f"Of {total} targets, {seq} have primer or probe sequences and {assay} a commercial "
            "assay id in the RDML file; for a commercial assay, MIQE asks for the assay context "
            "sequence.",
            [path],
        )
    return Hint("No primer or probe sequences in the RDML file.")


def rdml_tags(m: MiqeCtx) -> Outcome:
    """1.6: oligonucleotide modifications (tags)."""
    meta = m.rdml
    if meta is None or not meta.n_oligo_tags:
        return None
    path = "input.rdml:target.sequences.*Tag"
    return Fill(
        "Yes", f"{m.n('rdml_n_tags', meta.n_oligo_tags, path)} tags in the RDML file.", [path]
    )


def rdml_template(m: MiqeCtx) -> Outcome:
    """2.11 and 3.3: template quantities declared in the file."""
    meta = m.rdml
    if meta is None or not meta.n_template_quantities:
        return None
    path = "input.rdml:sample.templateQuantity"
    n = m.n("rdml_n_template", meta.n_template_quantities, path)
    return Hint(
        f"{n} samples declare a template quantity in the RDML file; please confirm.", [path]
    )


def rdml_dnase(m: MiqeCtx) -> Outcome:
    """2.12: DNase treatment as declared in the file."""
    meta = m.rdml
    if meta is None or not meta.dnase:
        return None
    words = "DNase-treated" if meta.dnase == [True] else "DNase treatment declared as mixed or no"
    return Hint(f"The RDML file declares the template {words}; please confirm.", ["input.rdml"])


def rdml_priming(m: MiqeCtx) -> Outcome:
    """3.1: cDNA priming method declared in the file (concentration needs the scientist)."""
    meta = m.rdml
    if meta is None or not meta.priming:
        return None
    methods = ", ".join(meta.priming)
    return Hint(
        f"Priming declared in the RDML file: {methods}; the primer concentration is not.",
        ["input.rdml:sample.cdnaSynthesisMethod.primingMethod"],
    )


def rdml_cycling(m: MiqeCtx) -> Outcome:
    """4.1: thermal-cycling programme in the file."""
    meta = m.rdml
    if meta is None or not meta.n_cycling_programmes:
        return None
    path = "input.rdml:thermalCyclingConditions"
    steps = m.n("rdml_n_steps", meta.n_cycling_steps, path)
    return Hint(f"The RDML file holds a cycling programme ({steps} steps); please confirm.", [path])


def rdml_cycling_volume(m: MiqeCtx) -> Outcome:
    """4.5: cycling parameters and reaction volume."""
    meta = m.rdml
    if meta is None:
        return Hint(NO_RDML + ".")
    have = []
    if meta.volumes:
        vol = m.ctx.facts.derive(
            "rdml_volume",
            ", ".join(f"{v:g}" for v in meta.volumes),
            unit=" µL",
            path="input.rdml:react.vol",
        )
        have.append(f"reaction volume {tok(vol)}")
    if meta.n_cycling_programmes:
        have.append("a cycling programme")
    if not have:
        return None
    return Hint(
        f"The RDML file holds {' and '.join(have)}; the full parameters need the scientist."
    )


def rdml_instrument(m: MiqeCtx) -> Outcome:
    """4.6: instrument named in the file."""
    meta = m.rdml
    if meta is None or not meta.instruments:
        return None
    name = m.ctx.facts.derive(
        "rdml_instrument", "; ".join(meta.instruments), path="input.rdml:run.instrument"
    )
    return Fill(
        "Yes", f"Instrument named in the RDML file: {tok(name)}.", ["input.rdml:run.instrument"]
    )


# ---------- resolvers (record and engine) ----------


def sample_counts(m: MiqeCtx) -> Outcome:
    """2.1: study samples, biological units per group, controls typed in the design."""
    c = m.ctx
    if not c.has("f_n_samples", "f_n_hi", "f_n_lo"):
        return None
    text = (
        f"{tok('f_n_samples')} study samples; {tok(c.group_a)} {tok('f_n_hi')} and "
        f"{tok(c.group_b)} {tok('f_n_lo')} biological units."
    )
    roles = {r: n for r, n in m.roles.items() if r != "unkn"}
    if roles:
        parts = [
            f"{m.n(f'role_{r}', n, 'study_design.json:samples.*.role')} {r.upper()}"
            for r, n in sorted(roles.items())
        ]
        text += " Controls and standards typed in the design: " + ", ".join(parts) + "."
    return Fill("Yes", text, ["f_n_samples", "f_n_hi", "f_n_lo"])


def nrt(m: MiqeCtx) -> Outcome:
    """3.5: copies with and without RT (footnote e: desirable, no longer essential)."""
    meta = m.rdml
    n_nrt = m.roles.get("nrt", 0) + (meta.sample_types.get("nrt", 0) if meta else 0)
    if m.ctx.view.has("rule_evals.json"):
        return Hint("Run Gate results are in the record; see the Run Gate section.")
    if n_nrt == 0 and (meta is not None or m.roles):
        return Fill(
            "No",
            "The study has no no-RT control wells (MIQE 2.0: desirable, no longer essential "
            "once the samples are shown to be free of DNA).",
            ["study_design.json:samples", "input.rdml:sample.type"],
        )
    return None


def raw_data(m: MiqeCtx) -> Outcome:
    """5.1: raw fluorescence in RDML, bound to the record."""
    meta = m.rdml
    if meta is None:
        return Hint("A shared record leaves the RDML file out; deposit it with the paper.")
    if not meta.n_reactions_with_curves:
        return Hint("The RDML file in the record holds no amplification curves.")
    sha = m.ctx.facts.derive(
        "input_sha256", m.ctx.result.input_sha256, path="results.json:input_sha256"
    )
    curves = m.n("rdml_n_curves", meta.n_reactions_with_curves, "input.rdml:react.data.adp")
    return Fill(
        "Yes",
        f"Raw fluorescence of {curves} reactions in RDML, kept in the record as input.rdml "
        f"(SHA-256 {tok(sha)}).",
        ["input.rdml"],
    )


def quantification(m: MiqeCtx) -> Outcome:
    """5.2: quantification method (relative, from efficiency-corrected N0)."""
    return Fill(
        "Yes",
        "Relative quantification from efficiency-corrected starting quantities (LinRegPCR); "
        "standard curves are not used to quantify.",
        ["methods/linregpcr.md"],
    )


def baseline_cq(m: MiqeCtx) -> Outcome:
    """5.3: baseline and Cq method."""
    commit = m.ctx.version("rdmlpython_vendored")
    text = (
        "Per-well baseline estimated and subtracted by LinRegPCR; Cq is the cycle where the "
        "third derivative of the curve crosses zero."
    )
    if commit:
        text += f" rdmlpython commit {tok(commit)}."
    return Fill("Yes", text, ["versions.json", "methods/linregpcr.md"])


def software(m: MiqeCtx) -> Outcome:
    """5.4: analysis program and version."""
    qp, rp = m.ctx.version("qpilot"), m.ctx.version("rdmlpython_vendored")
    if qp is None:
        return None
    text = f"qPilot {tok(qp)}"
    if rp:
        text += f" with LinRegPCR from rdmlpython (commit {tok(rp)})"
    py = m.ctx.version("python")
    if py:
        text += f", Python {tok(py)}"
    return Fill("Yes", text + ".", ["versions.json"])


def controls(m: MiqeCtx) -> Outcome:
    """5.5: which positive and negative controls the design types."""
    roles = {r: n for r, n in m.roles.items() if r != "unkn"}
    meta = m.rdml
    if not roles and meta is not None:
        roles = {r: n for r, n in meta.sample_types.items() if r != "unkn"}
        path = "input.rdml:sample.type"
    else:
        path = "study_design.json:samples.*.role"
    if not roles:
        return None
    parts = [f"{m.n(f'ctl_{r}', n, path)} {r.upper()}" for r, n in sorted(roles.items())]
    return Fill("Yes", "Control and standard samples: " + ", ".join(parts) + ".", [path])


def ntc_results(m: MiqeCtx) -> Outcome:
    """5.6: NTC frequency and Cq (Run Gate)."""
    if m.ctx.view.has("rule_evals.json"):
        return Hint("Run Gate results are in the record; see the Run Gate section.")
    return Hint("No control evaluation (Run Gate) is in this record.")


def efficiency(m: MiqeCtx) -> Outcome:
    """5.8: efficiency per well from the curve (LinRegPCR)."""
    c = m.ctx
    eff = c.result.efficiency
    if not eff:
        return Fill("No", "No efficiency in this record: quantities assume one (footnote j).", [])
    lo = c.facts.derive("eff_min", min(eff.values()), "{:.2f}", path="results.json:efficiency")
    hi = c.facts.derive("eff_max", max(eff.values()), "{:.2f}", path="results.json:efficiency")
    text = (
        "Estimated per well from the log-linear phase of each curve (LinRegPCR); per-assay "
        f"means range {tok(lo)} to {tok(hi)}"
    )
    if c.has("f_eff_median"):
        text += f" (median {tok('f_eff_median')})"
    return Fill("Yes", text + ", as amplification factor per cycle.", ["results.json:efficiency"])


def quantity_method(m: MiqeCtx) -> Outcome:
    """5.9: efficiency-corrected target quantity (footnote j)."""
    if not m.ctx.result.efficiency:
        return Fill("No", "Efficiency was assumed, not measured (footnote j).", [])
    return Fill(
        "Yes",
        "Efficiency-corrected starting quantity per well (LinRegPCR N0, using the assay's "
        "mean efficiency).",
        ["methods/linregpcr.md"],
    )


def replicates(m: MiqeCtx) -> Outcome:
    """5.10: biological units vs technical replicates."""
    c = m.ctx
    if not c.has("f_n_hi", "f_n_lo"):
        return None
    return Fill(
        "Yes",
        f"n is the number of biological units ({tok('f_n_hi')} and {tok('f_n_lo')}); "
        "technical replicates are averaged per unit before any test and never counted as n.",
        ["f_n_hi", "f_n_lo", "methods/contrast.md"],
    )


def lod(m: MiqeCtx) -> Outcome:
    """5.13 and 5.14: not determined by this analysis (scientist #0052)."""
    return Fill(
        "No",
        "Not determined by this analysis: it needs replicate detection rates at low input or a "
        "standard series evaluated for that purpose; change this answer if determined elsewhere.",
        ["results.json:confidence.*.checks.assay"],
    )


def refgene_validation(m: MiqeCtx) -> Outcome:
    """5.15: geNorm M and V, and the control-gene group-effect check."""
    c = m.ctx
    g = c.result.genorm
    if not g.M_initial:
        return None
    lo = c.facts.derive("m_min", min(g.M_initial.values()), "{:.2f}", path="results.json:genorm")
    hi = c.facts.derive("m_max", max(g.M_initial.values()), "{:.2f}", path="results.json:genorm")
    text = f"geNorm stability M {tok(lo)} to {tok(hi)}"
    if c.has("f_genorm_v_min"):
        text += f"; lowest pairwise variation V {tok('f_genorm_v_min')}"
    text += "."
    if c.has("f_n_ref_pairs_flagged", "f_n_ref_pairs"):
        text += (
            f" Pairwise ratios between the groups: {tok('f_n_ref_pairs_flagged')} of "
            f"{tok('f_n_ref_pairs')} control-gene pairs shift."
        )
    return Fill("Yes", text, ["results.json:genorm", "methods/genorm.md"])


def normalisation(m: MiqeCtx) -> Outcome:
    """5.16: geometric mean of the reference genes."""
    c = m.ctx
    refs = list(c.result.design.refs_primary)
    if not refs:
        return None
    n = c.count("n_refs", len(refs), "results.json:design.refs_primary")
    return Fill(
        "Yes",
        f"Each target divided by the geometric mean of {n} reference genes "
        f"({', '.join(refs)}), on the log2 scale per biological unit.",
        ["results.json:design.refs_primary"],
    )


def statistics(m: MiqeCtx) -> Outcome:
    """5.17: Welch's t-test on per-unit log2 quantities."""
    return Fill(
        "Yes",
        "Welch's t-test on per-unit log2 normalised quantities; fold changes with "
        "95 % confidence intervals; no correction for multiple testing.",
        ["methods/contrast.md"],
    )


def significance(m: MiqeCtx) -> Outcome:
    """5.18: significance level (machine); power is a form answer only (scientist #0052)."""
    return Fill(
        "Yes",
        "Significance level: a gene is called only when p < 0.05 and the change is at least "
        "2-fold. A priori power is not in the record; add it if it was calculated.",
        ["results.json:conclusion_rule"],
    )


def specificity(m: MiqeCtx) -> Outcome:
    """5.19: melt curves (Run Gate) or sequencing."""
    if m.ctx.view.has("rule_evals.json"):
        return Hint("Run Gate results are in the record; see the Run Gate section.")
    return None


RESOLVERS: dict[str, Callable[[MiqeCtx], Outcome]] = {
    f.__name__: f
    for f in (
        rdml_xref,
        rdml_amplicon,
        rdml_primers,
        rdml_tags,
        rdml_template,
        rdml_dnase,
        rdml_priming,
        rdml_cycling,
        rdml_cycling_volume,
        rdml_instrument,
        sample_counts,
        nrt,
        raw_data,
        quantification,
        baseline_cq,
        software,
        controls,
        ntc_results,
        efficiency,
        quantity_method,
        replicates,
        lod,
        refgene_validation,
        normalisation,
        statistics,
        significance,
        specificity,
    )
}


def load_pack(path: Path = PACK) -> tuple[dict, str]:
    """The item pack and its sha256."""
    raw = path.read_bytes()
    return yaml.safe_load(raw), hashlib.sha256(raw).hexdigest()


def miqe(ctx: Ctx, pack_path: Path = PACK) -> Miqe:
    """Answer every MIQE 2.0 item the record can, and count them."""
    try:
        pack, digest = load_pack(pack_path)
    except (OSError, yaml.YAMLError) as err:
        return Miqe(status="not_available", reason=f"the MIQE item pack could not be read ({err})")
    m = MiqeCtx(ctx)
    rows = []
    for item in pack["items"]:
        resolver = RESOLVERS.get(item.get("fill") or "")
        outcome = resolver(m) if resolver is not None and item["class"] != "d" else None
        section = pack["sections"][item["id"].split(".")[0]]
        row = MiqeRow(id=item["id"], section=section, label=item["label"], status="needs_scientist")
        if isinstance(outcome, Fill):
            row = row.model_copy(
                update={
                    "status": "filled",
                    "answer": outcome.answer,
                    "text": ctx.t(outcome.tokens),
                    "sources": outcome.sources,
                }
            )
        elif isinstance(outcome, Hint):
            row = row.model_copy(update={"text": ctx.t(outcome.tokens), "sources": outcome.sources})
        elif isinstance(outcome, NotApplicable):
            row = row.model_copy(update={"status": "not_applicable", "text": ctx.t(outcome.tokens)})
        rows.append(row)
    n_filled = sum(r.status == "filled" for r in rows)
    filled = ctx.count("miqe_n_filled", n_filled, "report:miqe.rows[status=filled]")
    total = ctx.count("miqe_n_items", len(rows), "packs/miqe2_items.yaml:items")
    yes = ctx.count("miqe_n_yes", sum(r.answer == "Yes" for r in rows), "report:miqe.rows")
    no = ctx.count("miqe_n_no", sum(r.answer == "No" for r in rows), "report:miqe.rows")
    headline = ctx.t(
        f"Items filled from the record: {filled} of {total} ({yes} answered Yes with the value, "
        f"{no} answered No with the reason). The rest need the scientist; qPilot never answers "
        "an item only a person can attest."
    )
    return Miqe(
        pack={
            "name": str(pack.get("name")),
            "version": str(pack.get("version")),
            "sha256": digest,
            "citation": " ".join(str(pack.get("citation", "")).split()),
        },
        headline=headline,
        rows=rows,
        n_filled=n_filled,
        n_items=len(rows),
    )
