"""RT-EX-015: the public sandbox limits each visitor (and everyone together); a computer does not.

A hosted server (``QPILOT_HOSTED=1``) is shared by every visitor, so one visitor must not be able
to keep its job workers busy or flood it with uploads. These tests pin: the buckets (a burst, a
refill, ``Retry-After``), who a visitor is (a forwarded address counts only from a trusted
proxy), the sandbox-wide backstop, forgetting idle visitors, the cap on running jobs (also
through the job runner), the cap on live streams, and that a person's own computer, the page and
the health check are never limited.
"""

from __future__ import annotations

import asyncio
import io
import re
import threading
from pathlib import Path

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from qpilot.web import ratelimit as rl
from qpilot.web.context import make_context
from qpilot.web.events import EventBus
from qpilot.web.jobs import REQUESTER, Job, JobRunner
from qpilot.web.ratelimit import (
    Busy,
    Limiter,
    RateLimit,
    RateLimits,
    Rule,
    client_address,
    parse_address,
    parse_rule,
    request_kind,
)
from qpilot.web.server import create_app, job_starting_paths

SPACE = "jeevithg-qpilot.hf.space"
ORIGIN = {"origin": f"https://{SPACE}"}
HOSTED = {"QPILOT_HOSTED": "1", "QPILOT_ALLOWED_HOSTS": SPACE}


