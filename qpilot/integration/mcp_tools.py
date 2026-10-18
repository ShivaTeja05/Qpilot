"""The Decision Simulator for agents: read-only MCP tools beside qPilot's own.

:func:`create_server` builds qPilot's MCP server (every tool in
:data:`qpilot.mcp_server.TOOL_NAMES`, unchanged) and adds the simulator's tools. None of them can
decide, accept, apply or export anything: they read an audit that was already written, or run a
what-if through the engine without storing it.

Where audits are found, in order: the ``audits`` mapping given to :func:`create_server`
(``{"simulator_audit": path, ...}`` as the workflow reports them, or ``{study_id: path}``), then
``<study store>/simulator_audits/<study_id>/`` (where ``python -m qpilot.integration audit`` writes
by default). An audit is served only when it verifies (:func:`verify_audit`) and is the study's.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from qpilot.core.store import StudyNotFound, StudyStore

SIM_TOOL_NAMES = ("sim_audit", "sim_gene", "sim_whatif", "sim_decisions")
SIM_INSTRUCTIONS = (
    " The sim_* tools read the Decision Simulator's audit of a study: every combination of eight "
    "analysis decisions (efficiency, flagged wells, late Cq, non-detects, control genes, cut-off, "
    "test, multiple testing), per-gene verdicts and what a call leans on. sim_whatif recomputes "
    "any combination of choices without storing anything. They are read-only; choices are still "
    "made by a person on the Decision Cards."
)
MAX_GENES = 100
AUDITS_FOLDER = "simulator_audits"


def default_audit_dir(store: StudyStore, study_id: str) -> Path:
    """Where ``python -m qpilot.integration audit`` writes a study's audit by default."""
    return Path(store.root) / AUDITS_FOLDER / study_id


