"""Docs quote the engine, never the reverse: numbers in docs/engine.md come from generated files."""

import json
import re
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


README = REPO / "README.md"


def test_readme_quotes_the_generated_validation_lines():
    data = json.loads((REPO / "validation" / "validation.json").read_text())
    text = README.read_text()
    for line in ValidationReport.from_dict(data).lines():
        assert f"- {line}\n" in text, f"README.md is out of date: {line}"


def test_every_command_in_the_readme_exists():
    from qpilot.cli import build_parser

    parser = build_parser()
    registered = set(parser._subparsers._group_actions[0].choices)  # argparse keeps them here
    mentioned = set(re.findall(r"\bqpilot ([a-z][a-z-]+)", README.read_text()))
    assert mentioned, "no commands found"
    assert mentioned <= registered, mentioned - registered


@pytest.mark.parametrize("doc", ["README.md", "CONTRIBUTING.md", "docs/engine.md"])
def test_relative_links_point_to_real_files(doc):
    path = REPO / doc
    for target in re.findall(r"\]\(([^)#]+)\)", path.read_text()):
        if "://" in target:
            continue
        assert (path.parent / target).exists(), f"{doc} links to a missing file: {target}"


def test_conformance_lists_every_corpus_set_as_the_page_opens_it():
    """docs/conformance.md (scripts/conformance.py) says what the intake tests check, set by set."""
    from tests.web.test_intake_corpus import OPENS, REFUSED

    rows = {
        line.split("`")[1]: line
        for line in (REPO / "docs" / "conformance.md").read_text(encoding="utf-8").splitlines()
        if line.startswith("| `")
    }
    for slug, (plates, wells) in OPENS.items():
        assert f"| {plates} · {wells} · " in rows[slug], (
            f"docs/conformance.md is out of date: {slug}"
        )
    for slug in REFUSED:
        assert "| refused: " in rows[slug], f"docs/conformance.md is out of date: {slug}"
    sets = [slug for slug in rows if slug.count("/") == 1]  # the second table lists files
    assert sorted(sets) == sorted([*OPENS, *REFUSED])