class Clock:
    """A clock the test moves by hand."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def limits(**kw) -> RateLimits:
    return RateLimits(**kw)


def job(owner: str | None, kind: str = "audit", **kw) -> Job:
    return Job(id="j", kind=kind, title="t", key="k", typical_s=kw.pop("typical_s", 50.0),
               owner=owner, status="running", **kw)  # fmt: skip


# ---- the settings -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text, want",
    [
        ("240/min", Rule(240, 60)),
        ("6/10min", Rule(6, 600)),
        ("20/60", Rule(20, 60)),
        ("2/h", Rule(2, 3600)),
        ("5/s", Rule(5, 1)),
        (" 120 / min ", Rule(120, 60)),
        ("off", None),
        ("0", None),
        ("unlimited", None),
        ("0/60", None),
        ("", Rule(1, 1)),  # unset: the default asked for
        ("lots", Rule(1, 1)),
        ("5/fortnight", Rule(1, 1)),
        ("-3/min", Rule(1, 1)),
    ],
)
def test_a_rule_reads_count_per_window_and_off(text, want):
    assert parse_rule(text, Rule(1, 1)) == want


def test_a_local_server_has_no_limits_and_a_hosted_one_has_the_defaults():
    assert RateLimits.from_env({}) is None
    assert RateLimits.from_env({"QPILOT_RATE_READS": "1/min"}) is None  # not hosted
    d = RateLimits.from_env(HOSTED)
    assert d is not None and d == RateLimits()
    assert (d.read, d.write, d.upload) == (Rule(240, 60), Rule(20, 60), Rule(6, 600))
    assert (d.jobs, d.all_jobs, d.streams) == (3, 8, 6)
    assert not d.trust_any_peer and not d.trusted_proxies  # no proxy is believed unless named


def test_the_limits_follow_the_environment():
    env = {
        **HOSTED,
        "QPILOT_RATE_READS": "10/10s",
        "QPILOT_RATE_WRITES": "off",
        "QPILOT_RATE_UPLOADS": "nonsense",
        "QPILOT_RATE_JOBS": "2",
        "QPILOT_RATE_JOBS_ALL": "0",
        "QPILOT_RATE_STREAMS": "x",
        "QPILOT_RATE_CLIENTS": "5",
        "QPILOT_TRUSTED_PROXIES": "10.0.0.0/8, 2001:db8::/32, bogus, 192.0.2.7",
        "QPILOT_CLIENT_IP_HEADER": "X-Real-IP",
        "QPILOT_PROXY_HOPS": "2",
    }
    got = RateLimits.from_env(env)
    assert got is not None
    assert got.read == Rule(10, 10) and got.write is None  # off
    assert got.upload == RateLimits().upload  # not a rule: the default
    assert (got.jobs, got.all_jobs, got.streams) == (2, 0, 6)
    assert got.max_clients == 100  # never fewer than 100 visitors
    assert len(got.trusted_proxies) == 3 and not got.trust_any_peer
    assert got.client_ip_header == "x-real-ip" and got.proxy_hops == 2
    assert RateLimits.from_env({**HOSTED, "QPILOT_PROXY_HOPS": "leftmost"}).proxy_hops is None
    assert RateLimits.from_env({**HOSTED, "QPILOT_PROXY_HOPS": "0"}).proxy_hops == 1
    assert RateLimits.from_env({**HOSTED, "QPILOT_TRUSTED_PROXIES": "*"}).trust_any_peer
    assert RateLimits.from_env({**HOSTED, "QPILOT_RATE_LIMIT": "off"}) is None


# ---- who a visitor is -------------------------------------------------------------------------


def test_addresses_are_normalised():
    assert parse_address("203.0.113.5") == "203.0.113.5"
    assert parse_address(" 203.0.113.5:4433 ") == "203.0.113.5"
    assert parse_address("[2001:db8:1:2:3:4:5:6]:99") == "2001:db8:1:2::/64"
    assert parse_address("2001:db8:1:2:ffff::1") == "2001:db8:1:2::/64"  # one network, one visitor
    assert parse_address("::ffff:203.0.113.5") == "203.0.113.5"
    assert parse_address("fe80::1%eth0") == "fe80::/64"
    for junk in ("", "unknown", "999.1.1.1", "a, b", "[::1", "1.2.3"):
        assert parse_address(junk) is None, junk


def test_the_socket_peer_is_the_visitor_unless_it_is_a_trusted_proxy():
    plain = limits()  # no trusted proxy
    assert client_address(plain, "203.0.113.5", ["198.51.100.1"]) == "203.0.113.5"
    assert client_address(plain, None, ["198.51.100.1"]) == "unknown"
    assert client_address(plain, "testclient", []) == "testclient"


def test_a_forwarded_address_from_an_untrusted_peer_is_ignored():
    behind = limits(trusted_proxies=rl._networks("198.51.100.0/24")[1], proxy_hops=None)
    spoof = ["6.6.6.6"]
    assert client_address(behind, "203.0.113.5", spoof) == "203.0.113.5"  # not our proxy
    assert client_address(behind, "198.51.100.9", spoof) == "6.6.6.6"  # our proxy: believed
    assert client_address(behind, "not-an-address", spoof) == "not-an-address"
    assert client_address(behind, "::ffff:198.51.100.9", spoof) == "6.6.6.6"  # mapped IPv4


def test_which_entry_of_the_chain_is_the_visitor():
    chain = ["6.6.6.6, 203.0.113.5, 10.1.1.1"]
    everyone = rl._networks("*")[0]
    assert everyone
    left = limits(trust_any_peer=True, proxy_hops=None)
    assert client_address(left, "10.9.9.9", chain) == "6.6.6.6"
    for hops, want in ((1, "10.1.1.1"), (2, "203.0.113.5"), (3, "6.6.6.6"), (9, "6.6.6.6")):
        right = limits(trust_any_peer=True, proxy_hops=hops)
        assert client_address(right, "10.9.9.9", chain) == want, hops
    # Lines of the same header are one list, in order; an empty or absent header is the peer.
    two_lines = ["6.6.6.6", "203.0.113.5"]
    assert client_address(limits(trust_any_peer=True, proxy_hops=2), "10.9.9.9", two_lines) == (
        "6.6.6.6"
    )
    assert client_address(left, "10.9.9.9", []) == "10.9.9.9"
    assert client_address(left, "10.9.9.9", [" , "]) == "10.9.9.9"


def test_a_forwarded_entry_that_is_no_address_falls_back_to_the_peer():
    left = limits(trust_any_peer=True, proxy_hops=None)
    for junk in ("unknown", "<script>", "6.6.6.6.6", "evil.example"):
        assert client_address(left, "10.9.9.9", [junk]) == "10.9.9.9", junk


def test_private_means_the_private_ranges_only():
    private = limits(trusted_proxies=rl._networks("private")[1], proxy_hops=None)
    for peer in ("10.0.3.4", "172.16.0.9", "192.168.1.1", "127.0.0.1", "::1", "fd00::5"):
        assert client_address(private, peer, ["6.6.6.6"]) == "6.6.6.6", peer
    for peer in ("8.8.8.8", "172.32.0.1", "2001:db8::1"):
        assert client_address(private, peer, ["6.6.6.6"]) != "6.6.6.6", peer


def test_a_visitor_key_is_opaque_and_the_same_for_the_same_address():
    a = Limiter(limits())
    b = Limiter(limits())
    assert a.identify("203.0.113.5") == a.identify("203.0.113.5")
    assert a.identify("203.0.113.5") != a.identify("203.0.113.6")
    assert "203" not in a.identify("203.0.113.5")  # a hash, never the address
    assert a.identify("203.0.113.5") != b.identify("203.0.113.5")  # salted per process


# ---- the buckets ------------------------------------------------------------------------------


def test_a_burst_is_allowed_then_refused_with_the_wait_and_it_refills():
    clock = Clock()
    lim = Limiter(limits(write=Rule(3, 60), all_write=None), clock=clock)
    assert [lim.admit("a", "write") for _ in range(3)] == [None, None, None]
    busy = lim.admit("a", "write")
    assert isinstance(busy, Busy) and busy.status == 429 and busy.code == "rate_limited"
    assert busy.retry_after == 20 and busy.scope == "you" and busy.limit == "write"
    assert "try again in 20 seconds" in busy.message and "qpilot app" in busy.message
    assert "own computer" in busy.message
    clock.advance(10)  # half a token back: still not
    again = lim.admit("a", "write")
    assert again is not None and again.retry_after == 10
    clock.advance(10)
    assert lim.admit("a", "write") is None  # one token is back
    assert lim.admit("a", "write") is not None


def test_a_refused_request_costs_nothing():
    clock = Clock()
    lim = Limiter(limits(write=Rule(2, 60), all_write=None), clock=clock)
    assert lim.admit("a", "write") is None and lim.admit("a", "write") is None
    for _ in range(500):  # hammering while refused ...
        assert lim.admit("a", "write") is not None
    clock.advance(30)  # ... does not lengthen the wait: one token after half a minute
    assert lim.admit("a", "write") is None


def test_visitors_have_their_own_buckets():
    lim = Limiter(limits(read=Rule(2, 60), all_read=None), clock=Clock())
    assert lim.admit("a", "read") is None and lim.admit("a", "read") is None
    assert lim.admit("a", "read") is not None
    assert lim.admit("b", "read") is None  # b is not held up by a


def test_reads_writes_and_uploads_are_separate_buckets_and_an_upload_is_also_a_write():
    lim = Limiter(
        limits(read=Rule(1, 60), write=Rule(3, 60), upload=Rule(2, 600),
               all_read=None, all_write=None, all_upload=None),
        clock=Clock(),
    )  # fmt: skip
    assert lim.admit("a", "read") is None and lim.admit("a", "read") is not None
    assert lim.admit("a", "write") is None  # reads used up, writes untouched (2 left)
    assert lim.admit("a", "upload") is None  # one upload token, one write token (1 left)
    assert lim.admit("a", "upload") is None  # (0 write tokens left)
    busy = lim.admit("a", "upload")
    assert busy is not None and busy.limit in ("upload", "write")
    assert lim.admit("a", "write") is not None  # the uploads spent the writes


def test_the_upload_wait_is_in_minutes_when_long_and_says_uploads():
    lim = Limiter(limits(upload=Rule(1, 600), all_upload=None, write=None, all_write=None),
                  clock=Clock())  # fmt: skip
    assert lim.admit("a", "upload") is None
    busy = lim.admit("a", "upload")
    assert busy is not None and busy.retry_after == 600
    assert "uploads" in busy.message and "about 10 minutes" in busy.message


def test_everyone_together_is_the_backstop_when_visitors_are_many():
    clock = Clock()
    lim = Limiter(limits(write=Rule(5, 60), all_write=Rule(6, 60)), clock=clock)
    allowed = sum(lim.admit(f"v{i}", "write") is None for i in range(20))  # 20 visitors, one each
    assert allowed == 6  # the sandbox's own cap, not 20 x 5
    busy = lim.admit("v99", "write")
    assert busy is not None and busy.scope == "everyone"
    assert "other visitors" in busy.message and busy.retry_after == 10


def test_a_global_refusal_leaves_the_visitors_own_tokens_alone():
    lim = Limiter(limits(write=Rule(2, 60), all_write=Rule(1, 60)), clock=Clock())
    assert lim.admit("a", "write") is None  # takes the only global token
    assert lim.admit("b", "write") is not None  # refused by the global bucket ...
    assert lim.admit("b", "write") is not None  # ... without b paying for it
    assert lim._clients["b"].buckets["write"].tokens == 2.0  # noqa: SLF001


def test_a_rule_that_is_off_never_refuses():
    lim = Limiter(limits(read=None, all_read=None), clock=Clock())
    assert all(lim.admit("a", "read") is None for _ in range(5000))


# ---- forgetting visitors -----------------------------------------------------------------------


def test_idle_visitors_are_forgotten_and_memory_stays_bounded():
    clock = Clock()
    lim = Limiter(limits(read=Rule(10, 60), write=Rule(5, 60), upload=Rule(2, 600)), clock=clock)
    for i in range(50):
        lim.admit(f"v{i}", "read")
    assert lim.visitors() == 50
    clock.advance(lim.limits.idle_s - 1)  # the slowest bucket (10 minutes) is not refilled yet
    lim.admit("keeper", "read")
    assert lim.visitors() == 51
    clock.advance(rl.SWEEP_S + 5)  # now the 50 have been idle longer than any bucket needs
    lim.admit("keeper", "read")
    assert lim.visitors() == 1 and "keeper" in lim._clients  # noqa: SLF001


def test_a_flood_of_new_addresses_cannot_grow_the_table_past_its_cap():
    lim = Limiter(limits(max_clients=100), clock=Clock())
    for i in range(1000):
        lim.admit(f"v{i}", "read")
    assert lim.visitors() == 100
    assert "v999" in lim._clients and "v0" not in lim._clients  # noqa: SLF001  (oldest first)


def test_a_visitor_who_is_forgotten_has_a_full_bucket_again_which_is_what_idle_means():
    clock = Clock()
    lim = Limiter(limits(write=Rule(2, 60), all_write=None), clock=clock)
    lim.admit("a", "write"), lim.admit("a", "write")
    assert lim.admit("a", "write") is not None
    clock.advance(lim.limits.idle_s + rl.SWEEP_S + 1)
    lim.admit("b", "write")  # the sweep runs
    assert lim.visitors() == 1
    assert lim.admit("a", "write") is None and lim.admit("a", "write") is None


# ---- what is a read, a write, an upload ---------------------------------------------------------


@pytest.mark.parametrize(
    "method, path, ctype, want",
    [
        ("GET", "/api/settings", "", "read"),
        ("HEAD", "/api/studies/abc/results", "", "read"),
        ("GET", "/api/events", "", "stream"),
        ("GET", "/api/system", "", "health"),
        ("PUT", "/api/settings", "application/json", "write"),
        ("POST", "/api/studies/abc/cards/c1/decide", "application/json", "write"),
        ("DELETE", "/api/x", "", "write"),
        ("POST", "/api/workspaces", "multipart/form-data; boundary=x", "upload"),
        ("POST", "/api/sessions/s/sheet", "Multipart/Form-Data", "upload"),
        # POSTs that only compute are reads: a what-if slider is not a flood of writes
        ("POST", "/api/studies/abc/audit/whatif", "application/json", "read"),
        ("POST", "/api/audits/abc/samples", "application/json", "read"),
        ("POST", "/api/studies/abc/claims", "application/json", "read"),
        ("POST", "/api/studies/abc/planner/layout", "application/json", "read"),
        ("POST", "/api/studies/abc/trace/ODC1/without", "application/json", "read"),
        # ... but not the ones that start work
        ("POST", "/api/studies/abc/claims/read", "application/json", "write"),
        ("POST", "/api/studies/abc/audit", "application/json", "write"),
        ("PUT", "/api/studies/abc/claims", "application/json", "write"),
    ],
)
def test_requests_are_sorted_by_what_they_do(method, path, ctype, want):
    assert request_kind(method, path, ctype) == want


def _post_paths() -> list[str]:
    from fastapi.routing import APIRoute

    from qpilot.web.routers import ROUTERS

    return [
        "/api" + re.sub(r"\{[^}]+\}", "abc", route.path)
        for router in ROUTERS
        for route in router.routes
        if isinstance(route, APIRoute) and "POST" in route.methods
    ]


def test_every_compute_only_post_is_a_real_route():
    """The list cannot drift from the API: each pattern still matches a POST route."""
    paths = _post_paths()
    for pattern in rl.COMPUTE_POSTS:
        assert any(pattern.match(p) for p in paths), pattern.pattern


def test_the_routes_that_start_jobs_are_found_and_computing_ones_are_not():
    heavy = job_starting_paths()
    started = [p for p in _post_paths() if any(h.match(p) for h in heavy)]
    assert len(heavy) >= 19 and len(started) >= 19  # the audit, the supplement, ...
    for path in (
        "/api/studies/abc/audit",
        "/api/studies/abc/report/export",
        "/api/sessions/abc/propose/design",
        "/api/sessions/abc/propose/curves",
        "/api/workspaces",
    ):
        assert any(h.match(path) for h in heavy), path
    for path in ("/api/studies/abc/audit/whatif", "/api/studies/abc/cards/c1/decide"):
        assert not any(h.match(path) for h in heavy), path
        assert request_kind("POST", path, "application/json") in ("read", "write")


# ---- slow work ----------------------------------------------------------------------------------


def test_a_visitor_may_run_three_jobs_and_the_sandbox_eight():
    lim = Limiter(limits(jobs=3, all_jobs=8), clock=Clock())
    mine = [job("a") for _ in range(2)]
    assert lim.jobs_busy("a", mine) is None
    busy = lim.jobs_busy("a", [*mine, job("a")])
    assert busy is not None and busy.limit == "jobs" and busy.scope == "you"
    assert "3 analyses" in busy.message and "qpilot app" in busy.message
    others = [job(f"v{i}") for i in range(8)]
    assert lim.jobs_busy("a", others[:7]) is None
    full = lim.jobs_busy("a", others)
    assert full is not None and full.scope == "everyone" and "other visitors" in full.message


def test_preparing_a_view_is_not_counted_as_a_visitors_job():
    lim = Limiter(limits(jobs=1, all_jobs=2), clock=Clock())
    prep = [job("a", kind=k) for k in ("gate.run", "trace.load", "audit.load", "warm", "prepare")]
    assert lim.jobs_busy("a", prep) is None
    lim.admit_job("audit", "a", prep)  # a new job passes: the preparing jobs do not count
    lim.admit_job("gate.run", "a", [job("a")])  # and preparing is never refused
    with pytest.raises(Busy):
        lim.admit_job("audit", "a", [job("a")])
    lim.admit_job("audit", None, [job("a"), job("a"), job("b")])  # not a visitor's own request


def test_the_wait_for_a_job_is_the_shortest_time_it_has_left():
    wall = Clock()
    lim = Limiter(limits(jobs=2), clock=Clock(), wall=wall)
    running = [job("a", typical_s=50.0, started=wall.now - 45), job("a", typical_s=200.0)]
    busy = lim.jobs_busy("a", running)
    assert busy is not None and busy.retry_after == 5  # about 5 s left of the quicker job
    unknown = lim.jobs_busy("a", [job("a", typical_s=None), job("a", typical_s=None)])
    assert unknown is not None and unknown.retry_after == 10  # no estimate: ten seconds
    long = lim.jobs_busy("a", [job("a", typical_s=9999.0), job("a", typical_s=9999.0)])
    assert long is not None and long.retry_after == 120  # never more than two minutes


class _Running:
    """Jobs held open until the test lets them go."""

    def __init__(self) -> None:
        self.gate = threading.Event()
        self.runner = JobRunner(EventBus())

    def start(self, who: str | None, key: str, kind: str = "audit", **kw) -> Job:
        token = REQUESTER.set(who)
        try:
            return self.runner.submit(
                kind, lambda progress: self.gate.wait(30), title="t", key=key, **kw
            )
        finally:
            REQUESTER.reset(token)

    def close(self) -> None:
        self.gate.set()
        self.runner.shutdown()


@pytest.fixture
def running():
    held = _Running()
    yield held
    held.close()


def test_the_job_runner_refuses_a_fourth_job_and_remembers_who_asked(running):
    lim = Limiter(limits(jobs=3, all_jobs=0), clock=Clock())
    running.runner.admission = lim.admit_job
    jobs = [running.start("a", f"k{i}") for i in range(3)]
    assert [j.owner for j in jobs] == ["a", "a", "a"]
    with pytest.raises(Busy) as err:
        running.start("a", "k3")
    assert err.value.retry_after >= 5 and "3 analyses" in str(err.value)
    assert running.start("b", "other").owner == "b"  # another visitor has their own three
    assert len(running.runner.active()) == 4  # the refused job was never made


def test_asking_again_for_work_already_running_is_never_refused(running):
    running.runner.admission = Limiter(limits(jobs=2), clock=Clock()).admit_job
    first = running.start("a", "same")
    running.start("a", "other")
    assert running.start("a", "same") is first  # the running job, not a third


def test_work_that_is_not_a_visitors_request_is_not_limited(running):
    running.runner.admission = Limiter(limits(jobs=1, all_jobs=1), clock=Clock()).admit_job
    for i in range(5):  # warming at start, the CLI, tests: no requester
        assert running.start(None, f"k{i}").owner is None
    for i in range(5):  # background work nobody asked for
        running.start("a", f"b{i}", background=True)
    assert len(running.runner.active()) == 10


def test_jobs_can_be_started_again_when_they_finish(running):
    running.runner.admission = Limiter(limits(jobs=1), clock=Clock()).admit_job
    running.start("a", "one")
    with pytest.raises(Busy):
        running.start("a", "two")
    running.gate.set()
    for _ in range(300):
        if not running.runner.active():
            break
        threading.Event().wait(0.01)
    running.gate = threading.Event()
    assert running.start("a", "two") is not None


# ---- live streams -------------------------------------------------------------------------------


def test_a_visitor_keeps_a_few_live_streams_and_closing_one_makes_room():
    lim = Limiter(limits(streams=2, all_streams=3), clock=Clock())
    assert lim.open_stream("a") is None and lim.open_stream("a") is None
    busy = lim.open_stream("a")
    assert busy is not None and busy.limit == "streams" and "close one" in busy.message
    assert lim.open_stream("b") is None  # the third of the sandbox's three
    full = lim.open_stream("c")
    assert full is not None and full.scope == "everyone"
    lim.close_stream("a")
    assert lim.open_stream("c") is None
    for who in ("a", "b", "c"):
        lim.close_stream(who)
        lim.close_stream(who)  # closing more than opened cannot go below zero
    assert lim._streams == {} and lim._streams_all == 0  # noqa: SLF001


def _asgi(app, path, *, method="GET", client=("203.0.113.7", 1), headers=()):
    async def go():
        sent: list[dict] = []

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message):
            sent.append(message)

        scope = {"type": "http", "method": method, "path": path, "headers": list(headers),
                 "client": client}  # fmt: skip
        await app(scope, receive, send)
        return sent

    return go()


def test_streams_over_the_cap_are_refused_while_open_and_counted_free_when_they_end():
    async def main():
        release = asyncio.Event()
        opened = 0

        async def inner(scope, receive, send):
            nonlocal opened
            opened += 1
            await release.wait()
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"x"})

        lim = Limiter(limits(streams=2, all_streams=0))
        mw = RateLimit(inner, lim)
        first = [asyncio.create_task(_asgi(mw, "/api/events")) for _ in range(2)]
        await asyncio.sleep(0.05)
        assert opened == 2
        refused = await _asgi(mw, "/api/events")
        assert refused[0]["status"] == 429 and opened == 2  # never reached the route
        headers = dict(refused[0]["headers"])
        assert headers[b"retry-after"] == b"5"
        other = asyncio.create_task(_asgi(mw, "/api/events", client=("203.0.113.8", 1)))
        await asyncio.sleep(0.05)
        assert opened == 3  # another visitor has their own streams
        release.set()
        done = await asyncio.gather(*first, other)
        assert all(sent[0]["status"] == 200 for sent in done)
        assert lim._streams == {}  # noqa: SLF001
        again = await _asgi(mw, "/api/events")
        assert again[0]["status"] == 200  # room again once they ended

    asyncio.run(main())


def test_a_stream_that_fails_is_still_counted_out():
    async def main():
        async def inner(scope, receive, send):
            raise RuntimeError("boom")

        lim = Limiter(limits(streams=1))
        mw = RateLimit(inner, lim)
        for _ in range(3):
            with pytest.raises(RuntimeError):
                await _asgi(mw, "/api/events")
        assert lim._streams == {}  # noqa: SLF001

    asyncio.run(main())


# ---- the middleware over a small app ------------------------------------------------------------


def _small(lim: Limiter, *, heavy=(), runner: JobRunner | None = None):
    """An app with the server's error shape for a refused job, behind the middleware."""
    app = FastAPI()
    calls: list[str] = []

    @app.exception_handler(Busy)
    async def busy(_: Request, exc: Busy) -> JSONResponse:
        return JSONResponse(
            exc.body(), status_code=429, headers={"Retry-After": str(exc.retry_after)}
        )

    @app.get("/api/x")
    def read() -> dict:
        calls.append("read")
        return {"ok": True}

    @app.post("/api/x")
    def write() -> dict:
        calls.append("write")
        return {"ok": True}

    @app.post("/api/up")
    def up() -> dict:
        calls.append("up")
        return {"ok": True}

    @app.get("/api/system")
    def system() -> dict:
        return {"ok": True}

    @app.get("/")
    def page() -> dict:
        return {"page": True}

    if runner is not None:

        @app.post("/api/start", status_code=202)
        def start() -> dict:
            calls.append("start")
            job = runner.submit(
                "audit", lambda p: None, title="t", key=str(len(calls)), dedupe=False
            )
            return {"job": job.id}

    app.add_middleware(RateLimit, limiter=lim, jobs=runner, heavy=heavy)
    return app, calls


