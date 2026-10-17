import json
import sys
import types
import zipfile

import pytest

from qpilot.core.record import (
    CHECKSUMS,
    RecordError,
    rerun,
    rerun_matches,
    unzip_record,
    verify,
    verify_chain,
    versions,
    write_record,
    zip_record,
)
from qpilot.core.store import sha256_file


@pytest.fixture
def rdml(tmp_path):
    path = tmp_path / "input.rdml"
    path.write_bytes(b"<rdml>fake input for record tests</rdml>")
    return path


@pytest.fixture
def study_with_input(store, rdml, fixture_result, fixture_cards):
    digest = sha256_file(rdml)
    result = fixture_result.model_copy(update={"input_sha256": digest, "study_id": digest[:12]})
    store.put(result, fixture_cards)
    store.set_source(result.study_id, rdml)
    for option, reason in [("top2", "two most stable"), ("recommended", "keep all five")]:
        store.append_decision(result.study_id, "card_refset", option, reason, "human", None)
    return result


@pytest.fixture
def fake_engine(monkeypatch, study_with_input, fixture_cards):
    """Stand-in for qpilot.qpcr.study until Dev 1's run_study lands."""
    module = types.ModuleType("qpilot.qpcr.study")
    module.run_study = lambda path, *a, **k: (study_with_input, fixture_cards)
    monkeypatch.setitem(sys.modules, "qpilot.qpcr.study", module)
    return module


@pytest.fixture
def record(store, study_with_input, tmp_path):
    out = tmp_path / "record"
    info = write_record(store, study_with_input.study_id, out)
    return out, info


def test_record_contents(record):
    out, info = record
    names = {p.name for p in out.iterdir()}
    assert {
        "results.json",
        "cards.json",
        "facts.json",
        "decisions.jsonl",
        "input.rdml",
        "design.json",
        "choices.json",
        "versions.json",
        "record.json",
        CHECKSUMS,
    } <= names
    assert info.input_included and info.n_files == len(names)
    choices = json.loads((out / "choices.json").read_text())
    assert choices["cards"]["card_refset"]["decision"] == "recommended"
    assert set(versions()) == set(json.loads((out / "versions.json").read_text()))


def test_checksums_list_every_file_but_itself(record):
    out, _ = record
    listed = {line.split("  ", 1)[1] for line in (out / CHECKSUMS).read_text().splitlines()}
    present = {p.name for p in out.iterdir() if p.name != CHECKSUMS}
    assert listed == present


def test_verify_ok(record):
    out, _ = record
    report = verify(out)
    assert report.ok, report.summary()
    assert report.n_entries == 3
    assert "3 entries, intact" in report.summary()


def test_tamper_one_byte_fails(record):
    out, _ = record
    path = out / "results.json"
    data = bytearray(path.read_bytes())
    data[10] ^= 1
    path.write_bytes(bytes(data))
    report = verify(out)
    assert not report.ok and report.changed == ["results.json"]


def test_edit_decision_two_reason_names_link_two(record):
    out, _ = record
    log = out / "decisions.jsonl"
    lines = log.read_text().splitlines()
    second = json.loads(lines[1])
    second["reason"] = "edited later"
    lines[1] = json.dumps(second, sort_keys=True, separators=(",", ":"))
    log.write_text("\n".join(lines) + "\n")
    report = verify(out)
    assert report.chain_broken_at == 2
    assert "broken at entry 2" in report.summary()


def test_verify_chain_detects_reorder(store, study_with_input):
    entries = store.entries(study_with_input.study_id)
    root = study_with_input.input_sha256
    assert verify_chain(entries, root) is None
    assert verify_chain([entries[1], entries[0], entries[2]], root) == 1
    assert verify_chain(entries, "0" * 64) == 1


def test_extra_file_is_reported(record):
    out, _ = record
    (out / "sneaky.txt").write_text("x")
    assert verify(out).unlisted == ["sneaky.txt"]


def test_rerun_is_byte_identical(record, fake_engine):
    out, _ = record
    path = rerun(out)
    assert path.read_bytes() == (out / "results.json").read_bytes()
    assert rerun_matches(out, out.parent / "again")


def test_rerun_needs_input(store, fixture_result, fixture_cards, tmp_path):
    store.put(fixture_result, fixture_cards)
    out = tmp_path / "noinput"
    info = write_record(store, fixture_result.study_id, out)
    assert not info.input_included
    assert verify(out).ok
    with pytest.raises(RecordError):
        rerun(out)


def test_write_into_non_empty_dir_refused(store, study_with_input, tmp_path):
    out = tmp_path / "busy"
    out.mkdir()
    (out / "x").write_text("x")
    with pytest.raises(RecordError):
        write_record(store, study_with_input.study_id, out)


def test_wrong_input_refused(store, study_with_input, tmp_path):
    other = tmp_path / "other.rdml"
    other.write_bytes(b"different")
    with pytest.raises(RecordError):
        write_record(store, study_with_input.study_id, tmp_path / "r2", rdml_path=other)
    with pytest.raises(ValueError):
        store.set_source(study_with_input.study_id, other)


def test_zip_round_trip(record, tmp_path):
    out, _ = record
    zipped = zip_record(out, tmp_path / "rec.zip")
    again = unzip_record(zipped, tmp_path / "unpacked")
    assert verify(again).ok
    assert zip_record(out, tmp_path / "rec2.zip").read_bytes() == zipped.read_bytes()


@pytest.mark.parametrize("bad", ["../x", "/etc/passwd", "a/../../x", "a\\..\\x"])
def test_zip_with_unsafe_path_refused(tmp_path, bad):
    zipped = tmp_path / "evil.zip"
    with zipfile.ZipFile(zipped, "w") as zf:
        zf.writestr(bad, "x")
    with pytest.raises(RecordError):
        unzip_record(zipped, tmp_path / "out")
    assert not (tmp_path / "x").exists()


def test_zip_symlink_refused(tmp_path):
    zipped = tmp_path / "link.zip"
    with zipfile.ZipFile(zipped, "w") as zf:
        info = zipfile.ZipInfo("link")
        info.external_attr = 0o120777 << 16
        zf.writestr(info, "/etc/passwd")
    with pytest.raises(RecordError):
        unzip_record(zipped, tmp_path / "out")


def test_zip_bomb_refused(tmp_path, monkeypatch):
    import qpilot.core.record as rec

    monkeypatch.setattr(rec, "MAX_UNZIPPED_BYTES", 100)
    zipped = tmp_path / "big.zip"
    with zipfile.ZipFile(zipped, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("big.txt", "0" * 10_000)
    with pytest.raises(RecordError):
        unzip_record(zipped, tmp_path / "out")
