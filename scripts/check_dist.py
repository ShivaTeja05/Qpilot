"""Check what ``python -m build`` produced before anything is published.

    python scripts/check_dist.py dist                  # contents and sizes
    python scripts/check_dist.py dist --tag v0.2.0     # also: the tag names this version

It reads the wheel and the sdist as archives (nothing is installed or run) and fails when
the wheel carries more than it should (tests, fixtures, Node modules, training data, big files),
lacks something the program reads at run time (the prebuilt page, the rule pack, the model),
when the two files disagree about the version, or when a release tag does not match the version
in ``qpilot/__init__.py`` and ``CITATION.cff``. Standard library only; same on every system.
"""

from __future__ import annotations

import argparse
import re
import sys
import tarfile
import zipfile
from pathlib import Path

MAX_WHEEL_MB = 6
MAX_SDIST_MB = 6
MAX_MEMBER_KB = 1024  # the largest legitimate members are the vendored rdml.py and the gene list

#: Top-level names a wheel may install (everything else is a packaging mistake).
WHEEL_TOP = {"qpilot", "qsim"}
#: Parts of a path that must never be inside the wheel or the sdist's package folders.
FORBIDDEN = ("/tests/", "/fixtures/", "node_modules", "/training/", ".rdml", "__pycache__", ".pyc")
#: What the program reads at run time from inside the package.
REQUIRED = (
    "qpilot/web/static/index.html",
    "qpilot/_packs/research-default.yaml",
    "qpilot/_methods/trace.md",
    "qpilot/models/curve_judge/model.json",
    "qpilot/data/hgnc/hgnc_symbols.tsv",
    "qpilot/report/miqe2_items.yaml",
    "qpilot/vendor/rdmlpython/rdml.py",
    "qpilot/vendor/rdmlpython/schema/RDML_v1_4_CR.xsd",
    "qsim/__init__.py",
)
#: The sdist must be enough to build the wheel and to read what it was built from.
SDIST_REQUIRED = ("pyproject.toml", "README.md", "LICENSE", "THIRD_PARTY_NOTICES.md", "packs/")
SDIST_FORBIDDEN = (
    "tests/",
    "frontend/",
    "research_notes/",
    "training/",
    "node_modules",
    ".github/",
)

problems: list[str] = []


def check(ok: bool, what: str) -> None:
    """Print one line; remember a failure."""
    print(f"  {'ok  ' if ok else 'FAIL'}  {what}")
    if not ok:
        problems.append(what)


def check_wheel(path: Path) -> str:
    """The wheel's contents; returns its version."""
    print(path.name)
    with zipfile.ZipFile(path) as wheel:
        infos = wheel.infolist()
        names = [i.filename for i in infos]
    tops = {n.split("/")[0] for n in names}
    extra = {t for t in tops if t not in WHEEL_TOP and not t.endswith(".dist-info")}
    check(not extra, f"only qpilot and qsim are installed (also found: {sorted(extra) or 'none'})")
    bad = [n for n in names if any(f in "/" + n for f in FORBIDDEN)]
    check(not bad, f"no tests, fixtures, caches or data files in the wheel {bad[:3] or ''}")
    missing = [r for r in REQUIRED if r not in names]
    check(not missing, f"everything read at run time is in the wheel {missing or ''}")
    big = [
        f"{i.filename} ({i.file_size // 1024} KB)"
        for i in infos
        if i.file_size > MAX_MEMBER_KB * 1024
    ]
    check(not big, f"no member over {MAX_MEMBER_KB} KB {big or ''}")
    size = path.stat().st_size / 1e6
    check(size < MAX_WHEEL_MB, f"wheel is {size:.1f} MB (limit {MAX_WHEEL_MB})")
    metadata = next(n for n in names if n.endswith(".dist-info/METADATA"))
    with zipfile.ZipFile(path) as wheel:
        text = wheel.read(metadata).decode("utf-8")
    version = re.search(r"^Version: (\S+)", text, re.M).group(1)
    check("](https://github.com/" in text and "](docs/" not in text, "README links are absolute")
    return version


def check_sdist(path: Path) -> str:
    """The sdist's contents; returns its version."""
    print(path.name)
    with tarfile.open(path) as sdist:
        members = sdist.getmembers()
        root = members[0].name.split("/")[0]
        names = [m.name[len(root) + 1 :] for m in members if m.name != root]
        info = sdist.extractfile(f"{root}/PKG-INFO")
        text = info.read().decode("utf-8") if info else ""
    missing = [r for r in SDIST_REQUIRED if not any(n == r or n.startswith(r) for n in names)]
    check(not missing, f"the sdist can build the wheel {missing or ''}")
    heavy = [n for n in names if any(n.startswith(f) or f in n for f in SDIST_FORBIDDEN)]
    check(not heavy, f"no tests, page source, training or notes in the sdist {heavy[:3] or ''}")
    size = path.stat().st_size / 1e6
    check(size < MAX_SDIST_MB, f"sdist is {size:.1f} MB (limit {MAX_SDIST_MB})")
    return re.search(r"^Version: (\S+)", text, re.M).group(1)


def read_version(file: Path, pattern: str) -> str | None:
    """The first match of ``pattern`` in a source file, or None."""
    found = re.search(pattern, file.read_text(encoding="utf-8"), re.M)
    return found.group(1) if found else None


def main() -> int:
    """Check ``dist/`` (one wheel, one sdist) and, with ``--tag``, the release tag."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("dist", type=Path, nargs="?", default=Path("dist"))
    parser.add_argument("--tag", help="the release tag, e.g. v0.2.0: it must name this version")
    args = parser.parse_args()
    wheels, sdists = sorted(args.dist.glob("*.whl")), sorted(args.dist.glob("*.tar.gz"))
    check(len(wheels) == 1 and len(sdists) == 1, f"one wheel and one sdist in {args.dist}")
    if len(wheels) != 1 or len(sdists) != 1:
        return 1
    wheel_version = check_wheel(wheels[0])
    sdist_version = check_sdist(sdists[0])
    check(
        wheel_version == sdist_version, f"wheel ({wheel_version}) and sdist ({sdist_version}) agree"
    )
    root = Path(__file__).resolve().parents[1]
    init = root / "qpilot" / "__init__.py"
    if init.is_file():
        source = read_version(init, r'^__version__ = "([^"]+)"')
        check(source == wheel_version, f"qpilot/__init__.py ({source}) is the wheel's version")
        cff = read_version(root / "CITATION.cff", r'^version: "?([^"\s]+)"?')
        check(cff == wheel_version, f"CITATION.cff ({cff}) is the wheel's version")
    if args.tag:
        check(args.tag == f"v{wheel_version}", f"tag {args.tag} names version {wheel_version}")
    print(
        "\n" + (f"FAILED: {len(problems)} problem(s)" if problems else "The distribution is fine.")
    )
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
