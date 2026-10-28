"""The next experiment's plates: every well assigned, groups balanced, nothing confounded.

:func:`make_layout` turns a planned design (samples per group, the genes, the reference genes,
technical replicates, the controls, the plate size) into plates with every well assigned, the
same way every time for the same inputs and seed:

* **Reference genes and controls on every plate.** Each plate carries the reference genes for
  its own samples (so every sample is normalised within its plate) and, per assay on it, the
  no-template controls (NTC), the no-RT controls (NRT) and the standard dilution points asked for.
* **Plate is never group.** Samples are dealt to plates group by group in a seeded random order,
  so every plate holds as even a share of every group as the sizes allow; within a plate the
  samples' order is shuffled (so position on the plate is not group either).
* **Fewest plates, most samples per plate.** The gene panel is split into as few panels as fit
  and the samples into as few batches as fit (Hellemans 2007's sample maximisation: a gene's
  comparison between samples is best made within one run). When a gene's samples still span
  more than one plate, an inter-run calibrator (the same sample, ``IRC``) is put on every plate
  for every assay, which links the runs (Hellemans 2007); the layout says so.

Wells are filled down the columns (A1, B1, …, H1, A2, …): each sample's reactions are adjacent
(its assays in order, each in its replicates), then the plate's controls, NTC last. Sample names
are the plan's own (``<group>-01`` …): rename them in the CSV for the real samples. Sample types
are RDML's (``unkn``, ``std``, ``ntc``, ``nrt``, and ``pos`` for the calibrator).

:func:`layout_csv` writes the CSV a plate-setup program or a pipetting robot imports (plate, well,
sample, group, target, type); :func:`read_layout_csv` reads one back.

Pure Python (the standard library only): no numbers from any study enter here except the sizes
and names the caller passes.
"""

from __future__ import annotations

import csv
import io
import math
import random
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field

PLATE_SHAPES: dict[int, tuple[int, int]] = {96: (8, 12), 384: (16, 24)}
CSV_COLUMNS: tuple[str, ...] = ("plate", "well", "sample", "group", "target", "type")
#: What a name may be: the engine's safe names (``curves.safe_name``), not starting with ``-``
#: (a spreadsheet would read ``-A1`` as a formula).
SAFE_NAME = re.compile(r"^(?!-)[\w()\-. ]{1,64}\Z")
MAX_PLATES = 64
MAX_SAMPLES_PER_GROUP = 1000
MAX_GROUPS = 8
MAX_GENES = 96
MAX_REFS = 12
MAX_REPLICATES = 6
MAX_PER_ASSAY = 4  # NTC or NRT wells per assay per plate
MAX_STANDARDS = 8  # dilution points per assay per plate
IRC = "IRC"
NTC = "NTC"
NRT = "NRT"


class LayoutError(ValueError):
    """The design cannot be laid out (the message says why, in words)."""


@dataclass(frozen=True)
class LayoutSpec:
    """A planned experiment.

    Attributes:
        groups: ``(label, samples)`` per group, in the order the comparison names them.
        genes: The genes of interest.
        refs: The reference genes (on every plate).
        replicates: Technical replicates per sample and assay.
        plate_size: 96 or 384 wells.
        ntc: No-template control wells per assay per plate.
        nrt: No-RT control wells per assay per plate.
        standards: Standard dilution points per assay per plate (each in ``replicates``).
        calibrator: Put an inter-run calibrator on every plate when a gene's samples span plates.
        seed: The random order's seed (the same seed gives the same plates).
    """

    groups: tuple[tuple[str, int], ...]
    genes: tuple[str, ...]
    refs: tuple[str, ...]
    replicates: int = 2
    plate_size: int = 96
    ntc: int = 1
    nrt: int = 0
    standards: int = 0
    calibrator: bool = True
    seed: int = 0

    @property
    def n_samples(self) -> int:
        """Every sample in the plan."""
        return sum(n for _, n in self.groups)


@dataclass(frozen=True)
class Well:
    """One reaction: where, what sample (and group), which assay, what kind of well."""

    plate: int
    well: str
    sample: str
    group: str  # "" for a control
    target: str
    type: str  # RDML sample type: unkn, std, ntc, nrt, pos (the calibrator)
    replicate: int


