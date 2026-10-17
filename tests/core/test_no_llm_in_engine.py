"""The numbers never depend on a model: the engine and the core cannot import the AI layer."""

import subprocess
import sys

ENGINE_AND_CORE = """
import importlib, pkgutil, sys
import qpilot.core, qpilot.qpcr
for pkg in (qpilot.core, qpilot.qpcr):
    for mod in pkgutil.iter_modules(pkg.__path__):
        importlib.import_module(f"{pkg.__name__}.{mod.name}")
bad = sorted(m for m in sys.modules if m.startswith(("qpilot.ai", "anthropic", "httpx")))
assert not bad, bad
print("ok")
"""

CORE_ALONE = """
import importlib, pkgutil, sys
import qpilot.core
for mod in pkgutil.iter_modules(qpilot.core.__path__):
    importlib.import_module(f"qpilot.core.{mod.name}")
bad = sorted(m for m in sys.modules if m.startswith(("qpilot.qpcr", "qpilot.ai")))
assert not bad, bad
print("ok")
"""


def _run(code: str) -> None:
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "ok"


def test_engine_and_core_never_import_ai():
    _run(ENGINE_AND_CORE)


def test_core_never_imports_qpcr_at_import_time():
    _run(CORE_ALONE)
