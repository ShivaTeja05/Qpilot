"""Record "Where to look" answers from a running ``qpilot app`` for the Trace tests (never typed).

Start the server on a store that holds the Studio walk of the demo, then, from the repository root:

    qpilot app --no-open --port 7896 &
    python frontend/src/features/trace/__tests__/recorded/record_where.py \
        --port 7896 --study e300000d4f9a --gene CAMTA2 --calm ODC1 [--open]

It writes, next to this file, exactly what the page reads
(``GET /api/studies/{id}/where-to-look``):

* ``where-gene.json`` -- the gene named by ``--gene`` (a place whose options change its call);
* ``where-calm.json`` -- the gene named by ``--calm`` (unusual places, none changes its call);
* ``where-sample.json`` -- the sample of the first place of ``where-gene.json``;
* ``where-well.json`` -- the well of that place, as ``PLATE:WELL``;
* ``where-absent.json`` -- the first sample ``where-gene.json`` lists as in no comparison.

With ``--open`` it also presses **Decide…** once on the first place of ``where-gene.json``
(``POST …/where-to-look/open`` with that view's head; it opens a ``trace_set_aside`` Decision
Card in the server's store, so do it on a scratch copy) and writes:

* ``place-opened.json`` -- the answer (``PlaceOpened``);
* ``where-gene-opened.json`` -- the gene's trace again (the place now has its card's status).

Then run ``frontend/src/features/results/__tests__/recorded/record_ledger.py`` for the card.
(``--study`` is a Studio session's current analysis, so its views say ``can_apply``: press
Decide… with ``--open`` on a study analysed outside Studio, where the place opens as a card.)

With ``--outside STUDY`` it records the gene's trace of a study analysed outside Studio (the demo
file analysed without a session, e.g. ``StudyStore().ensure_study(<demo rdml>)``):

* ``where-gene-outside.json`` -- Decide… there opens a Decision Card (``can_apply`` false).

With ``--decide`` it applies a person's Decide… in the session (``POST …/where-to-look/decide``
on the first place of ``where-gene.json``, the option ``--option``; it changes the server's
store, so do it on a scratch copy), waits for the analysis it starts, and writes:

* ``place-decided.json`` -- the answer (``TraceDecided``);
* ``set-aside.json`` -- ``GET …/where-to-look/set-aside`` at the new analysis.

With ``--stale`` it presses Decide… with a head the chain is not at (the server refuses it before
it reads anything else, so nothing is opened) and writes the refusal:

* ``place-stale.json`` -- ``{"status": 409, "body": {"error": {"code": "stale", …}}}``.
"""

from __future__ import annotations

import argparse
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
WAIT = ("warming", "loading")  # the server is reading the file or the study: ask again


class Refused(RuntimeError):
    """The server answered with an error: its status and its ``error`` body."""

    def __init__(self, path: str, status: int, error: dict[str, Any]) -> None:
        super().__init__(f"{path}: {status} {error}")
        self.status = status
        self.error = error


def call(port: int, path: str, body: object | None = None) -> Any:
    """GET (or POST ``body``) one API path with the dev launch key, waiting out a first load."""
    origin = f"http://127.0.0.1:{port}"
    request = urllib.request.Request(
        origin + path,
        data=None if body is None else json.dumps(body).encode(),
        headers={
            "x-qpilot-token": os.environ.get("QPILOT_APP_TOKEN", "qpilot-dev"),
            "content-type": "application/json",
            "origin": origin,
        },
        method="GET" if body is None else "POST",
    )
    for _ in range(150):
        try:
            with urllib.request.urlopen(request, timeout=300) as response:  # noqa: S310 (local)
                return json.loads(response.read())
        except urllib.error.HTTPError as err:
            error = json.loads(err.read()).get("error", {})
            if err.code in (409, 503) and error.get("code") in WAIT:
                time.sleep(2)
                continue
            raise Refused(path, err.code, error) from err
    raise RuntimeError(f"{path}: never ready")


