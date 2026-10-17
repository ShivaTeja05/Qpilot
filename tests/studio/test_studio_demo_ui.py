"""Studio on the cached demo: ``qpilot studio demo --check``, and the page through every stage.

The check walks the demo with a scripted person (``qpilot/cli/studio_cmds.py``); the page tests
drive the real service through the page's own handlers, with Gradio's preprocessing, and look at
everything the page renders while the stages are blind and after an accepted exclusion.
"""

import re
from pathlib import Path

import pytest

import qpilot.studio as st
from qpilot.ai.client import ModelClient, NoneBackend
from qpilot.cli import main as cli_main
from qpilot.cli.studio_cmds import demo_check
from qpilot.core.store import StudyStore
from qpilot.studio_service import Studio
from tests.studio.test_studio_app import Tab, html_outputs, text_of

pytestmark = pytest.mark.demo_data


@pytest.fixture(scope="module")
def checked(tmp_path_factory):
    """``qpilot studio demo --check`` with the studies kept, so the page can show them after."""
    from tests.conftest import DEMO_RDML

    if not DEMO_RDML.exists():
        pytest.skip("demo dataset not cached")
    studies = tmp_path_factory.mktemp("check") / "studies"
    lines: list[str] = []
    code = demo_check(studies, out=lines.append)
    return code, "\n".join(lines), studies


def demo_page(studies, tmp_path):
    from tests.conftest import DEMO_RDML

    studio = Studio(StudyStore(studies), client=ModelClient(backend=NoneBackend()))
    return studio, st.build_app(studio, DEMO_RDML, tmp_path / "exports", tmp_path / "inputs")


def assert_blind(out, ui):
    """No conclusion, fold change, p-value, card or preview anywhere on the page."""
    for html in html_outputs(out):
        assert "×" not in html and "data-fact" not in html, html[:300]
        assert not re.search(r"\bp\s*=\s*\d", html)
        assert "qp-card" not in html and "Prism preview</h4>" not in html
    if ui.right in out:
        assert out[ui.right]["visible"] is False


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


def test_after_the_exclusion_the_page_shows_only_the_new_analysis_then_sends_it(
    checked, tmp_path, monkeypatch
):
    import qpilot.studio_service as service

    monkeypatch.setattr(service, "_mac_prism_installed", lambda: False)  # never start a Prism
    _, output, studies = checked
    studio, page = demo_page(studies, tmp_path)
    tab = Tab(page)
    tab("on_load", None)
    out = tab("on_open", None, None, None)
    ui = tab.ui
    assert "continues where it was left" in out[ui.notice]
    new = re.search(r"a new analysis, ODC1 still up: (\w+):", output).group(1)
    summary = out[ui.summary]
    assert out[ui.right]["visible"] is True and f"<code>{new}</code>" in summary
    odc1 = re.search(r'qp-gene">ODC1</span><span class="qp-call">([^<]+)<', summary).group(1)
    assert odc1 == "3.3× up"  # the old analysis's 3.6× is not on the page as current
    assert tab.state["shown"] == "choices" and tab.state["card_study"] == new
    assert "Your decision" in out[ui.card]  # the choices are decided afresh
    assert "ODC1" in out[ui.preview] and "346" in out[ui.preview]  # one unit fewer for ODC1
    assert 'Choices</b><span class="qs-state">open' in out[ui.strip]
    assert out[ui.send_btn]["interactive"] is False  # no project accepted for this analysis

    # the person decides the new analysis's cards, confirms, drafts and accepts the project
    for _ in range(3):
        card = studio.store.card(new, tab.state["card_id"])
        if card.status not in ("open", "pending_human"):
            break
        out = tab("on_decide", None, card.recommended, "as before the exclusion")
        assert "Decided:" in out[ui.notice]
    out = tab("on_confirm_prepare", None)
    assert out[ui.confirm_box]["visible"] is True
    out = tab("on_confirm", None)
    assert "The Choices stage is confirmed." in out[ui.notice]
    out = tab("on_propose_prism", None)
    assert tab.state["shown"] == "prism"
    assert "Prism project from template two_groups_log2" in text_of(out[ui.slots[0].html])
    out = tab("on_accept_0", None, "the headline genes")
    assert out[ui.send_btn]["interactive"] is True

    # Send to Prism: a new folder in the export root; no Prism here, so a zip is offered
    out = tab("on_send", None)
    assert "Prism is not installed on this computer" in out[ui.send_info]
    assert out[ui.download]["visible"] is True
    bundle = tab.state["bundle"]
    assert bundle.startswith(str(page.qpilot_export_root))
    assert bundle in str(out[ui.bundle_pick]["choices"])
    folder = Path(bundle)
    assert (folder / "ODC1.csv").exists() and (folder / "run.pzc").exists()

    # the round trip: the tables come back with one value emptied, through the page
    sent_back = folder / "sent_back"
    sent_back.mkdir(exist_ok=True)
    for table in folder.glob("*.csv"):
        lines = table.read_text().split("\n")
        if table.name == "ODC1.csv":
            first = lines[1].split(",")[0]
            lines[1] = ",".join([first, "", ""])
        (sent_back / table.name).write_text("\n".join(lines))
    out = tab("on_roundtrip", None, bundle, str(sent_back))
    assert "1 difference(s) since the export; 1 question(s)" in out[ui.notice]
    assert tab.state["shown"] == "roundtrip"
    card = text_of(out[ui.slots[0].html])
    assert f"Sample {first} for ODC1 is empty in the table Prism sent back" in card
    assert "fold change of ODC1" in card and "conclusions that change" in card
    out = tab("on_accept_0", None, "")
    assert "Say why this value was excluded" in out[ui.notice]  # a reason is required


