"""Red-team checks of the MCP server's path policy (THREAT_MODEL rows 3 and 16; asset: the
user's filesystem, "an agent must not be able to read arbitrary files through qPilot").

RT-001: the default data roots are the qPilot cache **and the current directory**. An MCP
client starts ``qpilot serve`` in whatever directory it likes; Claude Desktop starts servers in
``/`` and many clients start them in the home folder. The current directory is then the whole
disk (or the whole home folder), and ``qpcr_inspect(rdml_path=<demo>, sheet_path=<any .csv or
.xlsx>)`` hands back every cell of that file to the agent as quoted data. Measured on main
@ 81484f7 with cwd ``/``: a CSV holding ``123-45-6789`` and ``HIV positive`` came back in
``quoted_names`` (fixed by 4f98f25 on agents/mcp). The tests below hold the server to its
threat model: with no ``QPILOT_DATA_ROOTS`` set, the filesystem root and the home folder are
never an implicit root.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from qpilot.mcp_server import check_path, check_sheet, data_roots


@pytest.fixture
def no_roots_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("QPILOT_DATA_ROOTS", raising=False)


def _secret_sheet(folder: Path) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    sheet = folder / "patients.csv"
    sheet.write_text("patient,diagnosis\nAlice Smith,positive\n", encoding="utf-8")
    return sheet


def test_a_server_started_in_the_filesystem_root_does_not_open_the_whole_disk(
    no_roots_env: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    sheet = _secret_sheet(tmp_path / "Documents")
    monkeypatch.chdir("/")
    assert Path("/") not in data_roots()
    with pytest.raises(PermissionError):
        check_sheet(str(sheet))


def test_a_server_started_in_the_home_folder_does_not_open_the_whole_home_folder(
    no_roots_env: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    home = tmp_path / "home"
    (home / ".cache" / "qpilot").mkdir(parents=True)
    sheet = _secret_sheet(home / "Documents")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.chdir(home)
    assert home.resolve() not in data_roots()
    with pytest.raises(PermissionError):
        check_sheet(str(sheet))


def test_an_explicit_root_still_works(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """The fix must keep QPILOT_DATA_ROOTS working: a lab names its data folder explicitly."""
    sheet = _secret_sheet(tmp_path / "lab")
    monkeypatch.setenv("QPILOT_DATA_ROOTS", str(tmp_path / "lab"))
    assert check_sheet(str(sheet)) == sheet.resolve()


def test_a_sibling_with_the_same_prefix_is_refused(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    (tmp_path / "lab").mkdir()
    sibling = _secret_sheet(tmp_path / "lab-secret")
    monkeypatch.setenv("QPILOT_DATA_ROOTS", str(tmp_path / "lab"))
    with pytest.raises(PermissionError):
        check_sheet(str(sibling))


def test_a_symlink_out_of_the_root_is_refused(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    outside = tmp_path / "outside" / "x.rdml"
    outside.parent.mkdir()
    outside.write_text("<rdml/>", encoding="utf-8")
    lab = tmp_path / "lab"
    lab.mkdir()
    (lab / "link.rdml").symlink_to(outside)
    monkeypatch.setenv("QPILOT_DATA_ROOTS", str(lab))
    with pytest.raises(PermissionError):
        check_path(str(lab / "link.rdml"))
