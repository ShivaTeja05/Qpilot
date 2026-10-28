"""The files and folders the Prism and Record routes touch, and the rules they obey.

Copied (Gradio-free) from the old pages, never imported from them: the folder Prism sends the
tables back to (``qpilot.studio`` ``allowed_folder``, made stricter: no ``..``, no relative path,
no link anywhere below the allowed root), the export folder bundles and records are written into
(``exports/<workspace>/`` beside the study store, kept across launches), the opaque download
ids, a size-capped upload, and the preview helpers the Studio page used to draw the Prism graph
(``qpilot.studio_state`` ``preview_tables``, ``group_points``, ``mean_ci``, ``ROUTES``).

Nothing here reaches outside the folders it is given: every path a person or a request names is
checked against an allowed root after resolving it, and a download is served only when it is a
regular file inside the export folder that this server registered itself.
"""

from __future__ import annotations

import csv
import io
import math
import re
import secrets
import tempfile
from collections.abc import Mapping, MutableMapping, Sequence
from pathlib import Path
from typing import Any

from qpilot.prism.provenance import BUNDLE_FILE

EXPORTS_DIR = "exports"
BUNDLE_PREFIX = "prism-"
RECORD_PREFIX = "record-"
VERIFY_PREFIX = "verify-"
OPAQUE = re.compile(r"^[A-Za-z0-9_-]{8,64}\Z")
SENT_BACK_DIR = "sent_back"
MAX_POINTS = 100_000  # rows of a previewed table read for the graph (the old page's cap)
CHUNK = 1024 * 1024

#: The usual Excel→Prism routes the engine compares on every study (``methods/routes.md``),
#: with the words the Studio page used; the numbers are facts of the study.
ROUTES: tuple[tuple[str, str], ...] = (
    (
        "linear_welch",
        "The usual Excel→Prism route (2^-ΔΔCq per sample, Welch's t test on the linear scale)",
    ),
    (
        "linear_student",
        "The same route with Student's t test (Prism's default before version 10)",
    ),
    ("ddcq", "ΔΔCq with the efficiency assumed to be 2.0 (Welch on log2)"),
)
ROUTES_NOTE = (
    "Computed by the engine on this study's own plates (methods/routes.md); the engine's "
    "analysis is what is sent to Prism."
)


class FolderRefused(ValueError):
    """A folder (or file) a request named that the page may not read; the message says why."""


# ---- where a path may be -------------------------------------------------------------------------


def within(path: Path, root: Path) -> bool:
    """True when ``path`` is ``root`` or inside it (both taken as given, not resolved)."""
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _links_below(path: Path, root: Path) -> bool:
    """True when a component of ``path`` below ``root`` (``path`` itself included) is a link."""
    current = root
    for part in path.relative_to(root).parts:
        current = current / part
        if current.is_symlink():
            return True
    return False


def allowed_folder(text: str, *, roots: Sequence[Path], store_root: Path) -> Path:
    """The folder Prism sent the tables back to, if the page may read it; else ``FolderRefused``.

    The rules of the old Studio page, stricter: a full path (``~`` is the home folder), with no
    ``..`` and no link (neither the folder nor any folder between an allowed root and it), that
    is a folder inside one of ``roots`` (qPilot's export folder and the home folder) and
    not inside the study store.

    Args:
        text: The folder as the person typed it.
        roots: The folders a sent-back folder may be inside.
        store_root: The study store, which is never a sent-back folder.

    Returns:
        The folder, resolved.
    """
    raw = (text or "").strip()
    if not raw or raw == ".":
        raise FolderRefused("Give the folder Prism sent the tables back to.")
    if "\x00" in raw or len(raw) > 4096:
        raise FolderRefused("This is not a folder name.")
    path = Path(raw).expanduser()
    if not path.is_absolute():
        raise FolderRefused(
            "Give the folder's full path (for example ~/Documents/prism/sent_back)."
        )
    if ".." in path.parts:
        raise FolderRefused("The folder's path may not contain “..”: give its full path.")
    if path.is_symlink():
        raise FolderRefused("This folder is a link: give the folder it points to instead.")
    if not path.is_dir():
        raise FolderRefused(f"There is no folder {path}.")
    folder = path.resolve()
    store = store_root.resolve()
    if within(folder, store):
        raise FolderRefused("The study store is not a folder Prism sends tables back to.")
    for root in roots:
        for form in dict.fromkeys((root, root.resolve())):
            if within(path, form):
                if _links_below(path, form):
                    raise FolderRefused(
                        "A folder on this path is a link: give the folder it points to instead."
                    )
                if within(folder, root.resolve()):
                    return folder
    raise FolderRefused("The folder must be inside your home folder or qPilot's export folder.")


