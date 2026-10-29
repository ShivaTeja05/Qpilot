"""A per-visitor rate limit for the public sandbox (``QPILOT_HOSTED=1`` only).

On a person's own computer nothing here runs: :func:`qpilot.web.server.create_app` adds the
middleware only when :meth:`RateLimits.from_env` finds hosted mode (RT-EX-015). The sandbox is
shared by every visitor, so one of them must not be able to keep its few job workers busy, fill
its disk through uploads, or fill the event-stream slots. Per visitor (and, as a backstop, for
everyone together):

* **Token buckets** by what a request is: reads (``GET``, and the ``POST`` requests that only
  compute), writes, uploads (a multipart body; also a write). A bucket holds its whole allowance
  at the start and refills steadily, so a burst is allowed and a steady flood is not.
* **Slow work.** A visitor may have a few jobs (audit, supplement export, curve check, design
  proposal, ...) running at once, and the sandbox only so many in all. The check is made twice:
  before a route that starts a job runs (so nothing is half done), and again when the job is
  made (:attr:`qpilot.web.jobs.JobRunner.admission`, which also knows the kind and the dedupe).
  Jobs that only prepare a view (the gate, Trace, the audit's load) are not counted: reading a
  view must not be refused for work nobody asked for.
* **Live event streams.** A few per visitor (a browser keeps about six per site anyway).

A refused request is answered ``429 rate_limited`` with ``Retry-After`` and a sentence that says
how long to wait and that qPilot on one's own computer has no limit. The page itself, its
assets and ``/api/system`` (the health check) are never limited.

**Who a visitor is.** The address of the socket peer, unless the peer is one of
``QPILOT_TRUSTED_PROXIES`` (addresses or networks, ``private`` for the private ranges, ``*`` for
"every peer is our platform's proxy": a container that can only be reached through it). Only
then is ``QPILOT_CLIENT_IP_HEADER`` (``X-Forwarded-For``) read, and ``QPILOT_PROXY_HOPS`` says
which entry is the visitor: ``leftmost`` when the outermost proxy overwrites the header with the
address it saw (Vercel does), else a number N, the Nth entry from the right (1: the address the
nearest proxy saw; each proxy that appends adds one). A header from an untrusted peer is ignored,
so a visitor cannot choose their own bucket by sending one. An address that is not an address is
ignored too. IPv6 addresses are grouped by their /64 (one network is one visitor). Visitors are
kept in memory only, under a salted hash that is lost at restart, and forgotten once idle for
longer than the slowest bucket needs to refill (at most ``QPILOT_RATE_CLIENTS`` are kept).

**The limit of the limit.** Behind a chain of proxies a visitor who can reach the server without
the outermost proxy can send any address they like and get a fresh bucket each time. The
sandbox-wide buckets and job cap, the upload and unpacked-size caps and the disk floor
(``QPILOT_MIN_FREE_MB``) bound what such a visitor can do; a signed header from the proxy would
close it (not available on Vercel's rewrites).
"""

from __future__ import annotations

import hashlib
import ipaddress
import math
import os
import re
import secrets
import threading
import time
from collections import OrderedDict
from collections.abc import Callable, Iterable, Mapping, MutableMapping
from dataclasses import dataclass
from typing import Any

from qpilot.web.jobs import REQUESTER, Job
from qpilot.web.security import WRITE_METHODS, Hosting

IPNetwork = ipaddress.IPv4Network | ipaddress.IPv6Network

