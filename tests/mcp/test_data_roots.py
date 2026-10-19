"""RT-001: with QPILOT_DATA_ROOTS unset, the server never shares the whole disk or home folder.

An MCP client chooses the server's working directory (Claude Desktop uses ``/``, others the home
folder), so the current directory is a data root only when it is a folder of its own.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import anyio
import pytest

from qpilot.core.store import StudyStore
from qpilot.mcp_server import (
    QpilotTools,
    check_path,
    check_sheet,
    data_roots,
    implicit_cwd_root,
    roots_notice,
)


@pytest.fixture
def home(tmp_path, monkeypatch):
    """A private home folder (with a qPilot cache) and no QPILOT_DATA_ROOTS."""
    folder = tmp_path / "home" / "pat"
    (folder / ".cache" / "qpilot").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(folder))
    monkeypatch.delenv("QPILOT_DATA_ROOTS", raising=False)
    return folder


def _sheet(folder: Path, name: str = "patients.csv") -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    path.write_text("patient,diagnosis\nAlice Smith,positive\n", encoding="utf-8")
    return path


@pytest.mark.parametrize("where", ["root", "home", "above_home"])
def test_a_wide_working_directory_is_never_a_data_root(home, monkeypatch, where):
    cwd = {"root": Path("/"), "home": home, "above_home": home.parent}[where]
    secret = _sheet(home / "Documents")
    monkeypatch.chdir(cwd)
    assert implicit_cwd_root() is None
    assert data_roots() == [(home / ".cache" / "qpilot").resolve()]
    with pytest.raises(PermissionError, match="outside"):
        check_sheet(str(secret))
    with pytest.raises(PermissionError, match="outside"):
        check_path(str(_sheet(home / "Documents", "plate.rdml")))
    assert "too wide" in roots_notice()


def test_a_project_folder_is_still_a_data_root(home, monkeypatch):
    project = home / "projects" / "qpcr"
    sheet = _sheet(project)
    monkeypatch.chdir(project)
    assert implicit_cwd_root() == project.resolve()
    assert project.resolve() in data_roots()
    assert check_sheet(str(sheet)) == sheet.resolve()
    assert "too wide" not in roots_notice() and str(project.resolve()) in roots_notice()


def test_explicit_roots_are_kept_as_given(home, monkeypatch, tmp_path):
    lab = tmp_path / "lab"
    sheet = _sheet(lab)
    monkeypatch.setenv("QPILOT_DATA_ROOTS", os.pathsep.join([str(lab), str(tmp_path / "gone")]))
    monkeypatch.chdir("/")
    assert data_roots() == [lab.resolve()]
    assert check_sheet(str(sheet)) == sheet.resolve()
    assert roots_notice() is None


def test_implicit_root_rule_on_plain_paths(tmp_path):
    home = tmp_path / "Users" / "pat"
    home.mkdir(parents=True)
    assert implicit_cwd_root(Path("/"), home) is None
    assert implicit_cwd_root(home, home) is None
    assert implicit_cwd_root(tmp_path / "Users", home) is None
    assert implicit_cwd_root(home / "data", home) == (home / "data").resolve()
    assert implicit_cwd_root(tmp_path / "elsewhere", home) == (tmp_path / "elsewhere").resolve()


def test_inspect_cannot_read_a_sheet_from_the_home_folder(home, monkeypatch, tmp_studies_dir):
    """The repro of RT-001: cwd '/', a demo-like file in the cache, a sheet elsewhere."""
    rdml = home / ".cache" / "qpilot" / "plate.rdml"
    rdml.write_bytes(b"<rdml>stand-in</rdml>")
    secret = _sheet(home / "Documents")
    monkeypatch.chdir("/")
    out = QpilotTools(StudyStore(tmp_studies_dir)).qpcr_inspect(str(rdml), str(secret))
    assert out["error"] == "path outside QPILOT_DATA_ROOTS"
    assert "Alice" not in str(out)
    assert not (Path(tmp_studies_dir) / "sessions").exists()  # nothing was bound


def test_serve_says_which_folders_it_shares(home, tmp_path, tmp_studies_dir):
    """`qpilot serve` started in '/' prints one line naming the roots and how to set them."""
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    env = {**os.environ, "HOME": str(home), "QPILOT_STUDIES_DIR": str(tmp_studies_dir)}
    env.pop("QPILOT_DATA_ROOTS", None)
    params = StdioServerParameters(
        command=sys.executable, args=["-m", "qpilot.mcp_server"], env=env, cwd="/"
    )
    errlog = tmp_path / "stderr.txt"

    async def scenario():
        with errlog.open("w") as err:
            async with stdio_client(params, errlog=err) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()

    anyio.run(scenario)
    text = errlog.read_text()
    assert "too wide to share" in text and "QPILOT_DATA_ROOTS" in text
    assert str((home / ".cache" / "qpilot").resolve()) in text
