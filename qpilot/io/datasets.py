"""Download the public demo dataset reproducibly: pinned URL, SHA-256 check, atomic write.

The demo study is the Vermeulen 2009 / Ruijter 2013 neuroblastoma qPCR benchmark (64 plates,
366 tumours, 24,576 raw amplification curves, CC BY 4.0). It is fetched at runtime into a cache
directory and never committed to the repository. Every caller gets exactly the same bytes: the
download is written to a temporary file, checked against a pinned size and SHA-256, and only then
renamed into place, so a half-written or tampered file can never be mistaken for the real one.
"""

from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import urlopen

VERMEULEN_COMMIT = "fce7a44e8b47b90759c646b557de568f7af77e75"
VERMEULEN_FILENAME = "data_vermeulen_raw.rdml"
VERMEULEN_URL = (
    "https://raw.githubusercontent.com/RDML-consortium/rdmlpython/"
    f"{VERMEULEN_COMMIT}/experiments/vermeulen/{VERMEULEN_FILENAME}"
)
VERMEULEN_SHA256 = "bc1d233e3866ad4d32736a9feea832ea6261a9c75d82a78e465d31bad554e151"
VERMEULEN_BYTES = 6_985_790

ALLOWED_SCHEMES = ("https", "file")  # file:// is used by the offline tests
_CHUNK = 1 << 16


class DatasetIntegrityError(Exception):
    """The downloaded or cached file is not byte-for-byte the pinned dataset."""


def default_cache_dir() -> Path:
    """Return ``$QPILOT_CACHE_DIR`` or ``~/.cache/qpilot``."""
    override = os.environ.get("QPILOT_CACHE_DIR")
    return Path(override) if override else Path.home() / ".cache" / "qpilot"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(_CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_file(path: Path, sha256: str, size: int) -> None:
    """Raise :class:`DatasetIntegrityError` unless ``path`` has exactly this size and hash."""
    actual_size = path.stat().st_size
    if actual_size != size:
        raise DatasetIntegrityError(f"{path.name}: {actual_size} bytes, expected {size}")
    actual_sha = _sha256(path)
    if actual_sha != sha256:
        raise DatasetIntegrityError(f"{path.name}: sha256 {actual_sha}, expected {sha256}")


def _download(url: str, target_dir: Path, max_bytes: int, timeout: float) -> Path:
    """Stream ``url`` into a temporary file in ``target_dir``; never more than ``max_bytes``."""
    scheme = urlparse(url).scheme
    if scheme not in ALLOWED_SCHEMES:
        raise DatasetIntegrityError(f"refusing to download over {scheme!r}: {url}")
    handle = tempfile.NamedTemporaryFile(dir=target_dir, suffix=".tmp", delete=False)
    tmp = Path(handle.name)
    try:
        written = 0
        with handle, urlopen(url, timeout=timeout) as response:  # noqa: S310 (scheme checked)
            for chunk in iter(lambda: response.read(_CHUNK), b""):
                written += len(chunk)
                if written > max_bytes:
                    raise DatasetIntegrityError(f"download exceeds {max_bytes} bytes: {url}")
                handle.write(chunk)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    return tmp


def fetch_vermeulen(
    cache_dir: str | Path | None = None,
    *,
    force: bool = False,
    url: str | None = None,
    timeout: float = 60.0,
) -> Path:
    """Return the path of the verified demo dataset, downloading it if needed.

    Args:
        cache_dir: Where to keep the file (default :func:`default_cache_dir`).
        force: Download again even if a verified copy is cached.
        url: Override the pinned URL (tests use a ``file://`` URL); the hash is still checked.
        timeout: Network timeout in seconds.

    Returns:
        Path to ``data_vermeulen_raw.rdml`` in the cache directory.

    Raises:
        DatasetIntegrityError: The download does not match the pinned size and SHA-256,
            or the URL scheme is not allowed.
    """
    directory = Path(cache_dir) if cache_dir is not None else default_cache_dir()
    directory.mkdir(parents=True, exist_ok=True)
    final = directory / VERMEULEN_FILENAME
    if final.exists() and not force:
        try:
            verify_file(final, VERMEULEN_SHA256, VERMEULEN_BYTES)
            return final
        except DatasetIntegrityError:
            final.unlink()  # corrupted cache: replace it with a verified download
    tmp = _download(url or VERMEULEN_URL, directory, VERMEULEN_BYTES, timeout)
    try:
        verify_file(tmp, VERMEULEN_SHA256, VERMEULEN_BYTES)
    except DatasetIntegrityError:
        tmp.unlink(missing_ok=True)
        raise
    os.replace(tmp, final)
    return final


def demo_dataset_info() -> dict[str, str]:
    """Citation, licence and provenance of the demo dataset, for the CLI, app and README."""
    return {
        "name": "Vermeulen/Ruijter neuroblastoma qPCR benchmark",
        "citation": (
            "Vermeulen J et al. (2009) Lancet Oncol 10:663-671; Ruijter JM et al. (2013) "
            "Methods 59:32-46"
        ),
        "licence": "CC BY 4.0",
        "contents": (
            "64 plates, 366 tumour cDNAs, 24,576 raw amplification curves, 5 reference genes"
        ),
        "groups": (
            "MYCN-high vs rest is defined from MYCN expression (top 15 %), "
            "not from a clinical amplification call"
        ),
        "url": VERMEULEN_URL,
        "sha256": VERMEULEN_SHA256,
        "note": "Fetched at runtime and never committed to the repository.",
    }
