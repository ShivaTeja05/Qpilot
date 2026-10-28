"""Curve Judge: a pinned model that refuses tampering, a numpy evaluator that matches XGBoost,
deterministic features, an honest validation flag, offline, and no AI imports.

No network and no XGBoost: the evaluator is checked against predictions XGBoost made in the
training environment and stored in ``metrics.json`` (``training/curve_judge/evaluate.py``).
"""

import hashlib
import json
import re
import shutil
import subprocess
import sys
import zipfile
from collections import OrderedDict
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from pytest_socket import disable_socket, enable_socket

from qpilot.qpcr import curve_judge as cj
from qpilot.schemas_studio import AmpCallRule
from tests.engine.test_curves import rewrite_run, tall_plate

ROOT = Path(__file__).resolve().parents[2]
MODEL_DIR = ROOT / "qpilot" / "models" / "curve_judge"


@pytest.fixture
def offline():
    disable_socket(allow_unix_socket=True)
    try:
        yield
    finally:
        enable_socket()


@pytest.fixture
def std_rdml(fixtures_dir):
    return fixtures_dir / "vermeulen_std_150000.rdml"


@pytest.fixture
def metrics():
    return json.loads((MODEL_DIR / "metrics.json").read_text())


@pytest.fixture
def model_copy(tmp_path):
    for name in ("model.json", "model.sha256"):
        shutil.copy(MODEL_DIR / name, tmp_path / name)
    return tmp_path / "model.json", tmp_path / "model.sha256"


def _sample(metrics):
    rows = metrics["evaluator_sample"]
    fluor = np.array([[np.nan if v is None else v for v in r["fluorescence"]] for r in rows])
    return rows, fluor


# ---------- the pin ----------


def test_shipped_model_matches_both_pins():
    payload = (MODEL_DIR / "model.json").read_bytes()
    digest = hashlib.sha256(payload).hexdigest()
    assert (MODEL_DIR / "model.sha256").read_text().split() == [digest, "model.json"]
    assert digest == cj.MODEL_SHA256
    model = cj.load_model()
    assert model.sha256 == digest
    assert len(model.trees) == 17 and model.n_features == 40


def test_modified_model_is_refused(model_copy):
    model, sha = model_copy
    cj.load_model(model, sha)  # the untouched copy loads
    text = model.read_text()
    model.write_text(text.replace('"split_conditions":[', '"split_conditions":[9', 1))
    with pytest.raises(cj.ModelIntegrityError, match="does not match model.sha256"):
        cj.load_model(model, sha)
    # Re-pinning the tampered file in model.sha256 is not enough: the code pin still refuses.
    sha.write_text(f"{hashlib.sha256(model.read_bytes()).hexdigest()}  model.json\n")
    with pytest.raises(cj.ModelIntegrityError, match="is not the pinned"):
        cj.load_model(model, sha)


@pytest.mark.parametrize("pin", ["", "not-a-digest\n", "ABC" * 30])
def test_bad_or_missing_pin_is_refused(model_copy, pin):
    model, sha = model_copy
    sha.write_text(pin)
    with pytest.raises(cj.ModelIntegrityError):
        cj.load_model(model, sha)
    sha.unlink()
    with pytest.raises(cj.ModelIntegrityError):
        cj.load_model(model, sha)


def test_unsupported_models_are_refused():
    payload = json.loads((MODEL_DIR / "model.json").read_text())
    payload["learner"]["objective"]["name"] = "reg:squarederror"
    with pytest.raises(cj.ModelIntegrityError, match="binary:logistic"):
        cj.parse_model(json.dumps(payload).encode(), "x")
    with pytest.raises(cj.ModelIntegrityError):
        cj.parse_model(b"\x80\x04 not json", "x")


# ---------- the evaluator reproduces XGBoost ----------


def test_evaluator_reproduces_stored_xgboost_predictions(metrics):
    rows, fluor = _sample(metrics)
    model = cj.load_model()
    x = cj.normalise(fluor)
    p = model.predict_proba(x)
    margin = model.margin(x)
    expected_p = np.array([r["xgboost_p"] for r in rows])
    expected_margin = np.array([r["xgboost_margin"] for r in rows])
    assert np.max(np.abs(p - expected_p)) <= 1e-6
    assert np.max(np.abs(margin - expected_margin)) <= 1e-5
    kinds = {r["kind"] for r in rows}
    assert {"misclassified", "borderline", "missing_cycles_31_40"} <= kinds  # hard cases too


