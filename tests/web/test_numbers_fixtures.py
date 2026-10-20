"""The results routes on small files: the same equality checks, and what a small study meets.

The Studio mini file (``tests/fixtures/studio/studio_mini.py``, two groups of two) walked by a
person (``tests.web.conftest.walk_mini``), as is and in two variants of the same generator: one
KO sample's ``1-Mar`` wells late (Cq about 37, so the Cq ≤ 38 and ≤ 35 rules leave that group
with one value), and the same wells flat (the engine withholds the gene: fewer than two
biological units with a value). Every number is checked against the engine run on that file.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from qpilot.core.store import StudyStore
from tests.web.conftest import BASE, TOKEN, walk_mini
from tests.web.numbers_checks import check_cards, check_flips, check_gene, check_gene_rows
from tests.web.numbers_engine import engine_of
from tests.web.numbers_world import get_json

GENE = "1-Mar"
VARIANTS = {"late": [36.6, 36.7, 36.8], "flat": [None, None, None]}


def _engine(store: StudyStore, study: str, rdml: Path):
    return engine_of(rdml, store.design(study))


def test_the_mini_study_is_the_engine(walked):
    client, store, study = walked["client"], walked["store"], walked["study"]
    eng = _engine(store, study, walked["root"] / "mini.rdml")
    check_gene_rows(get_json(client, f"/api/studies/{study}/results"), eng)
    check_flips(get_json(client, f"/api/studies/{study}/flips"), eng)
    check_cards(get_json(client, f"/api/studies/{study}/cards"), eng)
    for gene in eng.result.contrasts:
        check_gene(get_json(client, f"/api/studies/{study}/genes/{gene}"), eng, gene)


@pytest.fixture(scope="module", params=sorted(VARIANTS))
def variant(request, tmp_path_factory):
    """The mini file with one KO sample's 1-Mar wells changed, walked, and a client over it."""
    from qpilot.ai.client import ModelClient, NoneBackend
    from qpilot.qpcr import design_checks
    from qpilot.qpcr import inspect as qinspect
    from qpilot.studio_service import Studio
    from qpilot.web.context import make_context
    from qpilot.web.server import create_app
    from tests.fixtures.studio import studio_mini

    base = tmp_path_factory.mktemp(f"mini-{request.param}")
    root = base / "data"
    root.mkdir()
    plates = {target: dict(plate) for target, plate in studio_mini.PLATES.items()}
    plates[GENE]["KO_2"] = VARIANTS[request.param]
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("QPILOT_DATA_ROOTS", str(root))
        mp.setenv("QPILOT_STUDIES_DIR", str(base / "studies"))
        mp.setattr(studio_mini, "PLATES", plates)
        qinspect.clear_cache()
        rdml = studio_mini.write_studio_mini(root / "mini.rdml")
        store = StudyStore(base / "studies")
        studio = Studio(store, client=ModelClient(backend=NoneBackend()))
        _sid, study = walk_mini(studio, rdml)
        ctx = make_context(store, studio, token=TOKEN, watch=False)
        with TestClient(create_app(ctx), base_url=BASE) as client:
            client.headers["x-qpilot-token"] = TOKEN
            yield {
                "name": request.param,
                "client": client,
                "store": store,
                "study": study,
                "engine": _engine(store, study, rdml),
            }
        ctx.close()
        design_checks._DECLARED.clear()
        design_checks.set_input_resolver(None)
        qinspect.clear_cache()


def test_a_small_study_keeps_its_numbers(variant):
    """What the routes already serve on these files equals the engine."""
    client, study, eng = variant["client"], variant["study"], variant["engine"]
    check_gene_rows(get_json(client, f"/api/studies/{study}/results"), eng)
    check_cards(get_json(client, f"/api/studies/{study}/cards"), eng)


@pytest.mark.xfail(
    strict=True,
    reason="bus #0199 bug 1 to api: f_amp_primary is the rule's label, so the planned cell "
    "ties when cq_le_40 equals linregpcr and every option of the flip matrix is dropped",
)
def test_a_late_sample_keeps_the_flip_matrix_and_the_gene_grid(variant):
    if variant["name"] != "late":
        pytest.skip("only the late variant has a gene to show")
    client, study, eng = variant["client"], variant["study"], variant["engine"]
    check_flips(get_json(client, f"/api/studies/{study}/flips"), eng)
    for gene in eng.result.contrasts:  # also: a p the engine could not compute is null
        check_gene(get_json(client, f"/api/studies/{study}/genes/{gene}"), eng, gene)


def test_a_withheld_gene_is_named_with_its_reason(variant):
    if variant["name"] != "flat":
        pytest.skip("only the flat variant withholds a gene")
    client, study, eng = variant["client"], variant["study"], variant["engine"]
    assert GENE not in eng.result.contrasts
    reason = eng.result.facts[f"f_withheld_{GENE.lower().replace('-', '_')}"].value
    body = get_json(client, f"/api/studies/{study}/results")
    assert body["summary"]["n_genes"] == 0
    named = {w["gene"]: w["reason"] for w in body.get("withheld", [])}
    assert named == {GENE: reason}
