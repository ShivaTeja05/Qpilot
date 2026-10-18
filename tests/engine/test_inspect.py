"""qpcr_inspect: what qPilot knows about a file before any design, with every name quarantined."""

import pytest

from qpilot.io import sheets
from qpilot.io.sheets import SheetError
from qpilot.qpcr import inspect as qinspect
from qpilot.qpcr.inspect import file_facts, inspect
from qpilot.schemas_studio import text_id_for
from tests.fixtures.studio.studio_mini import INJECTION, write_studio_mini


@pytest.fixture
def mini(tmp_path):
    return write_studio_mini(tmp_path / "studio_mini.rdml")


@pytest.fixture
def cache(tmp_path):
    qinspect.clear_cache()
    yield tmp_path / "cache"
    qinspect.clear_cache()


def test_summary_of_the_synthetic_file(mini, cache):
    summary, quarantine = inspect(mini, cache_dir=cache)
    assert summary.n_samples == 10
    assert summary.declared_types == {"ntc": 1, "unkn": 9}
    assert summary.experiments == {"mini_set": 2}
    assert [(r.run_id, r.n_wells, r.targets) for r in summary.runs] == [
        ("GAPDH_plate", 30, ["GAPDH"]),
        ("1-Mar_plate", 30, ["1-Mar"]),
    ]
    targets = {t.target: t for t in summary.targets}
    assert targets["GAPDH"].declared_type == "ref"
    assert targets["GAPDH"].n_wells == 30 and targets["GAPDH"].n_with_cq == 24
    assert targets["1-Mar"].n_with_cq == 25  # one late NTC well
    assert 1.7 < targets["GAPDH"].eff_median < 2.0
    water = next(s for s in summary.samples if s.sample == "water")
    assert water.declared_type == "unkn" and water.n_wells == 6
    assert water.targets == ["1-Mar", "GAPDH"] and water.experiments == ["mini_set"]
    assert summary.input_sha256 == file_facts(mini, cache_dir=cache).sha256


def test_every_name_is_quarantined_and_cited_by_text_id(mini, cache):
    summary, quarantine = inspect(mini, cache_dir=cache)
    by_id = {e.text_id: e for e in quarantine}
    assert len(by_id) == len(quarantine)  # deduplicated
    for sample in summary.samples:
        entry = by_id[sample.text_id]
        assert entry.origin == "rdml:sample.id"
        assert sample.text_id == text_id_for("rdml:sample.id", entry.value)
    for target in summary.targets:
        assert by_id[target.text_id].origin == "rdml:target.id"
    origins = {e.origin for e in quarantine}
    assert {"rdml:sample.id", "rdml:target.id", "rdml:experiment.id", "rdml:run.id"} <= origins
    injected = [e for e in quarantine if e.value == INJECTION]
    assert len(injected) == 1 and injected[0].origin == "rdml:sample.id"
    assert injected[0].flags == []  # flagging instruction-like text is the firewall's job


def test_unsafe_names_become_safe_identifiers(tmp_path, cache):
    path = write_studio_mini(tmp_path / "unsafe.rdml", rename={"KO_2": "KO/2 <script>"})
    summary, quarantine = inspect(path, cache_dir=cache)
    names = [s.sample for s in summary.samples]
    assert "KO/2 <script>" not in names and "ko_2_script" in names
    assert any(e.value == "KO/2 <script>" for e in quarantine)
    assert any("not plain identifiers" in note for note in summary.notes)


def test_results_are_cached_and_returned_as_copies(mini, cache):
    first, _ = inspect(mini, cache_dir=cache)
    first.samples.clear()
    second, _ = inspect(mini, cache_dir=cache)
    assert second.n_samples == len(second.samples) == 10
    assert qinspect.cached_facts(second.input_sha256[:8]) is not None


