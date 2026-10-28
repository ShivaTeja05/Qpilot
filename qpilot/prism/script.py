"""The Prism scripts (Mode S): Prism itself opens the template, imports the tables and saves.

Step 2.2 of the Studio plan. qPilot writes plain-text Prism scripts (``.pzc``) in Prism's own
documented script language; the scientist's licensed Prism runs them and does every read and
write of a Prism file. qPilot never writes or parses ``.prism`` or ``.pzfx`` in this mode.

``run.pzc``, for each gene's table (GraphPad's "open a template and import data" pattern, [V]
https://graphpad.com/guides/prism/latest/user-guide/script_example_4__open_a_template_and_import_data.htm):
open the template, go to its first data table, import the gene's CSV, title the sheet with the
record ref and chain head, save the project as ``<gene>_qpilot_<record>.pzfx``, append the
provenance note to the Info sheet and save again, optionally export the first graph as PDF/PNG,
close. One project per gene: a script cannot create a data table except by duplicating one
("You can't create new data tables ... except by duplicating existing ones" [V]), and where
``DuplicateFamily`` leaves the script afterwards is not documented, so the plan's "go to each
data table" is done as one template copy per gene. Its last action writes ``qpilot_done.txt``,
because Prism runs scripts invisibly and gives no completion signal [V].

``send_back.pzc`` opens each saved project and exports its first data table to
``sent_back/<gene>.csv`` with ``ExportTable`` (comma-separated by the ``.csv`` extension [V]),
then writes ``qpilot_sent_back_done.txt``. It never closes a project: ``Close`` discards unsaved
changes [V], and the scientist may have the project open with edits.

Documented commands used ([V] = syntax confirmed on GraphPad's own page; [R] = not confirmed
there, so unverified until step 0.1 on a real Prism seat). ``GUIDE`` is
https://graphpad.com/guides/prism/latest/user-guide and the full command list is KB 1648,
https://www.graphpad.com/support/faq/list-of-all-script-commands-for-graphpad-prism

* ``// comment`` [V]: GUIDE/adding_comments_to_a_script.htm
* ``SetPath "dir"`` [V]: GUIDE/setting_the_default_drive_and_folder.htm. The Windows form is
  [V]; the macOS POSIX form (``SetPath "/Users/..."``) is documented for Prism 5 only, so [R]
  for Prism 10/11 (KB 1098, see :data:`MAC_PATH_KB`).
* ``Open "file.pzt"`` [V]: GUIDE/opening_and_saving_prism_files.htm (``.pzt`` is accepted).
* ``GoTo D, 1`` / ``GoTo I, 1`` / ``GoTo G, 1`` [V]: GUIDE/general_commands.htm
  (``GoTo <section: D, I, R, G, or L>, <sheet#>``; example ``GoTo G, 3``).
* ``Import "file.csv"`` [V]: GUIDE/importing_data.htm (row and column omitted when the table
  has one data object). Which import options apply (first row as titles, first column as row
  titles) is [R].
* ``SetSheetTitle "title"`` [V]: GUIDE/special_purpose_commands.htm (quoting the title is [R]).
* ``Save "file.pzfx"`` and ``Save`` [V]: GUIDE/opening_and_saving_prism_files.htm ("saves to
  either .PZF or .PZFX format, depending on the file name"); that Prism 10/11 still save
  ``.pzfx`` from a script is [R].
* ``SetInfo "text", 1, 2`` [V]: GUIDE/changing_info_constants.htm (position 2 appends to the
  notes); whether a template without an Info sheet stops the script is [R].
* ``ExportPDF "f.pdf"`` / ``ExportPNG "f.png"`` [V]: GUIDE/exporting_a_graph_or_layout.htm
  ("exports the current graph or layout"; PNG at 300 dpi by default).
* ``ExportTable "f.csv"`` [V]: GUIDE/exporting_data_results_or_info_tables.htm; how excluded
  values, titles and nested subcolumns appear in the CSV is [R].
* ``Close`` [V]: GUIDE/opening_and_saving_prism_files.htm ("without saving").
* ``OpenOutput "f", Clear`` / ``WText "text"`` / ``CloseOutput`` [V]:
  GUIDE/writing_to_text_files.htm.

The done file follows GraphPad's own recipe: "End the script with OpenOutput "done.txt", WText
"done", and CloseOutput", deleting any old done file before launching [V]
(https://graphpad.com/guides/prism/latest/user-guide/launching_a_prism_script_from_outside_prism_(windows).htm).

Paths are written in double quotes; any path or text containing a quote character, a line
break or another control character is refused, and so is non-ASCII text (how Prism decodes a
``.pzc`` file is [R]). Scripts for Windows use CRLF line ends, for macOS LF ([R]).
"""

