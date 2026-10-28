"""What ``rdml_io.load`` repairs to read real RDML files, and what it still refuses.

Every repair runs only when its defect is present, changes no measured value and is said in the
document's load notes; a clean RDML 1.4 file is read exactly as rdmlpython reads it. The real
files are the corpus's (``tests/fixtures/corpus/rdml``); the rest are built here.
"""

from __future__ import annotations

import io
import shutil
import zipfile
from pathlib import Path

import pytest
from lxml import etree

from qpilot.io import rdml_io
from qpilot.io.rdml_io import NS, RdmlLoadError, load, load_notes, name_repairs, names_key
from qpilot.vendor.rdmlpython import rdml

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
CORPUS = FIXTURES / "corpus" / "rdml"
STEPONE = CORPUS / "stepone-2.3-rdml-1.0" / "stepone_std.rdml"
LINREG = CORPUS / "linregpcr-rdml-1.3-lc480-kphaffii" / "12934_2025_2809_MOESM5_ESM.rdml"
CFX_MEMBER = CORPUS / "cfx-manager-3.0-rdml-1.1-nonstandard-member" / "BioRad_qPCR_melt.rdml"
SOYBEAN = CORPUS / "rdml-1.2-cq-only-soybean" / "VPZ_raw_data.rdml"
LC96P = CORPUS / "lightcycler96-lc96p-hmuy" / "hmuy_hm_vs_dip_r123.lc96p"
CLEAN = FIXTURES / "test_mca_1_raw_data.rdml"


def xml_of(path: Path) -> bytes:
    with zipfile.ZipFile(path) as archive:
        return archive.read(rdml_io.rdml_member(archive.infolist(), path.name))


def zipped(path: Path, members: dict[str, bytes]) -> Path:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in members.items():
            archive.writestr(name, data)
    return path


def measured(root: etree._Element) -> dict[tuple[str, str], list[tuple[str, str]]]:
    """Every (cycle, fluorescence) and Cq of every reaction and target, keyed by sample/target."""
    out: dict[tuple[str, str], list[tuple[str, str]]] = {}
    for react in root.iter(f"{NS}react"):
        sample = react.find(f"{NS}sample").get("id")
        for data in react.findall(f"{NS}data"):
            key = (sample, data.find(f"{NS}tar").get("id"))
            values = [("cq", (data.findtext(f"{NS}cq") or "").strip())]
            values += [
                (p.findtext(f"{NS}cyc").strip(), p.findtext(f"{NS}fluor").strip())
                for p in data.findall(f"{NS}adp")
            ]
            out.setdefault(key, []).extend(values)
    return out


# ---- a clean file is read as it was --------------------------------------------------------


def test_a_clean_file_is_read_exactly_as_rdmlpython_reads_it():
    doc = load(CLEAN)
    etree.set_default_parser(rdml_io.hardened_parser())
    plain = rdml.Rdml(str(CLEAN))
    plain_version = plain.version()
    if plain_version != rdml_io.LATEST_VERSION:
        rdml_io._migrate_to_latest(plain)
    notes = load_notes(doc)
    if plain_version == rdml_io.LATEST_VERSION:
        assert notes.notes == [] and notes.renamed == {}
    assert etree.tostring(doc._rdmlData) == etree.tostring(plain._rdmlData)
    assert names_key(CLEAN) == ""


# ---- the archive's member -------------------------------------------------------------------


def test_the_one_xml_member_is_read_whatever_its_name(tmp_path):
    path = zipped(tmp_path / "run.rdml", {"Run 7.xml": xml_of(CLEAN)})
    doc = load(path)
    assert len(rdml_io.runs(doc)) >= 1
    notes = load_notes(doc)
    assert notes.member == "Run 7.xml"
    assert any("not named rdml_data.xml" in n for n in notes.notes)
    assert not any("Run 7" in n for n in notes.notes)  # a member's name is file text


def test_the_corpus_archives_with_another_member_name_open():
    assert load_notes(load(CFX_MEMBER)).member == "BioRad_qPCR_melt.xml"
    assert load_notes(load(SOYBEAN)).member == "VPZ.xml"


def test_several_xml_members_and_none_named_rdml_data_is_refused_in_words(tmp_path):
    path = zipped(tmp_path / "two.rdml", {"a.xml": xml_of(CLEAN), "b.xml": xml_of(CLEAN)})
    with pytest.raises(RdmlLoadError) as err:
        load(path)
    assert err.value.kind == "ambiguous"
    assert "2 XML files and none is named rdml_data.xml" in str(err.value)


def test_rdml_data_xml_wins_over_other_members(tmp_path):
    path = zipped(tmp_path / "lc.rdml", {"app_data.xml": b"<x/>", "rdml_data.xml": xml_of(CLEAN)})
    assert load_notes(load(path)).member == "rdml_data.xml"


# ---- bombs and damaged archives: refused before anything inflates ---------------------------


