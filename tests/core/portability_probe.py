"""Run by ``test_portability.py`` in a child process whose text encoding is NOT UTF-8.

It writes a decided study with non-ASCII text (a reason, a sample name), writes and verifies its
Analysis Record, round-trips it through a zip, and prints ``qpilot --help`` through a pipe. Every
step used to depend on the machine's code page (cp1252 on Windows): wrong text read back, hashes
that differ from one system to another, or ``UnicodeEncodeError``. Prints one JSON line.
"""

import json
import sys
import tempfile
from pathlib import Path

from qpilot.cli import main
from qpilot.core.record import unzip_record, verify, write_record, zip_record
from qpilot.core.store import StudyStore, sha256_file
from qpilot.schemas import DecisionCard, StudyResult

REASON = "keep ÁÍÏÐÝ — Δ×→ “quoted” µ"  # bytes C3 81, C3 8D, C3 8F, C3 90, C3 9D break cp1252


def main_probe(fixtures: Path) -> dict:
    """Return what the test asserts on."""
    out: dict = {}
    result = StudyResult.model_validate_json(
        (fixtures / "results.json").read_text(encoding="utf-8")
    )
    cards = [
        DecisionCard.model_validate(c)
        for c in json.loads((fixtures / "cards.json").read_text(encoding="utf-8"))
    ]
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        root = Path(tmp)
        rdml = root / "input.rdml"
        rdml.write_bytes(b"<rdml>portability probe</rdml>")
        digest = sha256_file(rdml)
        result = result.model_copy(update={"input_sha256": digest, "study_id": digest[:12]})
        store = StudyStore(root / "studies")
        store.put(result, cards)
        store.set_source(result.study_id, rdml)
        store.append_decision(result.study_id, "card_refset", "top2", REASON, "human", None)
        out["reason_back"] = [
            e.reason for e in store.entries(result.study_id) if e.card_id == "card_refset"
        ][-1]
        info = write_record(store, result.study_id, root / "record")
        report = verify(root / "record")
        out["verify_ok"] = report.ok
        out["verify_problems"] = report.model_dump(exclude={"ok"}) if not report.ok else {}
        files = [p for p in (root / "record").rglob("*") if p.is_file()]
        out["files_with_cr"] = sorted(p.name for p in files if b"\r" in p.read_bytes())
        out["reason_in_record"] = REASON in (root / "record" / "decisions.jsonl").read_text(
            encoding="utf-8"
        )
        archive = zip_record(root / "record", root / "record.zip")
        unpacked = unzip_record(archive, root / "unpacked")
        out["unzipped_ok"] = verify(unpacked).ok
        out["record_id_len"] = len(info.record_id)
    return out


if __name__ == "__main__":
    probe = main_probe(Path(sys.argv[1]))
    sys.stdout.flush()
    print("PROBE " + json.dumps(probe), file=sys.stderr)
    sys.exit(main(["--help"]))