@dataclass(frozen=True)
class Plate:
    """One plate of the layout."""

    number: int
    panel: int  # which slice of the gene panel (1-based)
    batch: int  # which slice of the samples (1-based)
    genes: tuple[str, ...]
    refs: tuple[str, ...]
    samples: tuple[str, ...]  # in plate order
    wells: tuple[Well, ...]
    size: int

    @property
    def name(self) -> str:
        """The plate's name: ``Plate 01``, ``Plate 02``, …."""
        return f"Plate {self.number:02d}"


@dataclass(frozen=True)
class Shape:
    """How the plan is cut: panels of genes × batches of samples, and what each plate holds."""

    panels: tuple[tuple[str, ...], ...]
    batches: int
    samples_per_plate: int  # the most samples any plate holds
    calibrated: bool  # an inter-run calibrator on every plate

    @property
    def n_plates(self) -> int:
        """Panels × batches."""
        return len(self.panels) * self.batches


@dataclass(frozen=True)
class PlateBalance:
    """What one plate holds, for the balance badges."""

    number: int
    wells_used: int
    wells_free: int
    samples: dict[str, int]  # group → samples on this plate
    groups_present: int
    refs_present: bool
    controls: dict[str, int]  # type → wells
    edge_share: dict[str, float | None]  # group → share of its wells on the plate's edge


@dataclass(frozen=True)
class Balance:
    """The layout's balance, as numbers a test (and a person) can check."""

    plates: tuple[PlateBalance, ...]
    every_plate_every_group: bool
    plates_with_one_group: tuple[int, ...]
    refs_on_every_plate: bool
    controls_on_every_plate: bool
    each_reaction_once: bool  # every gene reaction once; a reference's once per gene panel
    group_plate_association: float  # Cramér's V of plate × group over samples: 0 = none
    max_share_gap: float  # largest |a group's share on a plate - its share overall|
    wells_total: int
    wells_samples: int
    wells_controls: int
    wells_free: int


@dataclass(frozen=True)
class Layout:
    """The plates, how the plan was cut, its balance and what a person should know."""

    spec: LayoutSpec
    shape: Shape
    plates: tuple[Plate, ...]
    balance: Balance
    notes: tuple[str, ...]
    warnings: tuple[str, ...] = field(default_factory=tuple)

    def wells(self) -> list[Well]:
        """Every well of every plate, plate by plate."""
        return [w for p in self.plates for w in p.wells]


# ---- checking the spec -------------------------------------------------------------------------


def _name(value: str, what: str) -> str:
    text = str(value).strip()
    if not SAFE_NAME.match(text):
        raise LayoutError(
            f"{what} {value!r} cannot go into a plate layout: use letters, digits, spaces and "
            "_ - . ( ), at most 64 characters, not starting with -"
        )
    return text


def _unique(names: Iterable[str]) -> tuple[str, ...]:
    seen: dict[str, None] = {}
    for n in names:
        seen.setdefault(n, None)
    return tuple(seen)


def check_spec(spec: LayoutSpec) -> LayoutSpec:
    """The spec with names cleaned and duplicates removed; refuse what no plate can hold.

    Raises:
        LayoutError: A value out of range or a name a CSV cannot carry safely.
    """
    if spec.plate_size not in PLATE_SHAPES:
        raise LayoutError("plates have 96 or 384 wells")
    if not 2 <= len(spec.groups) <= MAX_GROUPS:
        raise LayoutError(f"a comparison needs 2 to {MAX_GROUPS} groups")
    groups = []
    for label, n in spec.groups:
        if not isinstance(n, int) or not 2 <= n <= MAX_SAMPLES_PER_GROUP:
            raise LayoutError(
                f"every group needs 2 to {MAX_SAMPLES_PER_GROUP} samples ({label!s}: {n!s})"
            )
        groups.append((_name(label, "The group"), n))
    if len({g for g, _ in groups}) != len(groups):
        raise LayoutError("two groups have the same name")
    refs = _unique(_name(r, "The reference gene") for r in spec.refs)
    genes = tuple(g for g in _unique(_name(g, "The gene") for g in spec.genes) if g not in refs)
    if not genes:
        raise LayoutError("choose at least one gene to measure (besides the reference genes)")
    if len(genes) > MAX_GENES:
        raise LayoutError(f"at most {MAX_GENES} genes in one layout")
    if not refs:
        raise LayoutError("choose at least one reference gene: every plate needs one")
    if len(refs) > MAX_REFS:
        raise LayoutError(f"at most {MAX_REFS} reference genes")
    if not 1 <= spec.replicates <= MAX_REPLICATES:
        raise LayoutError(f"technical replicates are 1 to {MAX_REPLICATES}")
    for value, what, top in (
        (spec.ntc, "NTC wells per assay", MAX_PER_ASSAY),
        (spec.nrt, "NRT wells per assay", MAX_PER_ASSAY),
        (spec.standards, "standard points per assay", MAX_STANDARDS),
    ):
        if not 0 <= value <= top:
            raise LayoutError(f"{what} are 0 to {top}")
    names = {g for g, _ in groups} | set(genes) | set(refs)
    if {IRC, NTC, NRT} & names or any(n.startswith("STD-") for n in names):
        raise LayoutError("IRC, NTC, NRT and STD-… are the layout's own control names")
    return LayoutSpec(
        groups=tuple(groups),
        genes=genes,
        refs=refs,
        replicates=spec.replicates,
        plate_size=spec.plate_size,
        ntc=spec.ntc,
        nrt=spec.nrt,
        standards=spec.standards,
        calibrator=bool(spec.calibrator),
        seed=int(spec.seed),
    )