from __future__ import annotations

import shlex
import shutil
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Literal

from qpilot.prism.tables import INFO_NOTE, PrismExportError, template_spec, write_bytes
from qpilot.schemas_studio import PrismBundle

Platform = Literal["windows", "macos"]
RUN_SCRIPT = "run.pzc"
SEND_BACK_SCRIPT = "send_back.pzc"
DONE_FILE = "qpilot_done.txt"
SEND_BACK_DONE_FILE = "qpilot_sent_back_done.txt"
SENT_BACK_DIR = "sent_back"
GRAPH_FORMATS = ("pdf", "png")
# [R] The install path differs by version and edition; Studio should let the scientist pick it.
DEFAULT_PRISM_EXE = r"C:\Program Files\GraphPad\Prism 10\prism.exe"
DEFAULT_MAC_APP = "Prism"  # [R] the application's name differs by version ("Prism 10", ...)
_NEWLINE = {"windows": "\r\n", "macos": "\n"}
DOCS = {
    "command_list": "https://www.graphpad.com/support/faq/list-of-all-script-commands-for-graphpad-prism",
    "launch_windows": (
        "https://graphpad.com/guides/prism/latest/user-guide/"
        "launching_a_prism_script_from_outside_prism_(windows).htm"
    ),
    "launch_applescript": (
        "https://graphpad.com/guides/prism/latest/user-guide/launching_prism_from_applescript.htm"
    ),
    "applescript_paths": (
        "https://www.graphpad.com/support/faq/"
        "specifying-file-names-and-paths-when-opeining-a-prism-file-via-applescript"
    ),
}
MAC_PATH_KB = (
    "https://www.graphpad.com/support/faq/when-writing-a-prism-script-for-the-mac-how-do-i-"
    "separate-disk-names-folder-names-and-file-names"
)


def host_platform() -> Platform:
    """The platform of this computer, as Prism knows it (Prism runs on Windows and macOS).

    Linux and other POSIX systems get the macOS form, the one whose paths they share; Prism
    does not run there, so a bundle written on such a machine names folders as this machine
    sees them (:func:`prism_runs_here` is False and the export says so).
    """
    return "windows" if sys.platform.startswith("win") else "macos"


def prism_runs_here() -> bool:
    """Whether Prism can run on this computer at all (Windows or macOS)."""
    return sys.platform.startswith("win") or sys.platform == "darwin"


def check_text(text: str, what: str) -> str:
    """Refuse text that cannot be put safely between double quotes in a Prism script."""
    if not text:
        raise PrismExportError(f"{what} is empty")
    if not text.isascii():
        raise PrismExportError(
            f"{what} has non-ASCII characters; how Prism decodes a script is unverified, so "
            "use a plain-ASCII folder name (or pass the folder as Prism sees it)"
        )
    bad = [ch for ch in text if ch == '"' or ord(ch) < 32 or ord(ch) == 127]
    if bad:
        raise PrismExportError(f"{what} contains a quote, line break or control character")
    return text


def prism_dir_for(out_dir: Path, platform: Platform, prism_dir: str | None) -> str:
    """The bundle folder as the Prism computer sees it (checked, absolute)."""
    if prism_dir is None:
        if platform != host_platform():
            raise PrismExportError(
                f"give the bundle folder as the {platform} Prism computer sees it (prism_dir)"
            )
        prism_dir = str(out_dir.resolve())
    check_text(prism_dir, "the bundle folder")
    if platform == "windows":
        absolute = PureWindowsPath(prism_dir).is_absolute() or prism_dir.startswith("\\\\")
    else:
        absolute = PurePosixPath(prism_dir).is_absolute()
    if not absolute:
        raise PrismExportError(f"the bundle folder must be an absolute path: {prism_dir}")
    return prism_dir