def test_metrics_record_the_gate_and_the_full_comparison(metrics):
    assert metrics["model_sha256"] == cj.MODEL_SHA256
    assert metrics["gate"]["passed"] and metrics["held_out"]["accuracy"] >= 0.99
    assert metrics["held_out"]["n"] == 33043
    comparison = metrics["evaluator_vs_xgboost"]
    assert comparison["passed"]
    assert comparison["held_out"]["n"] == 33043
    assert comparison["held_out"]["max_abs_diff_p"] <= 1e-6
    assert comparison["held_out"]["calls_differ"] == 0


def test_missing_values_follow_default_directions(metrics):
    rows, fluor = _sample(metrics)
    gaps = [i for i, r in enumerate(rows) if r["kind"].startswith("missing_")]
    assert gaps and np.isnan(fluor[gaps]).any()
    p = cj.load_model().predict_proba(cj.normalise(fluor[gaps]))
    assert np.allclose(p, [rows[i]["xgboost_p"] for i in gaps], atol=1e-6, rtol=0)


def test_infinite_input_is_rejected():
    x = np.ones((1, 40))
    x[0, 3] = np.inf
    with pytest.raises(cj.CurveJudgeError):
        cj.load_model().margin(x)


# ---------- features ----------


def test_normalise_is_the_papers_formula():
    rn = np.array([[3.0, 2.0, 5.0], [np.nan, 0.5, 1.5], [np.nan, np.nan, np.nan]])
    out = cj.normalise(rn)
    assert np.allclose(out[0], [2.0, 1.0, 4.0])
    assert np.isnan(out[1, 0]) and np.allclose(out[1, 1:], [1.0, 2.0])
    assert np.isnan(out[2]).all()


def test_standardise_without_reference():
    curves = np.array([[2.0, 4.0, 8.0], [0.0, 1.0, 2.0], [-1.0, 1.0, 2.0], [np.nan] * 3])
    out, ok = cj.standardise_without_reference(curves)
    assert ok.tolist() == [True, False, False, False]
    assert np.allclose(out[0], [1.0, 2.0, 4.0])
    assert np.isnan(out[1:]).all()


def test_features_from_rdml_are_deterministic(std_rdml):
    first = cj.features_from_rdml(std_rdml, "biomarker_set")
    second = cj.features_from_rdml(std_rdml, "biomarker_set")
    pd.testing.assert_frame_equal(first, second)
    assert len(first) == 192 and first.index.is_unique
    assert first.index.names == ["run_id", "well"]
    assert list(first.columns[-40:]) == list(cj.CYC_COLUMNS)
    assert first["callable"].all() and set(first["n_cycles"]) <= {45, 50}
    x = first[list(cj.CYC_COLUMNS)].to_numpy()
    assert np.isfinite(x).all() and np.allclose(x.min(axis=1), 1.0)


def test_feature_keys_join_linregpcr_wells(std_rdml):
    from qpilot.qpcr.curves import analyse_study

    feats = cj.features_from_rdml(std_rdml, "biomarker_set")
    table = analyse_study(std_rdml, "biomarker_set", use_cache=False)
    assert set(feats.index) == set(zip(table["run_id"], table["well"], strict=True))
    joined = table.set_index(["run_id", "well"]).join(feats[["sample", "target"]], rsuffix="_cj")
    assert (joined["sample"] == joined["sample_cj"]).all()
    assert (joined["target"] == joined["target_cj"]).all()


def test_feature_keys_join_linregpcr_wells_past_row_26(std_rdml, tmp_path):
    """Rows 27-29 are AA, AB and AC on both sides; LinRegPCR's ``[1`` never reaches a key."""
    from qpilot.qpcr.curves import analyse_study

    tall = tall_plate(std_rdml, tmp_path / "tall.rdml")
    feats = cj.features_from_rdml(tall, "biomarker_set")
    table = analyse_study(tall, "biomarker_set", use_cache=False)
    assert set(feats.index) == set(zip(table["run_id"], table["well"], strict=True))
    run = feats.loc["AHCY_20080229"]
    assert sorted(run.index) == ["AA1", "AB1", "AC1"]
    assert list(cj.predict_calls(tall, "biomarker_set").index[:3]) == [
        "AHCY_20080229/AA1",
        "AHCY_20080229/AB1",
        "AHCY_20080229/AC1",
    ]


