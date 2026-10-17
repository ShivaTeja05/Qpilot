"""Download the Brintz et al. (2025) training data, pinned by commit and by SHA-256.

Usage (training environment, see ``requirements.txt``)::

    python training/curve_judge/fetch.py --out /path/outside/the/repo/cj-data

Every file comes from the authors' GitHub repository at the commit tagged ``v1.0.0``
(``191675b``), which is the release Zenodo archived as DOI 10.5281/zenodo.13798821. The data
files are byte-identical at the later ``main`` commit ``f07ced3`` (only ``README.md`` changed).
A file whose SHA-256 differs from the pin below is deleted and the script fails: nothing
downstream ever reads unverified bytes.

Licence: see ``README.md`` in this folder. The GitHub repository says CC0-1.0, the Zenodo
record says CC BY 4.0; qPilot follows the stricter of the two (CC BY 4.0: attribute).
``--check-licence`` re-reads both licence statements over the network and fails if either
has changed.

Data is training input only; it is never committed to the qPilot repository or shipped in
the package. Treat the downloaded files as untrusted: this script and the others read them
as CSV text only.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
import urllib.request
from pathlib import Path

REPO = "bbrintz/qPCR-amp-call"
COMMIT = "191675bd644a4b8e087d371d65b42ced58230afc"  # tag v1.0.0 = Zenodo 10.5281/zenodo.13798821
BASE_URL = f"https://raw.githubusercontent.com/{REPO}/{COMMIT}/"
ZENODO_RECORD = "https://zenodo.org/api/records/13798821"
GITHUB_LICENSE_API = f"https://api.github.com/repos/{REPO}/license"

#: file -> (sha256, size in bytes, git blob sha1 as listed by GitHub at COMMIT)
PINS: dict[str, tuple[str, int, str]] = {
    "raw_training.csv": (
        "beba58ebd9c8dc4e8f2d8cc762ce7ce440d60cff329eba0aaecd37c3642b738c",
        30921212,
        "b82ac47d86cb4913803b75f2f8280b6f7854f882",
    ),
    "qpcr_training_data.csv": (
        "d7e55d5d91b6569606c4c5ab8bce84387f498dcb3e70b876b8a67c1cbd4d6cda",
        39852277,
        "e4e67e883a9c3fcd1503acb902c42933e2e64a04",
    ),
    "niger_final.csv": (
        "fb89a8b178c3b4ef24e94145ee4368e6acf615474053169447701ca60483a7e6",
        77948217,
        "43ea760ffa891393ee9e3968c238f1f0d31deaa8",
    ),
    "qPCR-amp-call_xgboost.R": (
        "367d4561711dfb3f6ca3c53e91842589e9eb561e8ed1fe65797bb7c88d9d70e3",
        12872,
        "98ded3cb9ca68c7d87a5496026601f3a1ac39b03",
    ),
    "LICENSE": (
        "a2010f343487d3f7618affe54f789f5487602331c0a8d03f49e9a7c547cf0499",
        7048,
        "0e259d42c996742e9e3cba14c677129b2c1b6311",
    ),
}

#: The licence line of each source, as read on 17 Oct 2026 (quoted in README.md).
EXPECTED_GITHUB_LICENSE_SPDX = "CC0-1.0"
EXPECTED_LICENSE_FILE_LINE = "CC0 1.0 Universal"
EXPECTED_ZENODO_LICENSE_ID = "cc-by-4.0"

MAX_BYTES = 200 * 1024 * 1024
TIMEOUT_S = 120


def sha256_file(path: Path) -> str:
    """SHA-256 of a file, read in chunks."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git_blob_sha1(path: Path) -> str:
    """Git blob id of a file (sha1 of ``blob <size>``, a NUL, the content), as GitHub lists it."""
    digest = hashlib.sha1(usedforsecurity=False)
    digest.update(f"blob {path.stat().st_size}\0".encode())
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify(path: Path, name: str) -> bool:
    """True if ``path`` matches every pin for ``name``."""
    sha, size, blob = PINS[name]
    return path.stat().st_size == size and sha256_file(path) == sha and git_blob_sha1(path) == blob


def _download(url: str, target: Path, max_bytes: int = MAX_BYTES) -> None:
    if not url.startswith("https://"):
        raise ValueError(f"refusing non-https url {url}")
    target.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(dir=target.parent, suffix=".part", delete=False)
    try:
        with handle, urllib.request.urlopen(url, timeout=TIMEOUT_S) as response:  # noqa: S310
            total = 0
            while chunk := response.read(1 << 20):
                total += len(chunk)
                if total > max_bytes:
                    raise ValueError(f"{url}: larger than {max_bytes} bytes")
                handle.write(chunk)
        os.replace(handle.name, target)
    except BaseException:
        Path(handle.name).unlink(missing_ok=True)
        raise


def fetch(out_dir: Path) -> dict[str, str]:
    """Download (or re-verify) every pinned file into ``out_dir``; return name -> sha256."""
    out_dir.mkdir(parents=True, exist_ok=True)
    result = {}
    for name in PINS:
        target = out_dir / name
        if target.exists() and verify(target, name):
            print(f"ok (cached)  {name}")
        else:
            url = BASE_URL + urllib.request.quote(name)
            print(f"downloading  {url}")
            _download(url, target)
            if not verify(target, name):
                target.unlink()
                raise SystemExit(f"{name}: SHA-256 / size / git blob id do not match the pin")
            print(f"ok           {name}")
        result[name] = PINS[name][0]
    first_lines = (out_dir / "LICENSE").read_text(encoding="utf-8").splitlines()[:5]
    if EXPECTED_LICENSE_FILE_LINE not in [line.strip() for line in first_lines]:
        raise SystemExit("LICENSE file does not state CC0 1.0 Universal")
    return result


def _get_json(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=TIMEOUT_S) as response:  # noqa: S310
        return json.loads(response.read(1 << 22))


def check_licence() -> None:
    """Re-read the GitHub and Zenodo licence statements; fail if either changed."""
    spdx = _get_json(GITHUB_LICENSE_API)["license"]["spdx_id"]
    zenodo = _get_json(ZENODO_RECORD)["metadata"]["license"]["id"]
    print(f"GitHub licence: {spdx}; Zenodo licence: {zenodo}")
    if spdx != EXPECTED_GITHUB_LICENSE_SPDX or zenodo != EXPECTED_ZENODO_LICENSE_ID:
        raise SystemExit("a licence statement changed; re-read both and update README.md")
    print("stricter of the two: CC BY 4.0 (attribution required); qPilot attributes")


def main(argv: list[str] | None = None) -> int:
    """Command-line entry point."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, required=True, help="data directory (outside the repo)")
    parser.add_argument("--check-licence", action="store_true", help="re-check both licences")
    args = parser.parse_args(argv)
    if args.check_licence:
        check_licence()
    fetch(args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
