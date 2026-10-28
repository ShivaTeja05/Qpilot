"""Run qPilot's full harness (Studio items included) against local models on a GPU machine.

Used for the scorecards in ``docs/studio-measured.md`` that need more GPU memory than a laptop:
it installs qPilot from this checkout and Ollama, pulls each model, and runs one harness per
model in parallel against the Ollama server on the same machine, so nothing is sent anywhere
else. Only the public demo dataset is used (fetched with its SHA-256 pin).

Usage, from the root of a qPilot checkout on a Linux GPU machine (a RunPod or Kaggle box),
in a fresh virtual environment so the image's own packages never get in the way::

    python -m venv /workspace/venv
    /workspace/venv/bin/python scripts/gpu_harness.py --models qwen2.5:72b,llama3.3:70b \
        --out /workspace/scorecards

Each model's ``scorecard.md`` and ``scorecard.json`` are written under ``--out``, and every
scorecard is printed at the end. The per-call timeout is raised (``--timeout``, default 600 s)
so a large model is never cut off by qPilot's laptop default.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OLLAMA = "127.0.0.1:11434"

HARNESS = r"""
import json, sys, time
from pathlib import Path
from qpilot.ai.client import ModelClient, OpenAICompatibleBackend
from qpilot.ai.config import ModelConfig
from qpilot.core.store import StudyStore
from qpilot.harness.make_evalset import build_items
from qpilot.harness.report import markdown
from qpilot.harness.run import run
from qpilot.io.datasets import VERMEULEN_FILENAME, default_cache_dir

model, timeout, out = sys.argv[1], float(sys.argv[2]), Path(sys.argv[3])
store = StudyStore()
study_id = store.ensure_study(default_cache_dir() / VERMEULEN_FILENAME)
result = store.get(study_id)
items = build_items(result, store.cards(study_id), result.facts, n_per_type=10, studio=True)
endpoint = "http://127.0.0.1:11434/v1"
config = ModelConfig(provider="openai_compatible", endpoint=endpoint, model=model)
client = ModelClient(OpenAICompatibleBackend(config, timeout=timeout))
start = time.time()
report = run(items, client, store, study_id, profile_name=f"gpu {model}")
minutes = (time.time() - start) / 60
out.mkdir(parents=True, exist_ok=True)
(out / "scorecard.json").write_text(json.dumps(report.model_dump(), indent=2, default=str))
(out / "scorecard.md").write_text(
    f"# {model}, {minutes:.1f} min, timeout {timeout:.0f} s per call\n\n" + markdown([report])
)
"""


def _slug(model: str) -> str:
    """A folder name for a model (``qwen2.5:72b`` -> ``qwen2.5_72b``)."""
    return model.replace(":", "_").replace("/", "_")


def say(message: str) -> None:
    """One timestamped progress line."""
    print(f"[{time.strftime('%H:%M:%S')}] {message}", flush=True)


def sh(command: str) -> None:
    """Run a shell command (this script's own fixed commands only); stop on failure."""
    say(f"$ {command}")
    subprocess.run(command, shell=True, check=True)  # noqa: S602 (fixed commands, no user text)


def main() -> int:
    """Install, pull, run every model's harness in parallel, print the scorecards."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--models", required=True, help="comma-separated Ollama model names")
    parser.add_argument("--out", default="scorecards", help="where the scorecards go")
    parser.add_argument("--timeout", type=float, default=600.0, help="seconds per model call")
    args = parser.parse_args()
    models = [m.strip() for m in args.models.split(",") if m.strip()]
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)

    # Run this script with a virtual environment's Python on images whose system packages pip
    # cannot upgrade (RunPod's PyTorch image ships a Debian PyJWT); its scripts go on PATH.
    os.environ["PATH"] = str(Path(sys.executable).parent) + os.pathsep + os.environ["PATH"]
    # A Jupyter terminal exports its inline plotting backend, which the venv does not have;
    # the vendored RDML library imports matplotlib, so the children get a plain backend.
    os.environ["MPLBACKEND"] = "Agg"
    sh(f"{sys.executable} -m pip install -q -e '{ROOT}[ai,studio]'")
    os.environ.setdefault("QPILOT_CACHE_DIR", str(out / "cache"))
    sh("qpilot fetch-demo")
    if shutil.which("ollama") is None:
        sh("(command -v zstd || (apt-get -qq update && apt-get -qq install -y zstd curl))")
        sh("curl -fsSL https://ollama.com/install.sh | sh")
    env = {
        **os.environ,
        "OLLAMA_HOST": OLLAMA,
        "OLLAMA_KEEP_ALIVE": "24h",
        "OLLAMA_NUM_PARALLEL": "2",
        "OLLAMA_MAX_LOADED_MODELS": str(len(models)),
    }
    with open(out / "ollama.log", "w", encoding="utf-8", newline="\n") as log:
        server = subprocess.Popen(["ollama", "serve"], env=env, stdout=log, stderr=log)
    for _ in range(60):
        if subprocess.run(f"curl -sf {OLLAMA}/api/tags", shell=True).returncode == 0:
            break
        time.sleep(2)
    for model in models:
        sh(f"OLLAMA_HOST={OLLAMA} ollama pull {model}")
    script = out / "harness_one.py"
    script.write_text(HARNESS, encoding="utf-8", newline="\n")
    runs = {}
    for model in models:
        folder = out / _slug(model)
        folder.mkdir(parents=True, exist_ok=True)
        run_env = {**os.environ, "QPILOT_STUDIES_DIR": str(folder / "studies")}
        with open(folder / "harness.log", "w", encoding="utf-8", newline="\n") as log:
            runs[model] = subprocess.Popen(
                [sys.executable, str(script), model, str(args.timeout), str(folder)],
                env=run_env,
                stdout=log,
                stderr=subprocess.STDOUT,
            )
        say(f"harness started for {model} (log {folder / 'harness.log'})")
    failed = 0
    for model, process in runs.items():
        code = process.wait()
        say(f"{model}: harness exit code {code}")
        failed += code != 0
    server.terminate()
    for model in models:
        card = out / _slug(model) / "scorecard.md"
        print(
            card.read_text(encoding="utf-8") if card.exists() else f"(no scorecard for {model})",
            flush=True,
        )
    summary = {m: str(out / _slug(m)) for m in models}
    (out / "SUMMARY.json").write_text(json.dumps(summary, indent=2), encoding="utf-8", newline="\n")
    say("ALL DONE")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
