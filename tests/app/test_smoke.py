"""Dev 1 app smoke test: the explain package exists (templates arrive in Task 9)."""

import qpilot.explain


def test_explain_package_imports():
    assert qpilot.explain.__doc__
