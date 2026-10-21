"""The public instrument-export corpus is exactly what its manifests say it is.

Every file under ``tests/fixtures/corpus/<vendor>/<slug>/`` is listed in that directory's
``MANIFEST.yaml`` with its size and SHA-256, under a licence that allows redistribution, with
the evidence for that licence and an attribution. Nothing unlisted, nothing missing, nothing
too big. Synthetic files are labelled and point at a generator that exists.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
import yaml

CORPUS = Path(__file__).parent / "corpus"
ALLOWED_LICENCES = {"CC0-1.0", "CC-BY-4.0", "MIT", "Apache-2.0", "BSD-2-Clause", "BSD-3-Clause"}
MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_CORPUS_BYTES = 15 * 1024 * 1024
NOT_DATA = {"MANIFEST.yaml", "README.md", ".gitattributes"}
REQUIRED = (
    "schema",
    "slug",
    "title",
    "vendor",
    "licence",
    "licence_evidence",
    "attribution",
    "source",
    "modified",
    "synthetic",
    "files",
)


def _manifests() -> list[Path]:
    return sorted(CORPUS.glob("*/*/MANIFEST.yaml"))


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _data_dirs() -> list[Path]:
    return sorted(p for p in CORPUS.glob("*/*") if p.is_dir() and not p.parent.name.startswith("_"))


def test_corpus_has_manifests():
    assert len(_manifests()) >= 10


@pytest.mark.parametrize("directory", _data_dirs(), ids=lambda p: f"{p.parent.name}/{p.name}")
def test_every_data_directory_has_a_manifest(directory: Path):
    assert (directory / "MANIFEST.yaml").is_file()


@pytest.mark.parametrize("manifest", _manifests(), ids=lambda p: p.parent.name)
def test_manifest_matches_files(manifest: Path):
    data = _load(manifest)
    missing = [key for key in REQUIRED if key not in data]
    assert not missing, f"missing keys {missing}"
    assert data["schema"] == "qpilot.corpus/1"
    assert data["slug"] == f"{manifest.parent.parent.name}/{manifest.parent.name}"
    assert data["licence"] in ALLOWED_LICENCES
    assert data["licence_evidence"] and data["attribution"]
    on_disk = sorted(
        p.name for p in manifest.parent.iterdir() if p.is_file() and p.name not in NOT_DATA
    )
    listed = sorted(entry["name"] for entry in data["files"])
    assert on_disk == listed
    for entry in data["files"]:
        path = manifest.parent / entry["name"]
        raw = path.read_bytes()
        assert len(raw) == entry["bytes"], entry["name"]
        assert hashlib.sha256(raw).hexdigest() == entry["sha256"], entry["name"]
        assert len(raw) <= MAX_FILE_BYTES, entry["name"]
        if not data["synthetic"]:
            assert entry.get("source_url", "").startswith("https://"), entry["name"]


@pytest.mark.parametrize("manifest", _manifests(), ids=lambda p: p.parent.name)
def test_synthetic_sets_name_their_generator(manifest: Path):
    data = _load(manifest)
    if data["synthetic"]:
        generator = CORPUS / "_generators" / data["generator"]
        assert generator.is_file(), data["generator"]
    else:
        assert "generator" not in data


def test_corpus_size_budget():
    total = sum(p.stat().st_size for p in CORPUS.rglob("*") if p.is_file())
    assert total <= MAX_CORPUS_BYTES


def test_line_endings_are_never_converted():
    attributes = (CORPUS / ".gitattributes").read_text(encoding="utf-8")
    assert "* -text" in attributes.splitlines()
