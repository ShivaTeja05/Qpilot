"""The robustness audit on a study with several comparisons: it audits the first, and says so.

The simulator varies one comparison of two groups (its permutations, influence and verdicts are
built on it), so a study with a comparison plan is audited on its first comparison alone. The
invariant holds for that comparison: the simulator's baseline gives qPilot's stored fold change,
p-value and call for every gene, or nothing is written. A correction that changes one of the
first comparison's calls, a paired comparison or a pooled-variance correction (Dunnett, Tukey)
is refused in words before anything runs.
"""

from __future__ import annotations

import json

import pytest

from qpilot.core.store import StudyStore
from qpilot.integration import simulator as sim
from qpilot.qpcr.contrast import conclude
from tests.fixtures.studio.compare_mini import design, write_compare_mini

pytestmark = pytest.mark.skipif(
    not sim.available(), reason="the Decision Simulator is not installed"
)


@pytest.fixture(scope="module")
def mini(tmp_path_factory):
    root = tmp_path_factory.mktemp("compare_audit")
    return {
        "store": StudyStore(root / "studies"),
        "path": write_compare_mini(root / "mini.rdml"),
        "root": root,
    }


def test_the_first_comparison_is_audited_and_reproduced(mini, monkeypatch):
    monkeypatch.setenv("QPILOT_CACHE_DIR", str(mini["root"] / "cache"))
    store = mini["store"]
    sid = store.ensure_study(mini["path"], design())
    result = store.get(sid)
    first = result.comparisons.comparisons[0]
    assert all(  # Holm changes none of the first comparison's calls here
        conclude(c.log2fc, c.p) == c.conclusion for c in result.contrasts.values()
    )
    prepared = sim.prepare(sim.load_analysis(store, sid))
    scope = prepared.scope["comparisons"]
    assert scope["audited"] == first.id and scope["n_comparisons"] == 2
    assert "audits the first, Drug A vs Control, alone" in scope["note"]
    assert "without Holm's correction" in scope["note"]
    assert prepared.scope["groups"] == ["Drug A", "Control"]
    check = sim.reproduction(prepared, result)
    assert check["ok"], check
    audit = sim.audit(store, sid, mini["root"] / "audit", permutations=19)
    assert sim.verify_audit(audit.out_dir).ok
    manifest = json.loads((audit.out_dir / sim.MANIFEST).read_text(encoding="utf-8"))
    assert manifest["reproduces_qpilot"]["ok"]
    assert manifest["scope"]["comparisons"]["audited_label"] == "Drug A vs Control"


@pytest.mark.parametrize(
    ("kwargs", "words"),
    [
        ({"paired": True}, r"is a paired comparison \(by donor\)"),
        ({"correction": "dunnett"}, "one variance pooled over every group"),
        ({"pattern": "all_pairs", "correction": "tukey"}, "one variance pooled over every group"),
    ],
)
def test_what_the_audit_cannot_re_run_is_refused_in_words(mini, monkeypatch, kwargs, words):
    monkeypatch.setenv("QPILOT_CACHE_DIR", str(mini["root"] / "cache"))
    sid = mini["store"].ensure_study(mini["path"], design(**kwargs))
    with pytest.raises(sim.NotApplicable, match=words):
        sim.prepare(sim.load_analysis(mini["store"], sid))


def test_a_correction_that_changes_a_first_comparison_call_is_refused(mini):
    from qpilot.qpcr.contrast import DEFAULT_RULE
    from qpilot.schemas import ComparisonOutcome, ComparisonsResult, ContrastResult

    moved = ContrastResult(
        target="G", log2fc=2.0, fc=4.0, ci=(2.0, 8.0), p=0.03, t=3.0, n_hi=3, n_lo=3,
        conclusion="none",
    )  # fmt: skip
    outcome = ComparisonOutcome(
        id="a_vs_c", group_a="A", group_b="C", label="A vs C", primary=True, n_a=3, n_b=3,
        contrasts={"G": moved}, p_adjusted={"G": 0.06}, q_value={"G": 0.03}, robustness={},
    )  # fmt: skip
    result = type("R", (), {})()
    result.contrasts = {"G": moved}
    result.comparisons = ComparisonsResult(
        test="welch", correction="holm", comparisons=[outcome, outcome.model_copy()]
    )
    with pytest.raises(sim.NotApplicable, match="changes the call of G in A vs C"):
        sim.comparisons_scope(result, DEFAULT_RULE)
    assert sim.comparisons_scope(type("R", (), {"comparisons": None})(), DEFAULT_RULE) is None