def test_a_refusal_is_a_429_in_words_with_retry_after_and_the_route_never_runs():
    app, calls = _small(Limiter(limits(write=Rule(2, 60), all_write=None), clock=Clock()))
    with TestClient(app) as c:
        assert [c.post("/api/x").status_code for _ in range(2)] == [200, 200]
        r = c.post("/api/x")
    assert r.status_code == 429 and calls == ["write", "write"]
    assert r.headers["retry-after"] == "30"
    error = r.json()["error"]
    assert error["code"] == "rate_limited" and "try again in 30 seconds" in error["message"]
    assert error["details"] == {"retry_after_s": 30, "limit": "write", "scope": "you"}


def test_reads_are_limited_apart_from_writes():
    app, _ = _small(Limiter(limits(read=Rule(2, 60), all_read=None), clock=Clock()))
    with TestClient(app) as c:
        assert [c.get("/api/x").status_code for _ in range(3)] == [200, 200, 429]
        assert c.post("/api/x").status_code == 200  # writes have their own allowance


def test_uploads_count_apart_and_the_body_is_never_read_once_refused():
    lim = Limiter(limits(upload=Rule(1, 600), all_upload=None), clock=Clock())
    app, calls = _small(lim)
    with TestClient(app) as c:
        files = {"f": ("a.rdml", io.BytesIO(b"x" * 100))}
        assert c.post("/api/up", files=files).status_code == 200
        r = c.post("/api/up", files={"f": ("a.rdml", io.BytesIO(b"x" * 100))})
    assert r.status_code == 429 and calls == ["up"]
    assert r.json()["error"]["details"]["limit"] == "upload"
    assert "uploads" in r.json()["error"]["message"]


