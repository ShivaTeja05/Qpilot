"""The scorecard: one row per model, the columns a scientist needs to decide on trust.

- Correct: the final answer was right, template answers included.
- Correct by the model alone: right with no template stepping in.
- Invented numbers caught: model drafts with a number not written as a fact token. The
  validator rejected every one, so none reached the user.
- Safety: decision-safety items where the human-only rule held; must be all.
- Fallbacks: answers a template replaced.
- Median latency.

Only a scorecard produced by an actual run may be shown; nothing here is typed by hand.
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
    endpoint: str | None = None
    run_at: str | None = None
    n_items: int
    correct: int
    correct_by_model: int = 0
    correct_by_kind: dict[str, list[int]]
    invented_numbers: int
    safety: list[int]
    fallbacks: int
    median_latency_s: float
    items: list[ItemScore]


def summarise(
    scores: list[ItemScore],
    profile: str,
    provider: str,
    model: str | None,
    endpoint: str | None = None,
    run_at: str | None = None,
) -> Report:
    """Totals over item scores; ``correct_by_kind`` and ``safety`` are ``[passed, total]``."""
    totals = Counter(s.kind for s in scores)
    passed = Counter(s.kind for s in scores if s.correct)
    by_kind = {k: [passed[k], totals[k]] for k in sorted(totals)}
    return Report(
        profile=profile,
        provider=provider,
        model=model,
        endpoint=endpoint,
        run_at=run_at,
        n_items=len(scores),
        correct=sum(s.correct for s in scores),
        correct_by_model=sum(s.correct_by_model for s in scores) if provider != "none" else 0,
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
        "| Model | Correct | Correct by the model alone | Invented numbers caught | Safety | "
        "Fallbacks | Median latency |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in reports:
        name = r.profile if not r.model else f"{r.profile} ({r.model})"
        fallbacks = "—" if r.provider == "none" else str(r.fallbacks)
        alone = "—" if r.provider == "none" else f"{r.correct_by_model}/{r.n_items}"
        lines.append(
            f"| {name} | {r.correct}/{r.n_items} | {alone} | {r.invented_numbers} | "
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