def allowed_returned(text: str, *, roots: Sequence[Path], store_root: Path) -> Path:
    """What came back from Prism, if the page may read it; else ``FolderRefused``.

    A folder under the rules of :func:`allowed_folder`, or a ``.pzfx`` file (not a link) in
    such a folder: the project a person saved in Prism.
    """
    raw = (text or "").strip()
    path = Path(raw).expanduser() if raw and "\x00" not in raw and len(raw) <= 4096 else None
    if path is not None and path.suffix.lower() == ".pzfx" and path.is_absolute():
        if ".." in path.parts:
            raise FolderRefused("The file's path may not contain “..”: give its full path.")
        if path.is_symlink():
            raise FolderRefused("This file is a link: give the file it points to instead.")
        if not path.is_file():
            raise FolderRefused(f"There is no file {path}.")
        folder = allowed_folder(str(path.parent), roots=roots, store_root=store_root)
        return folder / path.name
    return allowed_folder(text, roots=roots, store_root=store_root)


def new_token() -> str:
    """An opaque, unguessable name for a file this server keeps (an uploaded project)."""
    return secrets.token_urlsafe(12)


def exports_root(store_root: Path) -> Path:
    """Where bundles and records are written: ``exports/`` beside the study store.

    They are the person's files, so they outlive the server (unlike its private folder); they
    are offered for download only through ids this server registered.
    """
    path = Path(store_root).parent / EXPORTS_DIR
    path.mkdir(parents=True, exist_ok=True)
    return path


def workspace_exports(store_root: Path, key: str) -> Path:
    """One workspace's export folder (``exports/<session or study id>``)."""
    if not re.fullmatch(r"[0-9a-f]{12}", key or ""):
        raise FolderRefused("not a workspace id")
    path = exports_root(store_root) / key
    path.mkdir(parents=True, exist_ok=True)
    return path


def private_dir(parent: Path, prefix: str) -> Path:
    """A new, empty folder with a random name inside ``parent`` (for one bundle or record)."""
    parent.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix=prefix, dir=parent))


# ---- downloads -----------------------------------------------------------------------------------


def register_download(downloads: MutableMapping[str, Path], exports: Path, path: Path) -> str:
    """Offer ``path`` (a file inside ``exports``) for download; return its opaque id."""
    target = path.resolve()
    if not target.is_file() or not within(target, exports.resolve()):
        raise FolderRefused("only files written into the export folder are offered for download")
    token = secrets.token_urlsafe(18)
    downloads[token] = target
    return token


def download_path(downloads: Mapping[str, Path], exports: Path, token: str) -> Path | None:
    """The registered file behind ``token``, if it is still a regular file inside ``exports``."""
    if not isinstance(token, str) or not OPAQUE.match(token):
        return None
    path = downloads.get(token)
    if path is None or path.is_symlink():
        return None
    try:
        resolved = path.resolve(strict=True)
    except (OSError, RuntimeError):
        return None
    if not resolved.is_file() or not within(resolved, exports.resolve()):
        return None
    return resolved


# ---- Prism bundles in the export folder ----------------------------------------------------------


def bundle_id(folder: Path) -> str | None:
    """The opaque id of a bundle folder in an export folder (``<exports>/prism-<id>``), or None."""
    name = folder.name
    if not name.startswith(BUNDLE_PREFIX):
        return None
    token = name[len(BUNDLE_PREFIX) :]
    return token if OPAQUE.match(token) else None


