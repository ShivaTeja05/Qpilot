"""Smoke-test an installed qPilot: the wheel as a user gets it, from outside the repository.

Run it with the Python of a virtual environment that has the wheel installed, from any directory
that is not a clone (the CI jobs and ``docs/release.md`` do exactly this)::

    python scripts/smoke_installed.py            # about 30 s, works offline
    python scripts/smoke_installed.py --full     # also fetches the demo, runs Studio's checks

It uses only the standard library, runs the same on Windows, macOS and Linux, and exits 1 when
anything fails. It never touches the real study store: everything goes to a temporary folder.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

TOKEN = "smoke-test-token"
FAILURES: list[str] = []


def report(ok: bool, what: str, detail: str = "") -> None:
    """Print one line per check and remember the failures."""
    print(f"  {'ok  ' if ok else 'FAIL'}  {what}" + (f": {detail}" if detail and not ok else ""))
    if not ok:
        FAILURES.append(what)


def script(name: str) -> str:
    """The installed console script (``qpilot``, ``qsim``) next to this Python."""
    suffix = ".exe" if os.name == "nt" else ""
    return str(Path(sys.executable).with_name(name + suffix))


def run(args: list[str], env: dict[str, str], cwd: Path, timeout: float = 300):
    """Run a command and capture its output as text; never raises on a non-zero exit."""
    return subprocess.run(  # noqa: S603 (fixed commands from this file)
        args,
        env=env,
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
    )


def tail(proc: subprocess.CompletedProcess) -> str:
    """The end of a failed command's output, for the failure line."""
    return (proc.stderr or proc.stdout or "").strip()[-400:]


def check_install(env: dict[str, str], cwd: Path) -> str:
    """The package is the installed one (not a checkout) and carries everything it reads."""
    code = (
        "import importlib.metadata as m, importlib.resources as r, json, pathlib, qpilot, qsim\n"
        "root = r.files('qpilot')\n"
        "need = ['web/static/index.html', '_packs/research-default.yaml', '_methods/trace.md',\n"
        "        'models/curve_judge/model.json', 'models/curve_judge/model.sha256',\n"
        "        'data/hgnc/hgnc_symbols.tsv', 'report/miqe2_items.yaml',\n"
        "        'vendor/rdmlpython/rdml.py', 'vendor/rdmlpython/schema/RDML_v1_4_CR.xsd',\n"
        "        'vendor/rdmlpython/README_VENDOR.md']\n"
        "here = pathlib.Path(qpilot.__file__).resolve()\n"
        "print(json.dumps({'version': m.version('qpilot'), 'module': qpilot.__version__,\n"
        "  'path': str(here), 'qsim': str(pathlib.Path(qsim.__file__).resolve()),\n"
        "  'missing': [n for n in need if not root.joinpath(n).is_file()],\n"
        "  'assets': len([p for p in root.joinpath('web/static/assets').iterdir()]),\n"
        "  'tests_shipped': (here.parents[1] / 'tests').exists()}))\n"
    )
    proc = run([sys.executable, "-I", "-c", code], env, cwd)
    report(proc.returncode == 0, "import qpilot and qsim from the installed wheel", tail(proc))
    if proc.returncode != 0:
        return ""
    info = json.loads(proc.stdout)
    report("site-packages" in info["path"], "qpilot is the installed copy", info["path"])
    report(not (Path(info["path"]).parents[1] / ".git").exists(), "not inside a git checkout")
    report(info["version"] == info["module"], "wheel metadata version equals qpilot.__version__")
    report(not info["missing"], "package data is in the wheel", ", ".join(info["missing"]))
    report(info["assets"] >= 10, "the prebuilt page's assets are in the wheel", str(info["assets"]))
    report(not info["tests_shipped"], "no tests folder next to the package")
    return info["version"]


def check_cli(env: dict[str, str], cwd: Path, version: str) -> None:
    """The console scripts start, print non-ASCII text through a pipe, and list the tools."""
    proc = run([script("qpilot"), "--version"], env, cwd)
    report(proc.returncode == 0 and version in proc.stdout, "qpilot --version", tail(proc))
    # --help has a Greek capital delta: a pipe on Windows is cp1252 unless the CLI sets UTF-8.
    proc = run([script("qpilot"), "--help"], env, cwd)
    report(proc.returncode == 0 and "usage: qpilot" in proc.stdout, "qpilot --help", tail(proc))
    proc = run([script("qpilot"), "doctor"], env, cwd)
    last = proc.stdout.strip().splitlines()[-1:] or [""]
    report(proc.returncode == 0 and last[0] == "OK", "qpilot doctor", tail(proc))
    proc = run([script("qpilot"), "serve", "--list-tools"], env, cwd)
    tools = [x for x in proc.stdout.splitlines() if re.fullmatch(r"(qpcr|sim)_\w+", x)]
    report(proc.returncode == 0 and "qpcr_study" in tools, "qpilot serve --list-tools", tail(proc))
    report(
        len(tools) >= 20 and "sim_audit" in tools, f"{len(tools)} tools, the simulator among them"
    )
    proc = run([script("qsim"), "--help"], env, cwd)
    report(proc.returncode == 0 and "usage: qsim" in proc.stdout, "qsim --help", tail(proc))
    proc = run([script("qsim"), "validate"], env, cwd)  # needs the repository's sim/data: says so
    said = "clone" in (proc.stderr + proc.stdout) and "Traceback" not in proc.stderr
    report(proc.returncode != 0 and said, "qsim validate says it needs a clone", tail(proc))


