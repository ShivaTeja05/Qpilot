"""Security gate (plan Task 11): the controls in THREAT_MODEL.md, checked end to end.

Each test drives the public entry point an attacker would reach (the study store, the MCP
tools, the record tools, the app's view of a card) with a hostile input.
"""

import zipfile

import pytest

from qpilot.core.record import RecordError, unzip_record
from qpilot.core.store import StudyNotFound, StudyStore
from qpilot.io.rdml_io import RdmlLoadError
from qpilot.mcp_server import QpilotTools, check_path

CANARY = "this sentence must never leave the canary file"


@pytest.fixture
def roots(tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setenv("QPILOT_DATA_ROOTS", str(data))
    return data


def _xxe_file(folder):
    canary = folder / "canary.txt"
    canary.write_text(CANARY)
    path = folder / "xxe.rdml"
    path.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<!DOCTYPE rdml [ <!ENTITY xxe SYSTEM "{canary.as_uri()}"> ]>\n'
        '<rdml xmlns="http://www.rdml.org" version="1.3"><id><publisher>&xxe;</publisher>'
        "<serialNumber>x</serialNumber></id></rdml>"
    )
    return path


def test_xxe_through_the_store_never_resolves_the_entity(tmp_studies_dir, tmp_path):
    path = _xxe_file(tmp_path)
    with pytest.raises(RdmlLoadError) as err:
        StudyStore(tmp_studies_dir).ensure_study(path)
    assert CANARY not in str(err.value)
    assert not any(tmp_studies_dir.iterdir())  # nothing was written


def test_xxe_through_mcp_is_refused_without_leaking(tmp_studies_dir, roots):
    path = _xxe_file(roots)
    out = QpilotTools(StudyStore(tmp_studies_dir)).qpcr_study(str(path))
    assert CANARY not in str(out)


def test_high_ratio_zip_input_is_refused(tmp_studies_dir, tmp_path):
    bomb = tmp_path / "bomb.rdml"
    with zipfile.ZipFile(bomb, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("rdml_data.xml", " " * 2_000_000)
    with pytest.raises(RdmlLoadError, match="compression ratio"):
        StudyStore(tmp_studies_dir).ensure_study(bomb)


def test_oversized_record_zip_is_refused(tmp_path, monkeypatch):
    import qpilot.core.record as rec

    monkeypatch.setattr(rec, "MAX_UNZIPPED_BYTES", 1000)
    big = tmp_path / "big.zip"
    with zipfile.ZipFile(big, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("results.json", "0" * 100_000)
    with pytest.raises(RecordError, match="1 GB"):
        unzip_record(big, tmp_path / "out")


@pytest.mark.parametrize("name", ["../escape.json", "/etc/passwd", "a/../../b"])
def test_record_zip_paths_cannot_escape(tmp_path, name):
    evil = tmp_path / "evil.zip"
    with zipfile.ZipFile(evil, "w") as archive:
        archive.writestr(name, "x")
    with pytest.raises(RecordError, match="unsafe path"):
        unzip_record(evil, tmp_path / "out")


def test_mcp_path_policy_refuses_dotdot_and_symlinks(roots, tmp_path):
    outside = tmp_path / "secret.rdml"
    outside.write_text("<rdml/>")
    (roots / "link.rdml").symlink_to(outside)
    sibling = tmp_path / "data-evil"
    sibling.mkdir()
    (sibling / "x.rdml").write_text("<rdml/>")
    for path in (roots / ".." / "secret.rdml", roots / "link.rdml", sibling / "x.rdml"):
        with pytest.raises(PermissionError, match="outside"):
            check_path(str(path))


@pytest.mark.parametrize("study_id", ["../../etc", "bc1d/../..", "<script>"])
def test_study_ids_cannot_reach_other_folders(tmp_studies_dir, study_id):
    with pytest.raises(StudyNotFound):
        StudyStore(tmp_studies_dir).workspace(study_id)


def test_rdml_supplied_names_are_escaped_in_the_app(fixture_cards, fixture_facts):
    from qpilot.app_state import card_view

    hostile = "<script>alert(1)</script>"
    card = fixture_cards[0]
    options = [card.options[0].model_copy(update={"label": hostile})] + card.options[1:]
    per_gene = dict(card.options[0].per_gene)
    first = next(iter(per_gene))
    per_gene[hostile] = per_gene[first].model_copy(update={"target": hostile})
    options[0] = options[0].model_copy(update={"per_gene": per_gene})
    view = card_view(card.model_copy(update={"options": options}), fixture_facts)
    assert "<script>" not in view.html
    assert "&lt;script&gt;" in view.html


def test_mcp_returns_an_error_for_unreadable_files(tmp_studies_dir, roots):
    (roots / "junk.rdml").write_text("not xml")
    out = QpilotTools(StudyStore(tmp_studies_dir)).qpcr_study(str(roots / "junk.rdml"))
    assert out["error"].startswith("could not read this RDML file")
