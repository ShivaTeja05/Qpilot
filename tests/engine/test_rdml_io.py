"""Task 1 gate: the vendored method is unchanged and RDML files are opened safely."""

import hashlib
import re
import zipfile
from pathlib import Path

import pytest
from lxml import etree

from qpilot.io import rdml_io
from qpilot.io.rdml_io import RdmlLoadError, hardened_parser, load, runs

VENDOR = Path(rdml_io.__file__).parents[1] / "vendor" / "rdmlpython"
CANARY_TEXT = "this sentence must never leave the canary file"


def _xxe_document(canary: Path) -> bytes:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<!DOCTYPE rdml [ <!ENTITY xxe SYSTEM "{canary.as_uri()}"> ]>\n'
        '<rdml xmlns="http://www.rdml.org" version="1.3"><id><publisher>&xxe;</publisher>'
        "<serialNumber>x</serialNumber></id></rdml>\n"
    ).encode()


def test_vendored_files_unchanged():
    readme = (VENDOR / "README_VENDOR.md").read_text()
    pinned = dict(
        (name, digest) for digest, name in re.findall(r"^([0-9a-f]{64})  (\S+)$", readme, re.M)
    )
    assert len(pinned) == 8
    for name, digest in pinned.items():
        assert hashlib.sha256((VENDOR / name).read_bytes()).hexdigest() == digest, name


def test_load_smoke_fixture_migrates_to_latest(smoke_rdml):
    doc = load(smoke_rdml)
    assert doc.version() == "1.4"
    assert len(runs(doc)) >= 1


def test_load_without_migration_keeps_version(smoke_rdml):
    assert load(smoke_rdml, migrate=False, validate=False).version() == "1.3"


def test_runs_unknown_experiment_names_the_known_ones(smoke_rdml):
    doc = load(smoke_rdml, validate=False)
    with pytest.raises(RdmlLoadError, match="Experiment 1"):
        runs(doc, "no_such_experiment")


@pytest.mark.parametrize(
    "content",
    [b"hello, not xml", b"<notrdml/>", b""],
    ids=["text", "wrong-root", "empty"],
)
def test_non_rdml_files_are_refused(tmp_path, content):
    path = tmp_path / "bad.rdml"
    path.write_bytes(content)
    with pytest.raises(RdmlLoadError):
        load(path)


def test_missing_file_is_refused(tmp_path):
    with pytest.raises(RdmlLoadError, match="not a file"):
        load(tmp_path / "missing.rdml")


def test_zip_without_rdml_member_is_refused(tmp_path):
    path = tmp_path / "other.rdml"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("something_else.xml", "<rdml/>")
    with pytest.raises(RdmlLoadError, match="no rdml_data.xml"):
        load(path)


def test_decompression_bomb_is_refused_before_parsing(tmp_path):
    path = tmp_path / "bomb.rdml"
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("rdml_data.xml", " " * 2_000_000)  # inflates far more than 100:1
    with pytest.raises(RdmlLoadError, match="compression ratio"):
        load(path)


def test_oversized_plain_xml_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(rdml_io, "MAX_XML_BYTES", 100)
    path = tmp_path / "big.xml"
    path.write_text("<rdml>" + "x" * 200 + "</rdml>")
    with pytest.raises(RdmlLoadError, match="too large"):
        load(path)


def test_external_entity_is_never_read_by_load(tmp_path):
    canary = tmp_path / "canary.txt"
    canary.write_text(CANARY_TEXT)
    path = tmp_path / "xxe.rdml"
    path.write_bytes(_xxe_document(canary))
    with pytest.raises(RdmlLoadError) as excinfo:
        load(path)
    assert CANARY_TEXT not in str(excinfo.value)


def test_hardened_parser_does_not_resolve_entities(tmp_path):
    canary = tmp_path / "canary.txt"
    canary.write_text(CANARY_TEXT)
    root = etree.fromstring(_xxe_document(canary), hardened_parser())
    assert CANARY_TEXT not in etree.tostring(root).decode()


def test_load_installs_hardened_default_parser(tmp_path, smoke_rdml):
    load(smoke_rdml, validate=False)
    canary = tmp_path / "canary.txt"
    canary.write_text(CANARY_TEXT)
    root = etree.fromstring(_xxe_document(canary))  # default parser, as the vendored code uses
    assert CANARY_TEXT not in etree.tostring(root).decode()


def test_committed_xxe_fixture_is_refused(fixtures_dir):
    with pytest.raises(RdmlLoadError):
        load(fixtures_dir / "xxe.rdml")


@pytest.mark.demo_data
def test_demo_dataset_loads_with_64_biomarker_plates(demo_rdml_path):
    doc = load(demo_rdml_path)
    assert doc.version() == "1.4"
    assert len(runs(doc, "biomarker_set")) == 64