def test_the_blind_stages_through_the_page(tmp_path):
    from tests.conftest import DEMO_RDML

    if not DEMO_RDML.exists():
        pytest.skip("demo dataset not cached")
    studio, page = demo_page(tmp_path / "studies", tmp_path)
    tab = Tab(page)
    ui = tab.ui
    assert_blind(tab("on_load", None), ui)
    assert_blind(tab("on_open", None, None, None), ui)
    out = tab("on_propose_design", None, "")
    assert_blind(out, ui)
    sid = tab.state["sid"]
    assert "131 design proposal(s)" in out[ui.notice]
    # the scripted person accepts the preset, then everything consistent through the page
    preset = next(p for p in studio.inbox(sid, "design", "proposed") if p.kind == "design.preset")
    studio.accept(sid, preset.id, "human", "the pinned dataset's published design")
    tab("on_bulk_show", None)
    out = tab("on_bulk_accept", None)
    assert "Accepted 121 proposal(s)" in out[ui.notice]
    assert_blind(out, ui)
    left = [p.id for p in studio.inbox(sid, "design", "proposed")]
    studio.reject_many(sid, left, "human", "contradicted by the engine check")
    tab("on_load", None)
    assert_blind(tab("on_confirm_prepare", None), ui)
    out = tab("on_confirm", None)
    assert "The Design (blind) stage is confirmed." in out[ui.notice]
    assert_blind(out, ui)
    out = tab("on_propose_curves", None)
    assert "disagrees with LinRegPCR on 166 study wells" in out[ui.notice]
    assert_blind(out, ui)
    cards = "".join(text_of(out[slot.html]) for slot in ui.slots)
    assert "This matters for at least one conclusion; decide on the evidence." in cards
    tab("on_reject_show", None)
    assert len(tab.state["reject"]["ids"]) == 110
    out = tab("on_reject_all", None, "LinRegPCR fitted a complete early curve")
    assert "Rejected 110 proposal(s)" in out[ui.notice]
    assert_blind(out, ui)
    assert studio.store.proposals(sid).get(tab.state["slots"][0]).kind == "curve.call_rule"
    out = tab("on_accept_0", None, "the engine's default call")
    assert_blind(out, ui)
    assert_blind(tab("on_confirm_prepare", None), ui)
    out = tab("on_confirm", None)
    assert "Both blind stages are confirmed" in out[ui.notice]
    assert out[ui.right]["visible"] is True
    assert 'qp-gene">ODC1</span><span class="qp-call">3.6× up' in out[ui.summary]
    assert 'data-fact="f_n_differ_route_linear_welch"' in out[ui.routes]
    assert "Which control genes" in out[ui.card]
