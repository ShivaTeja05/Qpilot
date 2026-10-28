"""Write the table of docs/conformance.md: what qPilot reads from each set of the public corpus.

Every set of ``tests/fixtures/corpus`` is dropped on the page's Open (``POST /api/workspaces``)
exactly as a person drops a folder, over a throwaway study store with no model; the rules then
propose its design. Each row says what opened (plates, wells, samples, targets), which reader read
it, the raw-ness verdict, whether its melt curves are read (``qpilot melt``) and how many design
proposals the rules made, or the refusal in qPilot's words. Nothing is hand-written: re-run it
after changing a reader and paste the output into docs/conformance.md.

    python scripts/conformance.py            # Markdown table on stdout
    python scripts/conformance.py --json     # the same rows as JSON
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "tests" / "fixtures" / "corpus"
NOT_DATA = {"MANIFEST.yaml", "truth.csv", ".gitattributes", "README.md"}
TOKEN = "conformance"
#: A manifest's note on an instrument's serial number: never repeated in the docs.
SERIAL = re.compile(r"\s*\([^)]*(serial|SN\s?\d|SN\b)[^)]*\)", re.IGNORECASE)
BASE = "http://127.0.0.1:7860"


def _data_files(folder: Path) -> list[Path]:
    return sorted(p for p in folder.iterdir() if p.is_file() and p.name not in NOT_DATA)


def _wait(client: Any, job: dict, timeout: float = 600.0) -> dict:
    deadline = time.monotonic() + timeout
    while True:
        view = client.get(f"/api/jobs/{job['id']}").json()
        if view["status"] in ("done", "failed"):
            return view
        if time.monotonic() > deadline:
            raise TimeoutError(job)
        time.sleep(0.05)


def _melt(paths: list[Path]) -> str:
    """What ``qpilot melt`` reads from the set: wells with a melt curve, or why none."""
    from qpilot.io.connectors import CaptureError, materialise
    from qpilot.qpcr import melt

    # the set as one export, else each file alone (an RDML file beside its Cq table)
    for files in [paths] + ([[p] for p in paths] if len(paths) > 1 else []):
        try:
            rdml = materialise(files if len(files) > 1 else files[0]).rdml_path
            data = melt.read_melt(rdml)
        except (CaptureError, melt.MeltError, OSError, ValueError):
            continue
        if data.has_melt:
            return f"{len(data.wells)} wells"
        if len(files) > 1:
            return "none in the files"
    return "none in the files"


def _row(client: Any, slug: str) -> dict[str, Any]:
    folder = CORPUS / slug
    manifest = yaml.safe_load((folder / "MANIFEST.yaml").read_text(encoding="utf-8"))
    files = _data_files(folder)
    row: dict[str, Any] = {
        "set": slug,
        "instrument": SERIAL.sub("", str(manifest.get("instrument") or "")),
        "software": manifest.get("software") or "",
        "synthetic": bool(manifest.get("synthetic")),
        "simulated": bool(manifest.get("vendor_simulated")),
        "files": len(files),
    }
    parts = [("files", (p.name, p.read_bytes(), "application/octet-stream")) for p in files]
    r = client.post("/api/workspaces", files=parts)
    if r.status_code != 202:
        row.update(opens=False, refusal=r.json()["error"]["message"])
        return row
    job = _wait(client, r.json()["job"])
    if job["status"] != "done":
        row.update(opens=False, refusal=job["error"]["message"])
        return row
    sid = job["result"]["key"]
    view = client.get(f"/api/sessions/{sid}").json()
    facts, capture = view["facts"], view.get("capture")
    row.update(
        opens=True,
        plates=facts["n_plates"],
        wells=facts["n_wells"],
        samples=facts["n_samples"],
        targets=facts["n_targets"],
        reader=capture["label"] if capture else "RDML (opened as it is)",
        rawness=capture["rawness"]["verdict"] if capture else "not checked (RDML)",
        import_trust=bool(capture and capture["rawness"].get("import_trust")),
        melt=_melt(files),
    )
    r = client.post(f"/api/sessions/{sid}/propose/design", json={})
    _wait(client, r.json()["job"])
    listed = client.get(f"/api/sessions/{sid}/proposals", params={"stage": "design"}).json()
    row["proposals"] = len(listed["proposals"])
    return row


def _alone(client: Any, path: Path) -> dict[str, Any]:
    """One RDML file or workbook of the corpus dropped alone."""
    parts = [("files", (path.name, path.read_bytes(), "application/octet-stream"))]
    row: dict[str, Any] = {"file": str(path.relative_to(CORPUS))}
    r = client.post("/api/workspaces", files=parts)
    job = _wait(client, r.json()["job"]) if r.status_code == 202 else None
    if job is None or job["status"] != "done":
        error = job["error"] if job else r.json()["error"]
        row.update(opens=False, refusal=error["message"])
        return row
    view = client.get(f"/api/sessions/{job['result']['key']}").json()
    facts, capture = view["facts"], view.get("capture")
    row.update(
        opens=True,
        plates=facts["n_plates"],
        wells=facts["n_wells"],
        reader=capture["label"] if capture else "RDML (opened as it is)",
        rawness=capture["rawness"]["verdict"] if capture else "not checked (RDML)",
    )
    return row


def rows() -> dict[str, list[dict[str, Any]]]:
    """Every corpus set, opened over a throwaway store (no model, nothing leaves the machine)."""
    os.environ["QPILOT_MODEL_PROVIDER"] = "none"
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["QPILOT_STUDIES_DIR"] = str(Path(tmp) / "studies")
        os.environ["QPILOT_CACHE_DIR"] = str(Path(tmp) / "cache")
        from fastapi.testclient import TestClient

        from qpilot.ai.client import ModelClient, NoneBackend
        from qpilot.core.store import StudyStore
        from qpilot.studio_service import Studio
        from qpilot.web.context import make_context
        from qpilot.web.server import create_app

        store = StudyStore(Path(tmp) / "studies")
        studio = Studio(store, client=ModelClient(backend=NoneBackend()))
        ctx = make_context(store, studio, token=TOKEN, watch=False)
        slugs = sorted(str(p.parent.relative_to(CORPUS)) for p in CORPUS.rglob("MANIFEST.yaml"))
        try:
            with TestClient(create_app(ctx), base_url=BASE) as client:
                client.headers.update({"x-qpilot-token": TOKEN, "origin": BASE})
                alone = sorted(
                    p
                    for p in (CORPUS / "rdml").rglob("*")
                    if p.suffix in (".rdml", ".lc96p", ".xlsx")
                )
                return {
                    "sets": [_row(client, slug) for slug in slugs],
                    "alone": [_alone(client, p) for p in alone],
                }
        finally:
            ctx.close()


RAWNESS = {
    "raw": "raw",
    "normalized": "normalised to a passive reference (Rn)",
    "baseline_subtracted": "baseline-subtracted: Import Trust card",
    "scaled": "rescaled",
    "cq_only": "Cq values only",
    "unknown": "could not tell: Import Trust card",
}


def markdown(tables: dict[str, list[dict[str, Any]]]) -> str:
    """The rows as the two Markdown tables docs/conformance.md shows."""
    table = tables["sets"]
    head = (
        "| Set | Instrument / software | Opens as | Plates · wells · samples · targets | Curves "
        "| Melt curves | Design proposals |\n|---|---|---|---|---|---|---|\n"
    )
    lines = []
    for r in table:
        name = f"`{r['set']}`"
        if r["synthetic"]:
            name += " (synthetic)"
        if r["simulated"]:
            name += " (instrument simulator)"
        what = f"{r['instrument']}; {r['software']}".strip("; ")
        if not r["opens"]:
            lines.append(f"| {name} | {what} | refused: {r['refusal']} | — | — | — | — |")
            continue
        counts = f"{r['plates']} · {r['wells']} · {r['samples']} · {r['targets']}"
        raw = RAWNESS.get(r["rawness"], r["rawness"])
        lines.append(
            f"| {name} | {what} | {r['reader']} | {counts} | {raw} | {r['melt']} "
            f"| {r['proposals']} |"
        )
    alone = "\n\n| File, dropped alone | Opens as | Plates · wells | Curves |\n|---|---|---|---|\n"
    for r in tables["alone"]:
        if not r["opens"]:
            alone += f"| `{r['file']}` | refused: {r['refusal']} | — | — |\n"
            continue
        raw = RAWNESS.get(r["rawness"], r["rawness"])
        alone += f"| `{r['file']}` | {r['reader']} | {r['plates']} · {r['wells']} | {raw} |\n"
    return head + "\n".join(lines) + alone


def main(argv: list[str] | None = None) -> int:
    """Print the tables (or their rows as JSON)."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--json", action="store_true", help="print the rows as JSON")
    args = parser.parse_args(argv)
    table = rows()
    if args.json:
        print(json.dumps(table, indent=1, ensure_ascii=False))
    else:
        sys.stdout.write(markdown(table))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
