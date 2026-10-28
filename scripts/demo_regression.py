"""Demo regression: the locked demo numbers, the legacy grid and determinism, end to end.

Runs the real CLI (``qpilot run --out`` twice and ``qpilot validate --out``) on the cached
demo study and checks, in this order:

1. **Locked numbers** (the brief's list, at the precision the product prints them).
2. **Fingerprint**: every gene's fold change, interval, p, conclusion and robustness share,
   every card's impact and per-option result, and every baseline fact's value are exactly
   (bit for bit) what ``scripts/demo_fingerprint.json`` recorded. New keys, facts or cards
   are allowed (additive); a changed or missing one fails.
3. **Legacy grid**: ``grid.csv`` is byte-identical to the baseline (new axes must be opt-in).
4. **Determinism**: two runs write byte-identical files.
5. **Validation**: ``qpilot validate`` writes a ``validation.json`` byte-identical to the
   committed ``validation/validation.json``.

Prints one summary line starting ``DEMO REGRESSION: PASS`` or ``DEMO REGRESSION: FAIL``.
Exit code 0 = pass, 1 = fail, 2 = skipped (demo dataset not cached).

Usage::

    python scripts/demo_regression.py                      # the check
    python scripts/demo_regression.py --fresh-curves       # recompute curves (no curve cache)
    python scripts/demo_regression.py --write-fingerprint  # re-baseline (release captain only)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FINGERPRINT = ROOT / "scripts" / "demo_fingerprint.json"
COMMITTED_VALIDATION = ROOT / "validation" / "validation.json"
OUTPUTS = ("results.json", "cards.json", "facts.json", "grid.csv")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _cache_dir() -> Path:
    override = os.environ.get("QPILOT_CACHE_DIR")
    return Path(override) if override else Path.home() / ".cache" / "qpilot"


def _qpilot(args: list[str], env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    cmd = [sys.executable, "-c", "import sys; from qpilot.cli import main; sys.exit(main())", *args]
    return subprocess.run(cmd, capture_output=True, text=True, env=env, cwd=ROOT, check=False)


def fingerprint(run_dir: Path) -> dict:
    """The legacy-analysis numbers that must never move, from one ``qpilot run --out``."""
    results = json.loads((run_dir / "results.json").read_text(encoding="utf-8"))
    cards = json.loads((run_dir / "cards.json").read_text(encoding="utf-8"))
    facts = json.loads((run_dir / "facts.json").read_text(encoding="utf-8"))
    genes = {}
    for gene in sorted(results["contrasts"]):
        c = results["contrasts"][gene]
        r = results["robustness"].get(gene, {})
        genes[gene] = {
            "fc": c["fc"],
            "ci": c["ci"],
            "p": c["p"],
            "conclusion": c["conclusion"],
            "n": [c["n_hi"], c["n_lo"]],
            "holds": r.get("holds"),
            "n_cells": r.get("n_cells"),
        }
    card_fp = {}
    for card in cards:
        impact = {
            k: v
            for k, v in card["impact"].items()
            if k.startswith("n_genes_flipped") or k == "flips"
        }
        options = {
            o["id"]: {g: [v["fc"], v["conclusion"]] for g, v in sorted(o["per_gene"].items())}
            for o in card["options"]
        }
        card_fp[card["id"]] = {
            "kind": card["kind"],
            "status": card["status"],
            "rank": card["rank"],
            "recommended": card["recommended"],
            "impact": impact,
            "options": options,
        }
    return {
        "study": {
            "study_id": results["study_id"],
            "n_plates": results["n_plates"],
            "n_reactions": results["n_reactions"],
            "n_samples": results["n_samples"],
            "n_hi": results["design"]["n_hi"],
            "n_lo": results["design"]["n_lo"],
            "n_contrasts": len(results["contrasts"]),
        },
        "genes": genes,
        "cards": card_fp,
        "facts": {fid: f.get("value") for fid, f in sorted(facts.items())},
        "grid_sha256": _sha(run_dir / "grid.csv"),
        "bytes_sha256": {name: _sha(run_dir / name) for name in OUTPUTS},
    }


def locked_checks(run_dir: Path, validation: dict) -> list[tuple[str, bool, str]]:
    """The brief's locked demo numbers, at printed precision: (name, ok, observed)."""
    results = json.loads((run_dir / "results.json").read_text(encoding="utf-8"))
    cards = {c["id"]: c for c in json.loads((run_dir / "cards.json").read_text(encoding="utf-8"))}
    out: list[tuple[str, bool, str]] = []

    def check(name: str, observed, expected) -> None:
        out.append((name, observed == expected, f"{observed!r} (want {expected!r})"))

    odc1 = results["contrasts"]["ODC1"]
    check("ODC1 fold change 3.59x", round(odc1["fc"], 2), 3.59)
    check("ODC1 interval [2.42-5.33]", [round(x, 2) for x in odc1["ci"]], [2.42, 5.33])
    check(
        "ODC1 conclusion up, holds 100 %",
        (odc1["conclusion"], results["robustness"]["ODC1"]["holds"]),
        ("up", 1.0),
    )
    refset = cards.get("card_refset", {"options": [], "impact": {}})
    per = {o["id"]: o["per_gene"] for o in refset["options"]}
    check(
        "HMBS-alone ODC1 2.66x",
        round(per.get("hmbs_alone", {}).get("ODC1", {}).get("fc", 0), 2),
        2.66,
    )
    check(
        "UBC-alone ODC1 4.66x",
        round(per.get("ubc_2_alone", {}).get("ODC1", {}).get("fc", 0), 2),
        4.66,
    )
    nm = results["contrasts"]["NM23A"]
    check("NM23A fold change 2.19x", round(nm["fc"], 2), 2.19)
    check("NM23A holds 64.5 % (120/186)", round(results["robustness"]["NM23A"]["holds"], 3), 0.645)
    check(
        "NM23A under HMBS alone: no call",
        per.get("hmbs_alone", {}).get("NM23A", {}).get("conclusion"),
        "none",
    )
    check("31 of 58 flip with the normaliser", refset["impact"].get("n_genes_flipped"), 31)
    check("17 of 58 flip between sets of >= 3", refset["impact"].get("n_genes_flipped_min3"), 17)
    check("58 genes", len(results["contrasts"]), 58)
    check("186 cells in the legacy grid", results["robustness"]["ODC1"]["n_cells"], 186)
    n0, cq = validation["n0"], validation["cq"]
    check("validation 930 wells", n0["wells"], 930)
    check("validation 99.6 % identical", round(n0["share_identical"] * 100, 1), 99.6)
    check("validation 100 % within 5 %", round(n0["share_within"] * 100, 1), 100.0)
    check("Cq offset +0.97", round(cq["mean_offset"], 2), 0.97)
    check("Cq offset SD 0.17", round(cq["sd_offset"], 2), 0.17)
    return out