class SimulatorTools:
    """The simulator's tools as plain methods (each returns a JSON-ready dict)."""

    def __init__(
        self, store: StudyStore | None = None, audits: Mapping[str, str] | None = None
    ) -> None:
        self._store = store
        self._audits = dict(audits or {})
        self._prepared: dict[str, Any] = {}
        self._lock = threading.Lock()  # the simulator's engine caches stages; one call at a time

    @property
    def store(self) -> StudyStore:
        """The study store (from ``QPILOT_STUDIES_DIR`` on first use)."""
        if self._store is None:
            self._store = StudyStore()
        return self._store

    # ---- finding and checking an audit ---------------------------------------------------------

    def _audit_dir(self, study_id: str) -> tuple[Path | None, str | None]:
        from qpilot.integration.simulator import MANIFEST, verify_audit

        candidates = [Path(p) for p in self._audits.values()]
        if study_id in self._audits:
            candidates.insert(0, Path(self._audits[study_id]))
        candidates.append(default_audit_dir(self.store, study_id))
        for folder in candidates:
            manifest = folder / MANIFEST
            if not manifest.exists():
                continue
            data = json.loads(manifest.read_text(encoding="utf-8"))
            if data.get("study_id") != study_id:
                continue
            check = verify_audit(folder)
            if not check.ok:
                return None, f"the audit of this study does not verify: {check.summary()}"
            return folder, None
        return None, "no simulator audit for this study; a person runs it after the choices stage"

    def _study(self, study_id: str) -> str | None:
        try:
            self.store.get(study_id)
        except (StudyNotFound, KeyError, FileNotFoundError):
            return "unknown study_id; call qpcr_study first"
        return None

    # ---- the tools -----------------------------------------------------------------------------

    def sim_audit(self, study_id: str) -> dict[str, Any]:
        """The audit of a study: verdict counts, scope, the reproduction check, what to lock.

        Verdicts: solid, holds with caveats, depends on your choices, fragile, check data first,
        no call. ``reproduces_qpilot`` says the simulator's baseline equals qPilot's result.
        """
        error = self._study(study_id)
        if error:
            return {"error": error}
        folder, error = self._audit_dir(study_id)
        if folder is None:
            return {"error": error}
        from qpilot.integration.simulator import MANIFEST

        manifest = json.loads((folder / MANIFEST).read_text(encoding="utf-8"))
        summary = json.loads((folder / "summary.json").read_text(encoding="utf-8"))
        return {
            "study_id": study_id,
            "analyses": manifest.get("analyses"),
            "verdict_counts": manifest.get("verdict_counts"),
            "verdict_rules": summary.get("verdicts", {}).get("rules"),
            "scope": manifest.get("scope"),
            "reproduces_qpilot": manifest.get("reproduces_qpilot"),
            "lock_sha256": manifest.get("lock_sha256"),
            "lock_in_advance_to_protect_called_genes": summary.get("lock_advisor", {}).get(
                "called_defensible"
            ),
            "your_choices": manifest.get("your_choices"),
            "influence": summary.get("influence"),
        }

    def sim_gene(self, study_id: str, gene: str) -> dict[str, Any]:
        """One gene in the audit: verdict, how often the call holds, what flips it, margins."""
        error = self._study(study_id)
        if error:
            return {"error": error}
        folder, error = self._audit_dir(study_id)
        if folder is None:
            return {"error": error}
        explain = json.loads((folder / "explain.json").read_text(encoding="utf-8"))
        name = next((g for g in explain if g.lower() == str(gene).strip().lower()), None)
        if name is None:
            return {"error": "gene not in this study's audit", "n_genes": len(explain)}
        import pandas as pd

        row = pd.read_csv(folder / "genes.csv").set_index("gene").loc[name]
        keep = [
            "all_holds",
            "defensible_holds",
            "defensible_fragility",
            "samples_whose_removal_flips",
            "drop_k_to_flip",
            "fold_margin_log2",
            "fold_margin_in_se",
            "share_forks_significant_same_direction",
        ]
        numbers = {k: (None if pd.isna(row[k]) else float(row[k])) for k in keep if k in row}
        return {"study_id": study_id, "gene": name, **explain[name], "numbers": numbers}

    def sim_decisions(self, study_id: str) -> dict[str, Any]:
        """The decisions the audit varied: options, tiers, roles and the prespecified option."""
        error = self._study(study_id)
        if error:
            return {"error": error}
        folder, error = self._audit_dir(study_id)
        if folder is None:
            return {"error": error}
        lock = json.loads((folder / "lock.json").read_text(encoding="utf-8"))
        return {
            "study_id": study_id,
            "baseline": lock.get("baseline"),
            "tiers": lock.get("tiers"),
            "roles": lock.get("roles"),
            "rule": lock.get("rule"),
            "lock_sha256": lock.get("sha256"),
        }

    def sim_whatif(
        self, study_id: str, changes: dict[str, str], genes: list[str] | None = None
    ) -> dict[str, Any]:
        """Recompute every gene under some choices (``{"refs": "HMBS", "late_cq": "cq35"}``).

        Nothing is stored and no choice is made: this answers "what if"; a person decides on
        the Decision Cards. Unknown decisions or options are named in the error.
        """
        error = self._study(study_id)
        if error:
            return {"error": error}
        if not isinstance(changes, dict) or not all(
            isinstance(k, str) and isinstance(v, str) for k, v in changes.items()
        ):
            return {"error": "changes must map decision ids to option ids (strings)"}
        if genes is not None and (not isinstance(genes, list) or len(genes) > MAX_GENES):
            return {"error": f"genes must be a list of at most {MAX_GENES} names"}
        from qpilot.integration import simulator as sim

        if not sim.available():
            return {"error": "the Decision Simulator (qsim) is not installed"}
        with self._lock:
            try:
                prepared = self._prepared.get(study_id)
                if prepared is None:
                    prepared = sim.prepare(sim.load_analysis(self.store, study_id))
                    check = sim.reproduction(prepared, self.store.get(study_id))
                    if not check["ok"]:
                        return {"error": "the simulator does not reproduce this study's result"}
                    self._prepared[study_id] = prepared
                from qsim.compare import whatif

                table = whatif(prepared.engine, changes)
            except sim.NotApplicable as err:
                return {"error": f"not applicable to this design: {err}"}
            except KeyError as err:
                return {"error": str(err).strip("'\"")}
        if genes:
            wanted = {str(g).strip().lower() for g in genes}
            table = table[table["gene"].str.lower().isin(wanted)]
        flipped = table[table["call"] != table["base_call"]]
        return {
            "study_id": study_id,
            "baseline": prepared.space.baseline,
            "changes": changes,
            "calls_that_change": sorted(flipped["gene"]),
            "genes": json.loads(table.round(6).to_json(orient="records")),
        }


def create_server(store: StudyStore | None = None, audits: Mapping[str, str] | None = None) -> Any:
    """QPilot's MCP server with every qPilot tool plus the simulator's read-only tools."""
    from qpilot.mcp_server import INSTRUCTIONS, SERVER_NAME, TOOL_NAMES, QpilotTools, _server_class

    tools = QpilotTools(store)
    sim_tools = SimulatorTools(store, audits)
    server = _server_class()(SERVER_NAME, instructions=INSTRUCTIONS + SIM_INSTRUCTIONS)
    for name in TOOL_NAMES:
        server.tool(name=name)(getattr(tools, name))
    for name in SIM_TOOL_NAMES:
        server.tool(name=name)(getattr(sim_tools, name))
    return server


def main() -> None:
    """Serve qPilot's tools plus the simulator's over stdio."""
    create_server().run("stdio")


__all__ = ["SIM_TOOL_NAMES", "SimulatorTools", "create_server", "default_audit_dir", "main"]