#: Never limited: the health check (the page and its assets are not under ``/api``).
HEALTH_PATHS = frozenset({"/api/system", "/api/health"})
STREAM_PATH = "/api/events"
#: Jobs that only prepare a view in memory. Reading a view is never refused for them.
LIGHT_JOBS = frozenset(
    {"warm", "warm.all", "prepare", "gate.run", "trace.load", "audit.load", "prism.check"}
)
#: ``POST`` requests that only compute (nothing is written): they count as reads, so a what-if
#: slider is not a flood of writes. The page lists the same in ``frontend/src/demo/key.ts``.
COMPUTE_POSTS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p)
    for p in (
        r"^/api/studies/[^/]+/audit/(whatif|samples|verify)$",
        r"^/api/audits/[^/]+/(whatif|samples|verify)$",
        r"^/api/studies/[^/]+/claims$",
        r"^/api/studies/[^/]+/planner(/layout)?$",
        r"^/api/studies/[^/]+/trace/[^/]+/without$",
    )
)
OWN_COMPUTER = "To work without limits, install qPilot and run `qpilot app` on your own computer."
#: How often idle visitors are looked for.
SWEEP_S = 30.0
PRIVATE_NETWORKS: tuple[IPNetwork, ...] = (
    ipaddress.IPv4Network((10 << 24, 8)),  # (not spelled out: a test keeps "every interface" out)
    *(
        ipaddress.ip_network(n, strict=False)
        for n in (
            "127.0.0.1/8",
            "172.16.0.1/12",
            "192.168.0.1/16",
            "169.254.0.1/16",
            "100.64.0.1/10",
            "::1/128",
            "fc00::/7",
            "fe80::/10",
        )
    ),
)


# ---- the settings ----------------------------------------------------------------------------


@dataclass(frozen=True)
class Rule:
    """``count`` requests per ``window_s`` seconds: the bucket's size and its refill."""

    count: float
    window_s: float

    @property
    def rate(self) -> float:
        """Tokens added per second."""
        return self.count / self.window_s


_UNITS = {"": 1.0, "s": 1.0, "sec": 1.0, "m": 60.0, "min": 60.0, "h": 3600.0, "hour": 3600.0}
_RULE = re.compile(r"^(\d+(?:\.\d+)?)\s*/\s*(\d*(?:\.\d+)?)\s*([a-z]*)$")
_OFF = frozenset({"off", "none", "unlimited", "0"})


def parse_rule(text: str | None, default: Rule | None) -> Rule | None:
    """``240/min``, ``6/10min``, ``20/60`` (seconds), ``2/h``; ``off`` or ``0``: no limit (None).

    Unset, or anything that is no rule, is ``default``.
    """
    word = (text or "").strip().lower()
    if word in _OFF:
        return None
    found = _RULE.match(word)
    if not found or found.group(3) not in _UNITS:
        return default
    window = (float(found.group(2)) if found.group(2) else 1.0) * _UNITS[found.group(3)]
    count = float(found.group(1))
    return Rule(count, window) if count > 0 and window > 0 else None


def _int(text: str | None, default: int) -> int:
    try:
        return max(int((text or "").strip()), 0) if (text or "").strip() else default
    except ValueError:
        return default


def _networks(text: str | None) -> tuple[bool, tuple[IPNetwork, ...]]:
    """(every peer is a trusted proxy, the trusted networks) from ``QPILOT_TRUSTED_PROXIES``."""
    anyone = False
    nets: list[IPNetwork] = []
    for item in (text or "").split(","):
        item = item.strip().lower()
        if not item:
            continue
        if item == "*":
            anyone = True
        elif item == "private":
            nets.extend(PRIVATE_NETWORKS)
        else:
            try:
                nets.append(ipaddress.ip_network(item, strict=False))
            except ValueError:  # not an address: trusts nobody
                continue
    return anyone, tuple(nets)


