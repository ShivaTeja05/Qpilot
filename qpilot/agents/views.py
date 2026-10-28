"""Reply shaping for agents: fact ids on the study's numbers, concise replies, JSON-safe values.

Pure functions over a tool's detailed reply (a dict), so the plain tool methods stay what the app
and the harness call, and the MCP layer only adds a view.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Callable, Mapping
from typing import Any

from qpilot.agents.refusals import Code, refuse

FORMATS = ("concise", "detailed")

# where the engine registers each per-gene number (Fact.path), by reply field
GENE_FACT_PATHS = {
    "fc": "contrasts.{gene}.fc",
    "ci_low": "contrasts.{gene}.ci[0]",
    "ci_high": "contrasts.{gene}.ci[1]",
    "p": "contrasts.{gene}.p",
    "holds": "robustness.{gene}.holds",
    "level": "confidence.{gene}.level",
    "min_flip_changes": "confidence.{gene}.min_flip_changes",
}


def json_safe(value: Any) -> Any:
    """``value`` with every non-finite float replaced by None (JSON has no NaN or infinity)."""
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {k: json_safe(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [json_safe(v) for v in value]
    return value


def fact_index(facts: Mapping[str, Any]) -> dict[str, str]:
    """Fact path -> fact id (the first id in sorted order when two facts share a path)."""
    index: dict[str, str] = {}
    for fid in sorted(facts):
        path = getattr(facts[fid], "path", None)
        if path and path not in index:
            index[path] = fid
    return index


def gene_fact_ids(index: Mapping[str, str], gene: str) -> dict[str, str]:
    """The fact ids of one gene's numbers, for the fields the study registers."""
    out = {}
    for field, pattern in GENE_FACT_PATHS.items():
        fid = index.get(pattern.format(gene=gene))
        if fid is not None:
            out[field] = fid
    return out


def check_format(response_format: Any) -> dict[str, Any] | None:
    """A refusal when ``response_format`` is not one of :data:`FORMATS`, else None."""
    if response_format in FORMATS:
        return None
    return refuse(
        Code.INVALID_ARGUMENT,
        "response_format must be concise or detailed",
        field="response_format",
    )


# ---- concise projections (detailed reply -> concise reply) ----------------------------------


def _study(out: dict[str, Any]) -> dict[str, Any]:
    keep = (
        "study_id",
        "record_root_hash",
        "chain_head",
        "agent_autonomy",
        "n_plates",
        "n_reactions",
        "n_samples",
        "conclusion_rule",
        "contrasts_are_for",
    )
    contrasts = {
        g: {k: c.get(k) for k in ("conclusion", "fc", "holds", "level")}
        for g, c in out["contrasts"].items()
    }
    cards = [
        {k: c[k] for k in ("card_id", "kind", "status", "needs_human", "recommended")}
        for c in out["open_cards"]
    ]
    concise = {
        **{k: out[k] for k in (*keep, "imported") if k in out},
        "contrasts": contrasts,
        "open_cards": cards,
        "n_decided_cards": len(out.get("decided_cards") or []),
    }
    if out.get("comparisons"):  # a study with several comparisons: each one's calls in counts
        found = out["comparisons"]
        concise["comparisons"] = {
            **{k: found[k] for k in ("test", "correction", "pair_by")},
            "comparisons": [
                {k: c[k] for k in ("id", "label", "group_a", "group_b", "primary", "n_a", "n_b",
                                   "n_pairs", "n_up", "n_down")}
                for c in found["comparisons"]
            ],
        }  # fmt: skip
    return concise


def _robustness(out: dict[str, Any]) -> dict[str, Any]:
    keep = ("study_id", "gene", "conclusion", "fc", "holds_fraction", "n_cells")
    confidence = out.get("confidence") or {}
    return {
        **{k: out[k] for k in keep},
        **{k: out[k] for k in ("comparison", "p_adjusted", "q") if k in out},
        "level": confidence.get("level"),
        "cards_that_can_flip_it": out["cards_that_can_flip_it"],
        "n_open_cards": len(out.get("open_cards") or []),
    }


