"""Run an evaluation set through the same paths a scientist uses, on a scratch copy.

The run never touches the scientist's study: the workspace is copied into a temporary store
first, so decision-safety items (which raise agent requests) and the Studio items (which open
a session, propose, export to a folder and re-analyse) leave no trace in the real one.
"Ask your data" items go through ``ask()``; Studio items through
:func:`qpilot.harness.studio.run_item`, which needs the study's input file. When that file is
not available the Studio items are left out and the report says so.
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
from qpilot.harness.make_evalset import STUDIO_KINDS, Item
from qpilot.harness.report import Report, summarise
from qpilot.harness.score import ItemScore, score_item

WORKSPACE_FILES = ("results.json", "cards.json", "facts.json", "decisions.jsonl")
SKIP = (".lock", "harness_scorecard.json")


def _scratch_store(store: StudyStore, study_id: str, root: Path) -> StudyStore:
    """A store in ``root`` holding a copy of the study's workspace (every file but the lock)."""
    scratch = StudyStore(root)
    source = store.workspace(study_id)
    target = root / source.name
    target.mkdir(parents=True)
    for path in source.iterdir():
        if path.is_file() and not path.is_symlink() and path.name not in SKIP:
            shutil.copyfile(path, target / path.name)
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
    """Ask or run every item, score it, and summarise into a :class:`Report`."""
    from qpilot.harness.studio import StudioEnv, run_item

    scores: list[ItemScore] = []
    notes: list[str] = []
    with tempfile.TemporaryDirectory(prefix="qpilot-harness-") as tmp:
        scratch = _scratch_store(store, study_id, Path(tmp) / "studies")
        facts = scratch.get(study_id).facts
        source = scratch.source(study_id)
        studio_items = [i for i in items if i.kind in STUDIO_KINDS]
        if studio_items and source is None:
            notes.append(
                f"{len(studio_items)} Studio items left out: the study's input file is not "
                "available (open the study from its RDML file first)."
            )
            items = [i for i in items if i.kind not in STUDIO_KINDS]
        env = StudioEnv(scratch, study_id, client, Path(tmp), source)
        for item in items:
            if item.kind in STUDIO_KINDS:
                start = time.perf_counter()
                score = run_item(item, env)
                scores.append(score.model_copy(update={"latency_s": time.perf_counter() - start}))
                continue
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
    from qpilot.ai.client import public_endpoint

    endpoint = public_endpoint(getattr(client.backend, "url", None))
    return summarise(
        scores,
        profile_name or client.provider,
        client.provider,
        client.model,
        endpoint,
        run_at,
        notes,
    )