def check_sheet(env: dict[str, str], cwd: Path) -> None:
    """A real .xlsx goes through Sheet Check: openpyxl is a core dependency, not an extra."""
    try:
        import openpyxl
    except ImportError:
        report(False, "openpyxl is installed with qpilot")
        return
    book = openpyxl.Workbook()
    sheet = book.active
    sheet.append(["Sample", "Group", "GAPDH", "MYC"])
    for i, (group, gapdh, myc) in enumerate(
        [
            ("vehicle", 18.0, 25.0),
            ("vehicle", 18.2, 25.3),
            ("drug", 18.1, 23.9),
            ("drug", 17.9, 23.7),
        ]
    ):
        sheet.append([f"S{i + 1}", group, gapdh, myc])
    path = cwd / "sheet.xlsx"
    book.save(path)
    proc = run([script("qpilot"), "check", "sheet", str(path), "--json"], env, cwd)
    ok = proc.returncode == 0
    if ok:
        try:
            ok = isinstance(json.loads(proc.stdout), dict)
        except ValueError:
            ok = False
    report(ok, "qpilot check sheet reads an .xlsx", tail(proc))


def free_port() -> int:
    """A port nobody listens on (asked from the system, closed again)."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def fetch(url: str, token: bool, timeout: float = 10):
    """One GET, returning (status, headers, body) whatever the status."""
    request = urllib.request.Request(url)  # noqa: S310 (127.0.0.1)
    if token:
        request.add_header("X-Qpilot-Token", TOKEN)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
            return response.status, response.headers, response.read()
    except urllib.error.HTTPError as err:
        return err.code, err.headers, err.read()


def check_app(env: dict[str, str], cwd: Path, version: str) -> None:
    """``qpilot app`` serves the prebuilt page and a guarded API (its own process is stopped)."""
    port = free_port()
    base = f"http://127.0.0.1:{port}"
    log = cwd / "app.log"
    with log.open("w", encoding="utf-8") as sink:
        proc = subprocess.Popen(  # noqa: S603
            [script("qpilot"), "app", "--no-open", "--port", str(port)],
            env={**env, "QPILOT_APP_TOKEN": TOKEN},
            cwd=cwd,
            stdout=sink,
            stderr=subprocess.STDOUT,
        )
    try:
        status = 0
        body = b""
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline and proc.poll() is None:
            try:
                status, _, body = fetch(f"{base}/api/system", token=True, timeout=3)
                if status == 200:
                    break
            except OSError:
                time.sleep(0.5)
        report(
            status == 200, "qpilot app answers /api/system", log.read_text(encoding="utf-8")[-400:]
        )
        if status == 200:
            report(json.loads(body).get("version") == version, "/api/system reports this version")
            report(
                fetch(f"{base}/api/system", token=False)[0] == 401,
                "the API refuses a request without the key",
            )
            code, headers, html = fetch(f"{base}/", token=False)
            text = html.decode("utf-8", errors="replace")
            report(code == 200 and 'id="root"' in text, "the page is served")
            report("content-security-policy" in headers, "the page carries its security headers")
            asset = re.search(r'src="(/assets/[^"]+\.js)"', text)
            got = fetch(f"{base}{asset.group(1)}", token=False)[0] if asset else 0
            report(got == 200, "the page's script is served", asset.group(1) if asset else "none")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=15)


def check_demo(env: dict[str, str], cwd: Path) -> None:
    """The whole Studio walk on the pinned demo: fetched (SHA-256 verified) and checked."""
    proc = run([script("qpilot"), "fetch-demo"], env, cwd, timeout=900)
    report(proc.returncode == 0, "qpilot fetch-demo", tail(proc))
    proc = run(
        [script("qpilot"), "studio", "demo", "--check", "--studies", str(cwd / "demo-studies")],
        {**env, "QPILOT_MODEL_PROVIDER": "none"},
        cwd,
        timeout=1800,
    )
    proc2 = run([script("qsim"), "options"], env, cwd, timeout=600)  # loads the demo study
    report(proc2.returncode == 0 and "*" in proc2.stdout, "qsim options", tail(proc2))
    done = re.search(r"All (\d+) checks passed", proc.stdout)
    report(proc.returncode == 0 and bool(done), "qpilot studio demo --check", tail(proc))
    if done:
        print(f"        ({done.group(1)} checks)")


def main() -> int:
    """Run the checks; the exit code is the number of failed groups, capped at 1."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--full", action="store_true", help="also fetch the demo and run its checks"
    )
    parser.add_argument("--no-app", action="store_true", help="skip starting the app server")
    args = parser.parse_args()

    with tempfile.TemporaryDirectory(prefix="qpilot-smoke-") as tmp:
        cwd = Path(tmp)
        env = {k: v for k, v in os.environ.items() if k not in {"PYTHONPATH", "PYTHONHOME"}}
        env.update(
            QPILOT_STUDIES_DIR=str(cwd / "studies"),
            QPILOT_MODEL_PROVIDER="none",
            MPLBACKEND="Agg",
        )
        print(f"Python {sys.version.split()[0]} on {sys.platform}, running in {cwd}")
        version = check_install(env, cwd)
        if version:
            check_cli(env, cwd, version)
            check_sheet(env, cwd)
            if not args.no_app:
                check_app(env, cwd, version)
            if args.full:
                check_demo(env, cwd)
    print(f"\n{'FAILED: ' + ', '.join(FAILURES) if FAILURES else 'All smoke checks passed.'}")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
