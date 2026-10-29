# The public sandbox: who may do how much

qPilot also runs as a shared online sandbox (`QPILOT_HOSTED=1`): a Hugging Face Space
(`deploy/hf-space/app.py`) behind a Vercel proxy that rewrites `/api/*` to it. Every visitor uses
one store, nothing private belongs there, and it resets when it restarts. On a person's own
computer (`qpilot app`) none of this exists: there is no limit.

Because every visitor may do what a person may do on the page, one visitor must not be able to
keep the sandbox's few job workers busy, flood it with uploads or take all its event streams.
This page says what is limited, how a visitor is told from another, and how to tune it
(security finding RT-EX-015; the code is `qpilot/web/ratelimit.py`).

## What a visitor may do

| What | Default | Setting | Why |
|---|---|---|---|
| Reads (`GET`, and the `POST`s that only compute: the audit's what-if, Claims, Plan next, Trace's "set these samples aside") | 240 a minute | `QPILOT_RATE_READS` | the page asks for about four views per section it opens |
| Writes (a decision, a proposal, a setting) | 20 a minute | `QPILOT_RATE_WRITES` | a person decides one thing at a time |
| Uploads (a file; also counts as a write) | 6 in 10 minutes | `QPILOT_RATE_UPLOADS` | each upload is kept on the sandbox's disk until it restarts |
| Slow work running at once (audit, supplement export, curve check, design proposal, opening a file, ...) | 3 | `QPILOT_RATE_JOBS` | the sandbox has four workers |
| Live streams open (one per tab of qPilot) | 6 | `QPILOT_RATE_STREAMS` | a browser keeps about six per site anyway |

Everyone together, as a backstop that does not depend on telling visitors apart:

| What | Default | Setting |
|---|---|---|
| Reads | 2400 a minute | `QPILOT_RATE_READS_ALL` |
| Writes | 200 a minute | `QPILOT_RATE_WRITES_ALL` |
| Uploads | 30 in 10 minutes | `QPILOT_RATE_UPLOADS_ALL` |
| Slow work running at once | 8 | `QPILOT_RATE_JOBS_ALL` |
| Live streams open | 200 | `QPILOT_RATE_STREAMS_ALL` |

A rate is `count/window`: `240/min`, `6/10min`, `20/60` (seconds), `2/h`. `off` or `0` removes that
limit; a number that is not a rate keeps the default. A bucket starts full and refills steadily,
so a burst (a page opening) is fine and a steady flood is not. Jobs that only prepare a view in
memory (the gate, Trace, the audit's load) never count: reading a view is not refused for work
nobody asked for. Asking again for work that is already running returns the running job, as
always. `QPILOT_RATE_LIMIT=off` switches the whole limit off on a hosted server; unset or any
other value keeps it on. `QPILOT_RATE_CLIENTS` (20000) bounds how many visitors are remembered.

**Never limited:** the page and its assets (everything outside `/api`) and `/api/system` (the
health check).

## What a visitor sees

A refused request is answered `429` with `Retry-After` (seconds) and, in the API's usual shape,

```json
{"error": {"code": "rate_limited",
           "message": "This shared sandbox is busy for you: try again in 12 seconds. To work without limits, install qPilot and run `qpilot app` on your own computer.",
           "details": {"retry_after_s": 12, "limit": "read", "scope": "you"}}}
```

`scope` is `you` (this visitor's own allowance) or `everyone` (the sandbox is busy with other
visitors); `limit` is `read`, `write`, `upload`, `jobs` or `streams`. The page shows the message
under the heading "The shared sandbox is busy" (a panel for a view, a toast for a write that stays
about as long as the wait). A request that is refused costs nothing, so waiting the time named is
always enough. A job refused for having too much running is refused before the route does
anything (no file is kept, nothing is half written).

## Who a visitor is

By default the visitor is the address of the socket peer. Behind a proxy that is the proxy, so
everyone would share one allowance; the proxy's own header says who the visitor is, and a header
may be believed only when it comes from a proxy that is ours:

| Setting | Meaning |
|---|---|
| `QPILOT_TRUSTED_PROXIES` | addresses or networks (`10.0.0.0/8, 198.51.100.7`), `private` for the private ranges, or `*` for "every peer is our platform's proxy" (a container that can only be reached through it). Unset: no proxy is believed, the visitor is the peer. A header from any other peer is **ignored**, so a visitor cannot pick their own allowance by sending one |
| `QPILOT_CLIENT_IP_HEADER` | which header names the visitor; `x-forwarded-for` by default |
| `QPILOT_PROXY_HOPS` | which entry of the header: `leftmost` when the outermost proxy overwrites the header with the address it saw, or a number N for the Nth from the right (1, the default: the address the nearest proxy saw; each proxy that appends one adds one) |

An entry that is not an address is ignored (the peer counts instead), `1.2.3.4:5678` and
`[2001:db8::1]:80` lose their port, an IPv4-mapped address is the IPv4 address, and an IPv6
address is its `/64` network (one network is one visitor, or a visitor would get a new allowance
with every address of their prefix). Visitors are kept in memory only, under a salted hash that
is lost at restart, and forgotten once idle for longer than the slowest bucket needs to refill
(11 minutes with the defaults). Addresses are never written down or logged.

**On the Space.** Vercel overwrites `X-Forwarded-For` with the address it saw, and the Space's
only way in is its platform's proxy, so `app.py` sets `QPILOT_TRUSTED_PROXIES=*`,
`QPILOT_CLIENT_IP_HEADER=x-forwarded-for` and `QPILOT_PROXY_HOPS=leftmost`, and starts uvicorn
with `proxy_headers=False` so that only qPilot reads the header. The Space's own *Variables*
override these (the values in `app.py` are defaults).

**What this does not do.** A visitor who reaches the Space's own address (`…hf.space`) instead of
the Vercel front door can send an `X-Forwarded-For` of their choosing, and the Space cannot tell
Vercel's request from theirs: they get a new allowance per address they invent. The
sandbox-wide buckets and the cap on running jobs above still hold, as do the upload cap
(`QPILOT_MAX_UPLOAD_MB`), the unpacked-size cap (`QPILOT_MAX_UNPACKED_MB`) and the disk floor
(`QPILOT_MIN_FREE_MB`): what such a visitor can take is bounded; what they cannot be is fair to
the others. A header signed by the proxy would close this; Vercel's rewrites cannot add one.
Vercel's own firewall (rate-limit rules on `/api/*`) can be switched on in the project's
dashboard in front of this, and costs the Space nothing.

**Many people behind one address** (a class on a university network) share one allowance. Raise
`QPILOT_RATE_READS`, `QPILOT_RATE_WRITES` and `QPILOT_RATE_JOBS` for such an event, or have them run
qPilot on their own computers, which is what the message suggests.

## Checking it

```bash
for i in $(seq 1 300); do
  curl -s -o /dev/null -w "%{http_code}\n" https://qpilot-navy.vercel.app/api/settings
done | sort | uniq -c        # 240 x 200, then 429s until the bucket refills
curl -si https://qpilot-navy.vercel.app/api/settings | head -8      # 429, retry-after: …
curl -s -o /dev/null -w "%{http_code}\n" https://qpilot-navy.vercel.app/api/system   # still 200
```

`tests/web/test_ratelimit.py` pins all of it: the buckets and their refill, `Retry-After`, a
forwarded address from a peer that is not a trusted proxy being ignored, idle visitors being
forgotten, the cap on running jobs (also through the job runner), the cap on live streams, a
computer never being limited, and the Space's own settings.
