"""Make shipped code independent of the system's text defaults (Windows: cp1252, CR LF).

    python scripts/fix_portability.py            # add the missing arguments, then:
    ruff format qpilot sim/src                   #   tidy the lines this made long
    python scripts/fix_portability.py --check    # only list them (the portability test does)

A text file read or written without an encoding uses the system's code page; one written without
a newline argument gets CR LF on Windows; ``DataFrame.to_csv`` without a line terminator does the
same. That broke Analysis Record verification and made record ids differ between systems. This
finds those calls with ``ast`` in ``qpilot/`` and ``sim/src/`` (not the vendored rdmlpython, the
built page, or binary I/O) and adds ``encoding="utf-8"`` and, for writes, a newline (or line
terminator) of one line feed. Standard library only.
"""

from __future__ import annotations

import argparse
import ast
import sys
from collections.abc import Iterator
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SHIPPED = (ROOT / "qpilot", ROOT / "sim" / "src")
SKIP_DIRS = {"vendor", "static", "__pycache__"}
ENCODING = 'encoding="utf-8"'
NEWLINE = 'newline="\\n"'
LINETERMINATOR = 'lineterminator="\\n"'


def _mode(call: ast.Call, position: int, default: str) -> str:
    """The literal ``mode`` of an open-like call ("?" when it is not a literal)."""
    for keyword in call.keywords:
        if keyword.arg == "mode":
            value = keyword.value
            return str(value.value) if isinstance(value, ast.Constant) else "?"
    if len(call.args) > position:
        value = call.args[position]
        return str(value.value) if isinstance(value, ast.Constant) else "?"
    return default


def missing(call: ast.Call) -> list[str]:
    """The arguments (as source text) a call needs to be independent of the system, or []."""
    func = call.func
    name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
    base = ast.unparse(func.value) if isinstance(func, ast.Attribute) else ""
    keywords = {k.arg for k in call.keywords}
    if name == "to_csv":
        return [] if "lineterminator" in keywords else [LINETERMINATOR]
    if name == "read_text" and base:
        return [] if "encoding" in keywords else [ENCODING]
    if name == "write_text" and base:
        return [a for k, a in (("encoding", ENCODING), ("newline", NEWLINE)) if k not in keywords]
    if name not in {"open", "fdopen", "NamedTemporaryFile"}:
        return []
    position = 0 if name == "NamedTemporaryFile" else 1  # open(file, mode), fdopen(fd, mode)
    if name == "open" and base and base not in {"io", "builtins"}:
        # ``something.open(...)`` is a text file only when it looks like Path.open: a literal mode
        # first, or Path's keywords (a zip member, a browser or a Studio is not a text file).
        first = call.args[0] if call.args else None
        literal = isinstance(first, ast.Constant) and isinstance(first.value, str)
        if not (literal or keywords & {"mode", "newline"} or base.startswith("Path(")):
            return []
        position = 0
    mode = _mode(call, position, "w+b" if name == "NamedTemporaryFile" else "r")
    if mode == "?" or "b" in mode:
        return []
    need = [] if "encoding" in keywords else [ENCODING]
    if any(c in mode for c in "wax+") and "newline" not in keywords:
        need.append(NEWLINE)
    return need


def source_files(roots: tuple[Path, ...] = SHIPPED) -> Iterator[Path]:
    """The Python files that ship, in a stable order."""
    for root in roots:
        for path in sorted(root.rglob("*.py")):
            if not SKIP_DIRS & set(path.relative_to(root).parts):
                yield path


def offenders(path: Path) -> list[tuple[ast.Call, list[str]]]:
    """Every call in a file that needs arguments, with those arguments."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found = [(n, missing(n)) for n in ast.walk(tree) if isinstance(n, ast.Call)]
    return [(call, need) for call, need in found if need]


def rewrite(path: Path) -> int:
    """Add the missing arguments to a file in place; returns how many calls changed."""
    data = path.read_bytes()
    found = offenders(path)
    if not found:
        return 0
    starts = [0]
    for line in data.split(b"\n"):
        starts.append(starts[-1] + len(line) + 1)
    edits = []
    for call, need in found:
        close = starts[call.end_lineno - 1] + call.end_col_offset - 1  # the ")" of the call
        assert data[close : close + 1] == b")", f"{path}:{call.lineno}"
        before = data[:close].rstrip()
        comma = "" if before.endswith((b",", b"(")) else ", "
        edits.append((close, comma + ", ".join(need)))
    for close, text in sorted(edits, reverse=True):
        data = data[:close] + text.encode("utf-8") + data[close:]
    path.write_bytes(data)
    return len(edits)


def main() -> int:
    """List (``--check``) or fix the calls; the exit code is 1 when ``--check`` finds any."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="only list them; exit 1 if any")
    args = parser.parse_args()
    total = 0
    for path in source_files():
        if args.check:
            for call, need in offenders(path):
                print(f"{path.relative_to(ROOT).as_posix()}:{call.lineno}: add {', '.join(need)}")
                total += 1
        else:
            changed = rewrite(path)
            if changed:
                print(f"{path.relative_to(ROOT).as_posix()}: {changed} call(s)")
            total += changed
    if args.check:
        print(f"{total} call(s) depend on the system's defaults" if total else "none")
        return 1 if total else 0
    print(f"{total} call(s) rewritten; now run: ruff format qpilot sim/src")
    return 0


if __name__ == "__main__":
    sys.exit(main())