# ---- cutting the plan into plates --------------------------------------------------------------


def _controls_per_assay(spec: LayoutSpec, calibrated: bool) -> int:
    reps = spec.replicates
    return spec.ntc + spec.nrt + spec.standards * reps + (reps if calibrated else 0)


def _samples_fitting(spec: LayoutSpec, n_assays: int, calibrated: bool) -> int:
    free = spec.plate_size - n_assays * _controls_per_assay(spec, calibrated)
    return max(0, free // (n_assays * spec.replicates))


def _split(items: Sequence[str], parts: int) -> tuple[tuple[str, ...], ...]:
    """``items`` in ``parts`` consecutive slices whose sizes differ by at most one."""
    size, extra = divmod(len(items), parts)
    out, start = [], 0
    for i in range(parts):
        end = start + size + (1 if i < extra else 0)
        out.append(tuple(items[start:end]))
        start = end
    return tuple(out)


def plan_shape(spec: LayoutSpec) -> Shape:
    """How few plates hold the plan, every plate carrying every group (no well assigned yet).

    Tries every panel size; for each, as many samples per plate as fit (all of them when they
    do: no calibrator needed), else the fewest batches with a calibrator when asked for. Picks
    the fewest plates, then the fewest batches (more of a gene's samples share a run), then the
    fewest panels.

    Raises:
        LayoutError: No plate can hold one gene, the reference genes and the controls for one
            sample of every group, or the plan needs more than :data:`MAX_PLATES` plates.
    """
    spec = check_spec(spec)
    n, n_groups, n_genes = spec.n_samples, len(spec.groups), len(spec.genes)
    best: tuple[tuple[int, int, int], Shape] | None = None
    for k in range(1, n_genes + 1):
        assays = k + len(spec.refs)
        panels = math.ceil(n_genes / k)
        s = _samples_fitting(spec, assays, calibrated=False)
        calibrated = False
        if s < n:
            calibrated = spec.calibrator
            s = _samples_fitting(spec, assays, calibrated)
        if s < n_groups:  # a plate must hold at least one sample of every group
            continue
        batches = math.ceil(n / min(s, n))
        if batches == 1:
            calibrated = False
        per_plate = math.ceil(n / batches)
        shape = Shape(_split(spec.genes, panels), batches, per_plate, calibrated)
        key = (shape.n_plates, batches, panels)
        if best is None or key < best[0]:
            best = (key, shape)
    if best is None:
        controls = _controls_per_assay(spec, spec.calibrator)
        raise LayoutError(
            f"a {spec.plate_size}-well plate cannot hold one gene and the {len(spec.refs)} "
            f"reference gene(s) for one sample of each of the {n_groups} groups with "
            f"{spec.replicates} replicate(s) and {controls} control well(s) per assay: use "
            "384-well plates, fewer replicates, fewer reference genes or fewer controls"
        )
    shape = best[1]
    if shape.n_plates > MAX_PLATES:
        raise LayoutError(
            f"this plan needs {shape.n_plates} plates of {spec.plate_size} wells (at most "
            f"{MAX_PLATES} are laid out here): plan fewer samples or genes, or 384-well plates"
        )
    return shape


def plates_needed(spec: LayoutSpec) -> int:
    """The number of plates :func:`make_layout` would use (cheap: no well is assigned)."""
    return plan_shape(spec).n_plates


# ---- assigning wells ---------------------------------------------------------------------------


def sample_names(spec: LayoutSpec) -> dict[str, list[str]]:
    """The plan's sample names per group: ``<group>-01`` … (zero-padded to the largest group)."""
    width = max(2, len(str(max(n for _, n in spec.groups))))
    return {g: [f"{g}-{i:0{width}d}" for i in range(1, n + 1)] for g, n in spec.groups}


def _batches(
    spec: LayoutSpec, names: Mapping[str, list[str]], batches: int, rng: random.Random
) -> list[list[tuple[str, str]]]:
    """Samples dealt to batches group by group (shuffled first), so every batch is balanced.

    The dealing continues where the previous group stopped, so batch sizes differ by at most
    one and each group's count per batch differs by at most one.
    """
    out: list[list[tuple[str, str]]] = [[] for _ in range(batches)]
    at = 0
    for group, _ in spec.groups:
        members = list(names[group])
        rng.shuffle(members)
        for sample in members:
            out[at % batches].append((group, sample))
            at += 1
    return out


def _positions(spec: LayoutSpec | RepeatSpec) -> list[str]:
    rows, cols = PLATE_SHAPES[spec.plate_size]
    letters = "ABCDEFGHIJKLMNOP"[:rows]
    return [f"{letters[r]}{c + 1}" for c in range(cols) for r in range(rows)]


def _plate(
    spec: LayoutSpec,
    number: int,
    panel: int,
    batch: int,
    genes: tuple[str, ...],
    members: list[tuple[str, str]],
    calibrated: bool,
    rng: random.Random,
) -> Plate:
    order = list(members)
    rng.shuffle(order)  # position on the plate is not group
    assays = genes + spec.refs
    reps = range(1, spec.replicates + 1)
    rows: list[tuple[str, str, str, str, int]] = []  # sample, group, target, type, replicate
    for group, sample in order:
        rows.extend((sample, group, a, "unkn", r) for a in assays for r in reps)
    if calibrated:
        rows.extend((IRC, "", a, "pos", r) for a in assays for r in reps)
    for point in range(1, spec.standards + 1):
        rows.extend((f"STD-{point}", "", a, "std", r) for a in assays for r in reps)
    rows.extend((NRT, "", a, "nrt", r) for a in assays for r in range(1, spec.nrt + 1))
    rows.extend((NTC, "", a, "ntc", r) for a in assays for r in range(1, spec.ntc + 1))
    positions = _positions(spec)
    if len(rows) > len(positions):  # plan_shape guarantees this never happens
        raise LayoutError(f"plate {number} would need {len(rows)} wells")
    wells = tuple(
        Well(number, pos, sample, group, target, kind, rep)
        for pos, (sample, group, target, kind, rep) in zip(positions, rows, strict=False)
    )
    return Plate(
        number=number,
        panel=panel,
        batch=batch,
        genes=genes,
        refs=spec.refs,
        samples=tuple(s for _, s in order),
        wells=wells,
        size=spec.plate_size,
    )


def make_layout(spec: LayoutSpec) -> Layout:
    """Every plate of the planned experiment, balanced, randomised and reproducible.

    Raises:
        LayoutError: The spec is out of range or cannot fit (see :func:`plan_shape`).
    """
    spec = check_spec(spec)
    shape = plan_shape(spec)
    rng = random.Random(f"qpilot-layout:{spec.seed}")
    names = sample_names(spec)
    batches = _batches(spec, names, shape.batches, rng)
    plates = []
    number = 0
    for p, genes in enumerate(shape.panels, start=1):
        for b, members in enumerate(batches, start=1):
            number += 1
            plates.append(_plate(spec, number, p, b, genes, members, shape.calibrated, rng))
    balance = measure(spec, plates)
    return Layout(
        spec=spec,
        shape=shape,
        plates=tuple(plates),
        balance=balance,
        notes=tuple(_notes(spec, shape)),
        warnings=tuple(_warnings(spec, shape, balance)),
    )


# ---- balance -----------------------------------------------------------------------------------


def _edge(well: str, plate_size: int) -> bool:
    rows, cols = PLATE_SHAPES[plate_size]
    row = ord(well[0]) - ord("A")
    col = int(well[1:]) - 1
    return row in (0, rows - 1) or col in (0, cols - 1)


def _cramers_v(table: list[list[int]]) -> float:
    """Cramér's V of a contingency table (0: no association; 1: one decides the other)."""
    rows = [r for r in table if sum(r)]
    if len(rows) < 2:
        return 0.0
    cols = [j for j in range(len(rows[0])) if sum(r[j] for r in rows)]
    if len(cols) < 2:
        return 0.0
    total = sum(sum(r) for r in rows)
    row_sum = [sum(r) for r in rows]
    col_sum = [sum(r[j] for r in rows) for j in cols]
    chi2 = 0.0
    for i, r in enumerate(rows):
        for jj, j in enumerate(cols):
            expected = row_sum[i] * col_sum[jj] / total
            chi2 += (r[j] - expected) ** 2 / expected
    return math.sqrt(chi2 / (total * (min(len(rows), len(cols)) - 1)))


def measure(spec: LayoutSpec, plates: Sequence[Plate]) -> Balance:
    """The balance of a layout: groups per plate, references and controls, every reaction once.

    A sample's reference genes are run again on each gene panel's plate (each plate normalises
    its own samples), so a reference reaction counts once per panel; a gene reaction, once.
    """
    labels = [g for g, _ in spec.groups]
    out = []
    table = []
    seen: dict[tuple[str, str, int], int] = {}
    controls_ok = True
    for plate in plates:
        samples = {g: 0 for g in labels}
        counted: set[str] = set()
        controls: dict[str, int] = {}
        edge = {g: [0, 0] for g in labels}
        for w in plate.wells:
            if w.type == "unkn":
                key = (w.sample, w.target, w.replicate)
                seen[key] = seen.get(key, 0) + 1
                if w.sample not in counted:
                    counted.add(w.sample)
                    samples[w.group] += 1
                edge[w.group][0] += _edge(w.well, plate.size)
                edge[w.group][1] += 1
            else:
                controls[w.type] = controls.get(w.type, 0) + 1
        targets = {w.target for w in plate.wells if w.type == "unkn"}
        assays = set(plate.genes) | set(plate.refs)
        refs_present = set(plate.refs) <= targets
        for kind, per in (("ntc", spec.ntc), ("nrt", spec.nrt)):
            have = {w.target for w in plate.wells if w.type == kind}
            if per and have != assays:
                controls_ok = False
        out.append(
            PlateBalance(
                number=plate.number,
                wells_used=len(plate.wells),
                wells_free=plate.size - len(plate.wells),
                samples=samples,
                groups_present=sum(1 for v in samples.values() if v),
                refs_present=refs_present,
                controls=controls,
                edge_share={g: (e / t if t else None) for g, (e, t) in edge.items()},
            )
        )
        table.append([samples[g] for g in labels])
    panels = len({p.panel for p in plates}) or 1
    expected = {
        (s, a, r): (panels if a in spec.refs else 1)
        for names in sample_names(spec).values()
        for s in names
        for a in spec.genes + spec.refs
        for r in range(1, spec.replicates + 1)
    }
    once = seen == expected
    totals = [sum(col) for col in zip(*table, strict=True)] if table else []
    grand = sum(totals) or 1
    gap = 0.0
    for row in table:
        n_plate = sum(row)
        if not n_plate:
            continue
        for j, v in enumerate(row):
            gap = max(gap, abs(v / n_plate - totals[j] / grand))
    one_group = tuple(b.number for b in out if b.groups_present < 2)
    used = sum(b.wells_used for b in out)
    controls_total = sum(sum(b.controls.values()) for b in out)
    return Balance(
        plates=tuple(out),
        every_plate_every_group=all(b.groups_present == len(labels) for b in out),
        plates_with_one_group=one_group,
        refs_on_every_plate=all(b.refs_present for b in out),
        controls_on_every_plate=controls_ok and all(b.controls for b in out),
        each_reaction_once=once,
        group_plate_association=_cramers_v([list(r) for r in table]),
        max_share_gap=gap,
        wells_total=sum(p.size for p in plates),
        wells_samples=used - controls_total,
        wells_controls=controls_total,
        wells_free=sum(b.wells_free for b in out),
    )


def _notes(spec: LayoutSpec, shape: Shape) -> list[str]:
    n_plates, reps = shape.n_plates, spec.replicates
    lines = [
        f"{n_plates} plate{'s' * (n_plates != 1)} of {spec.plate_size} wells: the "
        f"{len(spec.genes)} gene{'s' * (len(spec.genes) != 1)} in {len(shape.panels)} "
        f"panel{'s' * (len(shape.panels) != 1)} × the {spec.n_samples} samples in "
        f"{shape.batches} batch{'es' * (shape.batches != 1)}; every sample in {reps} "
        f"replicate{'s' * (reps != 1)} per assay.",
        f"Every plate carries the reference gene{'s' * (len(spec.refs) != 1)} "
        f"({', '.join(spec.refs)}) for its own samples, so each sample is normalised within "
        "its plate.",
    ]
    if shape.batches == 1:
        lines.append(
            "Each gene's samples are all on one plate (sample maximisation, Hellemans 2007): its "
            "comparison between groups is made within one run, so no inter-run calibrator is "
            "needed."
        )
    elif shape.calibrated:
        lines.append(
            "A gene's samples span plates, so the same inter-run calibrator (IRC) is on every "
            "plate for every assay: it links the runs (Hellemans 2007)."
        )
    lines.append(
        "Samples are dealt to plates group by group in a random order (seeded), and shuffled "
        "within each plate, so neither plate nor position is group."
    )
    return lines


def _warnings(spec: LayoutSpec, shape: Shape, balance: Balance) -> list[str]:
    out = []
    if shape.batches > 1 and not shape.calibrated:
        out.append(
            "A gene's samples span plates and there is no inter-run calibrator: plate effects "
            "add to the comparison. Turn the calibrator on, or use 384-well plates."
        )
    if balance.plates_with_one_group:
        small = min(n for _, n in spec.groups)
        out.append(
            f"{len(balance.plates_with_one_group)} plate(s) hold only one group, because the "
            f"smallest group has {small} samples for {shape.batches} batches: on those plates "
            "plate and group cannot be told apart."
        )
    if spec.ntc == 0:
        out.append("No NTC wells: contamination of a reagent cannot be seen on these plates.")
    return out


# ---- the repeat plate: the reactions a run review says to re-run ---------------------------------

POS = "POS"
MAX_REPEAT_REACTIONS = 2_000  # sample x assay pairs on one repeat layout


@dataclass(frozen=True)
class RepeatSpec:
    """The reactions to re-run after a run, and the controls their plate carries.

    Attributes:
        reactions: ``(sample, group, target)`` to re-run (the study's own names; group may be "").
        refs: The reference genes: every repeated sample is run with all of them, on its plate.
        calibrator: The inter-run calibrator: a sample of the original run, on every plate for
            every assay, which links the repeat to the original runs (Hellemans 2007).
        replicates: Technical replicates per sample and assay (the calibrator's too).
        plate_size: 96 or 384 wells.
        ntc: No-template control wells per assay per plate.
        nrt: No-RT control wells per assay per plate.
        positive: Assays that get a positive control well (``POS``) on every plate they are on.
        seed: The random order's seed (the same seed gives the same plates).
    """

    reactions: tuple[tuple[str, str, str], ...]
    refs: tuple[str, ...]
    calibrator: str = IRC
    replicates: int = 2
    plate_size: int = 96
    ntc: int = 1
    nrt: int = 1
    positive: tuple[str, ...] = ()
    seed: int = 0


@dataclass(frozen=True)
class RepeatLayout:
    """The repeat plates: every repeated sample with its reference genes, and the controls."""

    spec: RepeatSpec
    plates: tuple[Plate, ...]
    notes: tuple[str, ...]
    warnings: tuple[str, ...] = field(default_factory=tuple)

    def wells(self) -> list[Well]:
        """Every well of every plate, plate by plate."""
        return [w for p in self.plates for w in p.wells]


def _repeat_controls(
    spec: RepeatSpec, assays: Iterable[str]
) -> list[tuple[str, str, str, str, int]]:
    """Per assay: the calibrator in replicates, a positive control, the NRT and the NTC wells."""
    rows: list[tuple[str, str, str, str, int]] = []
    assays = list(assays)
    reps = range(1, spec.replicates + 1)
    rows.extend((spec.calibrator, "", a, "pos", r) for a in assays for r in reps)
    rows.extend((POS, "", a, "pos", 1) for a in assays if a in spec.positive)
    rows.extend((NRT, "", a, "nrt", r) for a in assays for r in range(1, spec.nrt + 1))
    rows.extend((NTC, "", a, "ntc", r) for a in assays for r in range(1, spec.ntc + 1))
    return rows


def make_repeat_layout(spec: RepeatSpec) -> RepeatLayout:
    """The repeat plates: as few as hold the reactions, each sample whole on one plate.

    Each repeated sample is run for its targets and every reference gene on the same plate (so
    it is normalised within the plate); each plate carries, per assay on it, the inter-run
    calibrator, a positive control where the original run had one, the no-RT and the
    no-template controls. Samples are dealt to plates in a seeded random order (position is
    not group) and fill the wells down the columns, the plate's controls last, as
    :func:`make_layout` does.

    Raises:
        LayoutError: Nothing to repeat, a name a CSV cannot carry, a value out of range, or
            one sample's reactions and their controls do not fit on one plate.
    """
    if spec.plate_size not in PLATE_SHAPES:
        raise LayoutError("plates have 96 or 384 wells")
    if not 1 <= spec.replicates <= MAX_REPLICATES:
        raise LayoutError(f"technical replicates are 1 to {MAX_REPLICATES}")
    for value, what in ((spec.ntc, "NTC wells per assay"), (spec.nrt, "NRT wells per assay")):
        if not 0 <= value <= MAX_PER_ASSAY:
            raise LayoutError(f"{what} are 0 to {MAX_PER_ASSAY}")
    if not spec.reactions:
        raise LayoutError("nothing to repeat")
    if len(spec.reactions) > MAX_REPEAT_REACTIONS:
        raise LayoutError(f"at most {MAX_REPEAT_REACTIONS:,} reactions in one repeat layout")
    refs = _unique(_name(r, "The reference gene") for r in spec.refs)
    calibrator = _name(spec.calibrator, "The calibrator")
    spec = RepeatSpec(
        reactions=spec.reactions,
        refs=refs,
        calibrator=calibrator,
        replicates=spec.replicates,
        plate_size=spec.plate_size,
        ntc=spec.ntc,
        nrt=spec.nrt,
        positive=tuple(spec.positive),
        seed=int(spec.seed),
    )
    targets: dict[str, list[str]] = {}
    groups: dict[str, str] = {}
    for sample, group, target in spec.reactions:
        sample = _name(sample, "The sample")
        targets.setdefault(sample, [])
        if target not in refs:
            targets[sample].append(_name(target, "The gene"))
        groups[sample] = str(group or "")
    if calibrator in targets:
        raise LayoutError("the calibrator is a sample to repeat: choose another sample")
    blocks = {
        s: [*_unique(sorted(t)), *refs] if refs else _unique(sorted(t)) for s, t in targets.items()
    }
    order = sorted(blocks)
    rng = random.Random(f"qpilot-repeat:{spec.seed}")
    rng.shuffle(order)
    positions = _positions(spec)
    plates: list[list[str]] = [[]]
    for sample in order:
        current = plates[-1]
        trial = [*current, sample]
        if _repeat_rows(spec, trial, blocks) > len(positions):
            if not current:
                raise LayoutError(
                    f"sample {sample}'s {len(blocks[sample])} assays in {spec.replicates} "
                    f"replicate(s) and their controls do not fit on a {spec.plate_size}-well "
                    "plate: use 384-well plates or fewer replicates"
                )
            plates.append([sample])
            if _repeat_rows(spec, [sample], blocks) > len(positions):
                raise LayoutError(
                    f"sample {sample}'s assays and their controls do not fit on a "
                    f"{spec.plate_size}-well plate: use 384-well plates or fewer replicates"
                )
        else:
            plates[-1] = trial
    if len(plates) > MAX_PLATES:
        raise LayoutError(f"the repeat needs more than {MAX_PLATES} plates: repeat fewer samples")
    built = []
    for number, members in enumerate(plates, start=1):
        assays = _unique(a for s in members for a in blocks[s])
        rows = [
            (s, groups[s], a, "unkn", r)
            for s in members
            for a in blocks[s]
            for r in range(1, spec.replicates + 1)
        ]
        rows += _repeat_controls(spec, assays)
        wells = tuple(
            Well(number, pos, sample, group, target, kind, rep)
            for pos, (sample, group, target, kind, rep) in zip(positions, rows, strict=False)
        )
        built.append(
            Plate(
                number=number,
                panel=1,
                batch=number,
                genes=tuple(a for a in assays if a not in refs),
                refs=tuple(refs),
                samples=tuple(members),
                wells=wells,
                size=spec.plate_size,
            )
        )
    return RepeatLayout(
        spec=spec,
        plates=tuple(built),
        notes=tuple(_repeat_notes(spec, built)),
        warnings=tuple(_repeat_warnings(spec)),
    )


def _repeat_rows(
    spec: RepeatSpec, members: Sequence[str], blocks: Mapping[str, Sequence[str]]
) -> int:
    assays = _unique(a for s in members for a in blocks[s])
    samples = sum(len(blocks[s]) for s in members) * spec.replicates
    return samples + len(_repeat_controls(spec, assays))


def _repeat_notes(spec: RepeatSpec, plates: Sequence[Plate]) -> list[str]:
    n_samples = sum(len(p.samples) for p in plates)
    n_plates, reps = len(plates), spec.replicates
    lines = [
        f"{n_plates} plate{'s' * (n_plates != 1)} of {spec.plate_size} wells for "
        f"{n_samples} sample{'s' * (n_samples != 1)}, each in {reps} "
        f"replicate{'s' * (reps != 1)} per assay.",
    ]
    if spec.refs:
        lines.append(
            f"Every repeated sample is run with the reference gene{'s' * (len(spec.refs) != 1)} "
            f"({', '.join(spec.refs)}) on its own plate, so it is normalised within the plate."
        )
    lines.append(
        f"Every plate carries, for every assay on it, the inter-run calibrator {spec.calibrator} "
        f"in {reps} replicate{'s' * (reps != 1)}: a sample of the original run, so the repeat "
        "can be put on the scale of the original runs (Hellemans 2007)."
    )
    controls = []
    if spec.positive:
        controls.append(f"a positive control ({POS}) where the original run had one")
    if spec.nrt:
        controls.append(f"{spec.nrt} no-RT control well{'s' * (spec.nrt != 1)} ({NRT})")
    if spec.ntc:
        controls.append(f"{spec.ntc} no-template control well{'s' * (spec.ntc != 1)} ({NTC})")
    if controls:
        lines.append("Per assay and plate, too: " + ", ".join(controls) + ".")
    lines.append(
        "Samples are dealt to the plates in a random order (seeded); rename the controls in the "
        "CSV to your own tubes."
    )
    return lines


def _repeat_warnings(spec: RepeatSpec) -> list[str]:
    out = []
    if spec.calibrator == IRC:
        out.append(
            "No sample of the original run could be named as the inter-run calibrator: rename IRC "
            "in the CSV to a sample that was on the original plates."
        )
    if spec.ntc == 0:
        out.append("No NTC wells: contamination of a reagent cannot be seen on these plates.")
    return out


# ---- the CSV -----------------------------------------------------------------------------------


def layout_csv(layout: Layout | RepeatLayout) -> str:
    """The layout as CSV: plate, well, sample, group, target, type (one row per well)."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(CSV_COLUMNS)
    for w in layout.wells():
        writer.writerow([w.plate, w.well, w.sample, w.group, w.target, w.type])
    return buffer.getvalue()


def read_layout_csv(text: str) -> list[tuple[int, str, str, str, str, str]]:
    """Read :func:`layout_csv`'s rows back as ``(plate, well, sample, group, target, type)``.

    Raises:
        LayoutError: The header is not the layout's.
    """
    reader = csv.reader(io.StringIO(text))
    header = next(reader, None)
    if tuple(header or ()) != CSV_COLUMNS:
        raise LayoutError(
            f"not a qPilot layout CSV (expected the columns {', '.join(CSV_COLUMNS)})"
        )
    return [(int(p), w, s, g, t, k) for p, w, s, g, t, k in reader]
