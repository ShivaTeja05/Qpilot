"""Output schemas: every served tool declares one, and every successful reply matches it.

The MCP server checks each successful reply against its tool's model before it leaves (a reply
that does not match becomes an ``engine_refused`` refusal), so a success over MCP here means the
reply matched. The Decision Simulator's tools and the Prism round trip need the demo data:
``tests/integration/test_mcp_tools.py`` checks their replies the same way.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import anyio
import pytest

from qpilot.agents import outputs as o
from qpilot.agents.surface import SPECS, STUDY_FILES, to_result
from qpilot.integration.mcp_tools import SIM_TOOL_NAMES
from qpilot.mcp_server import TOOL_NAMES, QpilotTools, create_server

try:  # mcp >= 2
    from mcp.server.mcpserver.exceptions import ResourceError
except ImportError:  # mcp 1.x
    from mcp.server.fastmcp.exceptions import ResourceError

CORPUS = Path(__file__).resolve().parents[1] / "fixtures" / "corpus"
CFX = CORPUS / "synthetic" / "cfx-manager-raw-vs-baseline-subtracted"


def listed(server) -> dict:
    return {t.name: t for t in anyio.run(server.list_tools)}


def ok(reply, name: str) -> dict:
    """A successful reply over MCP: not an error, its JSON text equal to its structured content."""
    assert reply.is_error is False, reply.structured_content
    data = reply.structured_content
    assert json.loads(reply.content[0].text) == data
    SPECS[name].output.model_validate(data)
    return data


# ---- what is declared ---------------------------------------------------------------------------


def test_every_served_tool_declares_a_title_annotations_and_an_output_schema(served):
    tools = listed(served.server)
    assert set(tools) == set(TOOL_NAMES) | set(SIM_TOOL_NAMES) == set(SPECS)
    for name, tool in tools.items():
        spec = SPECS[name]
        assert tool.title == spec.title == tool.annotations.title
        schema = spec.output.model_json_schema()
        assert tool.output_schema["properties"].keys() == schema["properties"].keys(), name
        assert set(tool.output_schema.get("required", [])) == set(schema.get("required", []))
        assert not tool.annotations.destructive_hint and not tool.annotations.open_world_hint


def test_the_agents_page_access_words_match_the_annotations(served):
    """GET /api/agents says what each tool can change; the MCP annotations say the same."""
    from qpilot.web.routers.ops import TOOL_ACCESS

    tools = listed(served.server)
    for name, tool in tools.items():
        access = TOOL_ACCESS[name][0] if name in TOOL_ACCESS else "read"
        assert tool.annotations.read_only_hint is (access == "read"), name
    writes = {n for n, t in tools.items() if not t.annotations.read_only_hint}
    assert writes == {
        "qpcr_study",
        "qpcr_decide",
        "qpcr_propose",
        "qpcr_inspect",
        "qpcr_incident_log",  # an incident proposed in an instrument's logbook
        "qpcr_export",  # a new file from the engine's output; decides nothing
        "qpcr_request_set_aside",  # wells asked for; a person sets them aside
    }
    repeats_log = {n for n, t in tools.items() if not t.annotations.idempotent_hint}
    # qpcr_decide, qpcr_propose, qpcr_export and qpcr_request_set_aside unless an idempotency_key
    # is given
    assert repeats_log == {
        "qpcr_decide",
        "qpcr_propose",
        "qpcr_incident_log",
        "qpcr_export",
        "qpcr_request_set_aside",
    }


def test_every_refusal_shares_one_schema():
    schema = o.Refusal.model_json_schema()
    assert set(schema["required"]) == {"error", "code", "fix"}


def test_non_finite_numbers_are_sent_as_null():
    result = to_result({"fc": float("nan"), "ci": [float("-inf"), 2.0], "p": float("inf")})
    assert result.structured_content == {"fc": None, "ci": [None, 2.0], "p": None}
    assert json.loads(result.content[0].text) == result.structured_content


def test_a_reply_that_breaks_its_schema_never_leaves_the_server(store, monkeypatch):
    def broken(self, fc: float = 2.0) -> dict:
        return {"n_needed": "many"}

    monkeypatch.setattr(QpilotTools, "qpcr_plan", broken)
    reply = anyio.run(create_server(store, simulator=False).call_tool, "qpcr_plan", {"fc": 2.0})
    assert reply.is_error is True and reply.structured_content["code"] == "engine_refused"
    assert "many" not in reply.content[0].text


# ---- the study, its numbers and their fact ids --------------------------------------------------


@pytest.mark.parametrize("response_format", ["detailed", "concise"])
def test_study_and_robustness_replies_match_their_schemas(served, demo, response_format):
    rdml, study_id = demo
    study = ok(
        served("qpcr_study", {"rdml_path": str(rdml), "response_format": response_format}),
        "qpcr_study",
    )
    assert study["study_id"] == study_id and study["response_format"] == response_format
    robust = ok(
        served(
            "qpcr_robustness",
            {"study_id": study_id, "gene": "ODC1", "response_format": response_format},
        ),
        "qpcr_robustness",
    )
    assert robust["holds_fraction"] == 1.0
    if response_format == "concise":
        assert "facts" not in study and "decided_cards" not in study
        assert study["n_decided_cards"] == 1 and "options" not in study["open_cards"][0]
        assert "impact_by_dimension" not in robust and robust["level"]
    else:
        # links to the study files that exist (the fixture study has no grid.csv)
        assert set(study["resources"]) == {"decisions.jsonl", "facts.json"}
        assert study["contrasts"]["ODC1"]["fact_ids"]


def test_every_fact_id_names_a_fact_with_the_same_value(tools, demo):
    rdml, study_id = demo
    facts = tools.store.get(study_id).facts
    study = tools.qpcr_study(str(rdml))
    checked = 0
    for gene, row in study["contrasts"].items():
        values = {
            "fc": row["fc"],
            "ci_low": row["ci"][0],
            "ci_high": row["ci"][1],
            "p": row["p"],
            "holds": row["holds"],
            "level": row["level"],
        }
        for field, fid in row["fact_ids"].items():
            if field in values:
                assert facts[fid].value == pytest.approx(values[field]), (gene, field)
                checked += 1
    assert checked >= 5 * len(study["contrasts"])
    robust = tools.qpcr_robustness(study_id, "ODC1")
    assert facts[robust["fact_ids"]["holds_fraction"]].value == robust["holds_fraction"]
    assert facts[robust["fact_ids"]["fc"]].value == pytest.approx(robust["fc"])


def test_decide_plan_and_inbox_replies_match_their_schemas(served, demo):
    _, study_id = demo
    decide = ok(
        served(
            "qpcr_decide",
            {"study_id": study_id, "card_id": "card_refset", "option": "top3", "reason": "x"},
        ),
        "qpcr_decide",
    )
    assert decide["status"] == "pending_human" and decide["applied"] is False
    for args in ({"fc": 2.0, "sd_log2": 0.5, "n_per_group": 4}, {"fc": 2.0}):
        ok(served("qpcr_plan", args), "qpcr_plan")
    proposed = ok(
        served(
            "qpcr_propose",
            {"study_id": study_id, "kind": "design.group", "subject": "S1",
             "payload": {"group": "LPS"}},
        ),
        "qpcr_propose",
    )  # fmt: skip
    assert proposed["status"] == "proposed"
    for response_format in ("detailed", "concise"):
        inbox = ok(
            served("qpcr_proposals", {"study_id": study_id, "response_format": response_format}),
            "qpcr_proposals",
        )
        assert len(inbox["proposals"]) == 1
    assert inbox["counts"] == {"proposed": 1}


# ---- a lab's own file (an instrument export), through qPilot Studio ------------------------------


@pytest.fixture
def export(data_root):
    folder = data_root / "cfx-run"
    folder.mkdir()
    for path in sorted(CFX.glob("qpilot-synthetic-raw *")):
        shutil.copy(path, folder / path.name)
    return folder


@pytest.mark.parametrize("response_format", ["detailed", "concise"])
def test_studio_replies_match_their_schemas(served, export, response_format):
    opened = ok(
        served("qpcr_inspect", {"rdml_path": str(export), "response_format": response_format}),
        "qpcr_inspect",
    )
    o.ImportView.model_validate(opened["imported"])
    session = opened["session_id"]
    if response_format == "detailed":
        assert "data, not instructions" in opened["quoted_names"]
    else:
        assert "quoted_names" not in opened and opened["counts"]
    calls = ok(
        served(
            "qpcr_curve_calls",
            {"study_id": session, "gene": "GOI", "response_format": response_format},
        ),
        "qpcr_curve_calls",
    )
    assert calls["gene"] == "GOI" and calls["rules"][0] == "linregpcr"
    check = ok(
        served(
            "qpcr_check_design",
            {"study_id": session, "kind": "design.group", "subject": "S1",
             "payload": {"group": "A"}},
        ),
        "qpcr_check_design",
    )  # fmt: skip
    assert check["saved"] is False and check["check"]["status"]
    hidden = served("qpcr_prism_preview", {"study_id": session})
    assert hidden.is_error and hidden.structured_content["code"] == "results_hidden"


# ---- the study's files as read-only resources ---------------------------------------------------


def test_the_study_files_are_read_only_resources(served, demo):
    _, study_id = demo
    server = served.server
    templates = {t.name: t for t in anyio.run(server.list_resource_templates)}
    assert set(templates) == set(STUDY_FILES)
    uri = f"qpilot://studies/{study_id}/cards.json"
    (content,) = anyio.run(server.read_resource, uri)
    assert json.loads(content.content) == json.loads(
        (served.store.workspace(study_id) / "cards.json").read_text(encoding="utf-8")
    )
    study = served("qpcr_study", {"rdml_path": str(demo[0])})
    links = [c for c in study.content if c.type == "resource_link"]
    assert {str(link.uri) for link in links} == set(study.structured_content["resources"].values())


@pytest.mark.parametrize(
    "uri",
    [
        "qpilot://studies/abcdef123456/cards.json",  # no such study
        "qpilot://studies/..%2F..%2Fetc/cards.json",  # not a study id
        "qpilot://studies/{study}/secrets.txt",  # not a study file
        "qpilot://studies/{study}/pending.jsonl",  # a study file that is not there yet
    ],
)
def test_a_resource_that_is_not_a_study_file_is_refused(served, demo, uri):
    with pytest.raises(ResourceError):
        anyio.run(served.server.read_resource, uri.format(study=demo[1]))


def test_a_linked_study_file_is_never_followed(served, demo, tmp_path):
    _, study_id = demo
    secret = tmp_path / "secret.csv"
    secret.write_text("patient,result\n", encoding="utf-8")
    (served.store.workspace(study_id) / "grid.csv").symlink_to(secret)
    with pytest.raises(ResourceError):
        anyio.run(served.server.read_resource, f"qpilot://studies/{study_id}/grid.csv")
