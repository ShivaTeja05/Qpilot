"""A person's names in files (``qpilot.core.names``): kept as written, never a path."""

from __future__ import annotations

import re

import pytest

from qpilot.core.names import MAX_NAME, ascii_slug, file_part, is_name, name_problem

LAB_NAMES = ("LPS + inhibitor", "IL-6/ctrl", "Day 3 (50 µM)", "KO#2", "α-syn")
PLAIN = re.compile(r"^[A-Za-z0-9_(][A-Za-z0-9_().\-]*\Z")


@pytest.mark.parametrize("name", [*LAB_NAMES, "Контроль", "对照", "<5 days", "=1+1", "WT"])
def test_a_labs_names_are_names(name):
    assert is_name(name) and name_problem(name) is None


@pytest.mark.parametrize(
    "name, words",
    [
        ("", "empty"),
        ("   ", "empty"),
        (" WT", "space"),
        ("WT ", "space"),
        ("x" * (MAX_NAME + 1), "longer than 64"),
        ("KO\t2", "invisible character"),
        ("KO\n2", "invisible character"),
        ("KO‮2", "invisible character"),  # right-to-left override
        ("KO​2", "invisible character"),  # zero-width space
        ("KO 2", "invisible character"),  # line separator
        ("KO2", "invisible character"),  # private use
    ],
)
def test_what_cannot_be_a_name_is_said_in_words(name, words):
    assert words in (name_problem(name) or "")


def test_a_plain_name_keeps_its_file_name():
    """The names earlier versions wrote as they were keep the same file name (the demo's)."""
    assert file_part("SDHA(1)") == "SDHA(1)"
    assert file_part("PRKACB bis") == "PRKACB_bis"
    assert file_part("ALUsq(Eurogentec)") == "ALUsq(Eurogentec)"
    assert file_part("CON", "gene") == "CON_gene"


@pytest.mark.parametrize("name", [*LAB_NAMES, "对照", ".hidden", "-Mar1", "=HYPERLINK(A1)"])
def test_any_other_name_is_an_ascii_slug_and_a_hash(name):
    part = file_part(name, "group")
    assert PLAIN.match(part) and part.isascii(), part
    assert re.fullmatch(r"[a-z0-9_]+_[0-9a-f]{8}", part), part
    assert "/" not in part and "\\" not in part and ".." not in part


def test_names_that_differ_only_in_signs_get_different_files():
    names = ["IL-6/ctrl", "IL-6_ctrl", "IL 6/ctrl", "il-6/ctrl", "Контроль", "对照"]
    parts = {file_part(n, "group").lower() for n in names}
    assert len(parts) == len(names)
    # The one sharing kept from earlier versions: a space is written as "_" (callers that
    # need one file per name check it, as the Prism tables do).
    assert file_part("IL-6 ctrl") == file_part("IL-6_ctrl")


def test_the_slug_drops_accents_and_keeps_ascii():
    assert ascii_slug("Café ß") == "cafe"
    assert ascii_slug("对照") == ""
