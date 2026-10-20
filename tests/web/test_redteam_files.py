"""Red team: downloads, record verification uploads and the Prism round-trip folder rules.

Skipped until the files router (``qpilot/web/routers/files.py``) is part of the app. Every zip
is built here, in memory; nothing outside ``tmp_path`` is ever written or read.
"""

from __future__ import annotations

import io
import stat
import zipfile
from pathlib import Path

import pytest

folders = pytest.importorskip("qpilot.web.folders")
pytest.importorskip("qpilot.web.routers.files")

SAME = {"origin": "http://127.0.0.1:7860"}


def _zip(members: dict[str, bytes], links: dict[str, str] | None = None) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, data in members.items():
            zf.writestr(zipfile.ZipInfo(name), data)
        for name, target in (links or {}).items():
            info = zipfile.ZipInfo(name)
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            zf.writestr(info, target)
    return buf.getvalue()


def _verify(client, data: bytes, name: str = "record.zip"):
    return client.post(
        "/api/records/verify", files={"record": (name, data, "application/zip")}, headers=SAME
    )


# ---- downloads -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "download_id",
    ["x", "..%2F..%2Fetc%2Fpasswd", "%2e%2e", "A" * 300, "%00", "uGZgJcXsQ10ao87GL5fSxYkx"],
)
def test_unknown_downloads_are_not_found(client, download_id):
    r = client.get(f"/api/downloads/{download_id}")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "not_found"


def test_a_download_needs_the_key(raw_client):
    assert raw_client.get("/api/downloads/anything").status_code == 401


# ---- verifying an uploaded record ------------------------------------------------------------


def test_a_file_that_is_not_a_zip_is_refused(client):
    r = _verify(client, b"PK\x03\x04 not really")
    assert r.status_code == 400 and r.json()["error"]["code"] in ("not_zip", "bad_record")


@pytest.mark.parametrize(
    "members,links",
    [
        ({"../escaped.txt": b"x"}, None),
        ({"rec/../../escaped.txt": b"x"}, None),
        ({"/tmp/escaped.txt": b"x"}, None),
        ({"rec\\..\\escaped.txt": b"x"}, None),
        ({"CHECKSUMS.sha256": b""}, {"results.json": "/etc/hosts"}),
    ],
)
def test_a_record_zip_never_writes_outside_its_folder(client, web_ctx, members, links):
    r = _verify(client, _zip(members, links))
    assert r.status_code == 400 and r.json()["error"]["code"] == "bad_record", r.text[:200]
    for parent in (web_ctx.private, web_ctx.private.parent):
        assert not (parent / "escaped.txt").exists()
    assert not Path("/tmp/escaped.txt").exists()


def test_a_record_zip_with_too_many_members_is_refused(client):
    r = _verify(client, _zip({f"f{i}.txt": b"" for i in range(20_000)}))
    assert r.status_code == 400 and r.json()["error"]["code"] == "bad_record"


@pytest.mark.xfail(
    strict=True,
    reason="RT-UI-024 record verify has no compression-ratio cap: a 50 KB zip that inflates to "
    "50 MB (or a ~1 MB zip to the 1 GB cap) is written to disk in full before the record is "
    "even recognised (the RDML and sheet readers refuse ratios above 100:1)",
)
def test_a_record_zip_bomb_is_refused_before_it_inflates(client):
    data = _zip({"CHECKSUMS.sha256": b"", "big.bin": b"\0" * (50 * 1024 * 1024)})
    assert len(data) < 200_000
    r = _verify(client, data)
    assert r.status_code in (400, 413)
    assert r.json()["error"]["code"] in ("bad_record", "too_large")
    message = r.json()["error"]["message"].lower()
    assert "compress" in message or "too large" in message or "inflate" in message, message


def test_verification_leaves_nothing_behind(client, web_ctx):
    _verify(client, _zip({"CHECKSUMS.sha256": b"0" * 64 + b"  results.json\n"}))
    left = (
        list((web_ctx.private / "verify").glob("*"))
        if (web_ctx.private / "verify").exists()
        else []
    )
    assert left == []


def test_a_cross_site_upload_to_verify_is_refused(client):
    r = client.post(
        "/api/records/verify",
        files={"record": ("r.zip", _zip({"a": b"b"}), "application/zip")},
        headers={"origin": "http://evil.example"},
    )
    assert r.status_code == 403


# ---- the Prism round trip's folder -----------------------------------------------------------


@pytest.fixture
def roots(tmp_path):
    home = tmp_path / "home"
    exports = tmp_path / "exports"
    store = home / "studies"
    outside = tmp_path / "outside"
    for p in (home / "Documents" / "sent_back", exports, store, outside):
        p.mkdir(parents=True)
    (home / "link_out").symlink_to(outside, target_is_directory=True)
    (home / "Documents" / "deep_link").symlink_to(outside, target_is_directory=True)
    return {"home": home, "exports": exports, "store": store, "outside": outside}


@pytest.mark.parametrize(
    "text",
    [
        "",
        ".",
        "relative/path",
        "/",
        "{outside}",
        "{home}/../outside",
        "{home}/link_out",
        "{home}/Documents/deep_link",
        "{home}/link_out/",
        "{store}",
        "{home}/studies",
        "{home}/Documents/sent_back\x00/etc",
        "{home}/does-not-exist",
        "{home}/" + "a" * 5000,
    ],
)
def test_round_trip_folders_outside_the_rules_are_refused(roots, text):
    folder_text = text.format(**{k: str(v) for k, v in roots.items()})
    with pytest.raises(folders.FolderRefused):
        folders.allowed_folder(
            folder_text, roots=(roots["exports"], roots["home"]), store_root=roots["store"]
        )


def test_a_plain_folder_in_home_is_allowed(roots):
    got = folders.allowed_folder(
        str(roots["home"] / "Documents" / "sent_back"),
        roots=(roots["exports"], roots["home"]),
        store_root=roots["store"],
    )
    assert got == (roots["home"] / "Documents" / "sent_back").resolve()