def test_sheet_cells_join_the_summary(mini, cache, tmp_path):
    sheet = tmp_path / "samples.csv"
    sheet.write_text("Sample,Group\nWT_1,WT\nKO_1,KO\n", encoding="utf-8")
    summary, quarantine = inspect(mini, sheet, cache_dir=cache)
    assert summary.sheet_sha256 is not None
    assert [c.cell for c in summary.sheet][:2] == ["samples!A1", "samples!B1"]
    ids = {e.text_id for e in quarantine}
    assert all(c.text_id in ids for c in summary.sheet)
    assert any(e.origin == "sheet:samples.csv!samples!B3" for e in quarantine)


def test_a_cached_sheet_is_never_read_again(mini, cache, tmp_path, monkeypatch):
    """Every Studio render asks for the facts; the sheet is parsed once per content."""
    reads = []
    real = qinspect.read_sheet
    monkeypatch.setattr(qinspect, "read_sheet", lambda path: reads.append(path) or real(path))
    sheet = tmp_path / "samples.csv"
    sheet.write_text("Sample,Group\nWT_1,WT\nKO_1,KO\n", encoding="utf-8")
    first = file_facts(mini, sheet, cache_dir=cache)
    for _ in range(3):
        assert file_facts(mini, sheet, cache_dir=cache) is first
    assert len(reads) == 1
    sheet.write_text("Sample,Group\nWT_1,KO\nKO_1,WT\n", encoding="utf-8")  # new content
    assert file_facts(mini, sheet, cache_dir=cache) is not first
    assert len(reads) == 2
    with pytest.raises(SheetError, match="not a file"):
        file_facts(mini, tmp_path / "missing.csv", cache_dir=cache)
    big = tmp_path / "big.csv"
    big.write_bytes(b"x" * 10)
    monkeypatch.setattr(sheets, "MAX_FILE_BYTES", 5)
    with pytest.raises(SheetError, match="too large"):
        file_facts(mini, big, cache_dir=cache)  # refused before it is hashed or read
    assert len(reads) == 2


def test_a_file_without_raw_curves_is_still_summarised(smoke_rdml, cache):
    summary, _ = inspect(smoke_rdml, cache_dir=cache)
    assert summary.n_samples == 50
    assert summary.runs[0].n_wells == 50
    assert summary.targets[0].n_with_cq == 0 and summary.targets[0].eff_median is None
    assert any("LinRegPCR could not analyse" in note for note in summary.notes)


def test_real_vermeulen_fixture(fixtures_dir, cache):
    summary, _ = inspect(fixtures_dir / "vermeulen_std_150000.rdml", cache_dir=cache)
    assert summary.experiments == {"biomarker_set": 64}
    assert sum(r.n_wells for r in summary.runs) == 192
    std = next(s for s in summary.samples if s.sample == "STD_150000")
    assert std.declared_type == "std" and std.n_wells == 192


@pytest.mark.demo_data
def test_demo_file_counts(demo_rdml_path):
    """Plan step 3.2 gate, as measured (docs/studio-measured.md): 427 samples, not 425."""
    qinspect.clear_cache()
    summary, quarantine = inspect(demo_rdml_path)
    assert summary.n_samples == 427
    assert summary.declared_types == {"ntc": 9, "std": 9, "unkn": 409}
    assert summary.experiments == {"technical_datasets": 3, "biomarker_set": 64}
    biomarker = [r for r in summary.runs if r.experiment_id == "biomarker_set"]
    assert len(biomarker) == 64 and sum(r.n_wells for r in biomarker) == 24_576
    technical = {r.run_id: r for r in summary.runs if r.experiment_id == "technical_datasets"}
    assert set(technical) == {
        "94_replicates_4_dilutions_set",
        "380_replicates_set",
        "competimer_set",
    }
    assert technical["competimer_set"].n_wells == 147
    stds = sorted(s.sample for s in summary.samples if s.declared_type == "std")
    assert stds == sorted(
        ["STDA15", "STDA150", "STDA1500", "STDA15000"]
        + ["STD_15", "STD_150", "STD_1500", "STD_15000", "STD_150000"]
    )
    sample_ids = [e for e in quarantine if e.origin == "rdml:sample.id"]
    assert len(sample_ids) == 427
