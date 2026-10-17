"""Dev 2 AI smoke test: the ai and harness packages import."""

import qpilot.ai
import qpilot.harness


def test_ai_packages_import():
    assert qpilot.ai.__doc__ and qpilot.harness.__doc__
