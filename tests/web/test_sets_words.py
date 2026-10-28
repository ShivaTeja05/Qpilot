"""The two robustness counts are said the same way by the backend and the page.

``qpilot/explain/sets.py`` (report, CLI, MCP, next steps) and ``frontend/src/lib/vocab.ts`` (every
page section) carry the same words for qPilot's choice grid, the audit's reasonable set and how
they differ (docs/user-guide.md §3). This keeps the two copies from drifting apart.
"""

from __future__ import annotations

import re
from pathlib import Path

from qpilot.explain import sets
from qpilot.qpcr.design import marker_group_names
from qpilot.web.results_views import reworded

VOCAB = Path(__file__).resolve().parents[2] / "frontend" / "src" / "lib" / "vocab.ts"


def _ts() -> str:
    return VOCAB.read_text(encoding="utf-8")


def test_constants_match_the_page() -> None:
    ts = _ts()
    for name in ("GRID_COUNT", "GRID_NAME", "GRID_WHAT", "AUDIT_NAME", "AUDIT_DOES"):
        value = getattr(sets, name)
        assert f'"{value}"' in ts, f"{name} differs between sets.py and vocab.ts"
    for key, words in sets.AUDIT_PLAIN.items():
        assert re.search(rf'\b{key}: "{re.escape(words)}"', ts), key
    assert all(f'"{d}"' in ts for d in sets.DEFAULT_AUDIT)


def test_bridge_words_match_the_page() -> None:
    ts = _ts()
    bridge = sets.bridge()
    # the page builds the same sentence from the same pieces
    assert "The audit also varies " in bridge and ", which qPilot's grid does not" in ts
    assert " (it tests the efficiency models only when you ask, under Results)" in ts
    tail = (
        "its verdicts leave out single and paired control genes and keep the group cut-off as "
        "planned, which qPilot's grid varies. So the same gene can hold in a different share of "
        "each."
    )
    assert bridge.endswith(tail) and tail in ts
    differs = sets.verdict_differs(None).removeprefix(
        "The audit counts only its reasonable analyses"
    )
    assert differs in ts


def test_bridge_names_what_only_the_audit_varies() -> None:
    assert sets.audit_only() == [
        "the efficiency model",
        "how flagged wells are handled",
        "the statistical test",
    ]
    # once a person asked qPilot's grid to test the efficiency models, the audit no longer
    # varies it alone; replicates join on a design with technical replicates
    assert sets.audit_only([*sets.DEFAULT_AUDIT, "replicates"], efficiency_in_grid=True) == [
        "how flagged wells are handled",
        "the statistical test",
        "how replicate wells are combined",
    ]
    assert "efficiency" not in sets.bridge(efficiency_in_grid=True)
    assert sets.bridge().startswith("The audit also varies the efficiency model, ")


def test_counts_line_names_both_sets() -> None:
    line = sets.counts_line(744, reasonable=144, full=90396)
    assert line.startswith("qPilot's choice grid is the 744 analyses qPilot checks")
    assert "it sets each gene's confidence level" in line
    assert "a wider re-analysis of 90,396 analyses; its verdicts count its 144 reasonable" in line
    assert sets.counts_line(744).endswith("confidence level.")
    assert sets.counts_line(None) == ""


def test_verdict_differs_takes_a_fact_token() -> None:
    assert "its 144 reasonable analyses" in sets.verdict_differs(144)
    token = "{{f_rpt_audit_reasonable}}"
    assert f"its {token} reasonable analyses" in sets.verdict_differs(token)
    assert "its reasonable analyses" in sets.verdict_differs(None)


def test_one_display_name_per_group() -> None:
    assert marker_group_names("MYCN_high") == ("MYCN-high", "rest")
    assert marker_group_names("KO") == ("KO-high", "rest")
    # a stored note that names the design's variable reads as every page names the groups
    note = "Groups are derived from the data (MYCN_high); minimum detectable effect reported."
    assert reworded(note, 744) == (
        "Groups are derived from the data (MYCN-high vs rest); minimum detectable effect reported."
    )
    assert reworded("Groups come from the confirmed design (KO).", 744).endswith("(KO).")
