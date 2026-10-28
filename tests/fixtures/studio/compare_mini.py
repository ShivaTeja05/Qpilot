"""A small synthetic RDML file with three groups and four donors, written at test time.

Groups ``Control``, ``Drug A`` and ``Drug B``; donors ``D1``..``D4`` each give one sample to every
group (sample ``<group>_<donor>``, e.g. ``DrugA_D2``), in triplicate. Targets: ``GAPDH`` and
``ACTB`` (declared ``ref``), ``IL6`` (about 8-fold up in both drugs), ``MYC`` (about 4-fold up in
Drug B only) and ``TP53`` (no change). Each donor shifts every gene of its samples by the same
amount (the cDNA input, which the control genes remove) and every target gene by a donor's own
biology (a donor effect only a paired test removes). With ``missing_well`` the sample
``DrugB_D4`` has no ``TP53`` well at all (a unit not measured for one gene). With
``ref_shift`` a control gene comes up later in one group (``{("ACTB", "Drug B"): 2.5}``: the
drug lowers ACTB), so which control genes normalise changes calls in that group's comparison
only. With ``silent`` a gene never amplifies in a group (``{("TP53", "Drug B")}``: flat
curves, so every such well is undetermined: under "cap" the group's values are all filled in,
and the gene is detected only in the other groups).

Curves are model curves (exponential growth to a plateau, efficiency 1.9) with a little baseline
noise from a fixed seed, so the file is identical on every run.
"""

from __future__ import annotations

import zipfile
from pathlib import Path
from xml.sax.saxutils import quoteattr

import numpy as np

CYCLES = 45
EFFICIENCY = 1.9
PLATEAU = 20.0
GROUPS = {"Control": "Control", "Drug A": "DrugA", "Drug B": "DrugB"}
DONORS = ("D1", "D2", "D3", "D4")
TARGETS = {"GAPDH": "ref", "ACTB": "ref", "IL6": "toi", "MYC": "toi", "TP53": "toi"}
BASE_CQ = {"GAPDH": 20.0, "ACTB": 21.0, "IL6": 26.0, "MYC": 25.0, "TP53": 24.0}
# cycles earlier than Control (log2 fold change at efficiency 2: 3 cycles ~ 8-fold)
EFFECT = {
    ("IL6", "Drug A"): 3.0,
    ("IL6", "Drug B"): 3.2,
    ("MYC", "Drug B"): 2.0,
    ("MYC", "Drug A"): 0.2,
}
DONOR_SHIFT = {"D1": -1.2, "D2": 0.0, "D3": 0.9, "D4": 1.8}  # how much cDNA each donor gave
DONOR_BIOLOGY = {
    "D1": -0.9,
    "D2": 0.4,
    "D3": 0.8,
    "D4": -0.3,
}  # targets only: a paired test removes it
WOBBLE = {  # biological noise per sample and gene (cycles), fixed so the file never changes
    (g, d): v
    for (g, d), v in zip(
        [(g, d) for g in GROUPS for d in DONORS],
        [0.15, -0.1, 0.05, -0.2, 0.1, 0.2, -0.15, 0.0, -0.05, 0.12, 0.18, -0.1],
        strict=True,
    )
}


def sample_name(group: str, donor: str) -> str:
    """The sample name of a donor's sample in a group (``DrugA_D2``)."""
    return f"{GROUPS[group]}_{donor}"


def samples() -> dict[str, tuple[str, str]]:
    """Sample name -> (group, donor)."""
    return {sample_name(g, d): (g, d) for g in GROUPS for d in DONORS}


def _curve(rng: np.random.Generator, crossing: float) -> list[float]:
    base = 0.5 + rng.normal(0.0, 0.002, CYCLES)
    n0 = 1.0 / EFFICIENCY**crossing
    cycles = np.arange(1, CYCLES + 1)
    return list(base + 1.0 / (1.0 / (n0 * EFFICIENCY**cycles) + 1.0 / PLATEAU))


