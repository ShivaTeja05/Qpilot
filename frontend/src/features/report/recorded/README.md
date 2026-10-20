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
