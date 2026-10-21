# Recorded from the real API (no hand-written numbers)

`report-e300000d4f9a.json` was recorded on 21 Oct 2026 from `qpilot app` over the seeded store of the demo study
(Vermeulen 2013, a Studio walk confirmed through the real service, with a robustness audit):

```bash
source agent-bus/ui-env.sh report
qpilot app --no-open --port $APP_PORT &
curl -s -H "x-qpilot-token: $QPILOT_APP_TOKEN" "http://127.0.0.1:$APP_PORT/api/studies/e300000d4f9a/report" > report-e300000d4f9a.json
```

(re-indented with `json.dump(..., indent=1)`). The exports list is not recorded: its download
links carry this computer's folder paths.

## The Run Review

`review.json`, `review-stale.json`, `review-signed.json`, `review-after.json` and `session.json`
were recorded on 21 Oct 2026 by `record.py` (beside this file) from `qpilot app` on port 7896, over
a copy of the seeded demo store (Studio session `bc1d233e3866`, study `e300000d4f9a`):

```bash
source <scratchpad>/env.sh   # the worktree's Python env, QPILOT_STUDIES_DIR on the copy
python frontend/src/features/report/recorded/record.py --port 7896 --session bc1d233e3866
```

It writes twice, both plainly a test: a sign-off read at a head that is not in the chain (the
server answers `409 stale`, nothing enters the chain), and one real sign-off (`discuss`, a
comment that says it is a test and holds `<b>markup</b>`, so the tests can check that it shows as
text). Run it only on a copy of a store. Re-running adds another sign-off to that copy.