def write_compare_mini(
    path: str | Path,
    *,
    missing_well: bool = False,
    ref_shift: dict[tuple[str, str], float] | None = None,
    silent: set[tuple[str, str]] | frozenset[tuple[str, str]] = frozenset(),
) -> Path:
    """Write the synthetic three-group RDML file to ``path`` and return the path."""
    rng = np.random.default_rng(11)
    parts = ['<rdml xmlns:rdml="http://www.rdml.org" xmlns="http://www.rdml.org" version="1.4">']
    parts.append('<dateMade>2026-10-28T00:00:00</dateMade><dye id="SYBR"/>')
    for name in samples():
        parts.append(f"<sample id={quoteattr(name)}><type>unkn</type></sample>")
    for target, kind in TARGETS.items():
        parts.append(
            f'<target id={quoteattr(target)}><type>{kind}</type><dyeId id="SYBR"/></target>'
        )
    parts.append('<experiment id="compare_set">')
    for target in TARGETS:
        parts.append(f"<run id={quoteattr(target + '_plate')}>")
        parts.append(
            "<backgroundDeterminationMethod>synthetic model curves</backgroundDeterminationMethod>"
            "<cqDetectionMethod>other</cqDetectionMethod><pcrFormat><rows>8</rows>"
            "<columns>12</columns><rowLabel>ABC</rowLabel><columnLabel>123</columnLabel>"
            "</pcrFormat>"
        )
        react = 0
        for name, (group, donor) in samples().items():
            if missing_well and target == "TP53" and name == "DrugB_D4":
                react += 3
                continue
            cq = BASE_CQ[target] + DONOR_SHIFT[donor] - EFFECT.get((target, group), 0.0)
            cq += (ref_shift or {}).get((target, group), 0.0)
            if target not in ("GAPDH", "ACTB"):
                cq += WOBBLE[(group, donor)] + DONOR_BIOLOGY[donor]
            for rep in range(3):
                react += 1
                crossing = cq + (rep - 1) * 0.05
                parts.append(f'<react id="{react}"><sample id={quoteattr(name)}/>')
                parts.append(f"<data><tar id={quoteattr(target)}/>")
                curve = _curve(rng, crossing)
                if (target, group) in silent:  # never amplifies: the baseline alone
                    curve = list(0.5 + rng.normal(0.0, 0.002, CYCLES))
                for cycle, fluor in enumerate(curve, start=1):
                    parts.append(f"<adp><cyc>{cycle}</cyc><fluor>{fluor:.4f}</fluor></adp>")
                parts.append("</data></react>")
        parts.append("</run>")
    parts.append("</experiment></rdml>")
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("rdml_data.xml", "".join(parts))
    return out


def design(*, paired: bool = False, pattern: str = "vs_control", correction: str = "holm"):  # noqa: ANN201
    """The study design: each drug vs Control (or every pair), optionally paired by donor."""
    from qpilot.schemas_studio import (
        Comparison,
        ComparisonPlan,
        SampleDesign,
        StudyDesign,
    )

    sample_designs = {
        name: SampleDesign(sample=name, group=group, pair=donor if paired else None)
        for name, (group, donor) in samples().items()
    }
    if pattern == "vs_control":
        comparisons = (
            Comparison(group_a="Drug A", group_b="Control"),
            Comparison(group_a="Drug B", group_b="Control"),
        )
        control = "Control"
    else:
        comparisons = (
            Comparison(group_a="Drug A", group_b="Control"),
            Comparison(group_a="Drug B", group_b="Control"),
            Comparison(group_a="Drug B", group_b="Drug A"),
        )
        control = None
    plan = ComparisonPlan(
        pattern=pattern,  # type: ignore[arg-type]
        control=control,
        comparisons=comparisons,
        correction=correction,  # type: ignore[arg-type]
        pair_by="donor" if paired else None,
    )
    return StudyDesign(
        experiment_id="compare_set",
        mode="groups",
        comparison=comparisons[0],
        samples=sample_designs,
        reference_candidates=("ACTB", "GAPDH"),
        headline=("IL6", "MYC"),
        comparisons=plan,
    )