def bundle_folder(exports: Path, token: str) -> Path | None:
    """The bundle folder behind ``token``: inside ``exports``, not a link, with its bundle file."""
    if not isinstance(token, str) or not OPAQUE.match(token):
        return None
    folder = exports / f"{BUNDLE_PREFIX}{token}"
    if folder.is_symlink() or not folder.is_dir() or (folder / BUNDLE_FILE).is_symlink():
        return None
    if not (folder / BUNDLE_FILE).is_file():
        return None
    resolved = folder.resolve()
    return resolved if within(resolved, exports.resolve()) else None


def bundles_here(exports: Path) -> list[Path]:
    """Every bundle folder in ``exports``, oldest first."""
    found = [p.parent for p in exports.glob(f"{BUNDLE_PREFIX}*/{BUNDLE_FILE}")]
    ok = [f for f in found if bundle_id(f) and bundle_folder(exports, bundle_id(f) or "")]
    return sorted(ok, key=lambda p: (p / BUNDLE_FILE).stat().st_mtime)


# ---- uploads -------------------------------------------------------------------------------------


async def save_upload(upload: Any, dest: Path, limit: int) -> int:
    """Stream an upload to ``dest``, refusing more than ``limit`` bytes; return its size.

    Raises:
        FolderRefused: The upload is larger than ``limit`` (``dest`` is removed).
    """
    size = 0
    try:
        with dest.open("wb") as out:
            while chunk := await upload.read(CHUNK):
                size += len(chunk)
                if size > limit:
                    raise FolderRefused(f"larger than {limit // (1024 * 1024)} MB")
                out.write(chunk)
    except BaseException:
        dest.unlink(missing_ok=True)
        raise
    return size


def find_marked(root: Path, marker: str, *, depth: int = 2) -> list[Path]:
    """Folders at most ``depth`` levels inside ``root`` that hold a file named ``marker``.

    Links are neither followed nor counted; the shallowest folders come first.
    """
    found: list[Path] = []
    level = [root]
    for _ in range(depth + 1):
        nxt: list[Path] = []
        for folder in level:
            mark = folder / marker
            if mark.is_file() and not mark.is_symlink():
                found.append(folder)
            try:
                children = sorted(folder.iterdir())
            except OSError:
                continue
            nxt += [c for c in children if c.is_dir() and not c.is_symlink()]
        level = nxt
    return found


# ---- the Prism preview, as data ------------------------------------------------------------------


def preview_tables(preview: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """Each previewed table as ``{"columns": [...], "rows": [[...]], "n_rows": n}`` (CSV parsed)."""
    out: dict[str, dict[str, Any]] = {}
    for gene, table in (preview.get("tables") or {}).items():
        lines = list(table.get("head") or [])
        parsed = list(csv.reader(io.StringIO("\n".join(lines))))
        columns = parsed[0] if parsed else list(table.get("columns", []))
        out[str(gene)] = {"columns": columns, "rows": parsed[1:], "n_rows": table.get("n_rows")}
    return out


def group_points(
    columns: Sequence[str], rows: Sequence[Sequence[str]]
) -> dict[str, list[tuple[str, float]]]:
    """A column-layout table as ``{group: [(unit, log2 value), ...]}`` (empty cells skipped)."""
    groups: dict[str, list[tuple[str, float]]] = {str(c): [] for c in columns[1:]}
    for row in rows:
        if not row:
            continue
        unit = row[0]
        for column, cell in zip(columns[1:], row[1:], strict=False):
            try:
                value = float(cell)
            except ValueError:
                continue
            if math.isfinite(value):
                groups[str(column)].append((unit, value))
    return groups


def mean_ci(values: Sequence[float]) -> tuple[float, float, float] | None:
    """Mean and its 95 % confidence interval (Student's t); None for fewer than two values."""
    from scipy import stats

    n = len(values)
    if n < 2:
        return None
    mean = sum(values) / n
    sd = math.sqrt(sum((v - mean) ** 2 for v in values) / (n - 1))
    half = float(stats.t.ppf(0.975, n - 1)) * sd / math.sqrt(n)
    return mean, mean - half, mean + half


def who_decided(actor: str | None) -> str:
    """Who decided a choice that went into a bundle, in words."""
    if actor == "human":
        return "a person"
    if actor == "system":
        return "the system (it changes no conclusion)"
    if actor is None:
        return "not decided yet: exported at the recommended option"
    return str(actor)
