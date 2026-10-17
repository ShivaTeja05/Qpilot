"""Pre-registered transfer test of the Curve Judge on the demo instrument -> ``transfer.json``.

**Pre-registration.** This file, with the gate, the counting rules and the two substitutions
below, was written and committed *before any Curve Judge prediction was made on demo data*
(including the ``tests/fixtures/vermeulen_std_150000.rdml`` subset of the demo). The commit
that adds this file is the pre-registration; the commit that adds ``transfer.json`` comes
after it. None of the constants or rules below may change after the result is known. If the
gate fails, the learned option ships disabled, labelled "not validated for this instrument":
the gate is never loosened and the model is never retrained or tuned on demo data to pass it.

Usage (qPilot's own environment; no XGBoost needed, the shipped numpy evaluator is tested)::

    python training/curve_judge/transfer.py --preregistered-in <commit> \
        [--rdml ~/.cache/qpilot/data_vermeulen_raw.rdml] [--out qpilot/models/curve_judge]

Why a transfer test. The model learned from TaqMan Array Cards (hydrolysis probes, FAM/VIC
with the ROX passive reference, QuantStudio, 40 cycles, stool nucleic acid). The demo is the
Vermeulen 2009 neuroblastoma study: SYBR Green I on a Roche LightCycler 480, no ROX, 45-50
cycles, cDNA. Nothing in the held-out accuracy says the model transfers.

The gate: all three must hold (experiment ``biomarker_set`` of the pinned demo RDML)
-----------------------------------------------------------------------------------
(a) >= 99 % of the dilution-standard wells are called amplified. The standards are the wells
    with sample type ``std`` and sample ``STD_15``, ``STD_150``, ``STD_1500``, ``STD_15000`` or
    ``STD_150000``: 64 plates x 5 levels x 3 replicates = **960** wells (checked: the file has
    exactly 960). If the count is not 960 the criterion fails.
(b) >= 99 % agreement with LinRegPCR's amplification call (the ``amplification`` column of
    :func:`qpilot.qpcr.curves.analyse_study`, library-default settings) on the unknown wells
    (sample type ``unkn``) whose LinRegPCR Cq (TD0) is below 30 (16,153 wells; a well without
    a Cq is not "below 30"). Agreement = learned call equals LinRegPCR's call.
(c) The NTC calls are tabulated: every ``ntc`` well (192) with its learned probability, learned
    call, LinRegPCR's amplification call and Cq. No threshold; it passes when the table holds
    every NTC well of the experiment (and there is at least one).

Counting rules: the learned call is ``p > 0.5`` exactly as trained (no re-thresholding). A well
that cannot be standardised (missing, zero or negative fluorescence) has no call; it counts as
"not amplified" in (a) and (b). "At least 99 %" is tested in integers:
``100 * hits >= 99 * n``.

Substitution 1, normalisation without ROX (per-curve). The paper's input is
``Fnorm = Fstand - (Fmin - 1)`` with ``Fstand = reporter / ROX``. With no passive reference,
``Fstand = F / min(F)``: each curve divided by its own minimum over cycles 1-40
(``qpilot.qpcr.curve_judge.standardise_without_reference``), so it starts from 1 as a
ROX-standardised TAC curve's minimum is shifted to 1; the paper's ``Fnorm`` step is then
applied unchanged. This keeps the shape (relative rise) and discards the instrument's arbitrary
fluorescence scale. Known mismatch, accepted in advance: SYBR Green rises far more, relative to
its baseline, than a probe's ROX-standardised signal, so amplitudes are larger than any in
training.

Substitution 2, cycle count. The model takes exactly 40 inputs, ``Cyc1..Cyc40``. The LC480
runs here record 45 or 50 cycles. Cycle *k* of the LC480 curve is input ``Cyc<k>`` for
k = 1..40 (same cycle numbers, as both instruments count from the first amplification cycle);
cycles 41-50 are dropped. No rescaling, resampling or alignment. A curve that rises only after
cycle 40 is invisible to the model, as it would be on a 40-cycle TAC run.

Descriptive only (no threshold, not part of the gate): learned vs LinRegPCR on all unknown
wells, and the standards by dilution level.

Known blind spot of this gate, stated before the result: (a) and (b) only ask for "amplified"
where amplification is expected, so a model that over-calls would pass them. The only evidence
on false positives is the NTC table (c) and the descriptive 2x2 on all unknown wells; both
are written to ``transfer.json`` and must be read, not just the verdict.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import sys
from dataclasses import asdict
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO))

from qpilot.io.datasets import VERMEULEN_FILENAME, VERMEULEN_SHA256, default_cache_dir  # noqa: E402
from qpilot.qpcr import curve_judge  # noqa: E402
from qpilot.qpcr.curves import CurveSettings, analyse_study  # noqa: E402

# ---- the pre-registered gate (never change after the result is known) ----
EXPERIMENT = "biomarker_set"
STANDARD_SAMPLES = ("STD_15", "STD_150", "STD_1500", "STD_15000", "STD_150000")
EXPECTED_STANDARD_WELLS = 960
MIN_FRACTION_STANDARDS = 0.99  # (a)
CQ_BELOW = 30.0  # (b): LinRegPCR Cq strictly below this
MIN_AGREEMENT = 0.99  # (b)
THRESHOLD = curve_judge.THRESHOLD  # 0.5, as trained
INSTRUMENT = "Roche LightCycler 480, SYBR Green I, no passive reference (Vermeulen et al. 2009)"
NORMALISATION = (
    "Fstand = F / min(F over cycles 1-40) per curve (no ROX on this instrument); "
    "then Fnorm = Fstand - (Fmin - 1) as in the paper"
)
CYCLE_MAPPING = "LC480 cycle k -> Cyc<k> for k = 1..40; cycles 41-50 dropped; no resampling"


def at_least(hits: int, n: int, fraction: float) -> bool:
    """``hits / n >= fraction`` in exact integer arithmetic (fraction given in percent steps)."""
    return n > 0 and 100 * hits >= round(100 * fraction) * n


def sha256_file(path: Path) -> str:
    """SHA-256 of a file."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run(rdml: Path) -> pd.DataFrame:
    """Learned call and LinRegPCR call side by side, one row per well of the experiment."""
    features = curve_judge.features_from_rdml(rdml, EXPERIMENT)
    p = curve_judge.predict_proba(features)
    learned = pd.DataFrame(
        {"learned_p": p, "learned": (p > THRESHOLD).to_numpy(), "callable": features["callable"]},
        index=features.index,
    )
    curves = analyse_study(rdml, EXPERIMENT).set_index(["run_id", "well"])
    if not curves.index.is_unique:
        raise SystemExit("LinRegPCR table has duplicate run_id/well keys")
    table = curves[["sample", "sample_type", "target", "cq", "amplification"]].join(
        learned, how="outer"
    )
    if table["sample_type"].isna().any() or table["callable"].isna().any():
        raise SystemExit("learned and LinRegPCR wells do not match one to one")
    table["learned"] = table["learned"].astype(bool)
    return table