def test_wells_without_amplification_data_are_not_called(smoke_rdml):
    feats = cj.features_from_rdml(smoke_rdml, "Experiment 1")  # melt curves only
    assert len(feats) and not feats["callable"].any()
    assert cj.predict_proba(feats).isna().all()
    calls = cj.predict_calls(smoke_rdml, "Experiment 1")
    assert all(call is None for call in calls)  # cannot score: no call, not "not amplified"
    assert calls.index.name == "run_id/well" and calls.index.is_unique
    assert all(key.startswith("Run 1/") for key in calls.index) and "Run 1/G12" in calls.index


def _shifted_below_zero(source, target, run_id="AHCY_20080229", by=5.0):
    """One run's fluorescence moved below zero, as in an offset or baseline-subtracted export."""

    def shift(match):
        return f"<fluor>{float(match.group(1)) - by:.4f}</fluor>"

    return rewrite_run(
        source, target, run_id, lambda run: re.sub(r"<fluor>([^<]*)</fluor>", shift, run)
    )


def test_a_curve_the_model_cannot_score_has_no_call_never_not_amplified(std_rdml, tmp_path):
    shifted = _shifted_below_zero(std_rdml, tmp_path / "shifted.rdml")
    feats = cj.features_from_rdml(shifted, "biomarker_set")
    unscored = ~feats["callable"]
    assert set(feats.index[unscored].get_level_values("run_id")) == {"AHCY_20080229"}
    learned = cj.predict(feats)
    assert learned.dtype == object
    assert all(call is None for call in learned[unscored])
    assert all(call is True or call is False for call in learned[~unscored])
    calls = cj.predict_calls(shifted, "biomarker_set")
    on_run = [call for key, call in calls.items() if key.startswith("AHCY_20080229/")]
    assert on_run == [None, None, None]
    assert calls.drop([k for k in calls.index if k.startswith("AHCY_20080229/")]).all()  # STDs


# ---------- the validation flag ----------


#: The demo's fingerprint: no instrument named, SYBR with no chemistry declared, targets of
#: interest only, 45- and 50-cycle runs. The standards fixture is cut from the same file.
DEMO_FINGERPRINT = {
    "cycles": [45, 50],
    "dye": [["SYBR", ""]],
    "instrument": [""],
    "target_type": ["toi"],
}

#: An instrument a variant of the standards fixture names in every run.
NAMED = "Roche LightCycler 480"


def _transfer(path, sha, *passed, fingerprint=DEMO_FINGERPRINT, tested=None):
    """A ``transfer.json`` for model ``sha``, criteria passing as given, run on file ``tested``."""
    criteria = {f"c{i}": {"passed": p} for i, p in enumerate(passed)}
    result = {"model_sha256": sha, "criteria": criteria}
    if tested is not None:
        result["data"] = {"sha256": tested}
    if fingerprint is not None:
        result["fingerprint"] = fingerprint
    path.write_text(json.dumps(result))
    return path


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _variant(source, target, edit):
    """A copy of an RDML file with its XML passed through ``edit`` (str -> str)."""
    with zipfile.ZipFile(source) as archive:
        xml = archive.read("rdml_data.xml").decode("utf-8")
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("rdml_data.xml", edit(xml))
    return target


def _name_instrument(xml, instrument=NAMED):
    """Every run names ``instrument``, where the RDML schema puts it."""
    return xml.replace(
        "<backgroundDeterminationMethod>",
        f"<instrument>{instrument}</instrument><backgroundDeterminationMethod>",
    )


def _rescaled(xml):
    """Every fluorescence value as ``3 F + 50``: another machine's scale, the same metadata."""

    def scale(match):
        return f"<fluor>{3 * float(match.group(1)) + 50:.4f}</fluor>"

    return re.sub(r"<fluor>([^<]*)</fluor>", scale, xml)


def _first_react_cut_to_40_cycles(xml):
    start = xml.index("<react ")
    end = xml.index("</react>", start)
    late = re.compile(r"<adp><cyc>(4[1-9]|50)</cyc><fluor>[^<]*</fluor></adp>")
    return xml[:start] + late.sub("", xml[start:end]) + xml[end:]


@pytest.fixture
def named_rdml(std_rdml, tmp_path):
    """The standards fixture with every run naming :data:`NAMED`."""
    return _variant(std_rdml, tmp_path / "named.rdml", _name_instrument)


