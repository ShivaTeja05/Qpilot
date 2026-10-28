"""qPilot behaves the same on Windows, macOS and Linux: text is UTF-8, lines end in LF.

What differs between systems is the *default*: Python on Windows reads and writes text in the ANSI
code page (cp1252) and turns ``\\n`` into CR LF; ``print`` through a pipe uses the same code page.
Each test below pins one thing that depended on it. The static scan fails for new code that
forgets, naming the line; the probe test runs the real record round trip in a child process whose
text encoding is not UTF-8 (a C locale where the system has one, the ANSI code page on Windows).
"""

import ast
import io
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from qpilot.cli import main
from qpilot.cli._console import ensure_utf8_output
from qpilot.core import pseudonym, store

REPO = Path(__file__).resolve().parents[2]
SHIPPED = [REPO / "qpilot", REPO / "sim" / "src"]
SKIP_DIRS = {"vendor", "static", "__pycache__"}  # vendored rdmlpython is byte-for-byte upstream
FIX = (
    'pass encoding="utf-8" (and newline="\\n" when writing text; lineterminator="\\n" '
    "to DataFrame.to_csv) so the result does not depend on the system"
)


def _mode(call: ast.Call, position: int, default: str = "r") -> str:
    for keyword in call.keywords:
        if keyword.arg == "mode":
            value = keyword.value
            return value.value if isinstance(value, ast.Constant) else "?"
    if len(call.args) > position:
        value = call.args[position]
        return value.value if isinstance(value, ast.Constant) else "?"
    return default


def _problem(call: ast.Call) -> str | None:
    """What a call leaves to the system's defaults, or None when it is portable."""
    func = call.func
    name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
    base = ast.unparse(func.value) if isinstance(func, ast.Attribute) else ""
    keywords = {k.arg for k in call.keywords}
    if name == "to_csv":
        return None if "lineterminator" in keywords else "to_csv without lineterminator"
    if name == "read_text" and base:
        return None if "encoding" in keywords else "read_text without encoding"
    if name == "write_text" and base:
        missing = [k for k in ("encoding", "newline") if k not in keywords]
        return f"write_text without {' and '.join(missing)}" if missing else None
    if name not in {"open", "fdopen", "NamedTemporaryFile"}:
        return None
    position = 0 if name == "NamedTemporaryFile" else 1  # open(file, mode), fdopen(fd, mode)
    if name == "open" and base and base not in {"io", "builtins"}:
        # ``something.open(...)`` is a file only when it looks like Path.open: a literal mode
        # first, or Path's keywords (a zip member, a browser or a Studio is not a text file).
        first = call.args[0] if call.args else None
        literal = isinstance(first, ast.Constant) and isinstance(first.value, str)
        if not (literal or keywords & {"mode", "newline"} or base.startswith("Path(")):
            return None
        position = 0
    mode = _mode(call, position, "w+b" if name == "NamedTemporaryFile" else "r")
    if mode == "?" or "b" in mode:
        return None
    if "encoding" not in keywords:
        return f"{name}({mode!r}) without encoding"
    if any(c in mode for c in "wax+") and "newline" not in keywords:
        return f"{name}({mode!r}) without newline"
    return None


def _offenders() -> list[str]:
    found = []
    for root in SHIPPED:
        for path in sorted(root.rglob("*.py")):
            if SKIP_DIRS & set(path.parts):
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and (why := _problem(node)):
                    found.append(f"{path.relative_to(REPO).as_posix()}:{node.lineno}: {why}")
    return found


@pytest.mark.skipif(not (REPO / "qpilot").is_dir(), reason="not a source checkout")
def test_no_shipped_code_leaves_encoding_or_line_ends_to_the_system():
    bad = _offenders()
    assert not bad, f"{FIX}:\n" + "\n".join(bad)


def test_the_scan_sees_what_it_should():
    """The rule itself: a bare call is flagged, an explicit one is not."""

    def flagged(code: str) -> bool:
        return any(_problem(n) for n in ast.walk(ast.parse(code)) if isinstance(n, ast.Call))

    assert flagged("p.read_text()")
    assert flagged("p.write_text(t, encoding='utf-8')")
    assert flagged("open(f, 'a', encoding='utf-8')")
    assert flagged("open(f)")
    assert flagged("df.to_csv(path, index=False)")
    assert flagged("Path(x).open('w')")
    assert not flagged("p.read_text(encoding='utf-8')")
    assert not flagged("p.write_text(t, encoding='utf-8', newline='\\n')")
    assert not flagged("open(f, 'a', encoding='utf-8', newline='\\n')")
    assert not flagged("open(f, 'rb')")
    assert not flagged("df.to_csv(path, lineterminator='\\n')")
    assert not flagged("zf.open(member)")