def join(directory: str, name: str, platform: Platform) -> str:
    """``directory`` + ``name`` with the platform's separator."""
    sep = "\\" if platform == "windows" else "/"
    return directory.rstrip(sep) + sep + name


def project_name(table_name: str, record_ref: str) -> str:
    """The project file run.pzc saves for one table (the record ref is in the name)."""
    return f"{table_name}_qpilot_{record_ref}"


def _q(text: str, what: str) -> str:
    return f'"{check_text(text, what)}"'


def _header(bundle: PrismBundle, purpose: str) -> list[str]:
    return [
        f"// qPilot -> GraphPad Prism (Mode S): {purpose}",
        f"// Study {bundle.study_id}, record {bundle.record_ref}, chain {bundle.chain_head[:12]}.",
        "// Written by qPilot; regenerate with `qpilot export prism` instead of editing.",
        "// Not yet run on a real Prism seat: behaviour is unverified until plan step 0.1.",
    ]


def run_script(
    bundle: PrismBundle,
    template_name: str,
    prism_dir: str,
    platform: Platform,
    graphs: Sequence[str] = ("pdf",),
) -> str:
    """The text of ``run.pzc`` (see the module docstring)."""
    unknown = [g for g in graphs if g not in GRAPH_FORMATS]
    if unknown:
        raise PrismExportError(f"graph formats must be among {GRAPH_FORMATS}, not {unknown}")
    note = bundle.info.get("note", INFO_NOTE)
    stamp = f"qPilot record {bundle.record_ref}, chain {bundle.chain_head[:12]}"
    lines = _header(bundle, "open the template, import qPilot's tables, save.")
    lines.append(f"SetPath {_q(prism_dir, 'the bundle folder')}")
    for table in bundle.tables:
        project = project_name(table.name, bundle.record_ref)
        lines += [
            f"// {table.gene}",
            f"Open {_q(template_name, 'the template file name')}",
            "GoTo D, 1",
            f"Import {_q(table.csv, 'the table file name')}",
            f"SetSheetTitle {_q(table.title, 'the table title')}",
            f"Save {_q(project + '.pzfx', 'the project file name')}",
            "GoTo I, 1",
            f"SetInfo {_q(note, 'the Info note')}, 1, 2",
            f"SetInfo {_q(stamp, 'the record stamp')}, 1, 2",
            "Save",
        ]
        if graphs:
            lines.append("GoTo G, 1")
        for fmt in graphs:
            command = "ExportPDF" if fmt == "pdf" else "ExportPNG"
            lines.append(f"{command} {_q(f'{project}.{fmt}', 'the graph file name')}")
        lines.append("Close")
    lines += [
        "// Done signal: Prism runs scripts invisibly and gives no completion signal of its own.",
        f"OpenOutput {_q(DONE_FILE, 'the done file')}, Clear",
        f"WText {_q(f'qPilot run.pzc finished for record {bundle.record_ref}', 'done text')}",
        "CloseOutput",
    ]
    return _NEWLINE[platform].join(lines) + _NEWLINE[platform]


def send_back_script(bundle: PrismBundle, prism_dir: str, platform: Platform) -> str:
    """The text of ``send_back.pzc`` (see the module docstring)."""
    target = join(prism_dir, SENT_BACK_DIR, platform)
    lines = _header(bundle, "export every data table to sent_back/ for qPilot.")
    lines += [
        "// Save your projects in Prism first. This script never closes them.",
        f"SetPath {_q(prism_dir, 'the bundle folder')}",
    ]
    for table in bundle.tables:
        project = project_name(table.name, bundle.record_ref)
        lines += [
            f"// {table.gene}",
            f"Open {_q(project + '.pzfx', 'the project file name')}",
            "GoTo D, 1",
            f"ExportTable {_q(join(target, table.csv, platform), 'the export path')}",
        ]
    lines += [
        "// Done signal for qPilot.",
        f"OpenOutput {_q(SEND_BACK_DONE_FILE, 'the done file')}, Clear",
        f"WText {_q(f'qPilot send_back.pzc finished for record {bundle.record_ref}', 'text')}",
        "CloseOutput",
    ]
    return _NEWLINE[platform].join(lines) + _NEWLINE[platform]


