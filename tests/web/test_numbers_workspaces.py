"""Every count on the workspace list and frames equals the file's, the store's and the engine's.

The file's counts are read straight from the RDML XML (not through the inspector the server
uses); the study's from a fresh ``run_study``; decisions and requests from the store's chain.
"""

from __future__ import annotations

import re
import zipfile
from collections import Counter
from pathlib import Path

import pytest
from lxml import etree

from qpilot.io.rdml_io import hardened_parser
from tests.conftest import DEMO_RDML
from tests.web.numbers_world import (
    World,
    api_client,
    demo_world,
    engine_for,
    get_json,
    session_meta,
)

pytestmark = pytest.mark.demo_data


@pytest.fixture(scope="module")
def world(tmp_path_factory) -> World:
    if not DEMO_RDML.exists():
        pytest.skip("demo dataset not cached; run `qpilot fetch-demo`")
    return demo_world(tmp_path_factory.getbasetemp() / "numbers-demo", DEMO_RDML)


@pytest.fixture(scope="module")
def api(world):
    with api_client(world.store) as client:
        yield client


@pytest.fixture(scope="module")
def listed(api) -> dict[str, list[dict]]:
    by_kind: dict[str, list[dict]] = {"session": [], "study": []}
    for item in get_json(api, "/api/workspaces")["workspaces"]:
        by_kind[item["kind"]].append(item)
    return by_kind


def xml_counts(path: Path) -> dict:
    """Plates, wells, samples, targets and declared sample types, from the RDML XML itself."""
    with zipfile.ZipFile(path) as archive:
        xml = archive.read("rdml_data.xml")
    root = etree.fromstring(xml, hardened_parser())
    ns = {"r": root.nsmap[None]}
    runs = root.findall("r:experiment/r:run", ns)
    samples = root.findall("r:sample", ns)
    return {
        "n_plates": len(runs),
        "n_wells": sum(len({r.get("id") for r in run.findall("r:react", ns)}) for run in runs),
        "n_samples": len(samples),
        "n_targets": len(root.findall("r:target", ns)),
        "declared_types": dict(Counter(s.findtext("r:type", namespaces=ns) for s in samples)),
    }


def _undecided(world: World, study_id: str) -> int:
    return sum(1 for c in world.store.cards(study_id) if c.status in ("open", "pending_human"))


def test_the_session_frame_counts_what_the_file_declares(api, world):
    facts = get_json(api, f"/api/sessions/{world.sid}")["facts"]
    want = xml_counts(world.rdml)
    got = {key: facts[key] for key in want}
    assert got == want


def test_the_session_line_counts_the_file_and_its_study_chain(listed, world):
    (line,) = (w for w in listed["session"] if w["key"] == world.sid)
    file = xml_counts(world.rdml)
    assert (line["n_plates"], line["n_samples"], line["n_genes"]) == (
        file["n_plates"],
        file["n_samples"],
        file["n_targets"],
    )
    assert line["study_id"] == session_meta(world.store, world.sid)["current_study"]
    assert line["decisions"] == len(world.store.entries(world.study))
    assert line["pending_requests"] == len(world.store.pending(world.study))
    assert line["has_audit"] is world.audited


def test_a_study_line_counts_what_the_engine_analysed(listed, world):
    lines = {w["key"]: w for w in listed["study"]}
    assert world.legacy in lines, "the demo analysed by `qpilot run` is listed"
    line = lines[world.legacy]
    result, _cards, _grid = engine_for(world, world.legacy)
    assert (line["n_plates"], line["n_samples"], line["n_genes"]) == (
        result.n_plates,
        result.n_samples,
        len(result.contrasts),
    )
    assert line["decisions"] == len(world.store.entries(world.legacy))
    assert line["pending_requests"] == len(world.store.pending(world.legacy))


def test_the_session_studies_are_not_listed_twice(listed, world):
    studies = set(session_meta(world.store, world.sid)["studies"])
    assert studies.isdisjoint(w["key"] for w in listed["study"])


@pytest.mark.parametrize("which", ["study", "legacy"])
def test_the_next_step_counts_the_open_cards(api, world, which):
    study_id = getattr(world, which)
    url = f"/api/studies/{study_id}"
    view = get_json(api, url)
    assert view["decisions_head"] == world.store.chain_head(study_id)
    match = re.match(r"Decide (\d+) analysis choices?$", view["next_step"]["title"])
    open_cards = _undecided(world, study_id)
    if open_cards:
        assert match, view["next_step"]
        assert int(match.group(1)) == open_cards
    else:
        assert match is None


def test_a_fresh_study_has_the_engine_open_cards(world):
    """Without a person's decisions the store's cards are the engine's own (nothing was lost)."""
    if any(e.actor != "system" for e in world.store.entries(world.legacy)):
        pytest.skip("the legacy demo study has decisions in this store")
    _result, cards, _grid = engine_for(world, world.legacy)
    assert {c.id: c.status for c in world.store.cards(world.legacy)} == {
        c.id: c.status for c in cards
    }


def test_the_demo_is_the_documented_size(world):
    """docs/app.md §4 Open: "64 plates, 366 tumours" (the analysed experiment of the file)."""
    for study_id in (world.legacy, world.study):
        result, _cards, _grid = engine_for(world, study_id)
        assert (result.n_plates, result.n_samples) == (64, 366)


@pytest.mark.xfail(
    strict=True,
    reason="bus #0122 to api: the demo session's id is its qpilot-run study's id (sha[:12])",
)
def test_every_workspace_has_its_own_key(listed):
    keys = [w["key"] for kind in listed.values() for w in kind]
    assert len(keys) == len(set(keys)), sorted(k for k in keys if keys.count(k) > 1)