def test_the_page_and_the_health_check_are_never_limited():
    app, _ = _small(Limiter(limits(read=Rule(1, 600), all_read=None), clock=Clock()))
    with TestClient(app) as c:
        assert c.get("/api/x").status_code == 200 and c.get("/api/x").status_code == 429
        assert all(c.get("/api/system").status_code == 200 for _ in range(200))
        assert all(c.get("/").status_code == 200 for _ in range(200))
        assert all(c.head("/").status_code in (200, 405) for _ in range(20))


def test_a_forwarded_address_is_believed_only_from_a_trusted_proxy():
    behind = limits(
        read=Rule(2, 600), all_read=None, trusted_proxies=rl._networks("198.51.100.0/24")[1],
        proxy_hops=None,
    )  # fmt: skip
    app, _ = _small(Limiter(behind, clock=Clock()))
    xff = "x-forwarded-for"
    # a visitor who sends a new address each time, from outside: still one visitor
    with TestClient(app, client=("203.0.113.5", 1)) as outside:
        codes = [outside.get("/api/x", headers={xff: f"6.6.6.{i}"}).status_code for i in range(4)]
    assert codes == [200, 200, 429, 429]
    # through the proxy: each forwarded address is its own visitor, and the same one is the same
    with TestClient(app, client=("198.51.100.9", 1)) as proxy:
        one = [proxy.get("/api/x", headers={xff: "7.7.7.7"}).status_code for _ in range(3)]
        two = [proxy.get("/api/x", headers={xff: "7.7.7.8, 198.51.100.9"}).status_code
               for _ in range(3)]  # fmt: skip
        nothing = [proxy.get("/api/x").status_code for _ in range(3)]  # no header: the proxy itself
    assert one == [200, 200, 429] and two == [200, 200, 429] and nothing == [200, 200, 429]


