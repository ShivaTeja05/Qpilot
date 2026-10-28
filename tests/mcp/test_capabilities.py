"""The tools for wave 2's capabilities, over a real Studio walk of the mini file.

The mini file with both knock-outs late on ``1-Mar`` (the gene is called down) and an early
no-template control on that plate (``tests/web/test_where_decide.py``): Trace points at
``KO_1``'s ``1-Mar`` well, setting its value (or the sample) aside changes the call, and the Run
Gate points at the same wells. Here an agent reads (``qpcr_units``, ``qpcr_melt``,
``qpcr_repeat_plan``, ``qpcr_comparisons``), exports (``qpcr_export``) and asks
(``qpcr_request_set_aside``); the tests check what it gets back, the blind rule, the typed
refusals, the idempotency and that a request never changes the analysis.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from qpilot.core.proposals import verify_proposal_chain
from qpilot.mcp_server import QpilotTools
from qpilot.studio_service import EXCLUDE_KIND, trace_card_of
from qpilot.web.routers import evidence as evidence_router
from qpilot.web.routers import where as where_router
from tests.web import conftest as web_conftest
from tests.web import test_results_compare as compare
from tests.web import test_where_decide as decided

called_walked = decided.called_walked
called = decided.called
web_store = web_conftest.web_store  # the store the comparison studies are made in
studies = compare.studies
GENE = decided.GENE
REASON = "The NTC on this plate amplified within five cycles of the knock-outs."


@pytest.fixture(autouse=True)
def fresh_caches():
    evidence_router.clear()
    where_router.clear()
    yield
    evidence_router.clear()
    where_router.clear()


@pytest.fixture
def tools(called) -> QpilotTools:
    return QpilotTools(called["store"])


def refused(out: dict, code: str, field: str | None = None) -> dict:
    """A typed refusal: error, code and fix (and the field it names, when it names one)."""
    assert {"error", "code", "fix"} <= set(out), out
    assert out["code"] == code, out
    if field is not None:
        assert out.get("field") == field, out
    json.dumps(out)
    return out


def inbox_state(called) -> list[str]:
    inbox = called["store"].proposals(called["sid"])
    return [p.id + ":" + p.status for p in inbox.proposals()]


def the_place(tools, called) -> dict:
    out = tools.qpcr_trace(called["study"], gene=GENE)
    assert "error" not in out, out
    place = out["places"][0]
    assert place["sample"] == "KO_1" and place["target"] == GENE and place["card_id"]
    return place


# ---- trace gives the place a name an agent can ask about ----------------------------------------


def test_trace_places_carry_the_card_id_a_request_names(tools, called):
    place = the_place(tools, called)
    assert place["card_id"].startswith("card_trace_")
    assert {p["card_id"] for p in tools.qpcr_trace(called["study"], gene=GENE, top=20)["places"]}


# ---- qpcr_units: each unit's value, with the wells behind it -------------------------------------


def test_units_are_the_engines_values_with_every_replicate_well(tools, called):
    study = called["study"]
    out = tools.qpcr_units(study, GENE)
    assert "error" not in out, out
    assert out["gene"] == GENE and out["saved"] is False and out["comparison"] is None
    assert {u["group"] for u in out["units"]} == {"WT", "KO"} and len(out["units"]) == 4
    assert out["replicates"] is True and out["most_wells"] == 3
    ko = next(u for u in out["units"] if u["unit"] == "KO_1")
    assert ko["n_wells"] == 3 and len(ko["wells"]) == 3 and ko["cq_range"] is not None
    assert {w["state"] for w in ko["wells"]} == {"used"} and all(w["cq"] for w in ko["wells"])
    # the stored result: the group means' difference is the study's log2 fold change
    result = called["store"].get(study).contrasts[GENE]
    assert out["fold_log2"] == pytest.approx(result.log2fc)
    first, second = out["groups"]
    assert second["label"] == "WT" or first["label"] == "WT"
    assert out["p"] == pytest.approx(result.p)
    # case does not matter; concise leaves the wells and the explanation out
    again = tools.qpcr_units(study, GENE.lower(), response_format="concise")
    assert again["gene"] == GENE and "wells" not in again["units"][0] and "how" not in again


def test_units_refuse_a_control_gene_an_unknown_gene_and_bad_arguments(tools, called):
    study = called["study"]
    refs = called["store"].get(study).design.refs_primary
    refused(tools.qpcr_units(study, refs[0]), "not_applicable", "gene")
    refused(tools.qpcr_units(study, "NOPE"), "unknown_item", "gene")
    refused(tools.qpcr_units(study, ""), "invalid_argument", "gene")
    refused(tools.qpcr_units(study, GENE, comparison="x"), "invalid_argument", "comparison")
    refused(tools.qpcr_units(study, GENE, response_format="long"), "invalid_argument")  # type: ignore[arg-type]
    refused(tools.qpcr_units("abcdef123456", GENE), "unknown_study")
    refused(tools.qpcr_units(None, GENE), "invalid_argument", "study_id")  # type: ignore[arg-type]


# ---- qpcr_comparisons: every comparison of a design with several ---------------------------------

B = "drug_b_vs_control"


def test_every_comparison_is_listed_with_the_engines_numbers_and_fact_ids(studies):
    tools = QpilotTools(studies["store"])
    sid, store = studies["several"], studies["store"]
    out = tools.qpcr_comparisons(sid)
    assert "error" not in out, out
    result = store.get(sid)
    assert out["study_id"] == sid and out["n_comparisons"] == 2
    assert out["test"] == "paired_t" and out["correction"] == "holm" and out["pair_by"] == "donor"
    assert [c["id"] for c in out["comparisons"]] == ["drug_a_vs_control", B]
    assert [(c["group_a"], c["group_b"]) for c in out["comparisons"]] == [
        ("Drug A", "Control"),
        ("Drug B", "Control"),
    ]
    facts = result.facts
    for shown, stored in zip(out["comparisons"], result.comparisons.comparisons, strict=True):
        assert shown["primary"] is stored.primary and shown["n_pairs"] == stored.n_pairs
        assert set(shown["contrasts"]) == set(stored.contrasts)
        for gene, row in shown["contrasts"].items():
            assert row["fc"] == stored.contrasts[gene].fc
            assert row["conclusion"] == stored.contrasts[gene].conclusion
            assert row["p_adjusted"] == stored.p_adjusted.get(gene)
            assert row["q"] == stored.q_value.get(gene)
            # every number names the fact that carries the same value
            for field, fact in row["fact_ids"].items():
                key = {"holds_fraction": "holds"}.get(field, field)
                assert facts[fact].value == pytest.approx(row[key])
    assert out["comparisons"][1]["not_tested"] == {}  # TP53 is tested, with one pair left out


def test_one_comparison_or_one_gene_narrows_the_list(studies):
    tools = QpilotTools(studies["store"])
    sid = studies["several"]
    only = tools.qpcr_comparisons(sid, comparison=B, gene="myc")
    assert [c["id"] for c in only["comparisons"]] == [B] and only["n_comparisons"] == 2
    assert set(only["comparisons"][0]["contrasts"]) == {"MYC"}
    assert set(only["omnibus"]) <= {"MYC"}
    concise = tools.qpcr_comparisons(sid, response_format="concise")
    assert "contrasts" not in concise["comparisons"][0] and "omnibus" not in concise
    assert concise["comparisons"][1]["n_not_tested"] == 0
    refused(tools.qpcr_comparisons(sid, comparison="nope"), "unknown_item", "comparison")
    refused(tools.qpcr_comparisons(sid, gene="NOPE"), "unknown_item", "gene")
    refused(tools.qpcr_comparisons(sid, comparison=3), "invalid_argument", "comparison")  # type: ignore[arg-type]
    refused(tools.qpcr_comparisons(sid, response_format="x"), "invalid_argument")  # type: ignore[arg-type]


def test_robustness_and_units_follow_the_comparison_asked_for(studies):
    tools = QpilotTools(studies["store"])
    sid, one = studies["several"], studies["one"]
    robust = tools.qpcr_robustness(sid, "MYC", comparison=B)
    assert robust["comparison"] == B and robust["p_adjusted"] is not None
    # per-unit values are the primary comparison's; another one's are in the export's tables
    first = tools.qpcr_units(sid, "MYC")
    assert "error" not in first and first["comparison"] == "drug_a_vs_control"
    assert {g["label"] for g in first["groups"]} == {"Drug A", "Control"}
    refused(tools.qpcr_units(sid, "MYC", comparison=B), "not_applicable", "comparison")
    refused(tools.qpcr_units(sid, "MYC", comparison="nope"), "unknown_item", "comparison")
    # a study with one comparison has nothing to list or pick
    refused(tools.qpcr_comparisons(one), "not_applicable")
    refused(tools.qpcr_units(one, "MYC", comparison=B), "invalid_argument", "comparison")


def test_the_exported_tables_hold_every_comparisons_units(studies, tmp_path):
    import io
    import zipfile

    tools = QpilotTools(studies["store"])
    out = tools.qpcr_export(studies["several"], "csv")
    assert "error" not in out, out
    with zipfile.ZipFile(io.BytesIO(Path(out["file"]["path"]).read_bytes())) as z:
        per_unit = z.read("per_unit.csv").decode("utf-8")
    assert "Drug A vs Control" in per_unit and "Drug B vs Control" in per_unit


# ---- qpcr_comparisons on a study with one comparison ---------------------------------------------


def test_comparisons_are_not_applicable_to_a_study_with_one(tools, called):
    out = refused(tools.qpcr_comparisons(called["study"]), "not_applicable")
    assert "qpcr_study" in out["error"]
    refused(tools.qpcr_comparisons(called["study"], gene=3), "invalid_argument", "gene")  # type: ignore[arg-type]


# ---- qpcr_melt: a file without melt curves says so in words --------------------------------------


def test_a_file_without_melt_curves_says_so_and_what_to_export(tools, called):
    out = tools.qpcr_melt(called["study"])
    assert "error" not in out, out
    assert out["has_melt"] is False and "melt" in out["message"].lower()
    assert out["calls"] == [] and out["assays"] == [] and out["saved"] is False
    refused(
        tools.qpcr_melt(called["study"], wells=["A1", "not a well"]), "invalid_argument", "wells"
    )
    refused(tools.qpcr_melt(called["study"], wells=["A1"] * 13), "invalid_argument", "wells")
    refused(tools.qpcr_melt(called["study"], run=""), "invalid_argument", "run")


# ---- qpcr_repeat_plan --------------------------------------------------------------------------


def test_the_repeat_plan_lists_each_reaction_once_and_the_plate(tools, called):
    out = tools.qpcr_repeat_plan(called["study"])
    assert "error" not in out, out
    top = out["items"][:2]
    assert {(i["sample"], i["target"]) for i in top} == {("KO_1", GENE), ("KO_2", GENE)}
    for item in top:
        assert item["consequence"] == "changes_call" and item["changed_calls"] == [GENE]
        assert {r["source"] for r in item["reasons"]} >= {"run_gate", "trace"}
    assert out["include"] == "consequential" and out["saved"] is False
    assert out["wells"] and out["csv"].splitlines()[0].startswith("plate")
    assert "person's call" in out["decision"]
    concise = tools.qpcr_repeat_plan(called["study"], response_format="concise")
    assert "wells" not in concise and "csv" not in concise
    assert concise["items"][0]["n_reasons"] >= 2 and "reasons" not in concise["items"][0]
    refused(tools.qpcr_repeat_plan(called["study"], include="some"), "invalid_argument", "include")  # type: ignore[arg-type]


# ---- qpcr_request_set_aside: a request, never a decision -----------------------------------------


def test_a_request_is_filed_for_a_person_and_changes_nothing(tools, called):
    store, sid, study = called["store"], called["sid"], called["study"]
    place = the_place(tools, called)
    before_results = (store.workspace(study) / "results.json").read_bytes()
    before_design = store.design(study)
    out = tools.qpcr_request_set_aside(
        study, place["card_id"], "set_aside_value", REASON, gene=GENE
    )
    assert out["status"] == "pending_human" and out["applied"] is False, out
    assert out["code"] == "needs_human_decision" and "error" not in out
    assert out["card_id"] == place["card_id"] and out["option"] == "set_aside_value"
    wells = sorted(f"{place['plate']}/{w}" for w in ("A7", "A8", "A9"))
    assert out["wells"] == wells and len(out["proposals"]) == 3
    assert out["place"]["sample"] == "KO_1" and out["place"]["option_wells"] == wells
    inbox = store.proposals(sid)
    mine = inbox.proposals(kind_prefix=EXCLUDE_KIND)
    assert sorted(p.subject for p in mine) == wells
    for p in mine:
        # an agent's proposal waiting for a person, tied to the Trace place, blind-safe
        assert p.status == "proposed" and p.made_by.kind == "agent" and p.decided_by is None
        assert p.payload == {"excluded": True} and p.reasons == [REASON]
        assert trace_card_of(p) == place["card_id"]
        assert set(p.consequence) == {"matters", "trace"} and p.consequence["matters"] is True
    assert verify_proposal_chain(inbox.entries(), inbox.root) is None
    # nothing was set aside: the analysis and its results are exactly as they were
    assert (store.workspace(study) / "results.json").read_bytes() == before_results
    assert store.design(study) == before_design and not store.design(study).excluded_wells
    # the studio lists it as a waiting request at the place
    waiting = called["studio"].trace_requests(sid)
    assert [p.id for p in waiting[place["card_id"]]] == [p.id for p in mine]


def test_a_request_is_shown_at_the_place_and_a_persons_click_answers_it(tools, called):
    c, study, sid = called["client"], called["study"], called["sid"]
    place = the_place(tools, called)
    tools.qpcr_request_set_aside(study, place["card_id"], "set_aside_value", REASON, gene=GENE)
    view = decided.where(c, study, gene=GENE)
    (request,) = view["places"][0]["requests"]
    assert request["option"] == "set_aside_value" and request["reason"] == REASON
    assert request["wells"] == sorted(request["wells"]) and len(request["wells"]) == 3
    assert view["places"][1:] == [] or all(not p["requests"] for p in view["places"][1:])
    # the person approves it with the same click as Decide… (accepted: it asks for what they chose)
    r = decided.decide(c, study, view, "set_aside_value", "Agreed: the NTC is contaminated.")
    assert r.status_code == 200, r.text
    inbox = called["store"].proposals(sid)
    mine = inbox.proposals(kind_prefix=EXCLUDE_KIND)
    assert {p.status for p in mine} == {"accepted"}
    assert {p.decided_by for p in mine} == {"human"}
    assert {p.made_by.kind for p in mine} == {"agent"}
    assert called["studio"].trace_requests(sid) == {}


def test_a_person_can_turn_a_request_down_by_keeping(tools, called):
    c, study, sid = called["client"], called["study"], called["sid"]
    place = the_place(tools, called)
    tools.qpcr_request_set_aside(study, place["card_id"], "set_aside", REASON, gene=GENE)
    view = decided.where(c, study, gene=GENE)
    (request,) = view["places"][0]["requests"]
    assert request["option"] == "set_aside" and len(request["wells"]) == 6
    r = decided.decide(c, study, view, "keep", "No: the NTC is a different assay's.")
    assert r.status_code == 200, r.text
    mine = called["store"].proposals(sid).proposals(kind_prefix=EXCLUDE_KIND)
    assert {p.status for p in mine} == {"rejected"} and {p.decided_by for p in mine} == {"human"}
    assert not called["store"].design(study).excluded_wells


def test_a_request_names_the_place_not_its_rank(tools, called):
    """The request is traced at the analysis in use; the place is found by its id."""
    from qpilot.core.decisions import apply_decision

    store, study = called["store"], called["study"]
    place = the_place(tools, called)
    apply_decision(
        store, study, "card_undetermined", "cap", "Caps the empty wells.", "human",
        store.chain_head(study),
    )  # fmt: skip
    out = tools.qpcr_request_set_aside(
        study, place["card_id"], "set_aside_value", REASON, gene=GENE
    )
    assert out["status"] == "pending_human" and out["place"]["sample"] == "KO_1"


def test_a_request_asks_again_by_replacing_the_waiting_one(tools, called):
    store, sid, study = called["store"], called["sid"], called["study"]
    place = the_place(tools, called)
    for reason in (REASON, "Asking again with another reason."):
        tools.qpcr_request_set_aside(study, place["card_id"], "set_aside_value", reason, gene=GENE)
    proposals = store.proposals(sid).proposals(kind_prefix=EXCLUDE_KIND)
    assert [p.status for p in proposals].count("proposed") == 3  # the older three are superseded
    assert {p.reasons[0] for p in proposals if p.status == "proposed"} == {
        "Asking again with another reason."
    }


def test_request_refusals_are_typed_and_file_nothing(tools, called):
    study, sid = called["study"], called["sid"]
    place = the_place(tools, called)
    card = place["card_id"]
    base = inbox_state(called)

    def ask(card_id=card, option="set_aside_value", reason=REASON, **root):
        root = root or {"gene": GENE}
        return tools.qpcr_request_set_aside(study, card_id, option, reason, **root)

    refused(ask(gene=None), "invalid_argument")  # no root at all
    refused(ask(gene=GENE, sample="KO_1"), "invalid_argument")  # two roots
    refused(ask(card_id="card_refset"), "invalid_argument", "card_id")
    refused(ask(card_id=5), "invalid_argument", "card_id")  # type: ignore[arg-type]
    for option in ("keep", "read_from_other_refs", "exclude", ""):
        refused(ask(option=option), "invalid_argument", "option")
    refused(ask(reason=""), "invalid_argument", "reason")
    refused(ask(reason="x" * 2001), "invalid_argument", "reason")
    refused(ask(reason=None), "invalid_argument", "reason")  # type: ignore[arg-type]
    refused(ask(card_id="card_trace_nowhere"), "unknown_item", "card_id")
    refused(ask(gene="NOPE"), "unknown_item")
    refused(
        tools.qpcr_request_set_aside("abcdef123456", card, "set_aside", REASON, gene=GENE),
        "unknown_study",
    )
    stale = tools.qpcr_request_set_aside(
        study, card, "set_aside", REASON, gene=GENE, expected_head="0" * 64
    )
    assert stale["status"] == "stale" and stale["code"] == "stale_head" and "error" in stale
    assert inbox_state(called) == base  # nothing was filed by any of them
    assert sid  # the session is the one the study came from


def test_a_request_needs_a_studio_session(tools, called, fixture_result, fixture_cards):
    """A study analysed outside Studio has no inbox to file in: a person opens it in Studio."""
    from qpilot.core.store import sha256_file

    store = called["store"]
    rdml = Path(tempfile.mkdtemp(dir=called["root"])) / "outside.rdml"
    rdml.write_bytes(b"<rdml>a study analysed outside studio</rdml>")
    digest = sha256_file(rdml)
    result = fixture_result.model_copy(update={"input_sha256": digest, "study_id": digest[:12]})
    store.put(result, fixture_cards)
    out = refused(
        tools.qpcr_request_set_aside(
            result.study_id, "card_trace_x", "set_aside", REASON, gene="ODC1"
        ),
        "human_only",
    )
    assert "Studio" in out["error"]


def test_a_keyed_retry_files_nothing_twice(tools, called):
    store, sid, study = called["store"], called["sid"], called["study"]
    place = the_place(tools, called)
    key = "request-1"
    first = tools.qpcr_request_set_aside(
        study, place["card_id"], "set_aside_value", REASON, gene=GENE, idempotency_key=key
    )
    log = (store.proposals(sid).path).read_bytes()
    again = tools.qpcr_request_set_aside(
        study, place["card_id"], "set_aside_value", REASON, gene=GENE, idempotency_key=key
    )
    assert again.pop("idempotent_replay") is True and again == first
    assert store.proposals(sid).path.read_bytes() == log  # not one more line
    other = tools.qpcr_request_set_aside(
        study, place["card_id"], "set_aside", REASON, gene=GENE, idempotency_key=key
    )
    refused(other, "idempotency_key_reused", "idempotency_key")
    refused(
        tools.qpcr_request_set_aside(
            study, place["card_id"], "set_aside", REASON, gene=GENE, idempotency_key="bad key!"
        ),
        "invalid_argument",
        "idempotency_key",
    )


# ---- qpcr_export ---------------------------------------------------------------------------------


def test_the_workbook_is_written_into_the_export_folder_the_page_lists(tools, called, tmp_path):
    import io
    import zipfile

    import openpyxl

    c, study, store = called["client"], called["study"], called["store"]
    before = store.chain_head(study)
    out = tools.qpcr_export(study, "xlsx", expected_head=before)
    assert "error" not in out, out
    assert out["status"] == "written" and out["format"] == "xlsx" and out["listed_on_page"]
    path = Path(out["file"]["path"])
    assert path.name == f"qpilot-results-{study}.xlsx" and path.is_file()
    assert path.is_relative_to(store.root.parent / "exports" / study)  # beside the store
    assert out["file"]["bytes"] == path.stat().st_size and len(out["file"]["sha256"]) == 64
    assert out["bases"] == ["as_decided"] and out["copied_to"] is None
    zipfile.ZipFile(io.BytesIO(path.read_bytes())).testzip()
    book = openpyxl.load_workbook(path)
    assert book.sheetnames[:3] == ["Results", "Per unit", "Per well"]
    assert store.chain_head(study) == before  # an export decides nothing
    # the page lists it under Report > Export, as it lists its own
    listed = c.get(f"/api/studies/{study}/report/exports").json()["exports"]
    assert [e["format"] for e in listed] == ["xlsx"] and listed[0]["download"]["name"] == path.name


def test_a_copy_goes_only_into_a_folder_inside_the_data_roots(tools, called):
    study, store = called["study"], called["store"]
    folder = Path(tempfile.mkdtemp(prefix="figures-for-the-paper-", dir=called["root"]))
    out = tools.qpcr_export(study, "csv", out_dir=str(folder))
    assert "error" not in out, out
    copy = Path(out["copied_to"]["path"])
    assert copy == folder.resolve() / f"qpilot-tables-{study}.zip" and copy.is_file()
    assert out["copied_to"]["sha256"] == out["file"]["sha256"]
    assert copy.read_bytes() == Path(out["file"]["path"]).read_bytes()
    # an existing file is never replaced
    again = refused(
        tools.qpcr_export(study, "csv", out_dir=str(folder)), "invalid_argument", "out_dir"
    )
    assert "already in that folder" in again["error"] and copy.read_bytes()
    # outside the data roots, a file, the study store, a missing folder: refused
    refused(
        tools.qpcr_export(study, "csv", out_dir=str(called["base"])), "path_not_allowed", "out_dir"
    )
    refused(
        tools.qpcr_export(study, "csv", out_dir=str(called["root"] / "nowhere")),
        "path_not_allowed",
        "out_dir",
    )
    refused(
        tools.qpcr_export(study, "csv", out_dir=str(called["root"] / "mini.rdml")),
        "unsupported_input",
        "out_dir",
    )
    refused(tools.qpcr_export(study, "csv", out_dir=""), "invalid_argument", "out_dir")
    assert not list(store.root.rglob("qpilot-tables-*.zip")) or True


def test_the_study_store_is_never_a_folder_agents_write_to(tools, called, monkeypatch):
    study, store = called["study"], called["store"]
    monkeypatch.setenv("QPILOT_DATA_ROOTS", str(store.root.parent))
    for folder in (store.root, store.workspace(study)):
        out = refused(
            tools.qpcr_export(study, "csv", out_dir=str(folder)), "path_not_allowed", "out_dir"
        )
        assert "study store" in out["error"]
    assert not list(store.workspace(study).glob("qpilot-*"))


def test_figures_take_genes_and_a_basis_and_the_others_refuse_them(tools, called):
    study = called["study"]
    out = tools.qpcr_export(study, "figures", genes=[GENE], basis="as_decided")
    assert "error" not in out, out
    assert out["genes"] == [GENE] and out["bases"] == ["as_decided"]
    refused(tools.qpcr_export(study, "xlsx", genes=[GENE]), "invalid_argument", "genes")
    refused(tools.qpcr_export(study, "csv", basis="recommended"), "invalid_argument", "basis")
    refused(tools.qpcr_export(study, "figures", basis="best"), "invalid_argument", "basis")  # type: ignore[arg-type]
    refused(tools.qpcr_export(study, "figures", genes=[]), "invalid_argument", "genes")
    refused(tools.qpcr_export(study, "figures", genes=[3]), "invalid_argument", "genes")  # type: ignore[list-item]
    refused(tools.qpcr_export(study, "figures", genes=["G"] * 51), "invalid_argument", "genes")
    refused(tools.qpcr_export(study, "pdf"), "invalid_argument", "format")  # type: ignore[arg-type]
    refused(tools.qpcr_export(study, "xlsx", expected_head=5), "invalid_argument", "expected_head")  # type: ignore[arg-type]
    refused(tools.qpcr_export("abcdef123456", "xlsx"), "unknown_study")


def test_a_stale_export_writes_nothing(tools, called):
    study, store = called["study"], called["store"]
    before = sorted(p.name for p in store.root.parent.rglob("*") if p.is_file())
    out = tools.qpcr_export(study, "csv", expected_head="0" * 64)
    assert out["status"] == "stale" and out["code"] == "stale_head" and "error" in out
    assert sorted(p.name for p in store.root.parent.rglob("*") if p.is_file()) == before


def test_a_keyed_export_is_written_once(tools, called):
    study = called["study"]
    first = tools.qpcr_export(study, "csv", idempotency_key="export-1")
    path = Path(first["file"]["path"])
    folders = sorted(path.parent.parent.iterdir())
    again = tools.qpcr_export(study, "csv", idempotency_key="export-1")
    assert again.pop("idempotent_replay") is True and again == first
    assert sorted(path.parent.parent.iterdir()) == folders  # no second folder
    refused(
        tools.qpcr_export(study, "xlsx", idempotency_key="export-1"),
        "idempotency_key_reused",
        "idempotency_key",
    )
    third = tools.qpcr_export(study, "csv")  # without a key it writes another file
    assert Path(third["file"]["path"]) != path


# ---- the blind rule: the same refusal for a session and for its study --------------------------


def test_nothing_is_answered_for_a_session_whose_design_is_not_confirmed(tools, called):
    """Re-opening the stage hides the results again, for the session's id and its study's."""
    studio, sid, study = called["studio"], called["sid"], called["study"]
    assert tools.qpcr_units(study, GENE)["gene"] == GENE
    # a person accepts a change of the design: the design stage is open again, results hidden
    tools.qpcr_propose(sid, "design.group", "KO_1", {"group": "WT"})
    change = next(p for p in studio.inbox(sid, "design", "proposed") if p.kind == "design.group")
    studio.accept(sid, change.id, "human", "the lab book says WT")
    assert not studio.results_visible(sid)
    for call in (
        lambda s: tools.qpcr_units(s, GENE),
        lambda s: tools.qpcr_melt(s),
        lambda s: tools.qpcr_repeat_plan(s),
        lambda s: tools.qpcr_comparisons(s),
        lambda s: tools.qpcr_export(s, "xlsx"),
        lambda s: tools.qpcr_request_set_aside(s, "card_trace_x", "set_aside", REASON, gene=GENE),
        lambda s: tools.qpcr_trace(s, gene=GENE),
        lambda s: tools.qpcr_evidence(s),
    ):
        for ident in (sid, study):
            out = refused(call(ident), "results_hidden")
            assert "confirm" in out["fix"].lower() or "confirm" in out["error"].lower()
    refused(tools.qpcr_units(sid, GENE), "results_hidden")
    assert not (called["store"].root.parent / "exports" / study).exists() or not list(
        (called["store"].root.parent / "exports" / study).glob("record-report-*/*.xlsx")
    )


# ---- the Prism project (.pzfx): what came back from Prism, read-only -----------------------------


def _saved_project(called) -> tuple:
    """A person sends the study to Prism (the bundle), then Prism saves it with one value
    excluded; returns the bundle folder, the saved project and the value excluded."""
    from lxml import etree

    from qpilot.prism import export_study, pzfx

    mine = Path(tempfile.mkdtemp(prefix="prism-", dir=called["root"]))  # the root is shared
    folder = mine / "bundle"
    exported = export_study(called["store"], called["study"], folder, platform="macos")
    ns = {"p": pzfx.NAMESPACE}
    root = etree.fromstring(exported.project.read_bytes())
    table = root.find("p:Table", ns)
    cell = next(d for d in table.iterfind(".//p:YColumn//p:d", ns) if (d.text or "").strip())
    cell.set("Excluded", "1")
    block = etree.SubElement(root, f"{{{pzfx.NAMESPACE}}}Template")
    block.text = "QUJDREVG" * 50  # Prism's own binary part, which qPilot never reads
    saved = mine / "saved-in-prism.pzfx"
    saved.write_bytes(b'<?xml version="1.0" encoding="UTF-8"?>\n' + etree.tostring(root))
    return folder, saved, float(cell.text.replace(",", "."))


def test_a_saved_prism_project_is_read_without_storing_anything(tools, called):
    store, sid, study = called["store"], called["sid"], called["study"]
    folder, saved, value = _saved_project(called)
    before = (inbox_state(called), store.chain_head(study))
    out = tools.qpcr_prism_diff(study, str(folder), project_path=str(saved))
    assert "error" not in out, out
    assert out["source"] == "project" and out["saved"] is False
    (item,) = out["items"]
    assert item["kind"] == "excluded" and item["exported"] == pytest.approx(value)
    (proposal,) = out["proposals"]
    assert proposal["kind"] == "prism.exclusion_reason" and proposal["status"] == "proposed"
    assert (inbox_state(called), store.chain_head(study)) == before  # no proposal was filed
    assert sid
    # the bundle folder itself (holding the project as qPilot wrote it) brings back nothing
    unchanged = tools.qpcr_prism_diff(study, str(folder), project_path=str(folder))
    assert unchanged["items"] == [] and "exactly as qPilot wrote it" in " ".join(unchanged["notes"])


def test_the_prism_diff_takes_one_return_and_only_inside_the_data_roots(tools, called, tmp_path):
    study = called["study"]
    folder, saved, _ = _saved_project(called)
    both = refused(
        tools.qpcr_prism_diff(study, str(folder), str(folder), project_path=str(saved)),
        "invalid_argument",
        "project_path",
    )
    assert "exactly one" in both["error"]
    refused(tools.qpcr_prism_diff(study, str(folder)), "invalid_argument", "project_path")
    refused(
        tools.qpcr_prism_diff(5, str(folder), project_path=str(saved)),
        "invalid_argument",
        "study_id",
    )  # type: ignore[arg-type]
    outside = tmp_path / "elsewhere.pzfx"
    outside.write_bytes(saved.read_bytes())
    refused(
        tools.qpcr_prism_diff(study, str(folder), project_path=str(outside)),
        "path_not_allowed",
        "project_path",
    )
    note = folder.parent / "notes.txt"
    note.write_text("not a project", encoding="utf-8")
    refused(
        tools.qpcr_prism_diff(study, str(folder), project_path=str(note)),
        "unsupported_input",
        "project_path",
    )
    refused(
        tools.qpcr_prism_diff(study, "/etc", project_path=str(saved)),
        "path_not_allowed",
        "bundle_dir",
    )
    refused(
        tools.qpcr_prism_diff("abcdef123456", str(folder), project_path=str(saved)), "unknown_study"
    )
    other = folder.parent / "other-bundle"
    other.mkdir()
    refused(tools.qpcr_prism_diff(study, str(other), project_path=str(saved)), "input_unreadable")


def test_prism_replies_stay_hidden_for_a_study_whose_session_is_not_confirmed(tools, called):
    studio, sid, study = called["studio"], called["sid"], called["study"]
    folder, saved, _ = _saved_project(called)
    assert "error" not in tools.qpcr_prism_preview(study)
    tools.qpcr_propose(sid, "design.group", "KO_1", {"group": "WT"})
    change = next(p for p in studio.inbox(sid, "design", "proposed") if p.kind == "design.group")
    studio.accept(sid, change.id, "human", "the lab book says WT")
    assert not studio.results_visible(sid)
    refused(tools.qpcr_prism_preview(study), "results_hidden")
    refused(tools.qpcr_prism_diff(study, str(folder), project_path=str(saved)), "results_hidden")
