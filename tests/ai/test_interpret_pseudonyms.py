"""A remote model never sees a real sample or target name, in any spelling."""

import json

from qpilot.ai.interpret import interpret, squash
from qpilot.core.pseudonym import Pseudonymiser
from qpilot.schemas_studio import QuarantineEntry, SheetCell, text_id_for
from tests.ai.interpret_helpers import quoted, remote_client, studio_file, view

RDML = ("Patient07_LPS", "Patient08_LPS", "Patient09_PBS", "Patient10_PBS")
SHEET = ("Patient07 LPS", "patient08-lps", "PATIENT09.PBS", "Patient 10 PBS")
NOTES = ("Patient07_LPS_rnalater", "2Patient08_LPS", "Patient09_PBS3", "ok Patient10_PBS.")
SENTENCE = "Patient 08 LPS and Patient07-LPS are the treated ones; patient09pbs is not"


def _sheet_file(notes=NOTES):
    """The RDML names the samples one way; the sheet spells them another and adds a note."""
    summary, entries = studio_file(tuple((name, "unkn", "") for name in RDML), sheet=False)
    rows = [("Sample", "Group", "Note")]
    groups = [name.split("_")[-1] for name in RDML]
    rows += list(zip(SHEET, groups, notes, strict=True))
    for r, row in enumerate(rows, 1):
        for c, value in enumerate(row, 1):
            ref = f"Sheet1!{'ABC'[c - 1]}{r}"
            origin = f"sheet:samples.xlsx!{ref}"
            tid = text_id_for(origin, value)
            entries.append(QuarantineEntry(text_id=tid, origin=origin, value=value))
            summary.sheet.append(SheetCell(cell=ref, text_id=tid, row=r, column=c))
    return summary, entries


def _sent(client) -> str:
    return json.dumps(client.backend.calls, ensure_ascii=False)


def _no_name_in(sent: str, names) -> None:
    for name in names:
        assert name.lower() not in sent.lower(), name
        assert squash(name) not in squash(sent), name


def _reply_then_retry(system, messages):
    """First a reply that fails the checks (so the retry text is sent too), then a good one."""
    content = messages[0]["content"]
    first = view(content)["samples"][0]["ref"]
    if len(messages) == 1:
        field = {"kind": "design.group", "subject": first, "value": {"group": "nope"}}
        return json.dumps({"fields": [{**field, "cites": [first]}]})
    field = {"kind": "design.group", "subject": first, "value": {"group": "LPS"}}
    return json.dumps({"fields": [{**field, "cites": [first], "reasons": ["the sheet"]}]})


def test_no_spelling_of_a_name_reaches_a_remote_model(tmp_path):
    summary, entries = _sheet_file()
    client = remote_client(_reply_then_retry)
    pseudonymiser = Pseudonymiser(tmp_path)
    out = interpret(summary, entries, SENTENCE, client, pseudonymiser=pseudonymiser)
    sent = _sent(client)
    assert len(client.backend.calls) == 2  # the retry message is scanned too
    _no_name_in(sent, (*RDML, *SHEET, "ODC1", "HMBS", "Patient 08 LPS", "Patient07-LPS"))
    # the whole payload: no sample name and no target name in any spelling
    names = {e.value for e in entries if e.origin.startswith("rdml:")}
    _no_name_in(sent, names)
    # every sheet copy of a name is shown as the sample's own token, beside it in its record
    content = client.backend.calls[0]["messages"][0]["content"]
    records = [json.loads(b["value"]) for b in quoted(content) if b["origin"] == "sample record"]
    for record in records:
        assert record["sheet_row"]["1"] == record["name"]
    tokens = {pseudonymiser.pseudonymise(n) for n in RDML}
    assert {r["name"] for r in records} == tokens
    # what is not a name stays readable
    assert any(r["sheet_row"]["3"].endswith("_rnalater") for r in records)
    sentence = next(b for b in quoted(content) if b["origin"] == "the scientist's sentence")
    assert "are the treated ones" in sentence["value"]
    # and the reply still maps back to the real sample
    model = [(f.subject, f.value) for f, m in out.tagged() if m.kind == "model"]
    assert model == [("Patient07_LPS", {"group": "LPS"})]


def test_text_that_cannot_be_pseudonymised_is_withheld_from_a_remote_model(tmp_path):
    notes = ("xPatient07_LPS", "Patient08_LPSrna", "Patient09_PBS", "Patient10_PBS")
    summary, entries = _sheet_file(notes)
    client = remote_client([json.dumps({"fields": []})])
    sentence = "IDPatient07_LPS is treated"
    out = interpret(summary, entries, sentence, client, pseudonymiser=Pseudonymiser(tmp_path))
    sent = _sent(client)
    _no_name_in(sent, (*RDML, *SHEET))
    content = client.backend.calls[0]["messages"][0]["content"]
    assert view(content)["study"]["sentence_ref"] is None
    assert "the scientist's sentence" not in [b["origin"] for b in quoted(content)]
    records = [json.loads(b["value"]) for b in quoted(content) if b["origin"] == "sample record"]
    assert [sorted(r["sheet_row"]) for r in records] == [["1", "2"]] * 2 + [["1", "2", "3"]] * 2
    assert any("could not be pseudonymised" in n for n in out.notes)
    assert out.quarantine and out.quarantine[0].value == sentence  # still stored for people


def test_a_short_name_is_not_found_inside_a_longer_word_or_number(tmp_path):
    samples = (("S1", "unkn", "LPS1"), ("S10", "unkn", "S1 control"), ("S2", "unkn", "PBS"))
    summary, entries = studio_file(samples)
    client = remote_client([json.dumps({"fields": []})])
    pseudonymiser = Pseudonymiser(tmp_path)
    interpret(summary, entries, "S1, S10 and S2", client, pseudonymiser=pseudonymiser)
    content = client.backend.calls[0]["messages"][0]["content"]
    blocks = quoted(content)
    s1, s10 = pseudonymiser.pseudonymise("S1"), pseudonymiser.pseudonymise("S10")
    records = {
        json.loads(b["value"])["name"]: json.loads(b["value"])
        for b in blocks
        if b["origin"] == "sample record"
    }
    assert records[s1]["sheet_row"]["2"] == "LPS1"  # not "LP" + a token
    assert records[s10]["sheet_row"]["2"] == f"{s1} control"
    sentence = next(b for b in blocks if b["origin"] == "the scientist's sentence")["value"]
    assert sentence == f"{s1}, {s10} and {pseudonymiser.pseudonymise('S2')}"
