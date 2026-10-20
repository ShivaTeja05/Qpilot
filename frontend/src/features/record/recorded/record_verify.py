"""Record real `core.record.verify` reports: an untouched record and a tampered copy of it.

Run from the worktree root (with the agent env sourced):
    python frontend/src/features/record/recorded/record_verify.py e300000d4f9a

Writes the record into a temporary folder, verifies it, then changes one decision's reason in
decisions.jsonl and verifies again. Until `POST /api/records/verify` lands this records the
`VerifyReport` fields alone; afterwards, re-record from the route.
"""

import json
import sys
import tempfile
from pathlib import Path

from qpilot.core.record import verify, write_record
from qpilot.core.store import StudyStore

study_id = sys.argv[1]
here = Path(__file__).parent
with tempfile.TemporaryDirectory() as tmp:
    info = write_record(StudyStore(), study_id, Path(tmp) / "record")
    record = Path(info.record_dir)
    ok = verify(record)
    log = record / "decisions.jsonl"
    lines = log.read_text(encoding="utf-8").splitlines()
    first = json.loads(lines[0])
    first["reason"] = first["reason"] + " (edited)"
    lines[0] = json.dumps(first, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    log.write_text("\n".join(lines) + "\n", encoding="utf-8")
    tampered = verify(record)
for name, report in (("verify-ok", ok), ("verify-tampered", tampered)):
    out = here / f"{name}.json"
    out.write_text(json.dumps(report.model_dump(), indent=1) + "\n", encoding="utf-8")
    print(out.name, report.summary().replace("\n", " | "))