def refusal(port: int, path: str, body: object) -> dict[str, Any]:
    """POST ``body`` and return the refusal it must get (status and body)."""
    try:
        call(port, path, body)
    except Refused as err:
        return {"status": err.status, "body": {"error": err.error}}
    raise RuntimeError(f"{path}: the server accepted it")


def where(port: int, study: str, **query: str) -> dict[str, Any]:
    """One ``where-to-look`` answer."""
    q = urllib.parse.urlencode(query)
    view = call(port, f"/api/studies/{study}/where-to-look?{q}")
    assert isinstance(view, dict)
    return view


def write(name: str, view: object) -> None:
    """Write one answer next to this file, as the server sent it."""
    (HERE / name).write_text(json.dumps(view, indent=1, ensure_ascii=False) + "\n")
    print(f"wrote {name}")


def main() -> None:
    """Record every view the Where to look panel reads."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--port", type=int, default=int(os.environ.get("APP_PORT", "7860")))
    parser.add_argument("--study", required=True, help="the study id (12 hex)")
    parser.add_argument("--gene", required=True, help="a gene with a place that changes its call")
    parser.add_argument("--calm", required=True, help="a gene no place changes")
    parser.add_argument("--open", action="store_true", help="press Decide… once (writes)")
    parser.add_argument("--stale", action="store_true", help="record a refused Decide… only")
    parser.add_argument("--outside", help="a study analysed outside Studio: its gene's trace")
    parser.add_argument("--decide", action="store_true", help="apply a Decide… (writes)")
    parser.add_argument("--option", default="set_aside", help="the option --decide applies")
    parser.add_argument("--reason", default="The reference well's curve never rose.")
    args = parser.parse_args()
    if args.outside:
        write("where-gene-outside.json", where(args.port, args.outside, gene=args.gene))
        return
    gene = where(args.port, args.study, gene=args.gene)
    if args.decide:
        first = next(p for p in gene["places"] if p["can_decide"])
        done = call(
            args.port,
            f"/api/studies/{args.study}/where-to-look/decide",
            {
                "kind": "gene",
                "id": args.gene,
                "rank": first["rank"],
                "option": args.option,
                "reason": args.reason,
                "expected_head": gene["head"],
                "expected_inbox": gene["inbox_head"],
            },
        )
        write("place-decided.json", done)
        job = done.get("job") or {}
        for _ in range(300):
            if not job or call(args.port, f"/api/jobs/{job['id']}")["status"] != "running":
                break
            time.sleep(1)
        session = call(args.port, f"/api/sessions/{gene['session']}")
        write(
            "set-aside.json",
            call(args.port, f"/api/studies/{session['study_id']}/where-to-look/set-aside"),
        )
        return
    if args.stale:
        rank = next(p["rank"] for p in gene["places"] if p["can_decide"])
        old = "0" * len(gene["head"])
        assert old != gene["head"]
        answer = refusal(
            args.port,
            f"/api/studies/{args.study}/where-to-look/open",
            {"kind": "gene", "id": args.gene, "rank": rank, "expected_head": old},
        )
        assert answer["status"] == 409 and answer["body"]["error"]["code"] == "stale", answer
        write("place-stale.json", answer)
        return
    first = next(p for p in gene["places"] if p["can_decide"])
    assert first["card_status"] is None, "the place is already open: record on a fresh store"
    write("where-gene.json", gene)
    calm = where(args.port, args.study, gene=args.calm)
    assert not any(p["can_decide"] for p in calm["places"])
    write("where-calm.json", calm)
    write("where-sample.json", where(args.port, args.study, sample=first["sample"]))
    write("where-well.json", where(args.port, args.study, well=f"{first['plate']}:{first['well']}"))
    write("where-absent.json", where(args.port, args.study, sample=gene["absent"][0]["sample"]))
    if args.open:
        opened = call(
            args.port,
            f"/api/studies/{args.study}/where-to-look/open",
            {"kind": "gene", "id": args.gene, "rank": first["rank"], "expected_head": gene["head"]},
        )
        write("place-opened.json", opened)
        write("where-gene-opened.json", where(args.port, args.study, gene=args.gene))


if __name__ == "__main__":
    main()