@pytest.mark.parametrize("member", ["rdml_data.xml", "plate.xml"])
def test_a_zip_bomb_is_refused_as_too_large_whatever_its_member(tmp_path, member):
    path = zipped(tmp_path / "bomb.rdml", {member: b"<rdml>" + b" " * 4_000_000 + b"</rdml>"})
    with pytest.raises(RdmlLoadError) as err:
        load(path)
    assert err.value.kind == "compression"
    assert "compression ratio above 100:1" in str(err.value)


def test_a_member_over_the_size_cap_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(rdml_io, "MAX_XML_BYTES", 1000)
    path = tmp_path / "big.rdml"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_STORED) as archive:
        archive.writestr("rdml_data.xml", b"<rdml>" + b"x" * 5000 + b"</rdml>")
    with pytest.raises(RdmlLoadError) as err:
        load(path)
    assert err.value.kind == "too_large"


def test_a_damaged_archive_is_called_damaged_not_invalid(tmp_path):
    path = tmp_path / "damaged.rdml"
    shutil.copyfile(CLEAN, path)
    with zipfile.ZipFile(path) as archive:
        info = archive.getinfo("rdml_data.xml")
    raw = bytearray(path.read_bytes())
    start = info.header_offset + 30 + len(info.filename) + len(info.extra)
    for i in range(start + 200, start + 260):  # flip bytes inside the compressed data
        raw[i] ^= 0xFF
    path.write_bytes(bytes(raw))
    with pytest.raises(RdmlLoadError) as err:
        load(path)
    assert err.value.kind == "damaged" and "damaged zip archive" in str(err.value)


# ---- the upgrade's own slips, and RDML 1.0 well names ---------------------------------------


def test_stepone_rdml_1_0_is_upgraded_valid_and_unchanged_in_value():
    raw = etree.fromstring(xml_of(STEPONE), rdml_io.hardened_parser())
    before = measured(raw)
    labels = sorted(r.get("id") for r in raw.iter(f"{NS}react"))
    doc = load(STEPONE)
    assert doc.version() == "1.4" and doc.isvalid()
    after = measured(doc._node)
    assert after == before  # every Cq and every point, under the same sample and target
    (run,) = rdml_io.runs(doc)
    assert (run["pcrFormat_rows"], run["pcrFormat_columns"]) == ("6", "8")
    from qpilot.qpcr.curves import react_well_label

    named = sorted(react_well_label(r.get("id"), 8) for r in doc._node.iter(f"{NS}react"))
    assert named == labels  # A1 ... C8: every well keeps its name
    notes = " ".join(load_notes(doc).notes)
    assert "RDML 1.0" in notes and "48-well plate (6 x 8)" in notes
    assert "deleted react data" in notes  # what rdmlpython's upgrade itself dropped is said


def test_linregpcr_rdml_1_3_ncopy_is_put_in_the_rdml_namespace():
    doc = load(LINREG)
    assert doc.isvalid()
    bare = [e for e in doc._node.iter() if isinstance(e.tag, str) and not e.tag.startswith("{")]
    assert bare == []
    assert any("(Ncopy)" in n for n in load_notes(doc).notes)


def test_without_validation_the_upgrade_is_still_repaired():
    doc = load(STEPONE, validate=False)
    assert all(r.get("id").isdigit() for r in doc._node.iter(f"{NS}react"))


# ---- elements out of the schema's order -----------------------------------------------------


def _shuffled(tmp_path: Path) -> tuple[Path, dict]:
    doc = load(CLEAN)
    root = doc._node
    before = measured(root)
    first = root[0]  # dateMade first: move it last
    root.remove(first)
    root.append(first)
    data = next(root.iter(f"{NS}data"))
    tar = data.find(f"{NS}tar")
    data.remove(tar)
    data.append(tar)  # <tar> belongs first in <data>
    path = tmp_path / "shuffled.xml"
    path.write_bytes(etree.tostring(doc._rdmlData))
    return path, before


def test_elements_out_of_schema_order_are_put_in_order_with_a_note(tmp_path):
    path, before = _shuffled(tmp_path)
    plain = rdml.Rdml(str(path))
    assert not plain.isvalid()
    doc = load(path)
    assert doc.isvalid()
    assert measured(doc._node) == before
    assert any("out of the order the RDML standard sets" in n for n in load_notes(doc).notes)


def test_a_file_that_stays_invalid_is_refused_in_plain_words(tmp_path):
    root = etree.fromstring(xml_of(CLEAN), rdml_io.hardened_parser())
    react = next(root.iter(f"{NS}react"))
    react.set("id", "not-a-well")
    path = tmp_path / "bad.xml"
    path.write_bytes(etree.tostring(root))
    with pytest.raises(RdmlLoadError) as err:
        load(path)
    message = str(err.value)
    assert err.value.kind == "schema"
    assert "does not follow the RDML standard at a <react> element" in message
    assert "Expected is one of" not in message and "{http" not in message and "\t" not in message


