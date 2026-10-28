"""Red team (excellence round): no upload route reads a file on the server's event loop (RT-EX-010).

The async upload routes stream a file to disk (``await``), then read it: a sample sheet (up to
200 MB of workbook XML), a Cq table's sample columns (up to 20 million cells), an instrument
export set's content sort, a run file (up to 200 MB). Done on the event loop, that read stops
every other request and the live event stream for as long as it takes, for every visitor of a
hosted sandbox. Each read must run in a worker thread, as ``verify_record`` and the Prism upload
already do. A probe wraps each reader and records the calls made with an event loop running in
their own thread.
"""

from __future__ import annotations

import asyncio
import functools
from pathlib import Path

import pytest

from tests.web.conftest import wait_job

CORPUS = Path(__file__).parents[1] / "fixtures" / "corpus"
STEPONE = CORPUS / "thermofisher" / "zamanian-stepone-plus-sybr-sections"
RUN_FILE = CORPUS / "rdml" / "stepone-2.3-rdml-1.0" / "stepone_std.rdml"
SHEET = "Sample,Group\nWT_1,WT\nWT_2,WT\nKO_1,KO\nKO_2,KO\n"


@pytest.fixture
def on_loop(monkeypatch) -> list[str]:
    """Names of the readers that ran on an event loop's thread."""
    import qpilot.io.sheets as sheets
    from qpilot.web import intake
    from qpilot.web.routers import instruments

    seen: list[str] = []

    def probe(name, real):
        @functools.wraps(real)
        def wrapped(*args, **kwargs):
            try:
                asyncio.get_running_loop()
            except RuntimeError:
                pass
            else:
                seen.append(name)
            return real(*args, **kwargs)

        return wrapped

    for module, name in (
        (sheets, "read_sheet"),
        (intake, "classify"),
        (intake, "sort_dropped"),
        (intake, "sheet_for"),
        (instruments, "_read_run"),
    ):
        monkeypatch.setattr(module, name, probe(name, getattr(module, name)))
    return seen


def test_attaching_a_sheet_reads_it_off_the_loop(sclient, opened, on_loop):
    files = {"sheet": ("groups.csv", SHEET.encode(), "text/csv")}
    r = sclient.post(f"/api/sessions/{opened}/sheet", files=files)
    assert r.status_code == 202, r.text
    wait_job(sclient, r.json()["job"])
    assert not on_loop, on_loop


def test_opening_a_file_with_a_sheet_reads_the_sheet_off_the_loop(sclient, mini_rdml, on_loop):
    files = {
        "rdml": ("mini.rdml", mini_rdml.read_bytes(), "application/xml"),
        "sheet": ("groups.csv", SHEET.encode(), "text/csv"),
    }
    r = sclient.post("/api/workspaces", files=files)
    assert r.status_code == 202, r.text
    wait_job(sclient, r.json()["job"])
    assert not on_loop, on_loop


def test_an_export_set_is_sorted_off_the_loop(sclient, on_loop):
    files = [
        ("files", (p.name, p.read_bytes(), "text/plain"))
        for p in sorted(STEPONE.glob("*.txt"))
        if p.name in ("amplification_data.txt", "results.txt", "sample_setup.txt")
    ]
    r = sclient.post("/api/workspaces", files=files)
    assert r.status_code == 202, r.text
    wait_job(sclient, r.json()["job"])
    assert not on_loop, on_loop


def test_a_run_file_is_read_off_the_loop(sclient, on_loop):
    with RUN_FILE.open("rb") as handle:
        r = sclient.post("/api/instruments/runs", files={"run": ("run.rdml", handle)})
    assert r.status_code in (200, 400, 422), r.text
    assert "_read_run" not in on_loop, on_loop


def test_a_run_file_linked_to_a_plate_is_read_off_the_loop(walked, on_loop):
    c, study = walked["client"], walked["study"]
    with RUN_FILE.open("rb") as handle:
        r = c.post(
            f"/api/studies/{study}/gate/run-files",
            data={"plate": "GAPDH_plate"},
            files={"run": ("run.rdml", handle, "application/octet-stream")},
        )
    assert r.status_code in (200, 400, 409, 422), r.text
    assert "_read_run" not in on_loop, on_loop