@dataclass(frozen=True)
class RateLimits:
    """The public sandbox's limits (environment; see the module doc for the names).

    A rule or a number of ``None``/``0`` is unlimited. Defaults: a visitor may read 240 times a
    minute (the page asks for about 4 views per section it opens), write 20 times a minute
    and upload 6 files in 10 minutes, have 3 jobs running and 6 live streams open; everyone
    together: ten visitors' reads, 200 writes a minute, 30 uploads in 10 minutes, 8 jobs.
    """

    read: Rule | None = Rule(240, 60)
    write: Rule | None = Rule(20, 60)
    upload: Rule | None = Rule(6, 600)
    all_read: Rule | None = Rule(2400, 60)
    all_write: Rule | None = Rule(200, 60)
    all_upload: Rule | None = Rule(30, 600)
    jobs: int = 3
    all_jobs: int = 8
    streams: int = 6
    all_streams: int = 200
    max_clients: int = 20000
    trust_any_peer: bool = False
    trusted_proxies: tuple[IPNetwork, ...] = ()
    client_ip_header: str = "x-forwarded-for"
    #: ``None``: the leftmost entry; N: the Nth from the right (see the module doc).
    proxy_hops: int | None = 1

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> RateLimits | None:
        """The limits of a hosted server, or None (local mode, or ``QPILOT_RATE_LIMIT=off``)."""
        env = os.environ if env is None else env
        if not Hosting.from_env(env).hosted:
            return None
        if (env.get("QPILOT_RATE_LIMIT") or "").strip().lower() in ("off", "0", "no"):
            return None
        d = cls()

        anyone, nets = _networks(env.get("QPILOT_TRUSTED_PROXIES"))
        hops_text = (env.get("QPILOT_PROXY_HOPS") or "").strip().lower()
        hops: int | None = d.proxy_hops
        if hops_text in ("leftmost", "left", "first"):
            hops = None
        elif hops_text.isdigit() and int(hops_text) >= 1:
            hops = int(hops_text)
        header = (env.get("QPILOT_CLIENT_IP_HEADER") or "").strip().lower()
        return cls(
            read=parse_rule(env.get("QPILOT_RATE_READS"), d.read),
            write=parse_rule(env.get("QPILOT_RATE_WRITES"), d.write),
            upload=parse_rule(env.get("QPILOT_RATE_UPLOADS"), d.upload),
            all_read=parse_rule(env.get("QPILOT_RATE_READS_ALL"), d.all_read),
            all_write=parse_rule(env.get("QPILOT_RATE_WRITES_ALL"), d.all_write),
            all_upload=parse_rule(env.get("QPILOT_RATE_UPLOADS_ALL"), d.all_upload),
            jobs=_int(env.get("QPILOT_RATE_JOBS"), d.jobs),
            all_jobs=_int(env.get("QPILOT_RATE_JOBS_ALL"), d.all_jobs),
            streams=_int(env.get("QPILOT_RATE_STREAMS"), d.streams),
            all_streams=_int(env.get("QPILOT_RATE_STREAMS_ALL"), d.all_streams),
            max_clients=max(_int(env.get("QPILOT_RATE_CLIENTS"), d.max_clients), 100),
            trust_any_peer=anyone,
            trusted_proxies=nets,
            client_ip_header=header or d.client_ip_header,
            proxy_hops=hops,
        )

    @property
    def idle_s(self) -> float:
        """A visitor is forgotten after this long without a request: the slowest refill."""
        windows = [r.window_s for r in (self.read, self.write, self.upload) if r is not None]
        return max(windows, default=60.0) + 60.0


# ---- who is asking ----------------------------------------------------------------------------


def parse_address(text: str) -> str | None:
    """A normalised address from a header entry (``1.2.3.4``, ``1.2.3.4:80``, ``[::1]:80``).

    IPv4-mapped IPv6 addresses are the IPv4 address; an IPv6 address is its /64 network
    (``2001:db8:1:2::/64``). Anything that is no address is None.
    """
    text = text.strip().strip('"')
    if text.startswith("["):
        end = text.find("]")
        text = text[1:end] if end > 0 else ""
    elif text.count(":") == 1:  # IPv4 with a port
        text = text.split(":", 1)[0]
    text = text.split("%", 1)[0]  # an IPv6 zone
    try:
        ip = ipaddress.ip_address(text)
    except ValueError:
        return None
    if isinstance(ip, ipaddress.IPv6Address):
        if ip.ipv4_mapped is not None:
            return str(ip.ipv4_mapped)
        return str(ipaddress.ip_network(f"{ip}/64", strict=False))
    return str(ip)


def _peer_trusted(limits: RateLimits, peer: str | None) -> bool:
    if limits.trust_any_peer:
        return True
    if not peer or not limits.trusted_proxies:
        return False
    try:
        ip = ipaddress.ip_address(peer.split("%", 1)[0])
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return any(ip in net for net in limits.trusted_proxies if net.version == ip.version)


