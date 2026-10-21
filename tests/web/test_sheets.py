"""The Spreadsheet Check on the page (origin/main's ``qpilot check sheet``, over the API).

Safety held over the API as on the command line and over MCP: the sheet is never edited and
nothing is saved; the mapping says it is a guess until a person confirms it; sample and group
labels from the sheet never come back; every number in the words is a fact; a comparison with
a study follows the study's blind rule.
"""

from __future__ import annotations

import pytest

from qpilot.qpcr.sheetcheck import MAPPING_CONFIRMED, MAPPING_GUESSED
from tests.engine.test_sheetcheck import (
    clean_columns,
    clean_sheet,
    synthetic,
    textbook,
    textbook_summaries,
    wide_table,
    write_csv,
)


def _upload(client, path, name=None):
    with path.open("rb") as fh:
        r = client.post("/api/sheets", files={"sheet": (name or path.name, fh, "text/csv")})
    assert r.status_code == 200, r.text
    return r.json()


def _no_naked_numbers(text):
    for segment in text["segments"]:
        if segment["fact"] is None:
            assert not any(ch.isdigit() for ch in segment["text"]), segment


def test_a_clean_sheet_reproduces_and_the_mapping_is_a_guess(client, tmp_path):
    sheet = clean_sheet(tmp_path)
    raw = sheet.read_bytes()
    up = _upload(client, sheet)
    assert len(up["sheet_id"]) == 24 and up["name"] == "clean.csv"
    r = client.post(f"/api/sheets/{up['sheet_id']}/check", json={})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["mapping"]["confirmed"] is False
    assert body["mapping"]["status"] == MAPPING_GUESSED
    assert body["counts"]["fold_changes"] == body["counts"]["reproduced"] == 10
    assert body["findings"] == [] and body["hand_overs"] == []
    assert body["headline"]["plain"].startswith(f"Column mapping: {MAPPING_GUESSED}.")
    _no_naked_numbers(body["headline"])
    roles = {c["column"]: c["role"] for c in body["mapping"]["columns"]}
    assert roles["C"] == "cq" and roles["A"] == "sample"
    dumped = r.text
    assert "mouse-c1" not in dumped and "vehicle" not in dumped  # labels never come back
    assert sheet.read_bytes() == raw and "never edited" in body["never_edited"]


def test_a_sign_inverted_sheet_names_the_column_and_the_slip(client, tmp_path):
    study = synthetic()
    _, ddcq, _, _ = textbook(study, "MYC")
    columns = {**clean_columns(study), "Fold change MYC": 2.0**ddcq}
    header, rows = wide_table(study, columns, textbook_summaries(study))
    sheet = write_csv(tmp_path / "inverted.csv", header, rows)
    body = client.post(f"/api/sheets/{_upload(client, sheet)['sheet_id']}/check", json={}).json()
    assert body["counts"]["differ"] > 0 and body["findings"]
    first = body["findings"][0]
    assert first["column"] == "H" and "sign_inverted" in first["paths"]
    _no_naked_numbers(body["findings_text"])


def test_a_person_confirms_the_mapping_and_can_set_a_column(client, tmp_path):
    up = _upload(client, clean_sheet(tmp_path))
    url = f"/api/sheets/{up['sheet_id']}/check"
    confirmed = client.post(url, json={"confirm": True}).json()
    assert confirmed["mapping"]["confirmed"] is True
    assert confirmed["mapping"]["status"] == MAPPING_CONFIRMED
    unset = client.post(url, json={"columns": [{"column": "h", "role": "ignored"}]}).json()
    by = {c["column"]: c for c in unset["mapping"]["columns"]}
    assert by["H"]["role"] == "ignored" and by["H"]["basis"] == "user"
    assert unset["mapping"]["confirmed"] is False  # setting a column is not confirming it
    assert unset["counts"]["fold_changes"] < confirmed["counts"]["fold_changes"]


@pytest.mark.parametrize(
    "body",
    [
        {"columns": [{"column": "A1", "role": "cq"}]},
        {"columns": [{"column": "C", "role": "ct"}]},
        {"study_id": "../etc"},
    ],
)
def test_bad_mappings_and_studies_are_refused(client, tmp_path, body):
    up = _upload(client, clean_sheet(tmp_path))
    r = client.post(f"/api/sheets/{up['sheet_id']}/check", json=body)
    assert r.status_code in (404, 422), r.text


def test_files_that_are_not_sheets_are_refused(client, tmp_path):
    other = tmp_path / "notes.pdf"
    other.write_bytes(b"%PDF-1.4")
    with other.open("rb") as fh:
        r = client.post("/api/sheets", files={"sheet": ("notes.pdf", fh, "application/pdf")})
    assert r.status_code == 400
    bad = tmp_path / "bad.csv"
    bad.write_text("nothing,to,see\n1,2,3\n", encoding="utf-8")
    r = client.post(f"/api/sheets/{_upload(client, bad)['sheet_id']}/check", json={})
    assert r.status_code == 422 and r.json()["error"]["code"] == "bad_sheet"
    for sheet_id in ("0" * 24, "a" * 25, "ZZ"):
        assert client.post(f"/api/sheets/{sheet_id}/check", json={}).status_code == 404


def test_against_a_study_the_hand_overs_follow_the_blind_rule(walked, tmp_path):
    c, study = walked["client"], walked["study"]
    up = _upload(c, clean_sheet(tmp_path))
    r = c.post(f"/api/sheets/{up['sheet_id']}/check", json={"study_id": study})
    assert r.status_code == 200, r.text
    assert r.json()["study_id"] == study
    assert (
        c.post(f"/api/sheets/{up['sheet_id']}/check", json={"study_id": "abcdef123456"}).status_code
        == 404
    )