# ---- LightCycler 96 names -------------------------------------------------------------------


def test_lightcycler96_samples_take_their_description_and_targets_their_own_name():
    doc = load(LC96P)
    samples = {s["id"] for s in doc.samples()}
    assert {"Hm_1", "Hm_2", "Hm_3", "DIP_1", "DIP_2", "DIP_3"} <= samples
    assert "5dd87e69-1f34-452e-928b-225eacee06ae" in samples  # no description: its id stays
    targets = {t["id"]: t["dyeId"] for t in doc.targets()}
    assert targets == {
        "HmuYPe": "SYBR Green I",
        "16S rRNA": "SYBR Green I",
        "no target (SYBR Green I)": "SYBR Green I",
    }
    reacts = {r.find(f"{NS}sample").get("id") for r in doc._node.iter(f"{NS}react")}
    assert reacts == samples  # every reference follows the new names
    renamed = load_notes(doc).renamed
    assert renamed["sample"]["e34dadd5-2903-42a1-abbd-4eb509eb05d5"] == "Hm_1"
    assert renamed["target"]["SYBR Green I@HmuYPe"] == "HmuYPe"
    assert names_key(LC96P) != ""


def _root(samples: list[tuple[str, str]], targets: list[tuple[str, str]]) -> etree._Element:
    root = etree.Element(f"{NS}rdml", nsmap={None: NS[1:-1]})
    for sid, description in samples:
        sample = etree.SubElement(root, f"{NS}sample", id=sid)
        etree.SubElement(sample, f"{NS}description").text = description
    for tid, dye in targets:
        target = etree.SubElement(root, f"{NS}target", id=tid)
        etree.SubElement(target, f"{NS}dyeId", id=dye)
    return root


GUID_A = "1c76448f-03d2-453f-8628-d764e1ca1d55"
GUID_B = "e34dadd5-2903-42a1-abbd-4eb509eb05d5"


def test_two_samples_are_never_merged_by_a_shared_description():
    root = _root([(GUID_A, "Hm_1"), (GUID_B, "Hm_1")], [])
    assert name_repairs(root) == {}
    root = _root([(GUID_A, "WT"), ("WT", "")], [])  # equal to another sample's id
    assert name_repairs(root) == {}


def test_a_plain_id_keeps_its_name_and_an_at_sign_needs_the_targets_dye():
    root = _root([("WT_1", "mouse 3")], [("FAM@GAPDH", "HEX"), ("me@lab", "FAM")])
    assert name_repairs(root) == {}


def test_the_names_key_follows_what_load_renames(tmp_path):
    copy = tmp_path / "hmuy.rdml"
    shutil.copyfile(LC96P, copy)
    assert names_key(copy) == names_key(LC96P)
    plain = tmp_path / "hmuy.xml"
    plain.write_bytes(xml_of(LC96P))
    assert names_key(plain) == names_key(LC96P)


def test_curve_cache_keys_are_unchanged_for_every_file_load_does_not_rename(tmp_path):
    from qpilot.qpcr import curves

    settings = curves.CurveSettings()
    plain = curves.cache_path("ab" * 32, "e", ("R",), settings, tmp_path)
    assert curves.cache_path("ab" * 32, "e", ("R",), settings, tmp_path, "") == plain
    assert curves.cache_path("ab" * 32, "e", ("R",), settings, tmp_path, "k1") != plain


def test_a_table_cached_before_the_names_were_taken_is_not_reused(tmp_path):
    from qpilot.qpcr import curves

    path = tmp_path / "hmuy.rdml"
    shutil.copyfile(LC96P, path)
    table = curves.analyse_study(
        path, "0311a87d-a929-434b-a01f-c9f5af1d20af", (), cache_dir=tmp_path
    )
    assert {"Hm_1", "DIP_3"} <= set(table["sample"]) and "HmuYPe" in set(table["target"])
    stale = curves.cache_path(
        curves.file_sha256(path), "0311a87d-a929-434b-a01f-c9f5af1d20af", (),
        curves.CurveSettings(), tmp_path,
    )  # fmt: skip
    assert not stale.exists()  # written under the names key only
    stale.write_text("not a table the new names would ever read")
    again = curves.analyse_study(
        path, "0311a87d-a929-434b-a01f-c9f5af1d20af", (), cache_dir=tmp_path
    )
    assert set(again["sample"]) == set(table["sample"])


def test_the_whole_document_is_still_rdmlpythons(tmp_path):
    doc = load(LC96P)
    buffer = io.BytesIO(etree.tostring(doc._rdmlData))
    assert etree.parse(buffer).getroot().tag == f"{NS}rdml"


def test_the_reports_metadata_reader_finds_the_member_by_the_same_rule():
    from qpilot.report.rdml_meta import read_meta

    assert read_meta(CFX_MEMBER).version == "1.1"
    assert read_meta(SOYBEAN).version == "1.2"