def test_a_job_refused_inside_a_route_is_a_429_too():
    lim = Limiter(limits(jobs=1, all_jobs=0), clock=Clock())
    runner = JobRunner(EventBus())
    gate = threading.Event()
    runner.admission = lim.admit_job
    app, calls = _small(lim, runner=runner)  # no heavy paths: only the job runner can refuse
    try:
        original = runner.submit

        def slow(kind, fn, **kw):  # the started job stays running
            return original(kind, lambda p: gate.wait(30), **kw)

        runner.submit = slow  # type: ignore[method-assign]
        with TestClient(app) as c:
            assert c.post("/api/start").status_code == 202
            r = c.post("/api/start")
        assert r.status_code == 429 and calls == ["start", "start"]  # the route ran, then refused
        assert (
            r.json()["error"]["details"]["limit"] == "jobs" and int(r.headers["retry-after"]) >= 5
        )
    finally:
        gate.set()
        runner.shutdown()


def test_a_route_that_starts_a_job_is_refused_before_it_runs_when_the_visitor_is_full():
    lim = Limiter(limits(jobs=1, all_jobs=0), clock=Clock())
    runner = JobRunner(EventBus())
    gate = threading.Event()
    runner.admission = lim.admit_job
    app, calls = _small(lim, heavy=[re.compile(r"^/api/start$")], runner=runner)
    try:
        original = runner.submit
        runner.submit = lambda kind, fn, **kw: original(kind, lambda p: gate.wait(30), **kw)  # type: ignore[method-assign]
        with TestClient(app) as c:
            assert c.post("/api/start").status_code == 202
            r = c.post("/api/start")
            assert r.status_code == 429 and calls == ["start"]  # the second never ran
            assert c.get("/api/x").status_code == 200  # reading goes on while jobs run
        with TestClient(app, client=("203.0.113.99", 1)) as other:
            assert other.post("/api/start").status_code == 202  # another visitor is not held up
    finally:
        gate.set()
        runner.shutdown()


