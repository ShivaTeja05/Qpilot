"""The folder and download rules of the Prism and Record routes (``qpilot.web.folders``).

No study needed: these are the rules that keep the page inside its own folders.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from qpilot.web import folders
from qpilot.web.folders import FolderRefused, allowed_folder
from tests.homes import set_home


@pytest.fixture
def roots(tmp_path):
    """An export folder, a home folder with a store inside it, and somewhere else."""
    exports = tmp_path / "exports"
    home = tmp_path / "home"
    store = home / ".cache" / "qpilot" / "studies"
    elsewhere = tmp_path / "elsewhere"
    for folder in (exports, store, elsewhere):
        folder.mkdir(parents=True)
    return {"exports": exports, "home": home, "store": store, "elsewhere": elsewhere}


def allowed(roots, text):
    return allowed_folder(text, roots=(roots["exports"], roots["home"]), store_root=roots["store"])


def refused(roots, text) -> str:
    with pytest.raises(FolderRefused) as err:
        allowed(roots, text)
    return str(err.value)


def test_a_folder_in_home_or_exports_is_allowed(roots):
    sent_back = roots["home"] / "prism" / "sent_back"
    sent_back.mkdir(parents=True)
    assert allowed(roots, str(sent_back)) == sent_back.resolve()
    inside = roots["exports"] / "prism-abcdefgh" / "sent_back"
    inside.mkdir(parents=True)
    assert allowed(roots, f"  {inside}  ") == inside.resolve()


def test_tilde_means_the_home_folder(roots, monkeypatch):
    set_home(monkeypatch, roots["home"])
    (roots["home"] / "back").mkdir()
    assert allowed(roots, "~/back") == (roots["home"] / "back").resolve()


@pytest.mark.parametrize("text", ["", "   ", "."])
def test_nothing_given_is_refused(roots, text):
    assert "Give the folder" in refused(roots, text)


def test_a_relative_path_is_refused(roots):
    assert "full path" in refused(roots, "prism/sent_back")


def test_dot_dot_is_refused_even_when_it_lands_inside(roots):
    (roots["home"] / "a" / "b").mkdir(parents=True)
    assert "“..”" in refused(roots, str(roots["home"] / "a" / "b" / ".." / "b"))


def test_the_store_is_refused(roots):
    assert "study store" in refused(roots, str(roots["store"]))
    session = roots["store"] / "sessions" / "x"
    session.mkdir(parents=True)
    assert "study store" in refused(roots, str(session))


def test_outside_the_roots_is_refused(roots):
    assert "home folder" in refused(roots, str(roots["elsewhere"]))


def test_a_link_is_refused_wherever_it_is(roots):
    target = roots["home"] / "real"
    target.mkdir()
    link = roots["home"] / "link"
    os.symlink(target, link)
    assert "link" in refused(roots, str(link))
    (target / "inner").mkdir()
    assert "link" in refused(roots, str(link / "inner"))  # a link between the root and the folder
    out = roots["home"] / "out"
    os.symlink(roots["elsewhere"], out)
    assert "link" in refused(roots, str(out))


def test_a_missing_folder_or_a_file_is_refused(roots):
    assert "There is no folder" in refused(roots, str(roots["home"] / "nope"))
    file = roots["home"] / "file.csv"
    file.write_text("x")
    assert "There is no folder" in refused(roots, str(file))


def test_odd_text_is_refused(roots):
    assert "not a folder name" in refused(roots, "/tmp/\x00x")
    assert "not a folder name" in refused(roots, "/" + "a" * 5000)


# ---- downloads ---------------------------------------------------------------------------------


def test_only_files_inside_exports_are_registered(tmp_path):
    exports = tmp_path / "exports"
    exports.mkdir()
    inside = exports / "r.zip"
    inside.write_bytes(b"zip")
    outside = tmp_path / "secret.txt"
    outside.write_text("no")
    downloads: dict[str, Path] = {}
    token = folders.register_download(downloads, exports, inside)
    assert folders.OPAQUE.match(token)
    assert folders.download_path(downloads, exports, token) == inside.resolve()
    with pytest.raises(FolderRefused):
        folders.register_download(downloads, exports, outside)
    with pytest.raises(FolderRefused):
        folders.register_download(downloads, exports, exports)  # a folder is not a download


def test_a_download_cannot_reach_outside_exports(tmp_path):
    exports = tmp_path / "exports"
    exports.mkdir()
    outside = tmp_path / "secret.txt"
    outside.write_text("no")
    link = exports / "link.zip"
    os.symlink(outside, link)
    downloads = {"aaaaaaaaaaaa": outside, "bbbbbbbbbbbb": link, "cccccccccccc": exports / "gone"}
    for token in downloads:
        assert folders.download_path(downloads, exports, token) is None
    for token in ("../../etc/passwd", "short", "a" * 65, "", "x/yyyyyyyyy"):
        assert folders.download_path(downloads, exports, token) is None


def test_bundle_ids_name_folders_inside_exports_only(tmp_path):
    exports = tmp_path / "exports"
    bundle = exports / "prism-abcd1234"
    bundle.mkdir(parents=True)
    assert folders.bundle_folder(exports, "abcd1234") is None  # no bundle file yet
    (bundle / "qpilot_bundle.json").write_text("{}")
    assert folders.bundle_id(bundle) == "abcd1234"
    assert folders.bundle_folder(exports, "abcd1234") == bundle.resolve()
    assert folders.bundles_here(exports) == [bundle]
    for token in ("../prism-abcd1234", "abcd", "abcd1234/..", "ABCD1234/x"):
        assert folders.bundle_folder(exports, token) is None
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / "qpilot_bundle.json").write_text("{}")
    os.symlink(elsewhere, exports / "prism-linkedxx")
    assert folders.bundle_folder(exports, "linkedxx") is None
    assert folders.bundle_id(tmp_path / "other-abcd1234") is None


def test_marked_folders_are_found_without_following_links(tmp_path):
    (tmp_path / "a" / "b").mkdir(parents=True)
    (tmp_path / "a" / "MARK").write_text("x")
    (tmp_path / "a" / "b" / "MARK").write_text("x")
    os.symlink(tmp_path / "a", tmp_path / "link")
    assert folders.find_marked(tmp_path, "MARK", depth=2) == [tmp_path / "a", tmp_path / "a" / "b"]
    assert folders.find_marked(tmp_path, "MARK", depth=1) == [tmp_path / "a"]


def test_group_points_and_mean_ci():
    columns = ["Sample", "A", "B"]
    rows = [["u1", "1.0", ""], ["u2", "3.0", "nan"], ["u3", "", "2.5"], ["u4", "x", "4.5"], []]
    groups = folders.group_points(columns, rows)
    assert groups == {"A": [("u1", 1.0), ("u2", 3.0)], "B": [("u3", 2.5), ("u4", 4.5)]}
    mean, lo, hi = folders.mean_ci([1.0, 3.0])
    assert mean == 2.0 and lo < 2.0 < hi
    assert folders.mean_ci([1.0]) is None


def test_the_export_folder_is_beside_the_store_one_folder_per_workspace(tmp_path):
    store = tmp_path / "cache" / "studies"
    store.mkdir(parents=True)
    assert folders.exports_root(store) == tmp_path / "cache" / "exports"
    assert (
        folders.workspace_exports(store, "bc1d233e3866")
        == tmp_path / "cache" / "exports" / "bc1d233e3866"
    )
    for key in ("../etc", "BC1D233E3866", "", "bc1d233e3866/..", "g" * 12):
        with pytest.raises(FolderRefused):
            folders.workspace_exports(store, key)
