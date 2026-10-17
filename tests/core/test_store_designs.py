"""Workspaces of confirmed designs (add_plan G7) and Studio sessions, with the plugin faked."""

import json
import sys
import types

import pytest

from qpilot.core.store import StudyNotFound, sha256_file, study_key
from tests.core.studio_helpers import fake_designs, groups_design


@pytest.fixture
def designs(monkeypatch):
    return fake_designs(monkeypatch)


def _designed(result, design):
    key = study_key(result.input_sha256, design)
    return result.model_copy(update={"study_id": key[:12]}), key


def test_a_designed_study_gets_its_own_workspace(
    store, study, fixture_result, fixture_cards, designs
):
    design = groups_design()
    result, key = _designed(fixture_result, design)
    assert key != fixture_result.input_sha256
    store.put(result, fixture_cards, design=design)
    workspace = store.workspace(result.study_id)
    assert workspace.name == key
    assert (workspace / "study_design.json").read_text() == design.canonical()
    assert store.design(result.study_id) == design
    # the legacy study of the same input is untouched and still found by its own id
    assert store.workspace(study).name == fixture_result.input_sha256
    assert store.design(study) is None
    assert sorted(store.list_studies()) == sorted([study, result.study_id])


def test_a_designed_study_id_must_name_its_workspace(store, fixture_result, fixture_cards, designs):
    with pytest.raises(ValueError, match="first 12 hex"):
        store.put(fixture_result, fixture_cards, design=groups_design())
    assert not any(store.root.iterdir())


def test_the_legacy_default_design_keeps_the_legacy_workspace(
    store, fixture_result, fixture_cards, designs
):
    design = groups_design().model_copy(update={"design_id": "legacy_default"})
    store.put(fixture_result, fixture_cards, design=design)
    assert store.workspace(fixture_result.study_id).name == fixture_result.input_sha256


@pytest.mark.parametrize("bad", ["../../etc", "A" * 64, "ab" * 31, None])
def test_an_unusable_plugin_key_is_refused(store, fixture_result, fixture_cards, monkeypatch, bad):
    module = types.ModuleType("qpilot.qpcr.designs")
    module.study_key = lambda input_sha256, design: bad
    monkeypatch.setitem(sys.modules, "qpilot.qpcr.designs", module)
    with pytest.raises(ValueError, match="unusable workspace key"):
        store.put(fixture_result, fixture_cards, design=groups_design())
    assert not any(store.root.iterdir())


def test_a_hostile_input_hash_cannot_name_a_folder(store, fixture_result, fixture_cards):
    with pytest.raises(ValueError):
        store.put(fixture_result.model_copy(update={"input_sha256": "../x"}), fixture_cards)


def test_ensure_study_runs_the_engine_with_the_design(
    store, tmp_path, fixture_result, fixture_cards, designs, monkeypatch
):
    rdml = tmp_path / "lab.rdml"
    rdml.write_bytes(b"<rdml>lab plate</rdml>")
    digest = sha256_file(rdml)
    design = groups_design()
    key = study_key(digest, design)
    calls = []

    class StudySettings:
        @classmethod
        def from_design(cls, d):
            calls.append(("from_design", d))
            return ("settings for", d.design_hash())

    def run_study(path, settings=None):
        calls.append(("run_study", settings))
        result = fixture_result.model_copy(update={"input_sha256": digest, "study_id": key[:12]})
        return result, fixture_cards

    module = types.ModuleType("qpilot.qpcr.study")
    module.StudySettings, module.run_study = StudySettings, run_study
    monkeypatch.setitem(sys.modules, "qpilot.qpcr.study", module)

    sid = store.ensure_study(rdml, design=design)
    assert sid == key[:12]
    assert calls == [("from_design", design), ("run_study", ("settings for", design.design_hash()))]
    assert store.design(sid) == design and store.source(sid) == rdml.resolve()
    assert store.ensure_study(rdml, design=design) == sid
    assert len(calls) == 2  # the workspace exists: not analysed again


# ---- Studio sessions -----------------------------------------------------------------------------


def test_sessions_are_named_by_a_strict_input_hash(store, tmp_path):
    rdml = tmp_path / "x.rdml"
    rdml.write_bytes(b"<rdml/>")
    sid = store.open_session(rdml)
    folder = store.find_session(sid)
    meta = json.loads((folder / "source.json").read_text())
    assert meta == {"path": str(rdml.resolve()), "sha256": folder.name}
    assert store.session_source(sid) == rdml.resolve()
    rdml.write_bytes(b"<rdml>changed</rdml>")
    assert store.session_source(sid) is None
    for bad in ("../" + "a" * 61, "A" * 64, "a" * 63, "", None):
        with pytest.raises(ValueError):
            store.session(bad)
    for bad in ("../etc", "zzzzzz", "", None, "a" * 65):
        with pytest.raises(StudyNotFound):
            store.find_session(bad)
    assert store.list_studies() == []


def test_a_session_and_a_study_of_different_inputs_with_one_id_are_ambiguous(
    store, study, fixture_result
):
    other = fixture_result.input_sha256[:12] + "f" * 52
    store.session(other)
    with pytest.raises(StudyNotFound):
        store.proposal_home(study)
    home, digest = store.proposal_home(fixture_result.input_sha256[:21])  # longer: one hit
    assert digest == fixture_result.input_sha256 and home.name == digest
