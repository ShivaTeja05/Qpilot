"""Record the agent requests waiting for a person in the real store, as the Agents page reads them.

Run from the worktree root (with the agent env sourced):
    python frontend/src/features/agents/recorded/record_pending.py

The requests were made through qPilot's MCP tools (`QpilotTools.qpcr_decide`, actor agent) on
the seeded demo study. Until `GET /api/agents` lands this builds the waiting list from the store
(`StudyStore.pending`, the cards' titles and option labels); afterwards, re-record from the route.
"""

import json
from pathlib import Path

from qpilot.ai.explain import KIND_TITLE
from qpilot.core.store import StudyStore

store = StudyStore()
pending = []
for study_id in store.list_studies():
    cards = {c.id: c for c in store.cards(study_id)}
    head = store.chain_head(study_id)
    for e in store.pending(study_id):
        card = cards[e.card_id]
        pending.append(
            {
                "study_id": study_id,
                "card_id": e.card_id,
                "card_title": KIND_TITLE.get(card.kind),
                "option": e.option,
                "option_label": next((o.label for o in card.options if o.id == e.option), None),
                "reason": e.reason,
                "at": e.at,
                "seq": e.seq,
                "hash": e.hash,
                "head": head,
            }
        )
out = Path(__file__).parent / "pending.json"
out.write_text(json.dumps(pending, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
print(out.name, len(pending), "requests")
