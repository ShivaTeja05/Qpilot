"""A remote model never sees a real sample or target name, in any spelling."""

import json
import re
import unicodedata

from qpilot.ai.interpret import interpret
from qpilot.core.pseudonym import Pseudonymiser
from qpilot.schemas_studio import QuarantineEntry, SheetCell, text_id_for
from tests.ai.interpret_helpers import quoted, remote_client, studio_file, view

RDML = ("Patient07_LPS", "Patient08_LPS", "Patient09_PBS", "Patient10_PBS")
# the last sheet spelling and note are fullwidth (Unicode compatibility) letters and digits
SHEET = ("Patient07 LPS", "patient08-lps", "PATIENT09.PBS", "Ｐａｔｉｅｎｔ 10 PBS")
NOTES = (
    "Patient07_LPS_rnalater",
    "2Patient08_LPS",
    "Patient09_PBS3",
    "ok Ｐａｔｉｅｎｔ１０_ＰＢＳ.",
)
SENTENCE = (
    "Patient 08 LPS and Patient07-LPS are the treated ones; patient09pbs is not, "
    "nor Ｐａｔｉｅｎｔ１０ PBS"
)


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


def _plain(text: str) -> str:
    """Text as a reader sees it: NFKC (fullwidth letters made plain) and case folded."""
    return unicodedata.normalize("NFKC", text).casefold()


def _squashed(text: str) -> str:
    return "".join(c for c in _plain(text) if c.isalnum())


def _no_name_in(sent: str, names) -> None:
    for name in names:
        assert _plain(name) not in _plain(sent), name
        assert _squashed(name) not in _squashed(sent), name
    # nor any patient id, with or without separators, leading zeros or the group
    for number in (7, 8, 9, 10):
        assert not re.search(rf"patient[\W_]*0*{number}(?!\d)", _plain(sent)), number


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
    p10 = pseudonymiser.pseudonymise("Patient10_PBS")
    assert sentence["value"].endswith(f"nor {p10}")  # the fullwidth spelling too
    assert f"ok {p10}." in [r["sheet_row"]["3"] for r in records]
    # and the reply still maps back to the real sample
    model = [(f.subject, f.value) for f, m in out.tagged() if m.kind == "model"]
    assert model == [("Patient07_LPS", {"group": "LPS"})]


def test_an_id_written_into_a_name_is_pseudonymised_on_its_own(tmp_path):
    """A column holding only the patient id, or the name with a zero dropped, says nothing."""
    notes = ("Patient07", "Patient8_LPS", "patient 09", "Ｐａｔｉｅｎｔ10")
    summary, entries = _sheet_file(notes)
    pseudonymiser = Pseudonymiser(tmp_path)
    p07 = pseudonymiser.pseudonymise("Patient07")

    def reply(system, messages):
        content = messages[0]["content"]
        for block in quoted(content):
            if (
                block["origin"] == "sample record"
                and json.loads(block["value"])["sheet_row"].get("3") == p07
            ):
                value = {"biological_unit": p07}
                field = {"kind": "design.bio_unit", "subject": block["ref"], "value": value}
                return json.dumps({"fields": [{**field, "cites": [block["ref"]]}]})
        return json.dumps({"fields": []})

    client = remote_client(reply)
    sentence = "Patient7 and Patient 8 are the treated ones"
    out = interpret(summary, entries, sentence, client, pseudonymiser=pseudonymiser)
    sent = _sent(client)
    _no_name_in(sent, (*RDML, *SHEET, *notes))
    content = client.backend.calls[0]["messages"][0]["content"]
    records = {
        json.loads(b["value"])["name"]: json.loads(b["value"])["sheet_row"]
        for b in quoted(content)
        if b["origin"] == "sample record"
    }
    row = {name: records[pseudonymiser.pseudonymise(name)] for name in RDML}
    assert row["Patient07_LPS"]["3"] == p07  # the id alone has a token of its own
    assert row["Patient08_LPS"]["3"] == pseudonymiser.pseudonymise("Patient08_LPS")
    assert row["Patient09_PBS"]["3"] == pseudonymiser.pseudonymise("Patient09")
    assert row["Patient10_PBS"]["3"] == pseudonymiser.pseudonymise("Patient10")
    shown = next(b for b in quoted(content) if b["origin"] == "the scientist's sentence")
    p08 = pseudonymiser.pseudonymise("Patient08")
    assert shown["value"] == f"{p07} and {p08} are the treated ones"
    # a unit the model reads from the id's token maps back to the id in the sheet
    model = [(f.subject, f.value) for f, m in out.tagged() if m.kind == "model"]
    assert model == [("Patient07_LPS", {"biological_unit": "Patient07"})]


def test_an_id_glued_to_a_word_and_a_spaced_out_zero_are_found(tmp_path):
    samples = (("Mouse12Liver", "unkn", "Mouse12"), ("A_07", "unkn", "A 0 7 here"))
    summary, entries = studio_file(samples)
    client = remote_client([json.dumps({"fields": []})])
    pseudonymiser = Pseudonymiser(tmp_path)
    interpret(summary, entries, "", client, pseudonymiser=pseudonymiser)
    _no_name_in(_sent(client), ("Mouse12", "Mouse12Liver"))
    content = client.backend.calls[0]["messages"][0]["content"]
    records = {
        json.loads(b["value"])["name"]: json.loads(b["value"])["sheet_row"]
        for b in quoted(content)
        if b["origin"] == "sample record"
    }
    assert records[pseudonymiser.pseudonymise("Mouse12Liver")]["2"] == pseudonymiser.pseudonymise(
        "Mouse12"
    )
    a07 = pseudonymiser.pseudonymise("A_07")
    assert records[a07]["2"] == f"{a07} here"


def test_text_that_cannot_be_pseudonymised_is_withheld_from_a_remote_model(tmp_path):
    notes = ("xPatient07_LPS", "rnaPatient08_LPS", "Patient09_PBS", "Patient10_PBS")
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