def client_address(limits: RateLimits, peer: str | None, forwarded: Iterable[str]) -> str:
    """The visitor's address: the socket peer, or the forwarded one when the peer is trusted.

    ``forwarded`` holds the values of every header line named by ``client_ip_header``.
    """
    if _peer_trusted(limits, peer):
        chain = [e for v in forwarded for e in v.split(",") if e.strip()]
        if chain:
            hops = limits.proxy_hops
            pick = chain[0] if hops is None or len(chain) < hops else chain[-hops]
            found = parse_address(pick)
            if found is not None:
                return found
    return parse_address(peer or "") or (peer or "unknown")


# ---- the buckets ------------------------------------------------------------------------------


class _Bucket:
    """One token bucket: ``tokens`` at the time ``at``."""

    __slots__ = ("at", "tokens")

    def __init__(self, rule: Rule, now: float) -> None:
        self.tokens = rule.count
        self.at = now

    def wait(self, rule: Rule, now: float) -> float:
        """Refill to ``now``; the seconds until one token is there (0: one is)."""
        self.tokens = min(rule.count, self.tokens + max(now - self.at, 0.0) * rule.rate)
        self.at = now
        return 0.0 if self.tokens >= 1.0 else (1.0 - self.tokens) / rule.rate


class _Client:
    """A visitor: their buckets and when they were last seen."""

    __slots__ = ("buckets", "seen")

    def __init__(self, now: float) -> None:
        self.buckets: dict[str, _Bucket] = {}
        self.seen = now


#: The buckets a kind of request takes a token from.
TAKES: dict[str, tuple[str, ...]] = {
    "read": ("read",),
    "write": ("write",),
    "upload": ("upload", "write"),
}


def in_words(seconds: int) -> str:
    """``12 seconds``, ``about 2 minutes``."""
    if seconds < 90:
        return f"{seconds} second{'' if seconds == 1 else 's'}"
    return f"about {round(seconds / 60)} minutes"


class Busy(Exception):  # noqa: N818
    """A request the sandbox will not take now (answered ``429 rate_limited``).

    Raised from inside a route when a job is refused; the server turns it into the answer.
    """

    status = 429
    code = "rate_limited"

    def __init__(self, message: str, retry_after: int, limit: str, scope: str = "you") -> None:
        super().__init__(message)
        self.message = message
        self.retry_after = max(int(retry_after), 1)
        self.limit = limit
        self.scope = scope

    def body(self) -> dict[str, Any]:
        """``{"error": {code, message, details}}`` as every refusal of the API."""
        details = {"retry_after_s": self.retry_after, "limit": self.limit, "scope": self.scope}
        return {"error": {"code": self.code, "message": self.message, "details": details}}


def _rate_busy(limit: str, scope: str, wait_s: float) -> Busy:
    retry = max(math.ceil(wait_s), 1)
    wait = in_words(retry)
    if scope == "everyone":
        text = f"This shared sandbox is busy with other visitors right now: try again in {wait}."
    elif limit == "upload":
        text = (
            "This shared sandbox takes only a few uploads from each visitor at a time: "
            f"try again in {wait}."
        )
    else:
        text = f"This shared sandbox is busy for you: try again in {wait}."
    return Busy(f"{text} {OWN_COMPUTER}", retry, limit, scope)


