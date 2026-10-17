"""Curve Judge: a pinned model that refuses tampering, a numpy evaluator that matches XGBoost,
deterministic features, an honest validation flag, offline, and no AI imports.

No network and no XGBoost: the evaluator is checked against predictions XGBoost made in the
training environment and stored in ``metrics.json`` (``training/curve_judge/evaluate.py``).
"""

import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from pytest_socket import disable_socket, enable_socket

from qpilot.qpcr import curve_judge as cj
from qpilot.schemas_studio import AmpCallRule

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


def test_wells_without_amplification_data_are_not_called(smoke_rdml):
    feats = cj.features_from_rdml(smoke_rdml, "Experiment 1")  # melt curves only
    assert len(feats) and not feats["callable"].any()
    assert cj.predict_proba(feats).isna().all()
    calls = cj.predict_calls(smoke_rdml, "Experiment 1")
    assert calls.dtype == bool and not calls.any()
    assert calls.index.name == "run_id/well" and calls.index.is_unique
    assert all(key.startswith("Run 1/") for key in calls.index) and "Run 1/G12" in calls.index


# ---------- the validation flag ----------


def _transfer(path, sha, *passed):
    criteria = {f"c{i}": {"passed": p} for i, p in enumerate(passed)}
    path.write_text(json.dumps({"model_sha256": sha, "criteria": criteria}))
    return path


def test_validated_reflects_transfer_json(tmp_path):
    good = cj.MODEL_SHA256
    assert cj.validated(_transfer(tmp_path / "a.json", good, True, True, True))
    assert not cj.validated(_transfer(tmp_path / "b.json", good, True, False, True))
    assert not cj.validated(_transfer(tmp_path / "c.json", "0" * 64, True, True, True))
    assert not cj.validated(_transfer(tmp_path / "d.json", good))
    assert not cj.validated(tmp_path / "missing.json")
    (tmp_path / "e.json").write_text("{not json")
    assert not cj.validated(tmp_path / "e.json")
    (tmp_path / "f.json").write_text(json.dumps({"model_sha256": good, "criteria": {"a": 1}}))
    assert not cj.validated(tmp_path / "f.json")


def test_validated_is_false_when_the_model_is_refused(tmp_path, monkeypatch):
    transfer = _transfer(tmp_path / "t.json", cj.MODEL_SHA256, True, True, True)

    def refuse():
        raise cj.ModelIntegrityError("tampered")

    monkeypatch.setattr(cj, "shipped_model", refuse)
    assert not cj.validated(transfer)


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