def _diff(base, new, path: str = "") -> list[str]:
    """Changed or missing entries of ``base`` in ``new``; keys only in ``new`` are fine."""
    if isinstance(base, dict) and isinstance(new, dict):
        problems = []
        for key, value in base.items():
            if key not in new:
                problems.append(f"{path}/{key}: missing")
            else:
                problems.extend(_diff(value, new[key], f"{path}/{key}"))
        return problems
    return [] if base == new else [f"{path}: {base!r} -> {new!r}"]


def _fresh_cache(tmp: Path) -> Path:
    """A private cache holding only the pinned inputs, so curves are recomputed."""
    cache = tmp / "cache"
    cache.mkdir()
    for item in _cache_dir().iterdir():
        if item.is_file() and not item.name.endswith(".curves.csv"):
            (cache / item.name).symlink_to(item)
    return cache


def main() -> int:
    """Run the demo regression and print one summary line."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", default=None, help="keep outputs here (default: a temp dir)")
    parser.add_argument("--fresh-curves", action="store_true", help="bypass the curve cache")
    parser.add_argument("--write-fingerprint", action="store_true", help="re-baseline")
    parser.add_argument("-v", "--verbose", action="store_true", help="list every check")
    args = parser.parse_args()

    demo = _cache_dir() / "data_vermeulen_raw.rdml"
    if not demo.exists():
        print("DEMO REGRESSION: SKIP (demo dataset not cached; run `qpilot fetch-demo`)")
        return 2

    with tempfile.TemporaryDirectory(prefix="qpilot-demo-reg-") as tmp_name:
        tmp = Path(args.out) if args.out else Path(tmp_name)
        tmp.mkdir(parents=True, exist_ok=True)
        env = dict(os.environ)
        env.setdefault("MPLBACKEND", "Agg")
        if args.fresh_curves:
            env["QPILOT_CACHE_DIR"] = str(_fresh_cache(Path(tmp_name)))
        failures: list[str] = []
        notes: list[str] = []

        for name in ("a", "b"):
            proc = _qpilot(["run", "--out", str(tmp / name)], env)
            if proc.returncode != 0:
                print(proc.stdout[-2000:], proc.stderr[-4000:], sep="\n")
                print(f"DEMO REGRESSION: FAIL (qpilot run exited {proc.returncode})")
                return 1
        proc = _qpilot(["validate", "--out", str(tmp / "validation")], env)
        if proc.returncode != 0:
            print(proc.stdout[-2000:], proc.stderr[-4000:], sep="\n")
            print(f"DEMO REGRESSION: FAIL (qpilot validate exited {proc.returncode})")
            return 1
        validation_path = tmp / "validation" / "validation.json"
        validation = json.loads(validation_path.read_text(encoding="utf-8"))

        nondeterministic = [
            n for n in OUTPUTS if (tmp / "a" / n).read_bytes() != (tmp / "b" / n).read_bytes()
        ]
        if nondeterministic:
            failures.append(f"not deterministic: {', '.join(nondeterministic)}")

        locked = locked_checks(tmp / "a", validation)
        for name, ok, observed in locked:
            if not ok:
                failures.append(f"locked: {name}: {observed}")
            elif args.verbose:
                print(f"  ok  {name}: {observed}")

        if validation_path.read_bytes() != COMMITTED_VALIDATION.read_bytes():
            failures.append("validation.json differs from the committed validation/validation.json")

        fp = fingerprint(tmp / "a")
        if args.write_fingerprint:
            FINGERPRINT.write_text(
                json.dumps(fp, indent=1, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
            )
            notes.append(f"fingerprint written to {FINGERPRINT.relative_to(ROOT)}")
        elif not FINGERPRINT.exists():
            failures.append("no scripts/demo_fingerprint.json (run with --write-fingerprint)")
        else:
            base = json.loads(FINGERPRINT.read_text(encoding="utf-8"))
            if fp["grid_sha256"] != base["grid_sha256"]:
                failures.append("legacy grid.csv is not byte-identical to the baseline")
            semantic = _diff({k: base[k] for k in ("study", "genes", "cards", "facts")}, fp)
            if semantic:
                failures.append(f"fingerprint: {len(semantic)} changed/missing value(s)")
                for line in semantic[:25]:
                    print(f"  changed {line}")
                if len(semantic) > 25:
                    print(f"  ... and {len(semantic) - 25} more")
            drift = [n for n in OUTPUTS if fp["bytes_sha256"][n] != base["bytes_sha256"][n]]
            added_facts = sorted(set(fp["facts"]) - set(base["facts"]))
            added_cards = sorted(set(fp["cards"]) - set(base["cards"]))
            if drift:
                notes.append(f"bytes changed (additive): {', '.join(drift)}")
            if added_facts:
                notes.append(f"+{len(added_facts)} facts")
            if added_cards:
                notes.append(f"+cards {', '.join(added_cards)}")
            if not drift:
                notes.append("outputs byte-identical to baseline")

        for line in failures:
            print(f"  FAIL {line}")
        n_ok = sum(ok for _, ok, _ in locked)
        detail = f"locked {n_ok}/{len(locked)}; " + "; ".join(notes)
        if args.fresh_curves:
            detail += "; fresh curves"
        verdict = "FAIL" if failures else "PASS"
        print(f"DEMO REGRESSION: {verdict} ({detail})")
        return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
