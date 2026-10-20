"""Record the agent requests waiting for a person, as `GET /api/agents` lists them.

Run from the worktree root (with the agent env sourced and `qpilot app` serving this store on
$APP_PORT, for the workspaces' keys and titles):
    python frontend/src/features/agents/recorded/record_pending.py

The requests were made through qPilot's MCP tools (`QpilotTools.qpcr_decide`, actor agent) on
the seeded demo study. Until `GET /api/agents` is merged this builds its `pending` rows from the
store; afterwards, re-record from the route.
"""

import json
import os
import urllib.request
from pathlib import Path

from qpilot.ai.explain import KIND_TITLE
from qpilot.core.decisions import needs_human
from qpilot.core.store import StudyStore

request = urllib.request.Request(
    f"http://127.0.0.1:{os.environ['APP_PORT']}/api/workspaces",
    headers={"x-qpilot-token": os.environ["QPILOT_APP_TOKEN"]},
)
with urllib.request.urlopen(request) as answer:  # noqa: S310 (this machine's own server)
    workspaces = json.load(answer)["workspaces"]
by_study = {w["study_id"]: w for w in workspaces if w.get("study_id")}

store = StudyStore()
pending = []
for study_id in store.list_studies():
    place = by_study.get(study_id)
    if place is None:
        continue
    head, cards, waiting = store.snapshot(study_id)
    cards = {c.id: c for c in cards}
    for e in waiting:
        card = cards[e.card_id]
        pending.append(
            {
                "key": place["key"],
                "kind": place["kind"],
                "study_id": study_id,
                "title": place["title"],
                "card_id": e.card_id,
                "card_title": KIND_TITLE.get(card.kind, card.kind),
                "option": e.option,
                "option_label": next((o.label for o in card.options if o.id == e.option), e.option),
                "reason": e.reason,
                "actor": e.actor,
                "at": e.at,
                "seq": e.seq,
                "hash": e.hash,
                "can_change_a_conclusion": needs_human(card),
                "expected_head": head,
            }
        )
out = Path(__file__).parent / "pending.json"
out.write_text(json.dumps(pending, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
print(out.name, len(pending), "requests")
