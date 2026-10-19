"""How qPilot's tools are served over MCP: titles, annotations, output schemas, results, resources.

The tools themselves are plain methods that return JSON-ready dicts (``QpilotTools``,
``SimulatorTools``); the app's model and the harness call them directly. This module is the MCP
layer on top, the protocol's "cheap half":

- a ``title`` and honest annotations on every tool (:data:`SPECS`);
- an ``outputSchema`` (:mod:`qpilot.agents.outputs`) and ``structuredContent`` on every reply,
  paired with the same JSON as text, validated before it leaves the server;
- ``isError: true`` with a typed ``code`` and ``fix`` on every refusal
  (:mod:`qpilot.agents.refusals`), including arguments that fail the input schema;
- ``resource_link`` blocks to the study's files instead of large inline tables, and the files
  themselves as read-only resources (``qpilot://studies/<study_id>/<file>``).

Calls stay blocking (no MCP Tasks).
"""

from __future__ import annotations

import inspect
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated, Any

from mcp.types import CallToolResult, ResourceLink, TextContent, ToolAnnotations
from pydantic import BaseModel

from qpilot.agents import outputs as o
from qpilot.agents.refusals import Code, is_error, refuse
from qpilot.agents.views import json_safe

log = logging.getLogger(__name__)

RESOURCE_SCHEME = "qpilot://studies/{study_id}/{name}"
MAX_RESOURCE_BYTES = 64 * 1024 * 1024
# the study files an agent may read as resources: fixed names inside the study's workspace
STUDY_FILES = {
    "results.json": ("application/json", "Every result of the study, as the engine wrote it."),
    "cards.json": ("application/json", "The Decision Cards with their decision state."),
    "facts.json": ("application/json", "Every fact id with its value, format and unit."),
    "decisions.jsonl": ("application/x-ndjson", "The hash-chained decision log, oldest first."),
    "pending.jsonl": ("application/x-ndjson", "Agent requests waiting for a person."),
    "grid.csv": ("text/csv", "Every reasonable analysis (grid cell) and each gene's result."),
}


@dataclass(frozen=True)
class ToolSpec:
    """How one tool is presented over MCP."""

    title: str
    output: type[BaseModel]
    read_only: bool
    destructive: bool = False
    idempotent: bool = True
    open_world: bool = False
    links: tuple[str, ...] = ()  # study files linked from a successful reply

    def annotations(self) -> ToolAnnotations:
        """The MCP annotations of this tool."""
        return ToolAnnotations(
            title=self.title,
            read_only_hint=self.read_only,
            destructive_hint=self.destructive,
            idempotent_hint=self.idempotent,
            open_world_hint=self.open_world,
        )


def _read(title: str, output: type[BaseModel]) -> ToolSpec:
    return ToolSpec(title=title, output=output, read_only=True)


SPECS: dict[str, ToolSpec] = {
    # Analyses (or reopens) a study: writes its workspace and the system's first log entries,
    # so it is not read-only; calling it again changes nothing more.
    "qpcr_study": ToolSpec(
        "Analyse a qPCR study",
        o.StudyOut,
        read_only=False,
        links=("grid.csv", "decisions.jsonl", "facts.json"),
    ),
    "qpcr_robustness": _read("How robust is a gene's conclusion", o.RobustnessOut),
    # Appends a request (or, where allowed, a decision that changes no conclusion) to the log.
    # Never destructive: nothing is overwritten, and a person can decide again. A repeat without
    # an idempotency_key logs again, so it is not idempotent.
    "qpcr_decide": ToolSpec(
        "Ask to decide a Decision Card",
        o.DecideOut,
        read_only=False,
        idempotent=False,
        links=("decisions.jsonl",),
    ),
    "qpcr_plan": _read("Plan samples per group", o.PlanOut),
    "qpcr_propose": ToolSpec(
        "Propose a design item for a person", o.ProposeOut, read_only=False, idempotent=False
    ),
    "qpcr_proposals": _read("Read the Studio inbox", o.ProposalsOut),
    # Opens (or reopens) the Studio session of a file: writes the session's source and quarantine.
    "qpcr_inspect": ToolSpec("Inspect a lab's qPCR file", o.InspectOut, read_only=False),
    "qpcr_check_design": _read("Check a would-be proposal", o.CheckDesignOut),
    "qpcr_curve_calls": _read("Compare amplification calls per well", o.CurveCallsOut),
    "qpcr_prism_preview": _read("Preview Send to Prism", o.PrismPreviewOut),
    "qpcr_prism_diff": _read("Diff a Prism round trip", o.PrismDiffOut),
    "sim_audit": _read("Read the Decision Simulator audit", o.SimAuditOut),
    "sim_gene": _read("Read one gene in the audit", o.SimGeneOut),
    "sim_whatif": _read("Recompute under other choices", o.SimWhatifOut),
    "sim_decisions": _read("List the audited decisions", o.SimDecisionsOut),
    "sim_findings": _read("Page through audit findings", o.SimFindingsOut),
}


