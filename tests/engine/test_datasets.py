"""Task 2 gate: the demo dataset is fetched verified and atomically (offline tests use file://)."""

import hashlib
from pathlib import Path

import pytest

from qpilot.cli import main
from qpilot.io import datasets
from qpilot.io.datasets import (
    VERMEULEN_FILENAME,
    DatasetIntegrityError,
    demo_dataset_info,
    fetch_vermeulen,
    verify_file,
)

PAYLOAD = b"<rdml>stand-in for the demo dataset</rdml>\n"


@pytest.fixture
def pinned_source(tmp_path, monkeypatch) -> str:
    """Serve PAYLOAD from a file:// URL and pin its size and hash in place of the real ones."""
    source = tmp_path / "source" / VERMEULEN_FILENAME
    source.parent.mkdir()
    source.write_bytes(PAYLOAD)
    monkeypatch.setattr(datasets, "VERMEULEN_SHA256", hashlib.sha256(PAYLOAD).hexdigest())
    monkeypatch.setattr(datasets, "VERMEULEN_BYTES", len(PAYLOAD))
    return source.as_uri()


def _leftovers(directory: Path) -> list[str]:
    return sorted(p.name for p in directory.iterdir() if p.suffix == ".tmp")


def test_verified_download_lands_atomically(tmp_path, pinned_source):
    cache = tmp_path / "cache"
    path = fetch_vermeulen(cache, url=pinned_source)
    assert path == cache / VERMEULEN_FILENAME
    assert path.read_bytes() == PAYLOAD
    assert _leftovers(cache) == []


def test_tampered_download_is_refused_and_leaves_nothing(tmp_path, pinned_source):
    tampered = tmp_path / "tampered.rdml"
    tampered.write_bytes(PAYLOAD.replace(b"stand-in", b"STAND-IN"))  # same size, other hash
    cache = tmp_path / "cache"
    with pytest.raises(DatasetIntegrityError, match="sha256"):
        fetch_vermeulen(cache, url=tampered.as_uri())
    assert not (cache / VERMEULEN_FILENAME).exists()
    assert _leftovers(cache) == []


def test_oversized_download_is_cut_off(tmp_path, pinned_source):
    big = tmp_path / "big.rdml"
    big.write_bytes(PAYLOAD * 10)
    cache = tmp_path / "cache"
    with pytest.raises(DatasetIntegrityError, match="exceeds"):
        fetch_vermeulen(cache, url=big.as_uri())
    assert list(cache.iterdir()) == []


def test_verified_cache_is_reused_without_downloading(tmp_path, pinned_source, monkeypatch):
    cache = tmp_path / "cache"
    fetch_vermeulen(cache, url=pinned_source)

    def no_network(*_args, **_kwargs):
        raise AssertionError("must not download when a verified copy is cached")

    monkeypatch.setattr(datasets, "urlopen", no_network)
    assert fetch_vermeulen(cache, url=pinned_source).read_bytes() == PAYLOAD


def test_corrupted_cache_is_replaced(tmp_path, pinned_source):
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / VERMEULEN_FILENAME).write_bytes(b"corrupted")
    assert fetch_vermeulen(cache, url=pinned_source).read_bytes() == PAYLOAD


def test_plain_http_is_refused(tmp_path):
    with pytest.raises(DatasetIntegrityError, match="refusing"):
        fetch_vermeulen(tmp_path, url="http://example.org/data.rdml")


def test_verify_file_reports_size_mismatch(tmp_path):
    path = tmp_path / "x"
    path.write_bytes(b"abc")
    with pytest.raises(DatasetIntegrityError, match="3 bytes, expected 4"):
        verify_file(path, "0" * 64, 4)


def test_cache_dir_can_be_overridden(tmp_path, monkeypatch):
    monkeypatch.setenv("QPILOT_CACHE_DIR", str(tmp_path))
    assert datasets.default_cache_dir() == tmp_path


def test_dataset_info_carries_citation_licence_and_group_caveat():
    info = demo_dataset_info()
    assert info["licence"] == "CC BY 4.0"
    assert "Vermeulen" in info["citation"] and "Ruijter" in info["citation"]
    assert "not from a clinical" in info["groups"]
    assert info["sha256"] == datasets.VERMEULEN_SHA256


def test_cli_fetch_demo(tmp_path, pinned_source, monkeypatch, capsys):
    monkeypatch.setattr(datasets, "VERMEULEN_URL", pinned_source)
    assert main(["fetch-demo", "--cache-dir", str(tmp_path / "cache")]) == 0
    out = capsys.readouterr().out
    assert "sha256 OK" in out and "CC BY 4.0" in out


def test_cli_fetch_demo_reports_integrity_failure(tmp_path, pinned_source, monkeypatch, capsys):
    bad = tmp_path / "bad.rdml"
    bad.write_bytes(b"x" * len(PAYLOAD))
    monkeypatch.setattr(datasets, "VERMEULEN_URL", bad.as_uri())
    assert main(["fetch-demo", "--cache-dir", str(tmp_path / "cache")]) == 1
    assert "sha256" in capsys.readouterr().err


@pytest.mark.demo_data
def test_cached_demo_dataset_matches_the_pin(demo_rdml_path):
    verify_file(demo_rdml_path, datasets.VERMEULEN_SHA256, datasets.VERMEULEN_BYTES)