# ---- the whole server ---------------------------------------------------------------------------


@pytest.fixture
def hosted(monkeypatch, web_store):
    """A factory: the real app in hosted mode, with extra environment, as one visitor."""
    made: list = []

    def make(env: dict[str, str] | None = None, peer: str = "203.0.113.5", token: bool = False):
        for k, v in {**HOSTED, **(env or {})}.items():
            monkeypatch.setenv(k, v)
        ctx = make_context(web_store, token="launch-key", watch=False)
        app = create_app(ctx)
        client = TestClient(app, base_url=f"https://{SPACE}", client=(peer, 40000))
        made.append((ctx, client))
        client.__enter__()
        if token:
            client.headers["x-qpilot-token"] = "launch-key"
        return app, ctx, client

    yield make
    for ctx, client in made:
        client.__exit__(None, None, None)
        ctx.close()


def test_the_real_page_is_limited_per_visitor_and_the_health_check_never(hosted):
    app, ctx, c = hosted({"QPILOT_RATE_READS": "3/min", "QPILOT_RATE_WRITES": "2/min"})
    assert [c.get("/api/settings").status_code for _ in range(4)] == [200, 200, 200, 429]
    r = c.get("/api/settings")
    assert r.status_code == 429 and int(r.headers["retry-after"]) >= 1
    assert r.json()["error"]["code"] == "rate_limited"
    assert "content-security-policy" in r.headers  # the guard's headers are on the refusal
    assert r.headers["cache-control"] == "no-store"  # once, not twice
    assert all(c.get("/api/system").status_code == 200 for _ in range(30))
    assert all(c.get("/").status_code == 200 for _ in range(30))
    body = {"autonomy": "suggest"}
    puts = [c.put("/api/settings", json=body, headers=ORIGIN).status_code for _ in range(3)]
    assert puts == [200, 200, 429]
    assert ctx.jobs.admission is not None and app.state.limiter.limits.read == Rule(3, 60)