@pytest.fixture
def named_transfer(named_rdml, tmp_path):
    """A passing transfer record whose tested file declared exactly what ``named_rdml`` does."""
    recorded = cj.fingerprint(named_rdml)
    return _transfer(tmp_path / "named.json", cj.MODEL_SHA256, True, True, fingerprint=recorded)


def test_validated_reflects_transfer_json(tmp_path, std_rdml):
    good, tested = cj.MODEL_SHA256, _sha(std_rdml)

    def accepts(transfer):
        return cj.validated(std_rdml, transfer_path=transfer)

    assert accepts(_transfer(tmp_path / "a.json", good, True, True, True, tested=tested))
    assert not accepts(_transfer(tmp_path / "b.json", good, True, False, True, tested=tested))
    assert not accepts(_transfer(tmp_path / "c.json", "0" * 64, True, True, True, tested=tested))
    assert not accepts(_transfer(tmp_path / "d.json", good, tested=tested))
    assert not accepts(tmp_path / "missing.json")
    (tmp_path / "e.json").write_text("{not json")
    assert not accepts(tmp_path / "e.json")
    (tmp_path / "f.json").write_text(
        json.dumps({"model_sha256": good, "criteria": {"a": 1}, "data": {"sha256": tested}})
    )
    assert not accepts(tmp_path / "f.json")
    # the tested file is named by its exact lower-case SHA-256 or not at all
    assert not accepts(_transfer(tmp_path / "g.json", good, True, tested=tested.upper()))
    assert not accepts(_transfer(tmp_path / "h.json", good, True, tested=tested[:-1]))
    # another file was tested: the same declared fingerprint is not enough (no instrument named)
    assert not accepts(_transfer(tmp_path / "i.json", good, True, tested="0" * 64))
    assert not accepts(_transfer(tmp_path / "j.json", good, True))


def test_no_file_no_claim(tmp_path):
    passing = _transfer(tmp_path / "t.json", cj.MODEL_SHA256, True, True, True)
    assert cj.validated() is False
    assert cj.validated(None, transfer_path=passing) is False
    assert cj.status() == cj.NOT_VALIDATED
    assert cj.validated(tmp_path / "missing.rdml", transfer_path=passing) is False
    (tmp_path / "junk.rdml").write_bytes(b"not an RDML file")
    assert cj.validated(tmp_path / "junk.rdml", transfer_path=passing) is False
    named = {**DEMO_FINGERPRINT, "instrument": [NAMED]}  # a record that can cover other files
    passing = _transfer(tmp_path / "n.json", cj.MODEL_SHA256, True, fingerprint=named)
    assert cj.validated(tmp_path / "junk.rdml", transfer_path=passing) is False


def test_a_file_that_names_no_instrument_is_validated_only_by_its_hash(std_rdml, tmp_path):
    """Regression (c26): any SYBR file of 45 or 50 cycles that named no instrument was validated.

    The demo names no instrument, and neither do many exports (a Bio-Rad CFX384 plate, a copy
    rescaled to another machine's units), so "no instrument named" matched the record for all.
    """
    rescaled = _variant(std_rdml, tmp_path / "rescaled.rdml", _rescaled)
    for path in (std_rdml, rescaled):  # cut from the tested file: the very same declarations
        assert cj.fingerprint(path) == DEMO_FINGERPRINT
        assert cj.validated(path) is False
        assert cj.status(path) == cj.NOT_VALIDATED

    own = cj.fingerprint(std_rdml)
    wider = {**own, "instrument": ["", NAMED]}
    for recorded in (own, wider):  # no record covers a run that names no instrument
        transfer = _transfer(tmp_path / "t.json", cj.MODEL_SHA256, True, fingerprint=recorded)
        assert cj.validated(std_rdml, transfer_path=transfer) is False

    # the tested file itself, wherever it lies, is validated by its hash; a rescaled copy is not
    tested = _transfer(tmp_path / "s.json", cj.MODEL_SHA256, True, tested=_sha(std_rdml))
    copy = Path(shutil.copy(std_rdml, tmp_path / "copy.rdml"))
    assert cj.validated(std_rdml, transfer_path=tested) is True
    assert cj.validated(copy, transfer_path=tested) is True
    assert cj.status(copy, transfer_path=tested) == "validated"
    assert cj.validated(rescaled, transfer_path=tested) is False