class Limiter:
    """The state of the limit: visitors, buckets, streams and the job check. Thread-safe."""

    def __init__(
        self,
        limits: RateLimits,
        *,
        clock: Callable[[], float] = time.monotonic,
        wall: Callable[[], float] = time.time,
    ) -> None:
        self.limits = limits
        self._clock = clock
        self._wall = wall
        self._lock = threading.Lock()
        self._salt = secrets.token_bytes(16)
        self._clients: OrderedDict[str, _Client] = OrderedDict()
        self._everyone: dict[str, _Bucket] = {}
        self._streams: dict[str, int] = {}
        self._streams_all = 0
        self._swept = clock()

    # ---- who

    def identify(self, peer: str | None, forwarded: Iterable[str] = ()) -> str:
        """An opaque, per-process key for the visitor (a salted hash of their address)."""
        address = client_address(self.limits, peer, forwarded)
        return hashlib.blake2b(address.encode(), key=self._salt, digest_size=10).hexdigest()

    def visitors(self) -> int:
        """How many visitors are kept now (tests)."""
        with self._lock:
            return len(self._clients)

    # ---- requests

    def admit(self, client: str, kind: str) -> Busy | None:
        """Take a token for a ``read``, ``write`` or ``upload`` of this visitor, or say wait."""
        now = self._clock()
        with self._lock:
            visitor = self._visitor(client, now)
            worst, refused = 0.0, None
            taken: list[tuple[_Bucket, Rule]] = []
            for name in TAKES[kind]:
                for scope, rule, bucket in self._buckets(visitor, name, now):
                    wait = bucket.wait(rule, now)
                    taken.append((bucket, rule))
                    if wait > worst:
                        worst, refused = wait, (name, scope)
            if refused is not None:
                return _rate_busy(refused[0], refused[1], worst)
            for bucket, _rule in taken:
                bucket.tokens -= 1.0
        return None

    def _buckets(self, visitor: _Client, name: str, now: float) -> list[tuple[str, Rule, _Bucket]]:
        out: list[tuple[str, Rule, _Bucket]] = []
        mine: Rule | None = getattr(self.limits, name)
        if mine is not None:
            bucket = visitor.buckets.get(name)
            if bucket is None:
                bucket = visitor.buckets[name] = _Bucket(mine, now)
            out.append(("you", mine, bucket))
        every: Rule | None = getattr(self.limits, "all_" + name)
        if every is not None:
            bucket = self._everyone.get(name)
            if bucket is None:
                bucket = self._everyone[name] = _Bucket(every, now)
            out.append(("everyone", every, bucket))
        return out

    def _visitor(self, client: str, now: float) -> _Client:
        """The visitor's record (made if new), most recently used last; idle ones are forgotten."""
        if now - self._swept >= SWEEP_S:
            self._swept = now
            horizon = now - self.limits.idle_s
            while self._clients:
                oldest = next(iter(self._clients.values()))
                if oldest.seen > horizon:
                    break
                self._clients.popitem(last=False)
        visitor = self._clients.get(client)
        if visitor is None:
            visitor = self._clients[client] = _Client(now)
            while len(self._clients) > self.limits.max_clients:
                self._clients.popitem(last=False)
        else:
            self._clients.move_to_end(client)
        visitor.seen = now
        return visitor

    # ---- live streams

    def open_stream(self, client: str) -> Busy | None:
        """Count a new event stream, or say the visitor (or the sandbox) has enough."""
        limits = self.limits
        with self._lock:
            mine = self._streams.get(client, 0)
            if limits.streams and mine >= limits.streams:
                return Busy(
                    f"This shared sandbox keeps {limits.streams} live connections open per "
                    "visitor and you are at that number (other tabs of qPilot): close one, "
                    f"then reload. {OWN_COMPUTER}",
                    5,
                    "streams",
                )
            if limits.all_streams and self._streams_all >= limits.all_streams:
                return Busy(
                    "This shared sandbox has as many live connections open as it can keep: "
                    f"try again in {in_words(10)}. {OWN_COMPUTER}",
                    10,
                    "streams",
                    "everyone",
                )
            self._streams[client] = mine + 1
            self._streams_all += 1
        return None

    def close_stream(self, client: str) -> None:
        """A counted stream ended."""
        with self._lock:
            mine = self._streams.get(client, 0)
            if mine <= 1:
                self._streams.pop(client, None)
            else:
                self._streams[client] = mine - 1
            self._streams_all = max(self._streams_all - 1, 0)

    # ---- slow work

    def jobs_busy(self, client: str | None, active: list[Job]) -> Busy | None:
        """Why this visitor may not start another job now (None: they may)."""
        limits = self.limits
        heavy = [j for j in active if j.kind not in LIGHT_JOBS]
        mine = [j for j in heavy if client is not None and j.owner == client]
        if client is not None and limits.jobs and len(mine) >= limits.jobs:
            wait = self._free_in(mine)
            return Busy(
                f"You already have {len(mine)} analyses running in this shared sandbox: wait "
                f"for one to finish (try again in {in_words(wait)}). {OWN_COMPUTER}",
                wait,
                "jobs",
            )
        if client is not None and limits.all_jobs and len(heavy) >= limits.all_jobs:
            wait = self._free_in(heavy)
            return Busy(
                "This shared sandbox is running as many analyses as it can for other visitors "
                f"right now: try again in {in_words(wait)}. {OWN_COMPUTER}",
                wait,
                "jobs",
                "everyone",
            )
        return None

    def _free_in(self, jobs: list[Job]) -> int:
        """About when one of these jobs ends: the shortest typical time left, 5 to 120 s."""
        now = self._wall()
        left = [
            max(j.typical_s - (now - (j.started or j.created)), 0.0) for j in jobs if j.typical_s
        ]
        return int(min(max(math.ceil(min(left, default=10.0)), 5), 120))

    def admit_job(self, kind: str, owner: str | None, active: list[Job]) -> None:
        """:attr:`~qpilot.web.jobs.JobRunner.admission`: refuse (:class:`Busy`) or let pass.

        Work that is not a visitor's request (no owner) and view preparation pass.
        """
        if owner is None or kind in LIGHT_JOBS:
            return
        busy = self.jobs_busy(owner, active)
        if busy is not None:
            raise busy


