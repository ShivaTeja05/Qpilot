"""Red team (excellence round): ``qpcr_export``'s copy never replaces a file, even one that
appears while the export is being written (RT-EX-008).

The tool checks that ``out_dir`` holds no file of the name it will write, then writes the export
(a supplement takes about a minute on the demo), then copies it. A person saving a file of that
name in the meantime (or a link put there) was replaced by the copy: ``os.replace`` overwrites.
Now the copy is linked into place, which fails when the name exists, and the answer says the file
was written to the export folder only.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

from qpilot.mcp_server import QpilotTools
from qpilot.web.routers import evidence as evidence_router
from qpilot.web.routers import where as where_router
from tests.web import test_where_decide as decided

called_walked = decided.called_walked
called = decided.called


@pytest.fixture(autouse=True)
def fresh_caches():
    evidence_router.clear()
    where_router.clear()
    yield
    evidence_router.clear()
    where_router.clear()


def _racing(monkeypatch, make) -> None:
    """While the export is written, ``make(name)`` puts something at the copy's name."""
    from qpilot.web.routers import report as report_router

    real = report_router._write_tables

    def slow(ctx, study_id, sid, folder, body, progress):
        done = real(ctx, study_id, sid, folder, body, progress)
        make(
            f"{report_router.STEMS[body.format]}-{study_id}.{report_router.EXTENSIONS[body.format]}"
        )
        return done

    monkeypatch.setattr(report_router, "_write_tables", slow)


def test_a_file_saved_meanwhile_is_never_replaced(called, monkeypatch):
    study = called["study"]
    folder = Path(tempfile.mkdtemp(prefix="paper-", dir=called["root"]))
    _racing(monkeypatch, lambda name: (folder / name).write_bytes(b"the person's own file"))
    out = QpilotTools(called["store"]).qpcr_export(study, "csv", out_dir=str(folder))
    assert out.get("code") == "invalid_argument" and out.get("field") == "out_dir", out
    assert "nothing was overwritten" in out["error"] and "export folder" in out["error"]
    (kept,) = [p for p in folder.iterdir()]
    assert kept.read_bytes() == b"the person's own file"
    assert not [p for p in folder.iterdir() if p.name.endswith(".tmp")]


def test_a_link_put_there_meanwhile_is_never_followed_or_replaced(called, monkeypatch, tmp_path):
    study = called["study"]
    folder = Path(tempfile.mkdtemp(prefix="paper-", dir=called["root"]))
    outside = tmp_path / "outside.zip"
    outside.write_bytes(b"outside the roots")
    _racing(monkeypatch, lambda name: os.symlink(outside, folder / name))
    out = QpilotTools(called["store"]).qpcr_export(study, "csv", out_dir=str(folder))
    assert out.get("code") == "invalid_argument", out
    assert outside.read_bytes() == b"outside the roots"
    (link,) = list(folder.iterdir())
    assert link.is_symlink()


def test_an_ordinary_copy_still_lands(called):
    study = called["study"]
    folder = Path(tempfile.mkdtemp(prefix="paper-", dir=called["root"]))
    out = QpilotTools(called["store"]).qpcr_export(study, "csv", out_dir=str(folder))
    assert "error" not in out, out
    copy = Path(out["copied_to"]["path"])
    assert copy.read_bytes() == Path(out["file"]["path"]).read_bytes()
    assert [p.name for p in folder.iterdir()] == [copy.name]


@pytest.mark.parametrize("links", [True, False])
def test_write_new_never_writes_over_a_name(tmp_path, monkeypatch, links):
    from qpilot.report import excel

    if not links:  # a drive without hard links: the exclusive create keeps the same rule
        monkeypatch.setattr(excel.os, "link", lambda *_a, **_k: (_ for _ in ()).throw(OSError()))
    excel.write_new(tmp_path / "a.zip", b"new")
    assert (tmp_path / "a.zip").read_bytes() == b"new"
    (tmp_path / "b.zip").write_bytes(b"old")
    os.symlink(tmp_path / "elsewhere", tmp_path / "c.zip")  # a dangling link is a name too
    for name in ("a.zip", "b.zip", "c.zip"):
        with pytest.raises(FileExistsError):
            excel.write_new(tmp_path / name, b"over")
    assert (tmp_path / "b.zip").read_bytes() == b"old"
    assert not (tmp_path / "elsewhere").exists()
    assert sorted(p.name for p in tmp_path.iterdir()) == ["a.zip", "b.zip", "c.zip"]