def criteria(table: pd.DataFrame) -> dict[str, dict[str, object]]:
    """Evaluate the three pre-registered criteria."""
    std = table[(table["sample_type"] == "std") & table["sample"].isin(STANDARD_SAMPLES)]
    n_std, hits_std = len(std), int(std["learned"].sum())
    a_pass = n_std == EXPECTED_STANDARD_WELLS and at_least(hits_std, n_std, MIN_FRACTION_STANDARDS)
    by_level = {
        level: {
            "n": int((std["sample"] == level).sum()),
            "called_amplified": int(std.loc[std["sample"] == level, "learned"].sum()),
            "linregpcr_amplified": int(std.loc[std["sample"] == level, "amplification"].sum()),
        }
        for level in STANDARD_SAMPLES
    }

    unkn = table[(table["sample_type"] == "unkn") & (table["cq"] < CQ_BELOW)]
    n_b = len(unkn)
    agree = int((unkn["learned"] == unkn["amplification"]).sum())
    b_pass = at_least(agree, n_b, MIN_AGREEMENT)

    ntc = table[table["sample_type"] == "ntc"].reset_index()
    rows = [
        {
            "run_id": r.run_id,
            "well": r.well,
            "target": r.target,
            "learned_p": None if pd.isna(r.learned_p) else round(float(r.learned_p), 6),
            "learned": bool(r.learned),
            "linregpcr_amplification": bool(r.amplification),
            "cq": None if pd.isna(r.cq) else round(float(r.cq), 3),
        }
        for r in ntc.itertuples()
    ]
    return {
        "a_standards_called_amplified": {
            "rule": f">= {MIN_FRACTION_STANDARDS:.0%} of the {EXPECTED_STANDARD_WELLS} standard "
            "wells (STD_15 ... STD_150000) called amplified",
            "n": n_std,
            "expected_n": EXPECTED_STANDARD_WELLS,
            "called_amplified": hits_std,
            "fraction": round(hits_std / n_std, 6) if n_std else None,
            "not_callable": int((~std["callable"].astype(bool)).sum()),
            "by_level": by_level,
            "passed": bool(a_pass),
        },
        "b_agreement_with_linregpcr_cq_below_30": {
            "rule": f">= {MIN_AGREEMENT:.0%} agreement with LinRegPCR's amplification call on "
            f"unknown wells with Cq < {CQ_BELOW:g}",
            "n": n_b,
            "agree": agree,
            "fraction": round(agree / n_b, 6) if n_b else None,
            "learned_yes_linregpcr_yes": int((unkn["learned"] & unkn["amplification"]).sum()),
            "learned_yes_linregpcr_no": int((unkn["learned"] & ~unkn["amplification"]).sum()),
            "learned_no_linregpcr_yes": int((~unkn["learned"] & unkn["amplification"]).sum()),
            "learned_no_linregpcr_no": int((~unkn["learned"] & ~unkn["amplification"]).sum()),
            "not_callable": int((~unkn["callable"].astype(bool)).sum()),
            "passed": bool(b_pass),
        },
        "c_ntc_calls_tabulated": {
            "rule": "every NTC well tabulated with both calls (no threshold)",
            "n": len(rows),
            "called_amplified": int(sum(r["learned"] for r in rows)),
            "linregpcr_amplified": int(sum(r["linregpcr_amplification"] for r in rows)),
            "table": rows,
            "passed": bool(
                len(rows) > 0 and len(rows) == int((table["sample_type"] == "ntc").sum())
            ),
        },
    }