# ---- the middleware ---------------------------------------------------------------------------

Scope = MutableMapping[str, Any]
ASGIApp = Callable[..., Any]


def request_kind(method: str, path: str, content_type: str) -> str:
    """``read``, ``write``, ``upload``, ``stream`` or ``health`` for one API request."""
    if path in HEALTH_PATHS:
        return "health"
    if method in WRITE_METHODS:
        if content_type.split(";", 1)[0].strip().lower() == "multipart/form-data":
            return "upload"
        if method == "POST" and any(p.match(path) for p in COMPUTE_POSTS):
            return "read"
        return "write"
    return "stream" if path == STREAM_PATH and method == "GET" else "read"


class RateLimit:
    """ASGI middleware: the limit above, for ``/api`` requests (a plain one, so events stream).

    It sits inside the guard (host, origin and size checks first; the security headers are added
    to its answers) and outside the cache (a refusal is never given an ETag).
    """

    def __init__(
        self,
        app: ASGIApp,
        limiter: Limiter,
        jobs: Any = None,
        heavy: Iterable[re.Pattern[str]] = (),
    ) -> None:
        self.app = app
        self.limiter = limiter
        self.jobs = jobs  # the JobRunner: its running jobs decide whether another may start
        self.heavy = tuple(heavy)  # the paths of routes that start a job

    async def __call__(self, scope: Scope, receive: Any, send: Any) -> None:
        """Count one request, refuse it in words, or pass it on."""
        path: str = scope.get("path", "")
        if scope["type"] != "http" or not path.startswith("/api") or path in HEALTH_PATHS:
            await self.app(scope, receive, send)
            return
        method: str = scope.get("method", "GET").upper()
        wanted = self.limiter.limits.client_ip_header.lower().encode("latin-1")
        forwarded: list[str] = []
        content_type = ""
        for key, value in scope.get("headers") or []:
            if key == wanted:
                forwarded.append(value.decode("latin-1"))
            elif key == b"content-type":
                content_type = value.decode("latin-1")
        peer = (scope.get("client") or (None,))[0]
        client = self.limiter.identify(peer, forwarded)
        kind = request_kind(method, path, content_type)
        if kind not in TAKES and kind != "stream":
            await self.app(scope, receive, send)
            return
        busy: Busy | None
        if kind == "stream":
            busy = self.limiter.open_stream(client)
        else:
            busy = self.limiter.admit(client, kind)
            if busy is None and method == "POST" and self.jobs is not None:
                if any(p.match(path) for p in self.heavy):
                    busy = self.limiter.jobs_busy(client, self.jobs.active())
        if busy is not None:
            await _refuse(send, busy)
            return
        token = REQUESTER.set(client)
        try:
            await self.app(scope, receive, send)
        finally:
            REQUESTER.reset(token)
            if kind == "stream":
                self.limiter.close_stream(client)


async def _refuse(send: Any, busy: Busy) -> None:
    import json

    body = json.dumps(busy.body()).encode()
    await send(
        {
            "type": "http.response.start",
            "status": busy.status,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode()),
                (b"retry-after", str(busy.retry_after).encode()),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})