def test_a_file_that_names_its_instrument_is_validated_by_its_fingerprint(
    named_rdml, named_transfer, tmp_path
):
    own = cj.fingerprint(named_rdml)
    assert own == {**DEMO_FINGERPRINT, "instrument": [NAMED]}
    assert cj.validated(named_rdml, transfer_path=named_transfer) is True
    assert cj.status(named_rdml, transfer_path=named_transfer) == "validated"

    def accepts(recorded):
        transfer = _transfer(tmp_path / "t.json", cj.MODEL_SHA256, True, fingerprint=recorded)
        return cj.validated(named_rdml, transfer_path=transfer)

    assert accepts({**own, "cycles": [40, 45, 50], "instrument": ["", NAMED]})  # a superset
    assert not accepts({k: v for k, v in own.items() if k != "cycles"})  # a field missing
    assert not accepts({**own, "dye": "SYBR"})  # not a list
    assert not accepts(None)
    # the shipped record's file named no instrument, so it covers no file that names one
    assert cj.validated(named_rdml) is False
    assert cj.status(named_rdml) == cj.NOT_VALIDATED


@pytest.mark.parametrize(
    ("label", "edit"),
    [
        (
            "another instrument in one run",
            lambda x: x.replace(NAMED, "Applied Biosystems QuantStudio 7 Flex", 1),
        ),
        (
            "a run that names no instrument",
            lambda x: x.replace(f"<instrument>{NAMED}</instrument>", "", 1),
        ),
        (
            "a run whose instrument is blank",
            lambda x: x.replace(
                f"<instrument>{NAMED}</instrument>", "<instrument> </instrument>", 1
            ),
        ),
        (
            "a probe chemistry",
            lambda x: x.replace(
                '<dye id="SYBR"/>',
                '<dye id="SYBR"><dyeChemistry>hydrolysis probe</dyeChemistry></dye>',
            ),
        ),
        ("another dye", lambda x: x.replace('"SYBR"', '"FAM"')),
        (
            "a reference target",
            lambda x: x.replace(
                '<target id="AHCY_20080229"><type>toi</type>',
                '<target id="AHCY_20080229"><type>ref</type>',
            ),
        ),
        ("a 40-cycle curve", _first_react_cut_to_40_cycles),
    ],
)
def test_validation_holds_only_for_the_instrument_and_chemistry_tested(
    named_rdml, named_transfer, tmp_path, label, edit
):
    assert cj.validated(named_rdml, transfer_path=named_transfer) is True
    changed = _variant(named_rdml, tmp_path / "changed.rdml", edit)
    assert cj.fingerprint(changed) != cj.fingerprint(named_rdml), label
    assert cj.validated(changed, transfer_path=named_transfer) is False, label
    assert cj.status(changed, transfer_path=named_transfer) == cj.NOT_VALIDATED


def test_the_shipped_record_reads_no_file_but_hashes(std_rdml, named_rdml, monkeypatch):
    """It covers its tested file only, so no other file is parsed (the demo takes ~11 s)."""

    def never(path):
        raise AssertionError(f"read {path}")

    monkeypatch.setattr(cj, "_read_fingerprint", never)
    assert cj.validated(std_rdml) is False
    assert cj.validated(named_rdml) is False


def test_the_tested_file_is_validated_without_being_read(std_rdml, tmp_path, monkeypatch):
    tested = _transfer(tmp_path / "t.json", cj.MODEL_SHA256, True, tested=_sha(std_rdml))

    def never(path):
        raise AssertionError(f"read {path}")

    monkeypatch.setattr(cj, "_read_fingerprint", never)
    assert cj.validated(std_rdml, transfer_path=tested) is True