def descriptive(table: pd.DataFrame) -> dict[str, object]:
    """Not part of the gate: learned vs LinRegPCR on every unknown well."""
    unkn = table[table["sample_type"] == "unkn"]
    return {
        "unknown_wells_all": {
            "n": len(unkn),
            "learned_yes_linregpcr_yes": int((unkn["learned"] & unkn["amplification"]).sum()),
            "learned_yes_linregpcr_no": int((unkn["learned"] & ~unkn["amplification"]).sum()),
            "learned_no_linregpcr_yes": int((~unkn["learned"] & unkn["amplification"]).sum()),
            "learned_no_linregpcr_no": int((~unkn["learned"] & ~unkn["amplification"]).sum()),
        },
        "learned_p_quantiles_unknown": {
            q: round(float(np.nanquantile(unkn["learned_p"], q)), 6) for q in (0.01, 0.5, 0.99)
        },
    }


def main(argv: list[str] | None = None) -> int:
    """Command-line entry point: run the test and write ``transfer.json``."""
    parser = argparse.ArgumentParser(description="Pre-registered Curve Judge transfer test.")
    parser.add_argument("--rdml", type=Path, default=default_cache_dir() / VERMEULEN_FILENAME)
    parser.add_argument("--out", type=Path, default=REPO / "qpilot" / "models" / "curve_judge")
    parser.add_argument(
        "--preregistered-in", required=True, help="commit that added this file (the gate)"
    )
    args = parser.parse_args(argv)

    rdml_sha = sha256_file(args.rdml)
    if rdml_sha != VERMEULEN_SHA256:
        raise SystemExit(f"{args.rdml} is not the pinned demo file (sha256 {rdml_sha})")
    model = curve_judge.shipped_model()  # verified against both pins
    table = run(args.rdml)
    result = criteria(table)
    passed = all(c["passed"] for c in result.values())
    out = {
        "test": "Curve Judge transfer to the demo instrument (pre-registered)",
        "preregistered_in_commit": args.preregistered_in,
        "date": dt.date.today().isoformat(),
        "model_sha256": model.sha256,
        "instrument": INSTRUMENT,
        "data": {
            "file": VERMEULEN_FILENAME,
            "sha256": rdml_sha,
            "experiment": EXPERIMENT,
            "wells": len(table),
            "linregpcr_settings": asdict(CurveSettings()),
        },
        "normalisation": NORMALISATION,
        "cycle_mapping": CYCLE_MAPPING,
        "threshold": THRESHOLD,
        "criteria": result,
        "verdict": "pass" if passed else "fail",
        "learned_option": "enabled" if passed else f"disabled: {curve_judge.NOT_VALIDATED}",
        "descriptive_not_gated": descriptive(table),
    }
    path = args.out / "transfer.json"
    path.write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
    summary = {
        k: {kk: v for kk, v in c.items() if kk not in ("table", "by_level")}
        for k, c in result.items()
    }
    print(json.dumps(summary, indent=1))
    print(f"verdict: {out['verdict']} -> learned option {out['learned_option']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
