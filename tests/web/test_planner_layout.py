"""Plate layouts, property by property, over many seeds and sizes (``qpilot.qpcr.layout``).

Every layout, whatever the seed, the group sizes, the panel, the replicates, the controls and the
plate size: every well used at most once and every planned reaction exactly once; the reference
genes and the controls on every plate; no plate holds only one group whenever the smallest group
can reach every plate (and the layout says so when it cannot); groups balanced across plates to
within one sample; the same seed gives the same plates; the CSV reads back to the same wells.
"""

from __future__ import annotations

import random

import pytest

from qpilot.qpcr import layout as lay

GENES = tuple(f"G{i}" for i in range(1, 13))
REFS = ("HMBS", "SDHA(1)", "UBC(2)")


def _specs(count: int) -> list[lay.LayoutSpec]:
    """Seeded random specs across the space (sizes, panels, replicates, controls, plates)."""
    rng = random.Random(20261020)
    out = []
    while len(out) < count:
        n_groups = rng.choice((2, 2, 2, 3))
        spec = lay.LayoutSpec(
            groups=tuple((f"grp{g}", rng.randint(2, 40)) for g in range(n_groups)),
            genes=GENES[: rng.randint(1, 8)],
            refs=REFS[: rng.randint(1, 3)],
            replicates=rng.randint(1, 3),
            plate_size=rng.choice((96, 384)),
            ntc=rng.randint(0, 2),
            nrt=rng.randint(0, 1),
            standards=rng.choice((0, 0, 1, 3)),
            calibrator=rng.random() < 0.8,
            seed=rng.randint(0, 10_000),
        )
        try:
            lay.plan_shape(spec)
        except lay.LayoutError:
            continue  # too big for the plates laid out here: refused, tested below
        out.append(spec)
    return out


SPECS = _specs(160)


@pytest.mark.parametrize("spec", SPECS, ids=lambda s: f"seed{s.seed}-{s.plate_size}")
def test_every_layout_keeps_its_promises(spec):
    layout = lay.make_layout(spec)
    b = layout.balance
    rows, cols = lay.PLATE_SHAPES[spec.plate_size]
    assays = set(spec.genes) | set(spec.refs)
    for plate in layout.plates:
        positions = [w.well for w in plate.wells]
        assert len(positions) == len(set(positions)) <= rows * cols  # every well once at most
        targets = {w.target for w in plate.wells if w.type == "unkn"}
        assert set(spec.refs) <= targets  # reference genes on every plate
        for kind, per in (("ntc", spec.ntc), ("nrt", spec.nrt)):
            have = [w.target for w in plate.wells if w.type == kind]
            assert sorted(have) == sorted(
                a for a in set(plate.genes) | set(spec.refs) for _ in range(per)
            )
        std = [w for w in plate.wells if w.type == "std"]
        assert len(std) == spec.standards * spec.replicates * (len(plate.genes) + len(spec.refs))
        irc = [w for w in plate.wells if w.type == "pos"]
        assert bool(irc) == layout.shape.calibrated
        assert {w.target for w in plate.wells} <= assays
    # every planned reaction exactly once (a reference gene's once per gene panel)
    panels = len(layout.shape.panels)
    planned = {
        (s, a, r): panels if a in spec.refs else 1
        for names in lay.sample_names(spec).values()
        for s in names
        for a in spec.genes + spec.refs
        for r in range(1, spec.replicates + 1)
    }
    done: dict[tuple[str, str, int], int] = {}
    for w in layout.wells():
        if w.type == "unkn":
            key = (w.sample, w.target, w.replicate)
            done[key] = done.get(key, 0) + 1
    assert done == planned
    assert b.each_reaction_once and b.refs_on_every_plate
    # a sample's assays share its plate (normalised within the plate)
    for plate in layout.plates:
        for sample in plate.samples:
            mine = {w.target for w in plate.wells if w.sample == sample}
            assert mine == set(plate.genes) | set(spec.refs)
    # groups: balanced to within one sample per plate, never one group alone when avoidable
    smallest = min(n for _, n in spec.groups)
    for pb in b.plates:
        for label, n in spec.groups:
            share = n / layout.shape.batches
            assert abs(pb.samples[label] - share) < 1
    if smallest >= layout.shape.batches:
        assert b.every_plate_every_group and b.plates_with_one_group == ()
    elif b.plates_with_one_group:
        assert any("only one group" in w for w in layout.warnings)
    assert 0.0 <= b.group_plate_association <= 1.0
    if layout.shape.batches == 1:
        assert b.group_plate_association == 0.0 and not layout.shape.calibrated
    assert b.wells_samples + b.wells_controls + b.wells_free == b.wells_total
    assert len(layout.plates) == layout.shape.n_plates <= lay.MAX_PLATES


