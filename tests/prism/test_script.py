"""prism/script.py: golden Prism scripts, documented commands only, safe paths, launchers.

Regenerate the golden files after an intended change with ``QPILOT_REGEN_GOLDEN=1`` and review
the diff by eye before committing.
"""

import os
import re

import pytest

from qpilot.prism.script import (
    DONE_FILE,
    LaunchCommand,
    check_text,
    launch_command,
    run_script,
    send_back_script,
    write_scripts,
)
from qpilot.prism.tables import PrismExportError, build_bundle
from tests.prism.conftest import FIXTURES, TOY_CHAIN, toy_inputs

WINDOWS_DIR = r"C:\Users\lab\qpilot_toy"
MAC_DIR = "/Users/lab/qpilot_toy"
# Every command a generated script may use; each is documented on GraphPad's own pages (see the
# docstring of qpilot/prism/script.py for the page of each).
DOCUMENTED = {
    "SetPath",
    "Open",
    "GoTo",
    "Import",
    "SetSheetTitle",
    "Save",
    "SetInfo",
    "ExportPDF",
    "ExportPNG",
    "ExportTable",
    "Close",
    "OpenOutput",
    "WText",
    "CloseOutput",
}


@pytest.fixture
def bundle(tmp_path):
    return build_bundle(
        toy_inputs(),
        ["T", "T2"],
        "two_groups_log2",
        tmp_path / "bundle",
        record_ref="toy-001",
        chain_head=TOY_CHAIN,
        design_hash="d0" * 32,
    )


def _golden(name: str, data: bytes) -> None:
    path = FIXTURES / name
    if os.environ.get("QPILOT_REGEN_GOLDEN"):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    assert data == path.read_bytes(), f"{name} differs from the golden file"


@pytest.mark.parametrize(
    "platform, folder, suffix", [("windows", WINDOWS_DIR, "windows"), ("macos", MAC_DIR, "macos")]
)
def test_golden_scripts(bundle, tmp_path, platform, folder, suffix):
    written = write_scripts(
        bundle,
        None,
        tmp_path / "bundle",
        platform=platform,
        prism_dir=folder,
        graphs=("pdf", "png"),
    )
    assert set(written) == {"run.pzc", "send_back.pzc"}
    _golden(f"run_{suffix}.pzc", written["run.pzc"].read_bytes())
    _golden(f"send_back_{suffix}.pzc", written["send_back.pzc"].read_bytes())
    assert (tmp_path / "bundle" / "sent_back").is_dir()


def test_windows_scripts_use_crlf_and_macos_lf(bundle):
    windows = run_script(bundle, "two_groups_log2.pzt", WINDOWS_DIR, "windows")
    mac = run_script(bundle, "two_groups_log2.pzt", MAC_DIR, "macos")
    assert windows.count("\r\n") == windows.count("\n")
    assert "\r" not in mac
    assert windows.isascii() and mac.isascii()


@pytest.mark.parametrize("platform", ["windows", "macos"])
def test_only_documented_commands_are_used(bundle, platform):
    folder = WINDOWS_DIR if platform == "windows" else MAC_DIR
    texts = [
        run_script(bundle, "two_groups_log2.pzt", folder, platform, ("pdf", "png")),
        send_back_script(bundle, folder, platform),
    ]
    for text in texts:
        for line in text.splitlines():
            if not line.strip() or line.startswith("//"):
                continue
            assert line.split()[0] in DOCUMENTED, line


def test_run_script_shape(bundle):
    text = run_script(bundle, "two_groups_log2.pzt", MAC_DIR, "macos")
    lines = text.splitlines()
    assert lines[4] == f'SetPath "{MAC_DIR}"'
    assert lines[-3:] == [
        f'OpenOutput "{DONE_FILE}", Clear',
        'WText "qPilot run.pzc finished for record toy-001"',
        "CloseOutput",
    ]
    for table in bundle.tables:
        block = text.split(f"// {table.gene}\n", 1)[1]
        assert block.startswith('Open "two_groups_log2.pzt"\nGoTo D, 1\n')
        assert f'Import "{table.csv}"' in block
        assert f'SetSheetTitle "{table.title}"' in block
        assert f'Save "{table.name}_qpilot_toy-001.pzfx"' in block
    assert text.count("Close\n") == len(bundle.tables)
    assert "Values computed by qPilot from raw curves" in text


def test_send_back_never_closes_a_project(bundle):
    text = send_back_script(bundle, WINDOWS_DIR, "windows")
    assert "\r\nClose\r\n" not in text
    assert f'ExportTable "{WINDOWS_DIR}\\sent_back\\T.csv"' in text
    assert "qpilot_sent_back_done.txt" in text


@pytest.mark.parametrize(
    "bad", ['C:\\a"b', "C:\\a\nb", "C:\\a\rb", "C:\\a\x00b", "C:\\Jos\u00e9", "relative\\dir"]
)
def test_unsafe_or_relative_folders_are_refused(bundle, tmp_path, bad):
    with pytest.raises(PrismExportError):
        write_scripts(bundle, None, tmp_path / "bundle", platform="windows", prism_dir=bad)


def test_other_platform_needs_its_own_folder(bundle, tmp_path):
    from qpilot.prism.script import host_platform

    other = "windows" if host_platform() == "macos" else "macos"
    with pytest.raises(PrismExportError, match="as the"):
        write_scripts(bundle, None, tmp_path / "bundle", platform=other)


def test_check_text():
    assert check_text("plain (ok) - 1.csv", "x") == "plain (ok) - 1.csv"
    for bad in ('a"b', "a\tb", "a\x7fb", ""):
        with pytest.raises(PrismExportError):
            check_text(bad, "x")


def test_unknown_graph_format_is_refused(bundle):
    with pytest.raises(PrismExportError, match="graph formats"):
        run_script(bundle, "t.pzt", MAC_DIR, "macos", ("svg",))


def test_template_is_copied_when_it_exists(bundle, tmp_path):
    template = tmp_path / "two_groups_log2.pzt"
    template.write_bytes(b"made in Prism by a person")
    written = write_scripts(
        bundle, template, tmp_path / "bundle", platform="macos", prism_dir=MAC_DIR
    )
    assert written["two_groups_log2.pzt"].read_bytes() == b"made in Prism by a person"


def test_missing_template_is_still_named_in_the_script(bundle, tmp_path):
    written = write_scripts(
        bundle, tmp_path / "absent.pzt", tmp_path / "bundle", platform="macos", prism_dir=MAC_DIR
    )
    assert "absent.pzt" not in written
    assert 'Open "absent.pzt"' in written["run.pzc"].read_text()


def test_windows_launch_command_is_the_documented_form():
    command = launch_command(WINDOWS_DIR + r"\run.pzc", "windows", prism_exe=r"C:\P\prism.exe")
    assert command == LaunchCommand(
        "windows", r'"C:\P\prism.exe" @"C:\Users\lab\qpilot_toy\run.pzc"'
    )


def test_macos_launch_command_is_applescript_open_posix_file():
    command = launch_command(MAC_DIR + "/run.pzc", "macos", app="Prism 10")
    assert command.argv == (
        "osascript",
        "-e",
        'tell application "Prism 10"',
        "-e",
        f'open POSIX file "{MAC_DIR}/run.pzc"',
        "-e",
        "end tell",
    )
    assert re.search(r"open POSIX file", command.command_line)


def test_launcher_refuses_quotes():
    with pytest.raises(PrismExportError):
        launch_command('C:\\x"y\\run.pzc', "windows")
    with pytest.raises(PrismExportError):
        launch_command("/x/run.pzc", "macos", app='Prism" to quit')