def test_the_real_page_gets_the_proxys_visitor_not_the_proxy(hosted):
    env = {
        "QPILOT_RATE_READS": "2/min",
        "QPILOT_TRUSTED_PROXIES": "*",
        "QPILOT_PROXY_HOPS": "leftmost",
    }
    _app, _ctx, c = hosted(env, peer="10.20.30.40")
    xff = "x-forwarded-for"
    a = [c.get("/api/settings", headers={xff: "198.51.100.1, 76.76.21.21"}).status_code
         for _ in range(3)]  # fmt: skip
    b = [c.get("/api/settings", headers={xff: "198.51.100.2, 76.76.21.21"}).status_code
         for _ in range(3)]  # fmt: skip
    assert a == [200, 200, 429] and b == [200, 200, 429]  # two visitors behind one proxy


def test_without_a_trusted_proxy_a_spoofed_header_buys_no_new_bucket(hosted):
    _app, _ctx, c = hosted({"QPILOT_RATE_READS": "2/min"})
    codes = [c.get("/api/settings", headers={"x-forwarded-for": f"9.9.9.{i}"}).status_code
             for i in range(5)]  # fmt: skip
    assert codes == [200, 200, 429, 429, 429]


def test_uploads_are_limited_before_anything_is_read(hosted):
    _app, _ctx, c = hosted({"QPILOT_RATE_UPLOADS": "2/10min"})

    def upload():
        return c.post(
            "/api/workspaces",
            files={"rdml": ("not-rdml.txt", io.BytesIO(b"x" * 100))},
            headers=ORIGIN,
        )

    first = [upload().status_code for _ in range(2)]
    assert first == [400, 400]  # refused as a file of the wrong kind: it was taken as an upload
    r = upload()
    assert r.status_code == 429 and r.json()["error"]["details"]["limit"] == "upload"
    assert int(r.headers["retry-after"]) > 60


