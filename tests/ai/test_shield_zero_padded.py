"""Zero-padded ids (P0007) are long names: they never reach a remote model in any spelling."""

import hashlib

import pytest

from qpilot.ai.interpret import _Shield


class _Keyed:
    def pseudonymise(self, text: str) -> str:
        return "s_" + hashlib.sha256(text.encode("utf-8")).hexdigest()[:10]


@pytest.fixture
def shield():
    names = {"P0007_LPS": ["P0007_LPS"], "P0008_LPS": ["P0008_LPS"], "ODC1": ["ODC1"]}
    return _Shield(_Keyed(), names)


@pytest.mark.parametrize(
    "text",
    [
        "P0007",
        "p0007",
        "P 0007",
        "xP0007",
        "P0007 was treated",
        "Animal P0007, liver",
        "Ｐ０００７",
    ],
)
def test_a_zero_padded_id_is_hidden_or_withheld(shield, text):
    shown = shield.hide(text)
    assert shown is None or ("0007" not in shown and "０００７" not in shown), shown


def test_the_whole_name_becomes_its_token(shield):
    assert shield.hide("P0007_LPS") == shield.token("P0007_LPS")
    assert shield.hide("p7 lps") == shield.token("P0007_LPS")  # same name, another spelling
