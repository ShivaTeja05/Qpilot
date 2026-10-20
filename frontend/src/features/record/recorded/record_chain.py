"""Record a study's decision chain from the real store, in the shape the Record page reads.

Run from the worktree root (with the agent env sourced):
    python frontend/src/features/record/recorded/record_chain.py e300000d4f9a cf49ccd72052

Until `GET /api/studies/{id}/decisions` lands this builds the same view from the store
(`StudyStore.entries`, the cards' titles and option labels); afterwards, re-record from the route.
"""

import json
import sys
from pathlib import Path

from qpilot.ai.explain import KIND_TITLE
from qpilot.core.record import verify_chain
from qpilot.core.store import StudyStore

store = StudyStore()
here = Path(__file__).parent
for study_id in sys.argv[1:]:
    cards = {c.id: c for c in store.cards(study_id)}
    root = store.get(study_id).input_sha256
    entries = store.entries(study_id)
    view = {
        "study_id": study_id,
        "root": root,
        "head": store.chain_head(study_id),
        "chain_intact": verify_chain(entries, root) is None,
        "n_pending": len(store.pending(study_id)),
        "entries": [
            {
                **e.model_dump(),
                "card_kind": cards[e.card_id].kind,
                "card_title": KIND_TITLE.get(cards[e.card_id].kind),
                "option_label": next(
                    (o.label for o in cards[e.card_id].options if o.id == e.option), None
                ),
            }
            for e in entries
        ],
    }
    out = here / f"decisions-{study_id}.json"
    out.write_text(json.dumps(view, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(out.name, len(entries), "entries")
