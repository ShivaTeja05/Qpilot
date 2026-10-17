"""Run an evaluation set through the same ``ask()`` path a scientist uses, on a scratch copy.

The run never touches the scientist's study: the workspace is copied into a temporary store
first, so decision-safety items (which raise agent requests) leave no trace in the real log.
"""

from __future__ import annotations

import shutil
import tempfile
import time
from pathlib import Path

from qpilot.ai.ask import ask
from qpilot.ai.client import ModelClient
from qpilot.ai.profile import Profile
from qpilot.core.store import StudyStore
from qpilot.harness.make_evalset import Item
from qpilot.harness.report import Report, summarise
from qpilot.harness.score import ItemScore, score_item

WORKSPACE_FILES = ("results.json", "cards.json", "facts.json", "decisions.jsonl")


def _scratch_store(store: StudyStore, study_id: str, root: Path) -> StudyStore:
    scratch = StudyStore(root)
    source = store.workspace(study_id)
    target = root / source.name
    target.mkdir(parents=True)
    for name in WORKSPACE_FILES:
        if (source / name).exists():
            shutil.copyfile(source / name, target / name)
    return scratch


def run(
    items: list[Item],
    client: ModelClient,
    store: StudyStore,
    study_id: str,
    profile: Profile | None = None,
    profile_name: str | None = None,
    run_at: str | None = None,
) -> Report:
    """Ask every item, score it, and summarise into a :class:`Report`."""
    scores: list[ItemScore] = []
    with tempfile.TemporaryDirectory(prefix="qpilot-harness-") as tmp:
        scratch = _scratch_store(store, study_id, Path(tmp))
        facts = scratch.get(study_id).facts
        for item in items:
            card_id = item.expected.get("card_id")
            before = scratch.card(study_id, card_id).decision if card_id else None
            start = time.perf_counter()
            answer = ask(
                item.question, scratch, study_id, client=client, profile=profile, log=False
            )
            latency = time.perf_counter() - start
            after = scratch.card(study_id, card_id).decision if card_id else None
            scores.append(
                score_item(item, answer, {**facts, **answer.facts}, before != after, latency)
            )
    endpoint = getattr(client.backend, "url", None)
    return summarise(
        scores, profile_name or client.provider, client.provider, client.model, endpoint, run_at
    )
