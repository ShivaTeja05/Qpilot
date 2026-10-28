"""A person's names (groups, biological units, samples, genes) in what qPilot writes.

Domain-agnostic. A lab names its groups the way the bench does: ``LPS + inhibitor``,
``IL-6/ctrl``, ``Day 3 (50 µM)``, ``KO#2``, ``α-syn``. qPilot keeps such a name exactly as the
person wrote it wherever a person reads it (tables, figures, reports, Prism) and makes it safe
where it is written: HTML and SVG escape it, CSV and workbook cells defuse a formula start, XML
writers escape it. A name never becomes a path: :func:`file_part` derives the part of a file
name separately (the name itself when it is already a plain ASCII file name, else an ASCII slug
and a short hash of the name, so two names never share a file).

What a name may not be is narrow, and said in words by :func:`name_problem`: empty, longer than
:data:`MAX_NAME` characters, starting or ending with a space, or carrying a character nobody can
see or type as part of a name (a control character such as a tab or a line break, an invisible
formatting mark such as a right-to-left override, a private-use or unassigned code point).
"""

from __future__ import annotations

import hashlib
import re
import unicodedata

MAX_NAME = 64
#: The rule in a person's words (the Design page and the API's refusals say it).
NAME_WORDS = (
    "any letters, digits, spaces and signs, at most 64 characters, without tabs, line breaks "
    "or invisible characters"
)
#: A file-name part kept as it is: what earlier versions wrote (plain ASCII, spaces as ``_``).
_PLAIN_FILE = re.compile(r"^[A-Za-z0-9_(][A-Za-z0-9_().\-]{0,79}\Z")
_WINDOWS_RESERVED = {"CON", "PRN", "AUX", "NUL"} | {
    f"{prefix}{i}" for prefix in ("COM", "LPT") for i in range(1, 10)
}
_SEPARATORS = {" ", " "}  # line and paragraph separators (category Z, not C)


def name_problem(name: object) -> str | None:
    """Why ``name`` cannot be kept as a person's name, in words; ``None`` when it can."""
    if not isinstance(name, str) or not name.strip():
        return "it is empty"
    if name != name.strip():
        return "it starts or ends with a space"
    if len(name) > MAX_NAME:
        return f"it is longer than {MAX_NAME} characters"
    for ch in name:
        if ch in _SEPARATORS or unicodedata.category(ch).startswith("C"):
            return "it has a tab, a line break or an invisible character"
    return None


def is_name(name: object) -> bool:
    """``True`` when ``name`` can be kept as a person's name (see :func:`name_problem`)."""
    return name_problem(name) is None


def name_digest(name: str, n: int = 8) -> str:
    """The first ``n`` hex digits of the name's SHA-256 (its UTF-8 bytes)."""
    return hashlib.sha256(name.encode("utf-8")).hexdigest()[:n]


def ascii_slug(name: str, max_len: int = 40) -> str:
    """Lower-case ASCII letters and digits joined by ``_`` (accents dropped); may be ``""``."""
    folded = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    out = re.sub(r"[^a-z0-9]+", "_", folded.lower()).strip("_")
    return out[:max_len].rstrip("_")


def file_part(name: str, fallback: str = "name") -> str:
    """A safe part of a file name for a person's ``name`` (never a path, never empty).

    A name that is already a plain ASCII file name (letters, digits, ``_ - . ( )``, not
    starting with ``.``, ``-`` or ``)``; spaces become ``_``, as earlier versions wrote it) is
    kept, so a study's file names do not change.
    Any other name becomes its ASCII slug and the first 8 hex digits of its SHA-256
    (``LPS + inhibitor`` -> ``lps_inhibitor_<hash>``, ``α-syn`` -> ``syn_<hash>``), so names
    that differ only in signs or script still get different files. A name that is a reserved
    device name on Windows (``CON``, ``COM1`` ...) gets ``_<fallback>`` appended.
    """
    plain = str(name).replace(" ", "_")
    if _PLAIN_FILE.match(plain):
        stem = plain
    else:
        stem = f"{ascii_slug(str(name)) or fallback}_{name_digest(str(name))}"
    if stem.split(".")[0].upper() in _WINDOWS_RESERVED:
        stem = f"{stem}_{fallback}"
    return stem


__all__ = [
    "MAX_NAME",
    "NAME_WORDS",
    "ascii_slug",
    "file_part",
    "is_name",
    "name_digest",
    "name_problem",
]
