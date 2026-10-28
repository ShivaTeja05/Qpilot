"""Red-team checks of the name rules that keep file text out of prompts, paths and tables.

RT-004: the allow-list patterns are written ``^...$`` and applied with ``.match``. In Python
``$`` also matches just before a trailing newline, so ``"Run 1\\n"`` passes
``curves.safe_name`` unchanged. An RDML attribute keeps a newline written as ``&#10;`` (XML
attribute normalisation only folds literal line breaks), so a run, sample or target id from a
file can carry one past the rule that promises "letters, digits, spaces, ``_ - . ( )``".
Measured on main @ 81484f7: ``<run id="Run 1&#10;">`` loads as ``'Run 1\\n'`` and LinRegPCR's
error names ``run Run 1\\n:``. Fixed on agents/integration @ a5983d4 (every pattern ends
at ``\\Z``); these tests guard it.
"""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from qpilot.io.rdml_io import load, runs
from qpilot.qpcr.curves import safe_name

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def test_an_rdml_attribute_can_carry_a_trailing_newline(tmp_path: Path) -> None:
    """Reachability: the loader hands a newline-terminated id to the name rules."""
    data = zipfile.ZipFile(FIXTURES / "test_mca_1_raw_data.rdml").read("rdml_data.xml").decode()
    data = data.replace('<run id="Run 1"', '<run id="Run 1&#10;"', 1)
    path = tmp_path / "newline.rdml"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("rdml_data.xml", data)
    assert runs(load(path))[0]["id"] == "Run 1\n"


@pytest.mark.parametrize("name", ["Run 1\n", "ODC1\n", "Sample 50\n"])
def test_safe_name_never_returns_a_line_break(name: str) -> None:
    assert "\n" not in safe_name(name, "target")


def test_the_export_label_rule_refuses_a_trailing_newline() -> None:
    from qpilot.qpcr.export import ExportError, check_label

    with pytest.raises(ExportError):
        check_label("ODC1\n", "group")


def test_the_model_label_rule_refuses_a_trailing_newline() -> None:
    from qpilot.ai.interpret import _LABEL

    assert not _LABEL.match("ODC1\n")


def test_a_study_id_with_a_trailing_newline_is_not_an_id() -> None:
    from qpilot.core.store import STUDY_ID

    assert not STUDY_ID.match("abcdef\n")


def test_plain_names_still_pass() -> None:
    """The fix must not touch ordinary names (the demo's names are all plain)."""
    assert safe_name("ALUsq(Eurogentec)", "target") == "ALUsq(Eurogentec)"
    assert safe_name("Sample 50", "sample") == "Sample 50"