def test_a_non_utf8_code_page_changes_no_record(tmp_path):
    """Record, verify, zip and unzip a decision with non-ASCII text under a legacy code page."""
    env = {k: v for k, v in os.environ.items() if k not in {"PYTHONIOENCODING", "PYTHONUTF8"}}
    env.update(PYTHONUTF8="0", PYTHONCOERCECLOCALE="0", LC_ALL="C", LANG="C")
    probe = Path(__file__).with_name("portability_probe.py")
    done = subprocess.run(  # noqa: S603
        [sys.executable, str(probe), str(REPO / "tests" / "fixtures")],
        env=env,
        cwd=tmp_path,
        capture_output=True,
        timeout=180,
        check=False,
    )
    err = done.stderr.decode("utf-8", "replace")
    assert done.returncode == 0, err[-1500:]
    line = next(x for x in err.splitlines() if x.startswith("PROBE "))
    result = json.loads(line[len("PROBE ") :])
    assert result["verify_ok"], result["verify_problems"]
    assert result["unzipped_ok"]
    assert result["reason_back"].startswith("keep ÁÍÏÐÝ — Δ×→")
    assert result["reason_in_record"]
    assert result["files_with_cr"] == []
    out = done.stdout.decode("utf-8")  # --help through a pipe: UTF-8 whatever the code page
    assert "ΔΔCq" in out and "usage: qpilot" in out


def test_console_output_is_utf8_even_when_the_code_page_is_not(monkeypatch):
    raw = io.BytesIO()
    stream = io.TextIOWrapper(raw, encoding="cp1252")
    monkeypatch.setattr(sys, "stdout", stream)
    ensure_utf8_output()
    print("ΔΔCq → 3.6×")  # the arrow is not in cp1252
    stream.flush()
    assert raw.getvalue() == "ΔΔCq → 3.6×\n".encode()
    monkeypatch.setattr(sys, "stdout", io.StringIO())
    ensure_utf8_output()  # a test double without reconfigure(): left alone


def test_the_cli_prints_help_through_a_legacy_pipe(monkeypatch, capsys):
    stream = io.TextIOWrapper(io.BytesIO(), encoding="cp1252")
    monkeypatch.setattr(sys, "stdout", stream)
    with pytest.raises(SystemExit) as stop:
        main(["--help"])
    assert stop.value.code == 0
    stream.flush()
    assert "ΔΔCq".encode() in stream.buffer.getvalue()


def test_qsim_validate_without_the_repository_data_says_so(monkeypatch, tmp_path, capsys):
    qsim_cli = pytest.importorskip("qsim.cli")
    monkeypatch.chdir(tmp_path)  # no ./data here, as after `pip install qpilot`
    assert qsim_cli.main(["validate"]) == 2
    err = capsys.readouterr().err
    assert "clone" in err and "Traceback" not in err
    assert qsim_cli.main(["external"]) == 2


def test_atomic_write_is_utf8_with_lf_line_ends(tmp_path):
    target = tmp_path / "x.json"
    store.atomic_write(target, 'a\n"Δ×→ Á"\n')
    assert target.read_bytes() == 'a\n"Δ×→ Á"\n'.encode()


def test_replace_file_retries_on_windows_only(monkeypatch, tmp_path):
    calls = []
    real = os.replace

    def flaky(src, dst):
        calls.append(1)
        if len(calls) < 3:
            raise PermissionError("in use")
        real(src, dst)

    src, dst = tmp_path / "a", tmp_path / "b"
    src.write_text("x", encoding="utf-8")
    monkeypatch.setattr(os, "replace", flaky)
    monkeypatch.setattr(store.time, "sleep", lambda s: None)
    monkeypatch.setattr(store, "_WINDOWS", True)
    store.replace_file(src, dst)
    assert len(calls) == 3 and dst.read_text(encoding="utf-8") == "x"

    calls.clear()
    src.write_text("y", encoding="utf-8")
    dst.unlink()
    monkeypatch.setattr(store, "_WINDOWS", False)  # elsewhere a PermissionError is real
    with pytest.raises(PermissionError):
        store.replace_file(src, dst)
    assert len(calls) == 1


def test_the_pseudonym_key_survives_bytes_windows_treats_as_text(monkeypatch, tmp_path):
    """0x0A would become CR LF and 0x1A would end a read, if the key file were opened as text."""
    nasty = (b"\x1a\n\r\n\x00" * 8)[:32]
    monkeypatch.setattr(pseudonym.secrets, "token_bytes", lambda n: nasty)
    first = pseudonym.hmac_key(tmp_path)
    assert first == nasty
    assert pseudonym.hmac_key(tmp_path) == nasty  # read back from disk
    assert (tmp_path / pseudonym.KEY_DIR / pseudonym.KEY_FILE).read_bytes() == nasty
