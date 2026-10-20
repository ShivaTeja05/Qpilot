# Recorded API answers for the Ask drawer's tests

Real responses from `qpilot app` on the seeded demo study store (Vermeulen 2013, study
`e300000d4f9a`, session `bc1d233e3866`). Never edited by hand.

| File              | Command                                                                                                                    |
| ----------------- | -------------------------------------------------------------------------------------------------------------------------- |
| `model-none.json` | `curl -s -H "x-qpilot-token: $QPILOT_APP_TOKEN" $QPILOT_API/api/system \| jq .model` (no model configured)                 |
| `no-route.json`   | `curl -s -X POST -H "x-qpilot-token: $QPILOT_APP_TOKEN" $QPILOT_API/api/studies/e300000d4f9a/nope` (the server's 404 body) |