def test_fingerprints_are_cached_by_content(std_rdml, tmp_path, monkeypatch):
    monkeypatch.setattr(cj, "_FINGERPRINTS", OrderedDict())
    reads = []
    read = cj._read_fingerprint

    def counted(path):
        reads.append(Path(path).name)
        return read(path)

    monkeypatch.setattr(cj, "_read_fingerprint", counted)
    copy = Path(shutil.copy(std_rdml, tmp_path / "copy.rdml"))
    first = cj.fingerprint(std_rdml)
    first["dye"].append("changed by the caller")
    assert cj.fingerprint(copy) == DEMO_FINGERPRINT  # same content at another path: no re-read
    assert reads == [std_rdml.name]
    _variant(std_rdml, copy, lambda x: x.replace('"SYBR"', '"FAM"'))  # new content, same path
    assert cj.fingerprint(copy)["dye"] == [["FAM", ""]]
    assert reads == [std_rdml.name, "copy.rdml"]
    monkeypatch.setattr(cj, "FINGERPRINT_CACHE_SIZE", 1)  # bounded: the oldest file goes first
    rescaled = _variant(std_rdml, tmp_path / "rescaled.rdml", _rescaled)
    cj.fingerprint(rescaled)
    assert list(cj._FINGERPRINTS) == [_sha(rescaled)]
    cj.fingerprint(std_rdml)
    assert reads == [std_rdml.name, "copy.rdml", "rescaled.rdml", std_rdml.name]


def test_a_file_that_changes_while_it_is_read_is_not_fingerprinted(
    named_rdml, named_transfer, tmp_path, monkeypatch
):
    monkeypatch.setattr(cj, "_FINGERPRINTS", OrderedDict())
    other = _variant(named_rdml, tmp_path / "other.rdml", lambda x: x.replace('"SYBR"', '"FAM"'))
    moving = Path(shutil.copy(named_rdml, tmp_path / "moving.rdml"))
    read = cj._read_fingerprint

    def swapped(path):
        out = read(path)
        shutil.copy(other, path)  # replaced between the hash and the end of the read
        return out

    monkeypatch.setattr(cj, "_read_fingerprint", swapped)
    with pytest.raises(cj.CurveJudgeError, match="changed while"):
        cj.fingerprint(moving)
    assert not cj._FINGERPRINTS  # neither content was filed under the other's hash
    shutil.copy(named_rdml, moving)
    assert cj.validated(moving, transfer_path=named_transfer) is False


def test_a_file_without_amplification_curves_is_not_validated(smoke_rdml):
    assert cj.fingerprint(smoke_rdml) == {
        "cycles": [0],
        "dye": [["dye 1", ""]],
        "instrument": [""],
        "target_type": ["toi"],
    }
    assert cj.validated(smoke_rdml) is False


def test_shipped_transfer_result_is_for_the_shipped_model(std_rdml):
    from qpilot.io.datasets import VERMEULEN_SHA256

    result = json.loads((MODEL_DIR / "transfer.json").read_text())
    assert result["model_sha256"] == cj.MODEL_SHA256
    assert len(result["preregistered_in_commit"]) == 40
    assert result["data"]["sha256"] == VERMEULEN_SHA256
    criteria = result["criteria"]
    assert set(criteria) == {
        "a_standards_called_amplified",
        "b_agreement_with_linregpcr_cq_below_30",
        "c_ntc_calls_tabulated",
    }
    passed = all(c["passed"] for c in criteria.values())
    assert result["verdict"] == ("pass" if passed else "fail")
    assert result["fingerprint"] == DEMO_FINGERPRINT
    assert cj.validated() is False  # no file, no claim
    assert cj.validated(std_rdml) is False  # cut from the tested file, but not that file
    assert cj.status(std_rdml) == cj.NOT_VALIDATED
    a, b = (
        criteria["a_standards_called_amplified"],
        criteria["b_agreement_with_linregpcr_cq_below_30"],
    )
    assert a["n"] == 960 and a["passed"] == (100 * a["called_amplified"] >= 99 * a["n"])
    assert b["passed"] == (100 * b["agree"] >= 99 * b["n"])
    assert criteria["c_ntc_calls_tabulated"]["n"] == len(criteria["c_ntc_calls_tabulated"]["table"])


@pytest.mark.demo_data
def test_the_recorded_fingerprint_is_the_transfer_tested_files(demo_rdml_path):
    from qpilot.qpcr.curves import file_sha256

    result = json.loads((MODEL_DIR / "transfer.json").read_text())
    assert file_sha256(demo_rdml_path) == result["data"]["sha256"]
    assert cj.fingerprint(demo_rdml_path) == result["fingerprint"]
    assert cj.validated(demo_rdml_path) is (result["verdict"] == "pass")
    assert cj.status(demo_rdml_path) == "validated"