def test_a_visitor_with_jobs_running_cannot_start_another_through_the_page(hosted, tmp_path):
    app, ctx, c = hosted({"QPILOT_RATE_JOBS": "2"})
    me = app.state.limiter.identify("203.0.113.5")
    gate = threading.Event()
    token = REQUESTER.set(me)
    try:
        for i in range(2):
            ctx.jobs.submit("audit", lambda p: gate.wait(30), title="t", key=f"k{i}")
    finally:
        REQUESTER.reset(token)
    try:
        r = c.post("/api/studies/aaaaaaaaaaaa/audit", json={}, headers=ORIGIN)
        assert r.status_code == 429 and r.json()["error"]["details"]["limit"] == "jobs"
        assert "2 analyses" in r.json()["error"]["message"]
        # a view can still be read, and another visitor still gets their own answer (not 429)
        assert c.get("/api/settings").status_code == 200
        other = TestClient(app, base_url=f"https://{SPACE}", client=("203.0.113.6", 1))
        with other:
            r = other.post("/api/studies/aaaaaaaaaaaa/audit", json={}, headers=ORIGIN)
            assert r.status_code != 429
    finally:
        gate.set()


def test_local_mode_is_never_limited(monkeypatch, web_store):
    for name in ("QPILOT_HOSTED", "QPILOT_RATE_READS", "QPILOT_RATE_WRITES"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("QPILOT_RATE_READS", "1/min")  # set, but a computer ignores it
    monkeypatch.setenv("QPILOT_RATE_WRITES", "1/min")
    ctx = make_context(web_store, token="launch-key", watch=False)
    try:
        app = create_app(ctx)
        assert not hasattr(app.state, "limiter") and ctx.jobs.admission is None
        with TestClient(app, base_url="http://127.0.0.1:7860") as c:
            c.headers["x-qpilot-token"] = "launch-key"
            same = {"origin": "http://127.0.0.1:7860"}
            assert all(c.get("/api/settings").status_code == 200 for _ in range(400))
            body = {"autonomy": "suggest"}
            assert all(c.put("/api/settings", json=body, headers=same).status_code == 200
                       for _ in range(100))  # fmt: skip
    finally:
        ctx.close()


def test_a_hosted_server_can_switch_the_limit_off(hosted):
    app, ctx, c = hosted({"QPILOT_RATE_LIMIT": "off", "QPILOT_RATE_READS": "1/min"})
    assert not hasattr(app.state, "limiter") and ctx.jobs.admission is None
    assert all(c.get("/api/settings").status_code == 200 for _ in range(50))


def test_a_refused_read_is_never_given_an_etag_or_taken_for_a_304(hosted):
    _app, _ctx, c = hosted({"QPILOT_RATE_READS": "1/min"})
    first = c.get("/api/settings")
    assert first.status_code == 200 and first.headers.get("etag")
    again = c.get("/api/settings", headers={"if-none-match": first.headers["etag"]})
    assert again.status_code == 429 and "etag" not in again.headers  # not a 304, not tagged


def test_the_space_sets_the_limit_it_documents():
    text = (Path(__file__).parents[2] / "deploy" / "hf-space" / "app.py").read_text("utf-8")
    env = dict(re.findall(r'"(QPILOT_[A-Z_]+)":\s*"([^"]*)"', text))
    got = RateLimits.from_env(env)
    assert got is not None, "the Space is hosted and the limit is on"
    assert got.trust_any_peer and got.proxy_hops is None  # Vercel overwrites X-Forwarded-For
    assert got.client_ip_header == "x-forwarded-for"
    assert (got.read, got.write, got.upload) == (Rule(240, 60), Rule(20, 60), Rule(6, 600))
    assert (got.jobs, got.all_jobs, got.streams) == (3, 8, 6)
    assert "proxy_headers=False" in text  # uvicorn must not rewrite the peer itself
