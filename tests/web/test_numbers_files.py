"""Prism's preview and routes, and the exported Analysis Record, carry the engine's numbers.

* The routes table: each usual Excel→Prism route's count of changed conclusions is the fact a
  fresh ``run_study`` computes, and the demo's documented counts (studio-measured §2.7).
* The preview: every gene's table is one value per biological unit; the groups' sizes are the
  contrast's n, the difference of their means is the engine's log2 fold change, their 95 % CIs
  are Student's t on the points, and Welch's test on the points gives the engine's p — what
  Prism will compute from the same table.
* The record: its id is the sha256 of the zip's ``CHECKSUMS.sha256``, its counts are the zip's,
  its chain head is the store's, and ``qpilot verify`` (the CLI) agrees with the page's verify.
"""

from __future__ import annotations

import hashlib
import io
import math
import shutil
import time
import zipfile

import numpy as np
import pytest
from scipy import stats

from qpilot.cli.studio_cmds import EXPECTED
from tests.conftest import DEMO_RDML
from tests.web.numbers_engine import CARD_DIMENSION, engine
from tests.web.numbers_world import BASE, World, api_client, demo_world, get_json

pytestmark = pytest.mark.demo_data
pytest.importorskip("qpilot.web.routers.files", reason="the Prism and Record routes are not merged")

ROUTES_DOCUMENTED = {
    "linear_welch": EXPECTED["route_linear_welch_differ"],
    "linear_student": EXPECTED["route_linear_student_differ"],
    "ddcq": EXPECTED["route_ddcq_differ"],
}


@pytest.fixture(scope="module")
def world(tmp_path_factory) -> World:
    if not DEMO_RDML.exists():
        pytest.skip("demo dataset not cached; run `qpilot fetch-demo`")
    return demo_world(tmp_path_factory.getbasetemp() / "numbers-demo", DEMO_RDML)


@pytest.fixture(scope="module")
def copy(world, tmp_path_factory):
    """A private copy of the demo store (exports write beside it)."""
    from qpilot.core.store import StudyStore

    root = tmp_path_factory.mktemp("numbers-files") / "studies"
    shutil.copytree(world.store.root, root)
    store = StudyStore(root)
    with api_client(store) as client:
        client.headers["origin"] = BASE
        yield client, store


def test_the_routes_table_is_the_engine_s_route_facts(copy, world):
    client, _ = copy
    view = get_json(client, f"/api/sessions/{world.sid}/prism/routes")
    assert view["study_id"] == world.study
    eng = engine(world, world.study).result
    assert view["n_genes"] == len(eng.contrasts)
    routes = {r["route"]: r for r in view["routes"]}
    assert set(routes) >= set(ROUTES_DOCUMENTED)
    for name, route in routes.items():
        assert route["n_differ"] == eng.facts[f"f_n_differ_route_{name}"].value, name
        assert route["n_differ"] == len(route["genes"]), name
        assert route["n_genes"] == len(eng.contrasts), name
        gid = f"f_genes_differ_route_{name}"
        if gid in eng.facts and route["genes"]:
            assert ", ".join(route["genes"]) == eng.facts[gid].value, name
    assert {k: routes[k]["n_differ"] for k in ROUTES_DOCUMENTED} == ROUTES_DOCUMENTED
    assert sorted(routes["ddcq"]["genes"]) == ["CAMTA2", "IGSF4", "PAICS", "PRKACB_bis"]
    for gene, call in view["engine"].items():
        assert call == eng.contrasts[gene].conclusion, gene


@pytest.fixture(scope="module")
def preview(copy, world) -> dict:
    client, _ = copy
    return get_json(client, f"/api/sessions/{world.sid}/prism/preview?rows=50")


