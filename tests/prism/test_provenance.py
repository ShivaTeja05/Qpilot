"""prism/provenance.py: provenance beside the project; it verifies and every sentence passes."""

import hashlib
import json
import shutil

import pytest

from qpilot.core.store import canonical_json
from qpilot.core.validator import validate
from qpilot.prism.provenance import (
    BUNDLE_FILE,
    INFO_NOTE,
    PROVENANCE_FILE,
    UNVERIFIED,
    caption,
    finalize,
    load_bundle,
    verify_provenance,
    write_provenance,
)
from qpilot.prism.tables import PrismExportError, build_bundle
from tests.prism.conftest import TOY_CHAIN, toy_inputs


def _toy_bundle(tmp_path):
    inputs = toy_inputs()
    bundle = build_bundle(
        inputs,
        ["T"],
        "two_groups_log2",
        tmp_path,
        record_ref="toy-001",
        chain_head=TOY_CHAIN,
        design_hash="d0" * 32,
    )
    bundle = finalize(bundle, tmp_path, [])
    write_provenance(bundle, inputs, tmp_path)
    return bundle


def test_info_note_is_the_specified_text_and_has_no_numbers():
    assert INFO_NOTE == (
        "Values computed by qPilot from raw curves (record id in the table titles); edits are "
        "detected when the tables are sent back."
    )
    assert validate(INFO_NOTE, {}).ok


def test_step_0_1_lists_seven_facts():
    assert len(UNVERIFIED) == 7


def test_toy_provenance_verifies_and_detects_tampering(tmp_path):
    bundle = _toy_bundle(tmp_path)
    assert verify_provenance(tmp_path) == []
    assert load_bundle(tmp_path) == bundle
    csv = tmp_path / bundle.tables[0].csv
    csv.write_bytes(csv.read_bytes().replace(b"-5.0", b"-4.0"))
    assert "changed: T.csv" in verify_provenance(tmp_path)


def test_a_changed_bundle_file_is_detected(tmp_path):
    _toy_bundle(tmp_path)
    data = json.loads((tmp_path / BUNDLE_FILE).read_text())
    data["test"] = "a t test on the linear scale"
    (tmp_path / BUNDLE_FILE).write_text(json.dumps(data))
    problems = verify_provenance(tmp_path)
    assert any("not the digest" in p for p in problems)


def test_a_missing_file_and_an_unreadable_provenance_are_reported(tmp_path):
    bundle = _toy_bundle(tmp_path)
    (tmp_path / bundle.tables[0].csv).unlink()
    assert "missing: T.csv" in verify_provenance(tmp_path)
    (tmp_path / PROVENANCE_FILE).write_text("{not json")
    assert verify_provenance(tmp_path)[0].startswith(PROVENANCE_FILE)


def test_write_provenance_refuses_a_stale_digest(tmp_path):
    bundle = _toy_bundle(tmp_path)
    stale = bundle.model_copy(update={"test": "something else"})
    with pytest.raises(PrismExportError, match="finalize"):
        write_provenance(stale, toy_inputs(), tmp_path)


def test_caption_without_study_facts_has_no_numbers():
    out = caption(toy_inputs(), ["T"])
    text = out["caption_tokens"]
    for name in ("log2", "R1", "R2"):  # the scale's name and the reference genes' names
        text = text.replace(name, "")
    assert not any(ch.isdigit() for ch in text)
    assert "{{" not in out["caption_tokens"]
    assert out["caption"] == out["caption_tokens"]


# ---------- the demo export ----------


@pytest.mark.demo_data
def test_demo_provenance_has_every_field(demo_export, demo_inputs):
    out = demo_export.out_dir
    assert verify_provenance(out) == []
    data = json.loads((out / PROVENANCE_FILE).read_text())
    assert data["versions"]["qpilot"]
    assert len(data["versions"]["rdmlpython_vendored"]) == 40
    study = data["study"]
    assert study["study_id"] == demo_inputs.study_id
    assert study["input_sha256"] == demo_inputs.input_sha256
    assert study["chain_head"] == demo_inputs.chain_head
    assert study["design_hash"] == demo_inputs.design_hash
    actors = {c["card_id"]: c["actor"] for c in data["choices"]}
    assert actors == {"card_refset": None, "card_cutoff": None, "card_undetermined": "system"}
    odc1 = data["genes"]["ODC1"]["recommended_analysis"]
    assert odc1["conclusion"] == "up" and odc1["holds"] == 1.0 and odc1["n_cells"] == 186
    assert odc1["level"] == "Moderate" and odc1["reasons"]
    assert data["conclusion_rule"]["alpha"] == 0.05
    assert (
        "two-fold" in data["conclusion_rule"]["text"] or "2-fold" in data["conclusion_rule"]["text"]
    )
    assert data["note"] == INFO_NOTE
    assert data["bundle_sha256"] == demo_export.bundle.bundle_sha256
    for name, digest in data["files"].items():
        assert hashlib.sha256((out / name).read_bytes()).hexdigest() == digest
    assert {"run.pzc", "send_back.pzc", "README.txt", "ODC1.csv"} <= set(data["files"])


@pytest.mark.demo_data
def test_demo_bundle_sha256_is_canonical_json_without_itself(demo_export):
    data = json.loads((demo_export.out_dir / BUNDLE_FILE).read_text())
    claimed = data.pop("bundle_sha256")
    assert hashlib.sha256(canonical_json(data).encode("utf-8")).hexdigest() == claimed


@pytest.mark.demo_data
def test_demo_caption_uses_fact_tokens_and_passes_the_validator(demo_export, demo_inputs):
    from qpilot.core.validator import names_from_result

    tokens = demo_export.bundle.info["caption_tokens"]
    assert "{{f_fc_odc1_recommended}}" in tokens and "{{f_p_odc1_recommended}}" in tokens
    names = names_from_result(demo_inputs.result) | set(demo_inputs.refs) | {"log2"}
    names |= set(demo_inputs.group_order)
    assert validate(tokens, demo_inputs.result.facts, names).ok
    assert "3.6×" in demo_export.bundle.info["caption"]
    assert "2.3e-08" in demo_export.bundle.info["caption"]


@pytest.mark.demo_data
def test_demo_export_is_deterministic(demo_study, demo_export, tmp_path):
    from qpilot.prism import export_study

    store, study_id = demo_study
    again = export_study(
        store,
        study_id,
        tmp_path / "again",
        platform="macos",
        prism_dir="/Users/lab/qpilot_demo_export",
    )
    assert again.bundle == demo_export.bundle
    for name in demo_export.bundle.files:
        assert (tmp_path / "again" / name).read_bytes() == (demo_export.out_dir / name).read_bytes()
    assert (tmp_path / "again" / PROVENANCE_FILE).read_bytes() == (
        demo_export.out_dir / PROVENANCE_FILE
    ).read_bytes()


@pytest.mark.demo_data
def test_files_prism_adds_later_do_not_break_verification(demo_export, tmp_path):
    copy = tmp_path / "copy"
    shutil.copytree(demo_export.out_dir, copy)
    (copy / "ODC1_qpilot_x.pzfx").write_bytes(b"saved by Prism")
    (copy / "qpilot_done.txt").write_text("done")
    assert verify_provenance(copy) == []
