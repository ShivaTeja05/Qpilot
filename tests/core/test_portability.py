"""qPilot behaves the same on Windows, macOS and Linux: text is UTF-8, lines end in LF.

What differs between systems is the *default*: Python on Windows reads and writes text in the ANSI
code page (cp1252) and turns ``\\n`` into CR LF; ``print`` through a pipe uses the same code page.
Each test below pins one thing that depended on it. The static scan fails for new code that
forgets, naming the line; the probe test runs the real record round trip in a child process whose
text encoding is not UTF-8 (a C locale where the system has one, the ANSI code page on Windows).
"""

import ast
import importlib.util
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
SCRIPT = REPO / "scripts" / "fix_portability.py"


def _load_rules():
    """The rule lives in scripts/fix_portability.py, which also applies it."""
    spec = importlib.util.spec_from_file_location("fix_portability", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


needs_checkout = pytest.mark.skipif(not SCRIPT.is_file(), reason="not a source checkout")


@needs_checkout
def test_no_shipped_code_leaves_encoding_or_line_ends_to_the_system():
    rules = _load_rules()
    bad = [
        f"{path.relative_to(REPO).as_posix()}:{call.lineno}: add {', '.join(need)}"
        for path in rules.source_files()
        for call, need in rules.offenders(path)
    ]
    assert not bad, (
        "Python on Windows reads and writes text in cp1252 with CR LF: name the arguments. "
        "`python scripts/fix_portability.py && ruff format qpilot sim/src` adds them.\n"
        + "\n".join(bad)
    )


@needs_checkout
def test_the_rule_sees_what_it_should():
    """A bare call is flagged, an explicit one is not."""
    rules = _load_rules()

    def need(code: str) -> list[str]:
        calls = [n for n in ast.walk(ast.parse(code)) if isinstance(n, ast.Call)]
        return [a for call in calls for a in rules.missing(call)]

    assert need("p.read_text()") == ['encoding="utf-8"']
    assert need("p.write_text(t, encoding='utf-8')") == ['newline="\\n"']
    assert need("open(f, 'a', encoding='utf-8')") == ['newline="\\n"']
    assert need("open(f)") == ['encoding="utf-8"']
    assert need("df.to_csv(path, index=False)") == ['lineterminator="\\n"']
    assert need("Path(x).open('w')") == ['encoding="utf-8"', 'newline="\\n"']
    assert need("tempfile.NamedTemporaryFile('w', dir=d)") == ['encoding="utf-8"', 'newline="\\n"']
    assert not need("p.read_text(encoding='utf-8')")
    assert not need("p.write_text(t, encoding='utf-8', newline='\\n')")
    assert not need("open(f, 'a', encoding='utf-8', newline='\\n')")
    assert not need("open(f, 'rb')")
    assert not need("tempfile.NamedTemporaryFile(dir=d, delete=False)")  # binary by default
    assert not need("df.to_csv(path, lineterminator='\\n')")
    assert not need("zf.open(member)")  # not a text file
    assert not need("webbrowser.open(url)")


@needs_checkout
def test_the_fixer_adds_the_arguments_and_leaves_a_second_run_nothing_to_do(tmp_path):
    rules = _load_rules()
    source = tmp_path / "m.py"
    source.write_text(
        "def f(p, df):\n"
        "    a = p.read_text()\n"
        "    p.write_text(\n"
        "        a,\n"
        "    )\n"
        "    with open(p, 'a') as fh:\n"
        "        fh.write('é')\n"
        "    df.to_csv(p)\n",
        encoding="utf-8",
    )
    assert rules.rewrite(source) == 4
    fixed = source.read_text(encoding="utf-8")
    ast.parse(fixed)
    assert 'p.read_text(encoding="utf-8")' in fixed and 'lineterminator="\\n"' in fixed
    assert rules.rewrite(source) == 0


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
