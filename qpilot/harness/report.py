"""The scorecard: one row per model, the five columns a scientist needs to decide on trust.

Correct · invented numbers (drafts the validator rejected; target 0) · safety (decision-safety
items where the human-only rule held; must be all) · fallbacks (answers a template replaced) ·
median latency. Only a scorecard produced by an actual run may be shown; nothing here is typed.
"""

from __future__ import annotations

import json
import statistics
from collections import Counter
from pathlib import Path

from pydantic import BaseModel

from qpilot.harness.score import ItemScore


class Report(BaseModel):
    """A harness run, item by item and in total."""

    profile: str
    provider: str
    model: str | None
    n_items: int
    correct: int
    correct_by_kind: dict[str, list[int]]
    invented_numbers: int
    safety: list[int]
    fallbacks: int
    median_latency_s: float
    items: list[ItemScore]


def summarise(scores: list[ItemScore], profile: str, provider: str, model: str | None) -> Report:
    """Totals over item scores; ``correct_by_kind`` and ``safety`` are ``[passed, total]``."""
    totals = Counter(s.kind for s in scores)
    passed = Counter(s.kind for s in scores if s.correct)
    by_kind = {k: [passed[k], totals[k]] for k in sorted(totals)}
    return Report(
        profile=profile,
        provider=provider,
        model=model,
        n_items=len(scores),
        correct=sum(s.correct for s in scores),
        correct_by_kind=by_kind,
        invented_numbers=sum(s.invented_numbers for s in scores),
        safety=by_kind.get("decision_safety", [0, 0]),
        fallbacks=sum(s.fallback for s in scores) if provider != "none" else 0,
        median_latency_s=statistics.median([s.latency_s for s in scores]) if scores else 0.0,
        items=scores,
    )


def markdown(reports: list[Report]) -> str:
    """A scorecard table, one row per report."""
    lines = [
        "| Model | Correct | Invented numbers | Safety | Fallbacks | Median latency |",
        "|---|---|---|---|---|---|",
    ]
    for r in reports:
        name = r.profile if not r.model else f"{r.profile} ({r.model})"
        fallbacks = "—" if r.provider == "none" else str(r.fallbacks)
        lines.append(
            f"| {name} | {r.correct}/{r.n_items} | {r.invented_numbers} | "
            f"{r.safety[0]}/{r.safety[1]} | {fallbacks} | {r.median_latency_s:.2f} s |"
        )
    return "\n".join(lines) + "\n"


def write(report: Report, out_dir: str | Path) -> tuple[Path, Path]:
    """Write ``<profile>.json`` and ``<profile>.md`` into ``out_dir``."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    json_path = out / f"{report.profile}.json"
    md_path = out / f"{report.profile}.md"
    json_path.write_text(json.dumps(report.model_dump(), indent=2, sort_keys=True) + "\n")
    md_path.write_text(markdown([report]))
    return json_path, md_path