def write_scripts(
    bundle: PrismBundle,
    template_path: str | Path | None,
    out_dir: str | Path,
    *,
    platform: Platform | None = None,
    prism_dir: str | None = None,
    graphs: Sequence[str] = ("pdf",),
) -> dict[str, Path]:
    """Write ``run.pzc`` and ``send_back.pzc`` (and copy the template, when it exists).

    Args:
        bundle: From :func:`qpilot.prism.tables.build_bundle`.
        template_path: The hand-made template (``.pzt``); when it does not exist the scripts
            still name it, and the scientist puts it into the bundle folder.
        out_dir: The bundle folder.
        platform: ``"windows"`` or ``"macos"`` (default: this computer's).
        prism_dir: The bundle folder as the Prism computer sees it (default: ``out_dir``).
        graphs: Graph formats to export after the import (``"pdf"``, ``"png"``).

    Returns:
        Written files by name (``run.pzc``, ``send_back.pzc`` and the template when copied).
    """
    platform = platform or host_platform()
    if platform not in _NEWLINE:
        raise PrismExportError(f"platform must be 'windows' or 'macos', not {platform!r}")
    directory = Path(out_dir)
    directory.mkdir(parents=True, exist_ok=True)
    folder = prism_dir_for(directory, platform, prism_dir)
    source = Path(template_path) if template_path is not None else None
    name = source.name if source is not None else template_spec(bundle.template_id).file
    check_text(name, "the template file name")
    written: dict[str, Path] = {}
    if source is not None and source.is_file():
        copy = directory / name
        if copy.resolve() != source.resolve():
            shutil.copyfile(source, copy)
        written[name] = copy
    (directory / SENT_BACK_DIR).mkdir(exist_ok=True)
    texts = {
        RUN_SCRIPT: run_script(bundle, name, folder, platform, graphs),
        SEND_BACK_SCRIPT: send_back_script(bundle, folder, platform),
    }
    for script, text in texts.items():
        write_bytes(directory / script, text.encode("ascii"))
        written[script] = directory / script
    return written


def readme_text(
    bundle: PrismBundle,
    *,
    template_present: bool,
    launch: LaunchCommand,
    send_back: LaunchCommand,
) -> str:
    """The short ``README.txt`` the scientist finds in the bundle folder."""
    spec = template_spec(bundle.template_id)
    tables = ", ".join(t.csv for t in bundle.tables)
    if template_present:
        template = [f"- {spec.file}: the Prism template (copied here)."]
    else:
        template = [
            f"- {spec.file} is NOT here yet. Build it once in Prism as described in",
            "  qpilot/prism/templates/README.md and save it into this folder. The tables,",
            "  scripts and provenance are complete without it.",
        ]
    layout = (
        "one value per biological unit, one column per group. Technical replicates are\n"
        "  averaged per unit by qPilot and never counted as n."
        if spec.layout == "column"
        else "one subcolumn per biological unit, its technical replicates as rows."
    )
    lines = [
        f"qPilot tables for GraphPad Prism: study {bundle.study_id}, record {bundle.record_ref}",
        "",
        "What is here",
        "- One table per gene (log2 relative quantities):",
        f"  {tables}",
        f"  Layout: {layout}",
        *template,
        f"- {RUN_SCRIPT}: a Prism script. It opens the template, imports each table, saves one",
        f"  project per table (<table>_qpilot_{bundle.record_ref}.pzfx), exports the graph and",
        f"  then writes {DONE_FILE} (Prism shows no other sign that it has finished).",
        f"- {SEND_BACK_SCRIPT}: after you edit in Prism, save your projects, then run this. It",
        f"  exports every data table to {SENT_BACK_DIR}/ so qPilot can show what changed:",
        "  qpilot prism diff --study <id> --bundle <this folder> --sent-back <this folder>/"
        + SENT_BACK_DIR,
        "- qpilot_provenance.json, qpilot_bundle.json: how every value was made, and checksums",
        "  (qpilot prism verify --bundle <this folder>).",
        "",
        "Statistics in Prism",
        "- Test (made once in the template):",
        f"  {bundle.test}.",
        "  The values are already log2: use the ordinary t test on them, not a lognormal",
        "  test, and do not convert them back to fold changes first.",
        "",
        f"How to run the scripts ({launch.platform})",
        f"- run:       {launch.command_line}",
        f"- send back: {send_back.command_line}",
        *(
            ["- Double-clicking a .pzc file also starts Prism and runs it."]
            if launch.platform == "macos"
            else []
        ),
        "- The scripts name this folder in their SetPath line. If you move the folder, run",
        "  qpilot export prism again (or pass --prism-dir as the Prism computer sees it).",
        f"- Running {RUN_SCRIPT} again replaces the projects it made.",
        "",
        "Not yet checked on a real Prism seat (plan step 0.1): the import options Prism applies,",
        "how ExportTable writes excluded values, whether a script may set Info notes and sheet",
        "titles, and the macOS path form. If a step fails, the CSVs can be imported by hand.",
        "",
        "Works with GraphPad Prism. Not affiliated with or endorsed by GraphPad Software or",
        "Dotmatics.",
    ]
    return "\n".join(lines) + "\n"


