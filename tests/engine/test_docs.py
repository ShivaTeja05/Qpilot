"""Docs quote the engine, never the reverse: numbers in docs/engine.md come from generated files."""

import json
from pathlib import Path

import pytest

from qpilot.qpcr.contrast import DEFAULT_RULE
from qpilot.qpcr.validation import ValidationReport

REPO = Path(__file__).resolve().parents[2]
ENGINE_DOC = REPO / "docs" / "engine.md"


@pytest.fixture(scope="module")
def engine_doc() -> str:
    return ENGINE_DOC.read_text()


def test_engine_doc_quotes_the_generated_validation_lines(engine_doc):
    data = json.loads((REPO / "validation" / "validation.json").read_text())
    for line in ValidationReport.from_dict(data).lines():
        assert f"- {line}\n" in engine_doc, f"docs/engine.md is out of date: {line}"


def test_engine_doc_states_the_conclusion_rule(engine_doc):
    assert DEFAULT_RULE.describe() in engine_doc


@pytest.mark.parametrize("card", ["linregpcr", "genorm", "contrast"])
def test_method_cards_exist_and_are_linked(engine_doc, card):
    assert (REPO / "methods" / f"{card}.md").exists()
    assert f"](../methods/{card}.md)" in engine_doc
