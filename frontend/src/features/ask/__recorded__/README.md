# Recorded API answers for the Ask drawer's tests

Real responses from `qpilot app` on the seeded demo study store (Vermeulen 2013, study
`e300000d4f9a`, session `bc1d233e3866`, no model configured, Suggest mode). Never edited by hand.
Run from the repository root with the server running (`source agent-bus/ui-env.sh ask` sets
`QPILOT_API` and `QPILOT_APP_TOKEN`).

| File                  | Command                                                                                                                                                         |
| --------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `model-none.json`     | `curl -s -H "x-qpilot-token: $QPILOT_APP_TOKEN" $QPILOT_API/api/system \| jq .model`                                                                            |
| `no-route.json`       | `curl -s -X POST -H "x-qpilot-token: $QPILOT_APP_TOKEN" $QPILOT_API/api/studies/e300000d4f9a/nope` (the server's 404 body)                                      |
| `ask-robustness.json` | `python frontend/src/features/ask/__recorded__/record_ask.py ask-robustness.json "Is the AHCY result robust?"`                                                  |
| `ask-study.json`      | `python frontend/src/features/ask/__recorded__/record_ask.py ask-study.json "How many plates, samples and genes are in this study?" study`                      |
| `ask-request.json`    | `python frontend/src/features/ask/__recorded__/record_ask.py ask-request.json "Normalise to HMBS alone"` (a change request in Suggest mode: waits for a person) |

Each `ask-*.json` is the finished job (`GET /api/jobs/{id}`), its `result` the `AskAnswer`.