def resource_uri(study_id: str, name: str) -> str:
    """The MCP resource URI of one study file."""
    return RESOURCE_SCHEME.format(study_id=study_id, name=name)


def study_links(store: Any, study_id: str, names: tuple[str, ...]) -> list[ResourceLink]:
    """``resource_link`` blocks for the study files that exist (none for an unknown study)."""
    try:
        workspace = store.workspace(study_id)
    except Exception:  # an unknown study has no files to link
        return []
    links = []
    for name in names:
        path = workspace / name
        if path.is_file():
            mime, description = STUDY_FILES[name]
            links.append(
                ResourceLink(
                    type="resource_link",
                    uri=resource_uri(study_id, name),
                    name=name,
                    description=description,
                    mime_type=mime,
                    size=path.stat().st_size,
                )
            )
    return links


def to_result(out: dict[str, Any], links: list[ResourceLink] | None = None) -> CallToolResult:
    """A reply as an MCP result: the JSON as text and as structured content, plus links."""
    data = json_safe(out)
    text = json.dumps(data, ensure_ascii=False, allow_nan=False)
    failed = is_error(data)
    content: list[Any] = [TextContent(type="text", text=text)]
    if not failed:
        content += links or []
    return CallToolResult(content=content, structured_content=data, is_error=failed)


def mcp_tool(name: str, method: Callable[..., dict[str, Any]], store: Callable[[], Any]) -> Any:
    """``method`` as an MCP tool: same arguments, a typed result, links to the study's files."""
    spec = SPECS[name]
    signature = inspect.signature(method, eval_str=True)

    def tool(**kwargs: Any) -> CallToolResult:
        out = method(**kwargs)
        links: list[ResourceLink] = []
        if spec.links and not is_error(out):
            study_id = out.get("study_id") or kwargs.get("study_id")
            card = out.get("card")
            if not study_id and isinstance(card, dict):
                study_id = kwargs.get("study_id")
            if isinstance(study_id, str):
                links = study_links(store(), study_id, spec.links)
                if links and "study_id" in out and out.get("response_format") == "detailed":
                    out = {**out, "resources": {link.name: str(link.uri) for link in links}}
        return to_result(out, links)

    tool.__name__ = name
    tool.__doc__ = method.__doc__
    tool.__signature__ = signature.replace(  # type: ignore[attr-defined]
        return_annotation=Annotated[CallToolResult, spec.output]
    )
    return tool


def input_refusal(name: str, error: Exception) -> CallToolResult:
    """A typed refusal for arguments that fail the input schema (field names only, no values)."""
    fields = sorted(
        {".".join(str(p) for p in e.get("loc", ())) or "arguments" for e in error.errors()}  # type: ignore[attr-defined]
    )
    out = refuse(
        Code.INVALID_ARGUMENT,
        f"arguments of {name} do not match its input schema: " + ", ".join(fields),
        fields=fields,
    )
    return to_result(out)


def crash_refusal(name: str) -> CallToolResult:
    """A typed refusal for a tool that failed unexpectedly (the details stay in the server log)."""
    out = refuse(Code.ENGINE_REFUSED, f"{name} failed unexpectedly; see the qPilot server log")
    return to_result(out)


def register(server: Any, owners: dict[str, Any], store: Callable[[], Any]) -> None:
    """Register every tool in ``owners`` (name -> object with that method) with its spec."""
    for name, owner in owners.items():
        spec = SPECS[name]
        server.add_tool(
            mcp_tool(name, getattr(owner, name), store),
            name=name,
            title=spec.title,
            annotations=spec.annotations(),
            structured_output=True,
        )


def register_resources(server: Any, store: Callable[[], Any]) -> None:
    """Serve each study file in :data:`STUDY_FILES` as a read-only resource template."""
    for name, (mime, description) in STUDY_FILES.items():

        def read(study_id: str, _name: str = name) -> str:
            workspace = store().workspace(study_id)  # the store checks the id (hex only)
            path = workspace / _name
            if path.is_symlink() or not path.is_file():
                raise FileNotFoundError(f"this study has no {_name}")
            if path.stat().st_size > MAX_RESOURCE_BYTES:
                raise ValueError(f"{_name} is too large to serve")
            return path.read_text(encoding="utf-8")

        read.__name__ = "study_" + name.replace(".", "_")
        server.resource(
            RESOURCE_SCHEME.replace("{name}", name),
            name=name,
            title=name,
            description=description,
            mime_type=mime,
        )(read)


__all__ = [
    "SPECS",
    "STUDY_FILES",
    "ToolSpec",
    "crash_refusal",
    "input_refusal",
    "mcp_tool",
    "register",
    "register_resources",
    "resource_uri",
    "study_links",
    "to_result",
]
