"""Record and store hardening found by the final audit (17 Oct 2026, evening)."""

import json
import zipfile
from pathlib import Path

import pytest

from qpilot.core.decisions import apply_decision, reject_request
from qpilot.core.record import (
    RecordDamaged,
    RecordError,
    _write_checksums,
    unzip_record,
    verify,
    write_record,
    zip_record,
)
from qpilot.core.store import canonical_json, read_entries
from qpilot.mcp_server import QpilotTools


def _record(store, study, tmp_path, name="rec") -> Path:
    return Path(write_record(store, study, tmp_path / name).record_dir)


def _reseal(rec: Path) -> None:
    """What a forger does after editing: rewrite CHECKSUMS.sha256 to match."""
    (rec / "CHECKSUMS.sha256").unlink()
    _write_checksums(rec)


@pytest.mark.parametrize("sep", [" ", " ", "\u0085"])
def test_a_unicode_line_separator_in_a_reason_never_breaks_the_study(store, study, tmp_path, sep):
    out = QpilotTools(store).qpcr_decide(study, "card_refset", "hmbs_alone", f"cleaner{sep}groups")
    assert out["status"] == "pending_human"
    store.chain_head(study)
    store.snapshot(study)
    assert QpilotTools(store).qpcr_study  # still usable
    assert verify(_record(store, study, tmp_path)).ok


def test_the_log_reads_back_a_separator_written_by_an_earlier_build(store, study):
    log = store.workspace(study) / "decisions.jsonl"
    entry = read_entries(log)[0]
    odd = entry.model_copy(update={"reason": "first\u2028second"})
    line = canonical_json(odd.model_dump(mode="json"))
    assert "\u2028" in line  # JSON leaves it unescaped
    log.write_text(line + "\n", encoding="utf-8")
    assert len(read_entries(log)) == 1


def test_an_interrupted_write_is_repaired_by_the_next_write(store, study, tmp_path):
    workspace = store.workspace(study)
    entries = read_entries(workspace / "decisions.jsonl")
    root = store.get(study).input_sha256
    # crash after the log line, before cards.json and pending.jsonl were rewritten
    store._append(
        workspace / "decisions.jsonl",
        entries,
        root,
        "card_refset",
        "top3",
        "pi",
        "human",
        "applied",
    )
    assert store.card(study, "card_refset").decision is None
    apply_decision(store, study, "card_cutoff", "cut_20", "next", "human")
    assert store.card(study, "card_refset").decision == "top3"
    assert verify(_record(store, study, tmp_path)).ok


def test_dropping_the_last_entries_is_caught_after_a_reseal(store, study, tmp_path):
    QpilotTools(store).qpcr_decide(study, "card_refset", "hmbs_alone", "agent")
    reject_request(store, study, "card_refset", "no")
    rec = _record(store, study, tmp_path)
    log = rec / "decisions.jsonl"
    log.write_text("".join(f"{x}\n" for x in log.read_text().splitlines()[:-2]))
    (rec / "pending.jsonl").write_text("")
    _reseal(rec)
    report = verify(rec)
    assert not report.ok and any("chain_head" in p for p in report.inconsistent)


@pytest.mark.parametrize("edit", ["extra_field", "duplicate_key"])
def test_a_chain_line_cannot_carry_bytes_the_hash_does_not_cover(store, study, tmp_path, edit):
    apply_decision(store, study, "card_cutoff", "cut_20", "pi", "human")
    rec = _record(store, study, tmp_path)
    log = rec / "decisions.jsonl"
    lines = log.read_text().splitlines()
    if edit == "extra_field":
        lines[-1] = lines[-1][:-1] + ', "approved_by": "the PI"}'
    else:
        lines[-1] = '{"actor": "agent", ' + lines[-1][1:]
    log.write_text("\n".join(lines) + "\n")
    _reseal(rec)
    assert verify(rec).chain_broken_at == len(lines)


def test_missing_pending_or_choices_is_caught_after_a_reseal(store, study, tmp_path):
    QpilotTools(store).qpcr_decide(study, "card_cutoff", "cut_20", "agent")
    rec = _record(store, study, tmp_path)
    (rec / "pending.jsonl").unlink()
    _reseal(rec)
    assert "pending.jsonl missing" in verify(rec).inconsistent
    rec2 = _record(store, study, tmp_path, "rec2")
    (rec2 / "choices.json").unlink()
    _reseal(rec2)
    assert "choices.json missing" in verify(rec2).inconsistent


def test_a_swapped_or_removed_input_is_caught_after_a_reseal(store, study, tmp_path):
    rec = _record(store, study, tmp_path)
    (rec / "input.rdml").write_text("<rdml>someone else's plate</rdml>")
    _reseal(rec)
    assert any("input.rdml is not" in p for p in verify(rec).inconsistent)
    (rec / "input.rdml").unlink()
    meta = json.loads((rec / "record.json").read_text())
    (rec / "record.json").write_text(json.dumps({**meta, "input_included": True}))
    _reseal(rec)
    assert any("input.rdml missing" in p for p in verify(rec).inconsistent)