@pytest.mark.parametrize("spec", SPECS[:40], ids=lambda s: f"seed{s.seed}")
def test_the_same_seed_gives_the_same_plates_and_the_csv_reads_back(spec):
    first, second = lay.make_layout(spec), lay.make_layout(spec)
    assert first.wells() == second.wells()
    text = lay.layout_csv(first)
    assert text.splitlines()[0] == ",".join(lay.CSV_COLUMNS)
    back = lay.read_layout_csv(text)
    assert back == [(w.plate, w.well, w.sample, w.group, w.target, w.type) for w in first.wells()]


def test_a_new_seed_reorders_the_samples():
    spec = SPECS[0]
    a = lay.make_layout(spec)
    b = lay.make_layout(lay.LayoutSpec(**{**spec.__dict__, "seed": spec.seed + 1}))
    assert [w.sample for w in a.wells()] != [w.sample for w in b.wells()]
    assert sorted(w.sample for w in a.wells()) == sorted(w.sample for w in b.wells())


def test_all_samples_on_one_plate_need_no_calibrator():
    spec = lay.LayoutSpec((("WT", 6), ("KO", 6)), ("ODC1",), ("HMBS", "SDHA(1)"), 2, 384)
    layout = lay.make_layout(spec)
    assert layout.shape.batches == 1 and not layout.shape.calibrated
    assert len(layout.plates) == 1 and layout.balance.group_plate_association == 0.0
    assert any("sample maximisation" in n for n in layout.notes)


def test_spanning_plates_puts_a_calibrator_on_every_plate_or_warns():
    big = (("WT", 30), ("KO", 30))
    with_irc = lay.make_layout(lay.LayoutSpec(big, ("ODC1", "MYCN"), ("HMBS",), 2, 96))
    assert with_irc.shape.batches > 1 and with_irc.shape.calibrated
    for plate in with_irc.plates:
        irc = {w.target for w in plate.wells if w.sample == lay.IRC}
        assert irc == set(plate.genes) | {"HMBS"}
    without = lay.make_layout(
        lay.LayoutSpec(big, ("ODC1", "MYCN"), ("HMBS",), 2, 96, calibrator=False)
    )
    assert not without.shape.calibrated
    assert any("no inter-run calibrator" in w for w in without.warnings)


def test_the_fewest_plates_are_used():
    spec = lay.LayoutSpec((("A", 12), ("B", 12)), GENES[:4], REFS, 2, 96)
    shape = lay.plan_shape(spec)
    # no other cut of the panel uses fewer plates
    for k in range(1, 5):
        assays = k + len(REFS)
        per_assay = spec.ntc + spec.replicates  # NTC + calibrator
        s = (96 - assays * per_assay) // (assays * spec.replicates)
        if s >= 2:
            assert shape.n_plates <= -(-4 // k) * -(-24 // s)


def test_a_labs_own_group_names_are_laid_out_as_written():
    groups = (("LPS + inhibitor", 3), ("IL-6/ctrl", 3), ("Day 3 (50 µM)", 3), ("KO#2", 3))
    layout = lay.make_layout(
        lay.LayoutSpec(groups=groups, genes=("α-syn",), refs=("R1",), replicates=2)
    )
    rows = lay.read_layout_csv(lay.layout_csv(layout))
    assert {g for _, _, _, g, _, _ in rows if g} == {g for g, _ in groups}
    assert "α-syn" in {t for *_, t, _ in rows}


@pytest.mark.parametrize(
    ("change", "words"),
    [
        ({"groups": (("A", 1), ("B", 4))}, "2 to"),
        ({"groups": (("A", 4),)}, "2 to"),
        ({"genes": ()}, "at least one gene"),
        ({"refs": ()}, "reference gene"),
        ({"genes": ("=HYPERLINK(1)",)}, "cannot go into a plate layout"),
        ({"genes": ("-A1",)}, "not starting with -"),
        ({"genes": ("NTC",)}, "control names"),
        ({"plate_size": 100}, "96 or 384"),
        ({"replicates": 0}, "replicates"),
        ({"ntc": 9}, "NTC"),
        ({"groups": (("A", 900), ("B", 900)), "replicates": 6}, "plates"),
        ({"genes": ("G1",), "refs": REFS * 1, "replicates": 6, "standards": 8}, "cannot hold"),
    ],
)
def test_impossible_layouts_are_refused_in_words(change, words):
    base = dict(groups=(("A", 4), ("B", 4)), genes=("G1",), refs=("R1",), replicates=2)
    with pytest.raises(lay.LayoutError, match=words):
        lay.make_layout(lay.LayoutSpec(**{**base, **change}))


def test_a_gene_named_as_a_reference_is_measured_once_as_a_reference():
    spec = lay.LayoutSpec((("A", 3), ("B", 3)), ("G1", "R1"), ("R1",), 1, 96)
    layout = lay.make_layout(spec)
    assert layout.spec.genes == ("G1",)
    done = [(w.sample, w.target) for w in layout.wells() if w.type == "unkn"]
    assert len(done) == len(set(done)) == 6 * 2


def test_csv_with_another_header_is_refused():
    with pytest.raises(lay.LayoutError):
        lay.read_layout_csv("a,b\n1,2\n")
