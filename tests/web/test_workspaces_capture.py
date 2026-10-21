"""Opening instrument exports from the page: POST /api/workspaces with ``files``.

The files are the public corpus's own (``tests/fixtures/corpus``), uploaded under their own
names, as a person would drop them. The ``rdml`` field keeps working exactly as before
(``test_studio_open.py``, ``test_workspaces.py``); these tests cover the new door.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from qpilot.web import intake, views
from qpilot.web.context import make_context
from qpilot.web.server import create_app
from tests.web.conftest import BASE, TOKEN, wait_job

CORPUS = Path(__file__).resolve().parents[1] / "fixtures" / "corpus"
SYNTH_CFX = CORPUS / "synthetic" / "cfx-manager-raw-vs-baseline-subtracted"
SYNTH_QS = CORPUS / "synthetic" / "quantstudio-design-analysis-rn-drn"
HSIEH = CORPUS / "biorad" / "hsieh2016-cfx-manager-3.1-sybr"
SAMPLES = "Sample,Group\nS1,A\nS2,A\nS3,A\nS4,A\nS5,B\nS6,B\nS7,B\nS8,B\n"


def cfx(stem: str = "qpilot-synthetic-raw") -> list[Path]:
    return sorted(SYNTH_CFX.glob(f"{stem} *"))


def drop(client, paths, *, extra=None, **fields):
    """POST the files as the page does: every file under ``files``, by its own name."""
    parts = [("files", (p.name, p.read_bytes(), "application/octet-stream")) for p in paths]
    parts += [("files", item) for item in extra or []]
    for name, value in fields.items():
        if name == "sheet":
            parts.append(("sheet", value))
    data = {k: v for k, v in fields.items() if k != "sheet"}
    return client.post("/api/workspaces", files=parts, data=data)


def opened(client, paths, **kwargs) -> tuple[str, dict]:
    r = drop(client, paths, **kwargs)
    assert r.status_code == 202, r.text
    job = wait_job(client, r.json()["job"])
    assert job["status"] == "done", job
    return job["result"]["key"], job


def frame(client, sid: str) -> dict:
    r = client.get(f"/api/sessions/{sid}")
    assert r.status_code == 200, r.text
    return r.json()


# ---- an export set opens, says what it is, and Studio works on it ------------------------------


def test_a_cfx_export_set_opens_and_the_design_can_be_proposed(sclient):
    sid, job = opened(sclient, cfx())
    assert job["result"]["unused"] == []
    view = frame(sclient, sid)
    capture = view["capture"]
    assert capture["connector"] == "cfx"
    assert capture["label"] == "Bio-Rad CFX Manager / Maestro export"
    assert [s["name"] for s in capture["sources"]] == [p.name for p in cfx()]
    assert {s["role"] for s in capture["sources"]} == {"amplification", "cq"}
    (plate,) = capture["plates"]
    assert plate["run_id"] == "qpilot-synthetic-raw"
    assert (plate["n_wells"], plate["n_cycles"], plate["rows"], plate["columns"]) == (80, 40, 8, 12)
    assert plate["targets"] == ["REF", "GOI"] and plate["dyes"] == ["SYBR"]
    assert plate["sample_types"] == {"nrt": 6, "ntc": 6, "std": 20, "unkn": 48}
    assert plate["n_with_vendor_cq"] == 70 and plate["vendor_omitted"] == []
    assert capture["rawness"]["verdict"] == "raw" and capture["rawness"]["linregpcr_ok"]
    assert "LinRegPCR" in capture["rawness"]["meaning"]
    assert view["title"] == "qpilot-synthetic-raw (2 files)" == view["facts"]["file_name"]
    assert view["facts"]["n_wells"] == 80

    r = sclient.post(f"/api/sessions/{sid}/propose/design")
    assert r.status_code == 202, r.text
    assert wait_job(sclient, r.json()["job"])["status"] == "done"
    proposals = sclient.get(f"/api/sessions/{sid}/proposals", params={"stage": "design"}).json()
    assert proposals["proposals"], "the rules propose on the imported file"


def test_baseline_subtracted_curves_say_what_that_means_for_the_analysis(sclient):
    sid, _ = opened(sclient, cfx("qpilot-synthetic-baselined"))
    capture = frame(sclient, sid)["capture"]
    rawness = capture["rawness"]
    assert rawness["verdict"] == "baseline_subtracted" and not rawness["linregpcr_ok"]
    assert "weakens LinRegPCR's per-well efficiency" in rawness["meaning"]
    assert "No Baseline Subtraction" in rawness["meaning"]
    assert "CURVES_NOT_RAW" in {w["code"] for w in capture["warnings"]}


def test_a_quantstudio_export_opens_with_rn_normalised(sclient):
    sid, _ = opened(sclient, sorted(p for p in SYNTH_QS.glob("*.csv") if p.name != "truth.csv"))
    capture = frame(sclient, sid)["capture"]
    assert capture["connector"] == "quantstudio" and capture["value_kind"] == "Rn"
    assert capture["value_words"].startswith("Rn")
    assert capture["rawness"]["verdict"] == "normalized" and capture["rawness"]["linregpcr_ok"]
    assert capture["plates"][0]["sample_types"] == {"ntc": 12, "std": 20, "unkn": 48}
    r = sclient.post(f"/api/sessions/{sid}/propose/design")
    assert wait_job(sclient, r.json()["job"])["status"] == "done"


def test_a_cq_only_table_says_there_are_no_curves_to_check(sclient):
    sid, _ = opened(sclient, [CORPUS / "roche" / "sanger-lc480-cp-table" / "qPCR.txt"])
    capture = frame(sclient, sid)["capture"]
    assert capture["rawness"]["verdict"] == "cq_only"
    assert "no curves to check" in capture["rawness"]["meaning"]
    (plate,) = capture["plates"]
    assert plate["n_cycles"] == 0 and plate["sample_types"]["std"] == 21
    assert len(plate["vendor_omitted"]) == 5
    assert "VENDOR_OMITTED" in {w["code"] for w in capture["warnings"]}


def test_files_the_export_does_not_use_are_named_back(sclient):
    gapdh = sorted(HSIEH.glob("2016-09-04 gapdh*"))
    sid, job = opened(sclient, gapdh)
    unused = [
        "2016-09-04 gapdh -  End Point Results_SYBR.csv",
        "2016-09-04 gapdh -  Melt Curve Peak Results_0.csv",
    ]
    assert job["result"]["unused"] == unused
    capture = frame(sclient, sid)["capture"]
    assert capture["unused"] == unused
    assert capture["layers"]["melt"] and capture["rawness"]["verdict"] == "baseline_subtracted"
    roles = {s["name"]: s["role"] for s in capture["sources"]}
    assert roles["2016-09-04 gapdh -  Melt Curve Derivative Results_SYBR.csv"] == "ignored"


# ---- a sample sheet with the export ------------------------------------------------------------


def test_a_sample_sheet_dropped_with_the_export_is_recognised(sclient):
    sheet = ("samples.csv", SAMPLES.encode(), "text/csv")
    sid, _ = opened(sclient, cfx(), extra=[sheet])
    view = frame(sclient, sid)
    assert view["facts"]["sheet_name"] == "samples.csv"
    assert view["capture"]["unused"] == []
    assert {s["name"] for s in view["capture"]["sources"]} == {p.name for p in cfx()}


def test_the_sheet_field_works_with_files_too(sclient):
    sid, _ = opened(sclient, cfx(), sheet=("design.csv", SAMPLES.encode(), "text/csv"))
    assert frame(sclient, sid)["facts"]["sheet_name"] == "design.csv"


def test_two_sample_sheets_are_refused(sclient):
    sheets = [("a.csv", SAMPLES.encode(), "text/csv"), ("b.csv", SAMPLES.encode() + b"S9,B\n", "")]
    r = drop(sclient, cfx(), extra=sheets)
    assert r.status_code == 400 and r.json()["error"]["code"] == "mixed_files"
    assert "one sample sheet at a time" in r.json()["error"]["message"]


# ---- RDML through the same door, and the old field ---------------------------------------------


def test_an_rdml_file_among_files_opens_as_it_is(sclient, mini_rdml):
    sid, job = opened(sclient, [mini_rdml])
    view = frame(sclient, sid)
    assert view["capture"] is None
    assert view["facts"]["file_name"] == "mini.rdml"
    assert job["result"] == {"key": sid, "unused": []}


def test_the_rdml_field_still_opens_as_before(sclient, mini_rdml):
    with mini_rdml.open("rb") as fh:
        r = sclient.post("/api/workspaces", files={"rdml": ("mini.rdml", fh, "application/xml")})
    job = wait_job(sclient, r.json()["job"])
    assert job["status"] == "done"
    assert frame(sclient, job["result"]["key"])["capture"] is None


def test_an_rdml_file_with_an_export_is_refused(sclient, mini_rdml):
    r = drop(sclient, [mini_rdml, *cfx()])
    assert r.status_code == 400 and r.json()["error"]["code"] == "mixed_files"
    assert "mini.rdml is an RDML file" in r.json()["error"]["message"]


def test_rdml_and_files_fields_together_are_refused(sclient, mini_rdml):
    parts = [
        ("rdml", ("mini.rdml", mini_rdml.read_bytes(), "application/xml")),
        ("files", (cfx()[0].name, cfx()[0].read_bytes(), "text/csv")),
    ]
    r = sclient.post("/api/workspaces", files=parts)
    assert r.status_code == 400 and r.json()["error"]["code"] == "mixed_files"


def test_no_file_at_all_is_refused_in_words(sclient):
    r = sclient.post("/api/workspaces", data={"sentence": "hello"})
    assert r.status_code == 400 and r.json()["error"]["code"] == "no_file"


# ---- refusals in words ------------------------------------------------------------------------


def test_a_file_qpilot_does_not_read_is_refused_with_a_sentence(sclient, web_store):
    r = drop(sclient, [], extra=[("notes.txt", b"Dear lab, see attached.\n", "text/plain")])
    assert r.status_code == 400
    error = r.json()["error"]
    assert error["code"] == "bad_file"
    assert error["message"].startswith("qPilot does not recognise notes.txt")
    assert "Dear lab" not in error["message"]


def test_an_instrument_project_file_says_how_to_export(sclient, web_store):
    r = drop(sclient, [], extra=[("run 3.pcrd", b"PK\x03\x04", "application/octet-stream")])
    assert r.status_code == 400 and "Export All Data Sheets" in r.json()["error"]["message"]
    assert not any(views.inputs_dir(web_store).iterdir()), "refused before anything was kept"


def test_two_kinds_of_export_are_refused(sclient):
    r = drop(sclient, [cfx()[0], sorted(SYNTH_QS.glob("*Amplification*"))[0]])
    assert r.status_code == 400 and r.json()["error"]["code"] == "mixed_files"
    assert "one kind of export at a time" in r.json()["error"]["message"]


def test_a_sample_sheet_alone_is_refused(sclient):
    r = drop(sclient, [], extra=[("samples.csv", SAMPLES.encode(), "text/csv")])
    assert r.status_code == 400
    assert "looks like a sample sheet" in r.json()["error"]["message"]


def test_an_export_the_reader_refuses_fails_the_job_with_a_sentence(sclient):
    nomads = CORPUS / "roche" / "nomads-lc480-raw-isothermal-not-pcr"
    r = drop(sclient, sorted(nomads.glob("*.txt")))
    assert r.status_code == 202, r.text
    job = wait_job(sclient, r.json()["job"])
    assert job["status"] == "failed" and job["error"]["code"] == "cannot_open"
    message = job["error"]["message"]
    assert message.startswith("The export could not be read: evIC50_1_plate1_07APRIL2026.txt")
    assert "not a PCR run" in message


def test_more_than_64_files_are_refused(sclient):
    extra = [(f"f{i}.csv", b"x", "text/csv") for i in range(intake.MAX_FILES + 1)]
    r = drop(sclient, [], extra=extra)
    assert r.status_code == 400 and r.json()["error"]["code"] == "too_many_files"


def test_two_different_files_with_one_name_are_refused(sclient):
    a, b = cfx()
    r = drop(sclient, [], extra=[(a.name, a.read_bytes(), ""), (a.name, b.read_bytes(), "")])
    assert r.status_code == 202
    job = wait_job(sclient, r.json()["job"])
    assert job["status"] == "failed" and "Two different files are named" in job["error"]["message"]


# ---- kept with the session, blind-safe --------------------------------------------------------


def test_the_import_survives_a_restart(sclient, web_store, studio_ctx):
    sid, _ = opened(sclient, cfx())
    before = frame(sclient, sid)["capture"]
    folder = web_store.find_session(sid)
    record = json.loads((folder / intake.CAPTURE_FILE).read_text())
    assert record["schema"] == "qpilot.web.capture/1" and record["meta"]["connector"]["id"] == "cfx"
    built = Path(json.loads((folder / "source.json").read_text())["path"])
    assert built.parent == web_store.root / "imports" / "capture"
    ctx = make_context(web_store, studio_ctx.studio, token=TOKEN, watch=False)
    try:
        with TestClient(create_app(ctx), base_url=BASE) as fresh:
            fresh.headers["x-qpilot-token"] = TOKEN
            assert frame(fresh, sid)["capture"] == before
    finally:
        ctx.close()


def test_the_same_export_opened_twice_is_one_session(sclient, web_store):
    first, _ = opened(sclient, cfx())
    again, _ = opened(sclient, cfx())
    assert first == again
    built = list((web_store.root / "imports" / "capture").glob("*.rdml"))
    assert len(built) == 1


def test_the_import_summary_carries_no_sample_name_and_no_group(sclient):
    sid, _ = opened(sclient, cfx())
    capture = frame(sclient, sid)["capture"]
    text = json.dumps(capture)
    assert "quarantine" not in capture and "header" not in capture
    strings = set()

    def walk(value):
        if isinstance(value, str):
            strings.add(value)
        elif isinstance(value, dict):
            for v in value.values():
                walk(v)
        elif isinstance(value, list):
            for v in value:
                walk(v)

    walk(capture)
    samples = {f"S{i}" for i in range(1, 9)} | {"NTC", "NRT"}
    assert not samples & strings
    assert '"A"' not in text and '"B"' not in text  # the truth's groups never appear


@pytest.mark.parametrize("name", ["../../escape.csv", "..", ".hidden.csv"])
def test_hostile_file_names_never_choose_where_a_file_is_staged(sclient, web_store, name):
    data = cfx()[0].read_bytes()
    r = drop(sclient, [cfx()[1]], extra=[(name, data, "text/csv")])
    if r.status_code == 202:
        wait_job(sclient, r.json()["job"])
    sources = web_store.root / "imports" / "sources"
    for path in sources.rglob("*") if sources.exists() else []:
        assert sources in path.resolve().parents
        assert not path.name.startswith(".")
    assert not (web_store.root.parent / "escape.csv").exists()
