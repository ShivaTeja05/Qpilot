"""Dev 2 core smoke test: the core package imports without pulling in the qPCR plugin."""

import importlib
import sys


def test_core_imports_alone():
    sys.modules.pop("qpilot.qpcr", None)
    importlib.import_module("qpilot.core")
    assert "qpilot.qpcr" not in sys.modules