def test_each_prism_table_reproduces_the_engine_contrast(preview, world):
    eng = engine(world, world.study)
    assert preview["study_id"] == world.study
    assert preview["genes"] == [g for g in eng.settings.headline if g in eng.result.contrasts]
    tables = {t["gene"]: t for t in preview["tables"]}
    for gene in preview["genes"]:
        contrast = eng.result.contrasts[gene]
        figure = preview["figures"][gene]
        first, second = figure["groups"]
        assert (first["n"], second["n"]) == (contrast.n_hi, contrast.n_lo), gene
        assert tables[gene]["n_rows"] == contrast.n_hi + contrast.n_lo, gene
        a = np.array([p["value"] for p in first["points"]])
        b = np.array([p["value"] for p in second["points"]])
        assert (len(a), len(b)) == (contrast.n_hi, contrast.n_lo), gene
        assert math.isclose(a.mean() - b.mean(), contrast.log2fc, abs_tol=1e-9), gene
        welch = stats.ttest_ind(a, b, equal_var=False)
        assert math.isclose(welch.pvalue, contrast.p, rel_tol=1e-6), gene
        for group, x in ((first, a), (second, b)):
            half = stats.t.ppf(0.975, len(x) - 1) * x.std(ddof=1) / math.sqrt(len(x))
            assert math.isclose(group["mean"], x.mean(), abs_tol=1e-12), gene
            assert math.isclose(group["ci_lo"], x.mean() - half, abs_tol=1e-9), gene
            assert math.isclose(group["ci_hi"], x.mean() + half, abs_tol=1e-9), gene


def test_the_preview_is_exported_at_the_options_in_use(preview, world):
    eng = engine(world, world.study)
    cards = {c.id: c for c in world.store.cards(world.study)}
    for choice in preview["choices"]:
        card = cards[choice["card_id"]]
        option = card.decision or card.recommended
        assert choice["option"] == option, choice
        assert choice["dimension"] == CARD_DIMENSION[card.kind]
        want = eng.option_values(card)[option]
        got = tuple(choice["value"]) if isinstance(choice["value"], list) else choice["value"]
        assert got == want, choice


def test_the_caption_cites_the_engine_numbers(preview, world):
    eng = engine(world, world.study).result
    caption = preview["caption"]
    for gene in preview["genes"]:
        n = eng.robustness[gene].n_cells
        pct = round(100 * eng.robustness[gene].holds)
        assert f"holds in {pct}% of the {n} analyses" in caption.replace(" %", "%"), (gene, caption)


def _job(client, response) -> dict:
    assert response.status_code == 202, response.text
    job = response.json()["job"]
    deadline = time.monotonic() + 600
    while (view := get_json(client, f"/api/jobs/{job['id']}"))["status"] not in ("done", "failed"):
        assert time.monotonic() < deadline, view
        time.sleep(0.2)
    assert view["status"] == "done", view
    return view["result"]


def test_the_exported_record_is_the_zip_and_the_cli_agrees(copy, world, tmp_path):
    from qpilot.cli import main as qpilot

    client, store = copy
    study = world.study
    exported = _job(client, client.post(f"/api/studies/{study}/record", json={}))
    archive = client.get(exported["download"]["url"])
    assert archive.status_code == 200
    assert len(archive.content) == exported["download"]["bytes"]
    with zipfile.ZipFile(io.BytesIO(archive.content)) as zf:
        names = zf.namelist()
        checksums = zf.read("CHECKSUMS.sha256")
    assert exported["record_id"] == hashlib.sha256(checksums).hexdigest()
    assert exported["n_files"] == len(names)
    listed = {line.split(maxsplit=1)[1].strip() for line in checksums.decode().splitlines()}
    assert listed == set(names) - {"CHECKSUMS.sha256"}
    assert exported["chain_head"] == store.chain_head(study)
    assert exported["open_flips"] == [
        c.id
        for c in store.cards(study)
        if c.impact.get("flips") and c.status in ("open", "pending_human")
    ]
    path = tmp_path / exported["download"]["name"]
    path.write_bytes(archive.content)
    assert qpilot(["verify", str(path)]) == 0
    verified = client.post(
        "/api/records/verify", files={"record": (path.name, archive.content, "application/zip")}
    )
    assert verified.status_code == 200, verified.text
    body = verified.json()
    assert body["ok"] is True
    assert body["record"]["record_id"] == exported["record_id"]
    assert body["record"]["chain_head"] == exported["chain_head"]
    assert body["report"]["n_entries"] == len(store.entries(study))
