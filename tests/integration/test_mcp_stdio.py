"""The integrated MCP server over a real stdio connection, as an agent would use it (demo data)."""

from __future__ import annotations

import json
import os
import shutil
import sys

import anyio
import pytest

from qpilot.integration.mcp_tools import SIM_TOOL_NAMES, default_audit_dir
from qpilot.mcp_server import TOOL_NAMES

pytestmark = pytest.mark.demo_data


def test_an_agent_over_stdio_reads_the_audit_and_cannot_decide(workflow):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    store, report = workflow["store"], workflow["report"]
    study = report.study_id
    # where `python -m qpilot.integration audit` writes, so the served process finds it
    shutil.copytree(report.paths["simulator_audit"], default_audit_dir(store, study))
    env = {**os.environ, "QPILOT_STUDIES_DIR": str(store.root)}
    params = StdioServerParameters(
        command=sys.executable, args=["-m", "qpilot.integration", "serve"], env=env
    )

    async def call(session, name, args):
        result = await session.call_tool(name, args)
        failed = result.is_error if hasattr(result, "is_error") else result.isError
        assert not failed, result
        return json.loads(result.content[0].text)

    async def scenario():
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                listed = await session.list_tools()
                assert {t.name for t in listed.tools} == set(TOOL_NAMES) | set(SIM_TOOL_NAMES)
                audit = await call(session, "sim_audit", {"study_id": study})
                assert audit["analyses"] == 90_396 and audit["reproduces_qpilot"]["ok"]
                whatif = await call(
                    session, "sim_whatif", {"study_id": study, "changes": {"refs": "HMBS"}}
                )
                assert "NM23A" in whatif["calls_that_change"]
                decide = await call(
                    session,
                    "qpcr_decide",
                    {"study_id": study, "card_id": "card_refset", "option": "top3", "reason": "x"},
                )
                assert decide["status"] in ("pending_human", "stale")

    before = store.card(study, "card_refset")
    anyio.run(scenario)
    after = store.card(study, "card_refset")
    assert (after.decision, after.decided_by) == (before.decision, before.decided_by)
    assert all(card.decided_by != "agent" for card in store.cards(study))


def test_qpilot_serve_is_the_one_server_with_the_simulator_tools(workflow):
    """`python -m qpilot.mcp_server` (what `qpilot serve` runs) serves sim_* when qsim imports."""
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    store, report = workflow["store"], workflow["report"]
    study = report.study_id
    target = default_audit_dir(store, study)
    if not target.exists():
        shutil.copytree(report.paths["simulator_audit"], target)
    env = {**os.environ, "QPILOT_STUDIES_DIR": str(store.root)}
    params = StdioServerParameters(
        command=sys.executable, args=["-m", "qpilot.mcp_server"], env=env
    )

    async def call(session, name, args):
        result = await session.call_tool(name, args)
        failed = result.is_error if hasattr(result, "is_error") else result.isError
        assert not failed, result
        return json.loads(result.content[0].text)

    async def scenario():
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                init = await session.initialize()
                assert "sim_findings" in (init.instructions or "")
                listed = await session.list_tools()
                assert [t.name for t in listed.tools] == list(TOOL_NAMES + SIM_TOOL_NAMES)
                audit = await call(session, "sim_audit", {"study_id": study})
                assert audit["reproduces_qpilot"]["ok"]
                page = await call(
                    session, "sim_findings", {"study_id": study, "table": "issues", "limit": 3}
                )
                assert len(page["rows"]) == 3 and page["next_offset"] == 3
                flips = await call(
                    session, "sim_findings", {"study_id": study, "table": "one_sample_flips"}
                )
                assert flips["total"] >= 1

    anyio.run(scenario)
