"""Task 2 gate: the demo dataset is fetched verified and atomically (offline tests use file://)."""

import hashlib
from pathlib import Path

import pytest

from qpilot.cli import main
from qpilot.io import datasets
from qpilot.io.datasets import (
    BENCHMARK_TABLES,
    VERMEULEN_FILENAME,
    DatasetIntegrityError,
    PinnedFile,
    cached_benchmark_tables,
    demo_dataset_info,
    fetch_benchmark_tables,
    fetch_pinned,
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


@pytest.fixture
def pinned_tables(tmp_path, monkeypatch) -> dict[str, bytes]:
    """Serve two stand-in benchmark tables from a file:// base URL, pinned in place of the real."""
    source = tmp_path / "tables"
    source.mkdir()
    payloads = {"n0": b"n0 table\n", "cq": b"cq table\n"}
    pins = {}
    for key, payload in payloads.items():
        (source / f"{key}.tsv").write_bytes(payload)
        pins[key] = PinnedFile(f"{key}.tsv", hashlib.sha256(payload).hexdigest(), len(payload))
    monkeypatch.setattr(datasets, "VERMEULEN_BASE_URL", source.as_uri())
    monkeypatch.setattr(datasets, "BENCHMARK_TABLES", pins)
    return payloads


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


def test_cli_fetch_demo(tmp_path, pinned_source, pinned_tables, monkeypatch, capsys):
    monkeypatch.setattr(datasets, "VERMEULEN_URL", pinned_source)
    assert main(["fetch-demo", "--cache-dir", str(tmp_path / "cache")]) == 0
    out = capsys.readouterr().out
    assert "sha256 OK" in out and "CC BY 4.0" in out
    assert "benchmark tables" in out and (tmp_path / "cache" / "cq.tsv").exists()


def test_benchmark_tables_are_pinned_at_the_dataset_commit():
    assert set(BENCHMARK_TABLES) == {"n0", "cq", "results"}
    for pinned in BENCHMARK_TABLES.values():
        assert len(pinned.sha256) == 64 and pinned.size > 0
        assert pinned.url.startswith("https://raw.githubusercontent.com/RDML-consortium/")
        assert datasets.VERMEULEN_COMMIT in pinned.url and pinned.url.endswith(pinned.filename)


def test_fetch_pinned_verifies_like_the_dataset(tmp_path, pinned_tables):
    cache = tmp_path / "cache"
    pin = datasets.BENCHMARK_TABLES["n0"]
    assert fetch_pinned(pin, cache).read_bytes() == pinned_tables["n0"]
    wrong = PinnedFile("n0.tsv", "0" * 64, pin.size)
    with pytest.raises(DatasetIntegrityError, match="sha256"):
        fetch_pinned(wrong, tmp_path / "other")
    assert _leftovers(tmp_path / "other") == []


def test_cached_benchmark_tables_never_downloads(tmp_path, pinned_tables, monkeypatch):
    cache = tmp_path / "cache"
    assert cached_benchmark_tables(cache) is None  # nothing cached yet, and no download
    assert not cache.exists() or list(cache.iterdir()) == []
    fetched = fetch_benchmark_tables(cache)
    assert cached_benchmark_tables(cache) == fetched
    fetched["cq"].write_bytes(b"tampered\n")  # same size, other hash
    assert cached_benchmark_tables(cache) is None


def test_cli_fetch_demo_reports_integrity_failure(tmp_path, pinned_source, monkeypatch, capsys):
    bad = tmp_path / "bad.rdml"
    bad.write_bytes(b"x" * len(PAYLOAD))
    monkeypatch.setattr(datasets, "VERMEULEN_URL", bad.as_uri())
    assert main(["fetch-demo", "--cache-dir", str(tmp_path / "cache")]) == 1
    assert "sha256" in capsys.readouterr().err


@pytest.mark.demo_data
def test_cached_demo_dataset_matches_the_pin(demo_rdml_path):
    verify_file(demo_rdml_path, datasets.VERMEULEN_SHA256, datasets.VERMEULEN_BYTES)