def _transfer_script():
    import importlib.util

    path = ROOT / "training" / "curve_judge" / "transfer.py"
    spec = importlib.util.spec_from_file_location("curve_judge_transfer_script", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.demo_data
def test_the_transfer_script_writes_the_shipped_record(demo_rdml_path, tmp_path, monkeypatch):
    """A re-run writes ``transfer.json`` byte for byte (but the date), the fingerprint included.

    The test itself is not re-run: the measured parts are the shipped ones, passed through.
    """
    shipped_text = (MODEL_DIR / "transfer.json").read_text(encoding="utf-8")
    shipped = json.loads(shipped_text)
    script = _transfer_script()
    monkeypatch.setattr(script, "run", lambda rdml: range(shipped["data"]["wells"]))
    monkeypatch.setattr(script, "criteria", lambda table: json.loads(shipped_text)["criteria"])
    monkeypatch.setattr(
        script, "descriptive", lambda table: json.loads(shipped_text)["descriptive_not_gated"]
    )
    args = ["--rdml", str(demo_rdml_path), "--out", str(tmp_path)]
    assert script.main([*args, "--preregistered-in", shipped["preregistered_in_commit"]]) == 0
    written = json.loads((tmp_path / "transfer.json").read_text(encoding="utf-8"))
    assert list(written) == list(shipped)  # "fingerprint" right after "data"
    written["date"] = shipped["date"]
    assert json.dumps(written, indent=1) + "\n" == shipped_text


def test_validated_is_false_when_the_model_is_refused(tmp_path, monkeypatch, std_rdml):
    transfer = _transfer(tmp_path / "t.json", cj.MODEL_SHA256, True, True, tested=_sha(std_rdml))
    assert cj.validated(std_rdml, transfer_path=transfer)

    def refuse():
        raise cj.ModelIntegrityError("tampered")

    monkeypatch.setattr(cj, "shipped_model", refuse)
    assert not cj.validated(std_rdml, transfer_path=transfer)


def test_learned_rule_is_one_option_never_the_default():
    rule = cj.LEARNED_RULE
    assert isinstance(rule, AmpCallRule)
    assert (rule.id, rule.kind, rule.recommended) == ("learned", "learned", False)
    assert (ROOT / rule.method_card).is_file()
    assert cj.NOT_VALIDATED in rule.note


def test_packaged_method_card_is_the_method_card():
    packaged = (MODEL_DIR / "METHOD_CARD.md").read_text()
    assert packaged == (ROOT / cj.METHOD_CARD).read_text()
    assert "CC BY 4.0" in packaged and cj.MODEL_SHA256 in packaged


# ---------- offline, and no AI ----------


def test_inference_runs_offline(offline, metrics, std_rdml):
    cj.shipped_model.cache_clear()
    _, fluor = _sample(metrics)
    assert np.isfinite(cj.load_model().predict_proba(cj.normalise(fluor))).all()
    assert len(cj.features_from_rdml(std_rdml, "biomarker_set")) == 192


def test_curve_judge_imports_nothing_from_ai_or_xgboost():
    code = (
        "import sys\n"
        "import qpilot.qpcr.curve_judge as cj\n"
        "cj.load_model()\n"
        "bad = sorted(m for m in sys.modules if m.startswith("
        "('qpilot.ai', 'anthropic', 'httpx', 'xgboost')))\n"
        "assert not bad, bad\n"
        "print('ok')\n"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "ok"


def test_features_are_read_once_per_file_contents(tmp_path, monkeypatch):
    """perf: Check the curves and the curve-calls view share one read of the file's curves."""
    import shutil

    import qpilot.qpcr.curve_judge as cj

    calls = []
    frame = pd.DataFrame({"Cyc1": [1.0]})
    monkeypatch.setattr(cj, "_FEATURES", {})
    path = tmp_path / "a.rdml"
    path.write_bytes(b"not read")
    monkeypatch.setattr(cj, "read_features", lambda *a: calls.append(a) or frame)
    first = cj.features_from_rdml(path, "exp")
    first.loc[0, "Cyc1"] = 99.0  # a caller's change stays its own
    again = cj.features_from_rdml(path, "exp")
    assert len(calls) == 1 and again.loc[0, "Cyc1"] == 1.0
    cj.features_from_rdml(path, "other")
    shutil.copy(path, tmp_path / "b.rdml")
    cj.features_from_rdml(tmp_path / "b.rdml", "exp")  # same bytes elsewhere: kept
    assert len(calls) == 2
    path.write_bytes(b"other bytes")
    cj.features_from_rdml(path, "exp")
    assert len(calls) == 3