def test_rerun_never_writes_into_the_record(store, study, tmp_path):
    from qpilot.core.record import rerun

    rec = _record(store, study, tmp_path)
    (rec / "input.rdml").write_text("stand-in")
    with pytest.raises(RecordError):
        rerun(rec, rec)
    with pytest.raises(RecordError):
        rerun(rec, rec / "inside")


def test_a_stale_attempt_says_what_was_attempted(store, study):
    tools = QpilotTools(store)
    tools.qpcr_decide(study, "card_refset", "hmbs_alone", "a")
    tools.qpcr_decide(study, "card_refset", "top2", "b")
    reject_request(store, study, "card_refset", "neither", "0" * 64)
    attempt = store.attempts(study)[-1]
    assert attempt["attempted"] == "rejected"
    assert set(attempt["options"]) == {"hmbs_alone", "top2"}


def test_turning_down_one_request_keeps_the_card_waiting_for_the_other(store, study, tmp_path):
    tools = QpilotTools(store)
    tools.qpcr_decide(study, "card_cutoff", "cut_10", "a")
    tools.qpcr_decide(study, "card_cutoff", "cut_20", "b")
    reject_request(store, study, "card_cutoff", "not ten", option="cut_10")
    assert [p.option for p in store.pending(study)] == ["cut_20"]
    assert store.card(study, "card_cutoff").status == "pending_human"
    assert verify(_record(store, study, tmp_path)).ok


def test_a_damaged_zip_is_a_clear_error(store, study, tmp_path):
    rec = _record(store, study, tmp_path)
    archive = Path(zip_record(rec, tmp_path / "rec.zip"))
    data = bytearray(archive.read_bytes())
    with zipfile.ZipFile(archive) as zf:
        info = zf.getinfo("results.json")
    start = info.header_offset + 30 + len(info.filename) + len(info.extra) + 5
    data[start] ^= 0xFF  # corrupt the compressed bytes of one member
    archive.write_bytes(bytes(data))
    with pytest.raises(RecordDamaged, match="altered or damaged after export: results.json"):
        unzip_record(archive, tmp_path / "out")
    # told to go on, it names the member, leaves it out and unpacks the rest
    damaged: list[str] = []
    out = unzip_record(archive, tmp_path / "out2", damaged=damaged)
    assert damaged == ["results.json"] and not (out / "results.json").exists()
    report = verify(out).with_damaged(damaged)
    assert not report.ok and report.outcome() == "altered"
    assert report.damaged == ["results.json"] and "results.json" not in report.missing
    assert report.headline() == "This record was altered or damaged after export: results.json."
    assert report.summary().splitlines()[0].startswith("altered or damaged after export")


def _flip_one_byte(archive: Path, member: str) -> None:
    """Flip one byte of a member's compressed data (what a careless edit or a bad disk does)."""
    data = bytearray(archive.read_bytes())
    with zipfile.ZipFile(archive) as zf:
        info = zf.getinfo(member)
    data[info.header_offset + 30 + len(info.filename) + len(info.extra) + 7] ^= 0x01
    archive.write_bytes(bytes(data))


def test_verify_says_which_way_a_record_fails(store, study, tmp_path, capsys):
    """Verified, altered (which file), chain broken (resealed), each in its own plain words."""
    from qpilot.cli import main

    rec = _record(store, study, tmp_path)
    report = verify(rec)
    assert report.outcome() == "verified" and report.headline().startswith("This record checks")
    archive = Path(zip_record(rec, tmp_path / "flipped.zip"))
    _flip_one_byte(archive, "decisions.jsonl")
    assert main(["verify", str(archive)]) == 1
    out = capsys.readouterr().out
    assert out.startswith("This record was altered or damaged after export: decisions.jsonl.")
    # an edited line with the checksums rewritten: the files match, the chain does not
    log = rec / "decisions.jsonl"
    text = log.read_text()
    assert '"reason":"' in text
    log.write_text(text.replace('"reason":"', '"reason":"(edited) ', 1))
    _reseal(rec)
    forged = verify(rec)
    assert forged.outcome() == "chain_broken" and forged.changed == []
    assert forged.headline().startswith("This record's decision chain is broken at entry ")


def test_a_zip_with_an_upper_case_or_no_extension_is_read_as_a_zip(store, study, tmp_path):
    from qpilot.cli.core_cmds import _record_dir

    rec = _record(store, study, tmp_path)
    archive = Path(zip_record(rec, tmp_path / "rec.zip"))
    for name in ("REC.ZIP", "record"):
        copy = tmp_path / name
        copy.write_bytes(archive.read_bytes())
        assert verify(_record_dir(str(copy), tmp_path / f"x-{name}")).ok
    junk = tmp_path / "notes.txt"
    junk.write_text("hello")
    with pytest.raises(RecordError, match="not an Analysis Record"):
        _record_dir(str(junk), tmp_path / "y")


def test_finder_metadata_does_not_fail_verify(store, study, tmp_path):
    rec = _record(store, study, tmp_path)
    (rec / ".DS_Store").write_bytes(b"\x00\x01")
    (rec / "._results.json").write_bytes(b"\x00")
    assert verify(rec).ok
    (rec / "extra.json").write_text("{}")
    assert not verify(rec).ok  # a real extra file still counts