@dataclass(frozen=True)
class LaunchCommand:
    """How to start a script in the scientist's Prism (returned, never run here).

    ``argv`` is for running without a shell (macOS); on Windows Prism wants the documented
    command line verbatim (``prism.exe @"<script>"``), so ``argv`` is empty and
    ``command_line`` is the string to pass to the system as it is.
    """

    platform: Platform
    command_line: str
    argv: tuple[str, ...] = ()


def launch_command(
    script: str,
    platform: Platform | None = None,
    *,
    prism_exe: str = DEFAULT_PRISM_EXE,
    app: str = DEFAULT_MAC_APP,
) -> LaunchCommand:
    r"""The OS command that runs ``script`` (its path as the Prism computer sees it).

    Windows: ``"<prism.exe>" @"<dir>\run.pzc"`` [V] (GraphPad's "launching a Prism script from
    outside Prism (Windows)"). macOS: AppleScript ``open POSIX file "<dir>/run.pzc"`` inside a
    ``tell application`` block [V for the form, KB 1957 and "launching Prism from AppleScript";
    the application name and this exact use from ``osascript`` are R].
    """
    platform = platform or host_platform()
    check_text(script, "the script path")
    if platform == "windows":
        check_text(prism_exe, "the Prism program path")
        return LaunchCommand(platform, f'"{prism_exe}" @"{script}"')
    if platform == "macos":
        check_text(app, "the Prism application name")
        argv = (
            "osascript",
            "-e",
            f'tell application "{app}"',
            "-e",
            f'open POSIX file "{script}"',
            "-e",
            "end tell",
        )
        return LaunchCommand(platform, shlex.join(argv), argv)
    raise PrismExportError(f"platform must be 'windows' or 'macos', not {platform!r}")


def open_command(
    project: str,
    platform: Platform | None = None,
    *,
    prism_exe: str = DEFAULT_PRISM_EXE,
    app: str = DEFAULT_MAC_APP,
) -> LaunchCommand:
    """How to open a project file in Prism (returned, never run here; no script involved).

    Windows: ``"<prism.exe>" "<project.pzfx>"`` (Prism opens a project named on its command
    line). macOS: ``open -a <Prism> <project.pzfx>`` (no shell; ``argv``). Double-clicking the
    file does the same on both, which is what a person is told.
    """
    platform = platform or host_platform()
    if not project or any(ch == '"' or ord(ch) < 32 for ch in project):
        raise PrismExportError("the project path contains a quote or a control character")
    if platform == "windows":
        return LaunchCommand(platform, f'"{prism_exe}" "{project}"')
    if platform == "macos":
        argv = ("open", "-a", app, project)
        return LaunchCommand(platform, shlex.join(argv), argv)
    raise PrismExportError(f"platform must be 'windows' or 'macos', not {platform!r}")


__all__ = [
    "DONE_FILE",
    "RUN_SCRIPT",
    "SEND_BACK_DONE_FILE",
    "SEND_BACK_SCRIPT",
    "SENT_BACK_DIR",
    "LaunchCommand",
    "Platform",
    "check_text",
    "host_platform",
    "join",
    "launch_command",
    "open_command",
    "project_name",
    "run_script",
    "send_back_script",
    "write_scripts",
]
