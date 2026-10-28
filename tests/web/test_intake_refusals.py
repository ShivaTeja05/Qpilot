"""Every way an RDML file is refused says why in its own plain sentence (RT-UI-025).

A zip bomb used to read "not a valid RDML file"; a damaged archive, an archive with several XML
files, an unknown RDML version and a file that breaks the RDML standard each have their own
reason now, through the ``rdml`` field and through ``files`` alike. No sentence quotes the
schema validator, a traceback or the loader's internal wording.
"""

from __future__ import annotations

import io
import zipfile

import pytest

from qpilot.web import intake
from tests.web.conftest import wait_job

RDML_OPEN = '<rdml xmlns="http://www.rdml.org" version="1.4">'


def zipped(members: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in members.items():
            archive.writestr(name, data)
    return buffer.getvalue()


def bomb(member: str) -> bytes:
    return zipped({member: b"<rdml>" + b" " * 8_000_000 + b"</rdml>"})


def damaged() -> bytes:
    data = bytearray(zipped({"rdml_data.xml": (RDML_OPEN + "<dateMade>x</dateMade>" * 400 +
                                               "</rdml>").encode()}))  # fmt: skip
    data[60:120] = bytes(b ^ 0xFF for b in data[60:120])
    return bytes(data)


CASES = {
    "bomb.rdml": (lambda: bomb("rdml_data.xml"), "too large when unpacked"),
    "bomb named.rdml": (lambda: bomb("Run 1.xml"), "too large when unpacked"),
    "damaged.rdml": (damaged, "the zip archive is damaged"),
    "two.rdml": (
        lambda: zipped({"a.xml": RDML_OPEN.encode(), "b.xml": RDML_OPEN.encode()}),
        "holds 2 XML files and none is named rdml_data.xml",
    ),
    "empty zip.rdml": (lambda: zipped({"readme.txt": b"hello"}), "no RDML data in it"),
    "future.rdml": (
        lambda: b'<rdml xmlns="http://www.rdml.org" version="9.9"></rdml>',
        "an RDML version qPilot does not know",
    ),
    "broken.rdml": (
        lambda: (
            RDML_OPEN + "<experiment id='e'><run id='r'><react id='x1'/></run></experiment></rdml>"
        ).encode(),  # fmt: skip
        "does not follow the RDML standard",
    ),
    "html.xml": (lambda: b"<html><body>hello</body></html>", "it is an XML file, but not RDML"),
    "cut.rdml": (lambda: (RDML_OPEN + "<dateMade>2020").encode(), "not a valid RDML file"),
}
LOADER_WORDS = ("XML load error", "Expected is one of", "{http", "Traceback", "input too large")


def _sentence(client, field: str, name: str, data: bytes) -> str:
    r = client.post("/api/workspaces", files=[(field, (name, data, "application/octet-stream"))])
    if r.status_code != 202:
        return r.json()["error"]["message"]
    job = wait_job(client, r.json()["job"])
    assert job["status"] == "failed", job
    return job["error"]["message"]


@pytest.mark.parametrize("name", sorted(CASES))
@pytest.mark.parametrize("field", ["rdml", "files"])
def test_each_refusal_says_its_own_reason(sclient, field, name):
    make, words = CASES[name]
    if field == "files" and name == "html.xml":  # not claimed as RDML at all: not an export
        words = "does not recognise html.xml as an instrument export"
    message = _sentence(sclient, field, name, make())
    assert name in message, message
    assert words in message, message
    assert not any(w in message for w in LOADER_WORDS), message
    assert "\n" not in message


def test_a_zip_bomb_lc96p_is_refused_as_a_bomb(sclient):
    message = _sentence(sclient, "files", "run.lc96p", bomb("rdml_data.xml"))
    assert "too large when unpacked" in message and "compression ratio above 100:1" in message


def test_every_loader_refusal_kind_has_a_sentence():
    kinds = ("too_large", "compression", "damaged", "no_member", "ambiguous", "version",
             "schema", "entities", "not_xml_rdml", "not_rdml")  # fmt: skip
    assert set(kinds) <= set(intake.UNREADABLE)
    for kind in kinds:
        assert "could not" not in intake.UNREADABLE[kind]  # the prefix is added once
