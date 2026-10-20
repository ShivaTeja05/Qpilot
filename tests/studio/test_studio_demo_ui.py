"""Studio on the cached demo: ``qpilot studio demo --check``.

The check walks the demo with a scripted person through the real Studio service
(``qpilot/cli/studio_cmds.py``) and prints the measured numbers. The page itself is the one
server's (``tests/web/test_studio_demo_walk.py``).
"""

import re

import pytest

from qpilot.cli import main as cli_main
from qpilot.cli.studio_cmds import demo_check

pytestmark = pytest.mark.demo_data


@pytest.fixture(scope="module")
def checked(tmp_path_factory):
    """``qpilot studio demo --check`` with the studies kept."""
    from tests.conftest import DEMO_RDML

    if not DEMO_RDML.exists():
        pytest.skip("demo dataset not cached")
    studies = tmp_path_factory.mktemp("check") / "studies"
    lines: list[str] = []
    code = demo_check(studies, out=lines.append)
    return code, "\n".join(lines), studies


def test_demo_check_passes_with_the_measured_numbers(checked):
    code, output, _ = checked
    assert code == 0, output
    for expected in (
        "design proposals (the rules alone): 131",
        "“Accept all consistent” lists only consistent proposals: 121",
        "comp_50 series contradicted (R² 0.707)",
        "the standards' series on the ALUsq plate contradicted (R² 0.694)",
        "study wells where the Curve Judge disagrees with LinRegPCR: 166",
        "Curve Judge well calls proposed: 110",
        "ODC1 fold change, up: 3.590× up",
        "changes conclusions: 14 of 58",
        "the same with Student's t test: 21 of 58",
        "ΔΔCq at an assumed efficiency of 2.0: 4 of 58",
        "3.590× → 3.319× up",
        "conclusions that change: 0 of 58",
        "person accepts the exclusion — reason: “failed RNA extraction”",
    ):
        assert expected in output, expected
    assert re.search(r"^All \d+ checks passed\.$", output, re.MULTILINE)
    assert "FAIL" not in output


def test_demo_check_refuses_a_studies_folder_in_use(checked, capsys):
    _, _, studies = checked
    assert cli_main(["studio", "demo", "--check", "--studies", str(studies)]) == 2
    assert "new or empty folder" in capsys.readouterr().out
