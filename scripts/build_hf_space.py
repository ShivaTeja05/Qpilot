"""Assemble the Hugging Face Space for qPilot's public sandbox (``deploy/hf-space`` + the code).

    python scripts/build_hf_space.py OUT_DIR

Copies the Space's ``app.py`` / ``README.md`` / ``requirements.txt`` and the parts of the repo the
server needs at run time (``qpilot/`` with the built page, ``sim/src`` and the simulator's data and
results, the licences) into ``OUT_DIR``, ready to upload as the Space repo (not uploaded here).
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PARTS = ["qpilot", "sim/src", "sim/data", "sim/results", "LICENSE", "THIRD_PARTY_NOTICES.md"]
SKIP = shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store", "*.rdml.tmp")


def build(out: Path) -> Path:
    """Write the Space's files into ``out`` (which must not exist or be empty)."""
    if out.exists() and any(out.iterdir()):
        raise SystemExit(f"{out} is not empty")
    out.mkdir(parents=True, exist_ok=True)
    for name in ("app.py", "README.md", "requirements.txt"):
        shutil.copy2(ROOT / "deploy" / "hf-space" / name, out / name)
    for part in PARTS:
        src, dst = ROOT / part, out / part
        if src.is_dir():
            shutil.copytree(src, dst, ignore=SKIP)
        else:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
    if not (out / "qpilot" / "web" / "static" / "index.html").is_file():
        raise SystemExit("the page is not built: run `npm run build` in frontend/ first")
    return out


if __name__ == "__main__":
    print(build(Path(sys.argv[1])))