def _proposals(out: dict[str, Any]) -> dict[str, Any]:
    keep = ("id", "kind", "subject", "status", "level")
    items = []
    for p in out["proposals"]:
        item = {k: p[k] for k in keep if k in p}
        item["made_by"] = (p.get("made_by") or {}).get("kind")
        item["check"] = (p.get("check") or {}).get("status")
        items.append(item)
    counts = Counter(p.get("status") for p in out["proposals"])
    return {
        "study_id": out["study_id"],
        "head": out["head"],
        "counts": dict(sorted(counts.items())),
        "proposals": items,
    }


def _inspect(out: dict[str, Any]) -> dict[str, Any]:
    summary = out.get("summary") or {}
    counts = {k: v for k, v in summary.items() if k.startswith("n_") and isinstance(v, int)}
    concise = {
        "session_id": out["session_id"],
        "counts": counts,
        "n_quoted": out["n_quoted"],
        "stages": out["stages"],
    }
    if "imported" in out:
        concise["imported"] = out["imported"]
    return concise


def _curve_calls(out: dict[str, Any]) -> dict[str, Any]:
    return {
        "gene": out["gene"],
        "rules": out["rules"],
        "n_wells": len(out.get("wells") or []),
        "n_disagreements": len(out.get("disagreements") or []),
        "disagreements": out.get("disagreements") or [],
    }


def _sim_audit(out: dict[str, Any]) -> dict[str, Any]:
    keep = ("study_id", "analyses", "verdict_counts", "reproduces_qpilot", "lock_sha256")
    return {k: out[k] for k in keep if k in out}


def _sim_whatif(out: dict[str, Any]) -> dict[str, Any]:
    keep = ("study_id", "baseline", "changes", "calls_that_change")
    return {**{k: out[k] for k in keep if k in out}, "n_genes": len(out.get("genes") or [])}


def _comparisons(out: dict[str, Any]) -> dict[str, Any]:
    keep = ("study_id", "n_comparisons", "test", "correction", "pair_by", "omnibus_groups")
    fields = ("id", "label", "group_a", "group_b", "primary", "n_a", "n_b", "n_pairs", "n_up")
    return {
        **{k: out[k] for k in keep if k in out},
        "comparisons": [
            {
                **{k: c.get(k) for k in (*fields, "n_down")},
                "n_not_tested": len(c.get("not_tested") or {}),
            }
            for c in out["comparisons"]
        ],
    }


def _units(out: dict[str, Any]) -> dict[str, Any]:
    drop = ("units", "how")
    concise = {k: v for k, v in out.items() if k not in drop}
    concise["units"] = [
        {k: u.get(k) for k in ("unit", "group", "samples", "log2", "n_wells", "capped")}
        for u in out["units"]
    ]
    return concise


def _melt(out: dict[str, Any]) -> dict[str, Any]:
    drop = ("calls", "wells")
    concise = {k: v for k, v in out.items() if k not in drop}
    calls = out.get("calls") or []
    concise["n_calls"] = len(calls)
    concise["flagged"] = sorted(c["key"] for c in calls if c.get("flagged"))
    return concise


def _repeat(out: dict[str, Any]) -> dict[str, Any]:
    drop = ("wells", "csv", "not_repeated")
    concise = {k: v for k, v in out.items() if k not in drop}
    fields = ("rank", "sample", "target", "scope", "consequence", "changed_calls", "on_plate")
    concise["items"] = [
        {**{k: i.get(k) for k in fields}, "n_reasons": len(i.get("reasons") or [])}
        for i in out["items"]
    ]
    return concise


CONCISE: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
    "qpcr_study": _study,
    "qpcr_robustness": _robustness,
    "qpcr_proposals": _proposals,
    "qpcr_inspect": _inspect,
    "qpcr_curve_calls": _curve_calls,
    "qpcr_comparisons": _comparisons,
    "qpcr_units": _units,
    "qpcr_melt": _melt,
    "qpcr_repeat_plan": _repeat,
    "sim_audit": _sim_audit,
    "sim_whatif": _sim_whatif,
}


def shape(tool: str, out: dict[str, Any], response_format: str) -> dict[str, Any]:
    """The reply in the asked form; refusals and unknown tools pass through unchanged."""
    if "error" in out:
        return out
    shaped = CONCISE[tool](out) if response_format == "concise" and tool in CONCISE else out
    return {**shaped, "response_format": response_format}


__all__ = [
    "CONCISE",
    "FORMATS",
    "GENE_FACT_PATHS",
    "check_format",
    "fact_index",
    "gene_fact_ids",
    "json_safe",
    "shape",
]
