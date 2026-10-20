# Recorded API answers for the Ask drawer's tests

Real responses from `qpilot app` on the seeded demo study store (Vermeulen 2013, study
`e300000d4f9a`, session `bc1d233e3866`, no model configured unless said). Never edited by hand.
Run from the repository root with the server running (`source agent-bus/ui-env.sh ask` sets
`QPILOT_API` and `QPILOT_APP_TOKEN`).

| File                       | Command                                                                                                                                                                                                                          |
| -------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `model-none.json`          | `curl -s -H "x-qpilot-token: $QPILOT_APP_TOKEN" $QPILOT_API/api/system \| jq .model`                                                                                                                                             |
| `no-route.json`            | `curl -s -X POST -H "x-qpilot-token: $QPILOT_APP_TOKEN" $QPILOT_API/api/studies/e300000d4f9a/nope` (the server's 404 body)                                                                                                       |
| `results-examples.json`    | `curl -s -H "x-qpilot-token: $QPILOT_APP_TOKEN" $QPILOT_API/api/studies/e300000d4f9a/results \| jq '{genes: [.genes[] \| {gene, conclusion, holds}], references: {used: .references.used}}'` (only the fields the examples read) |
| `ask-robustness.json`      | `python frontend/src/features/ask/__recorded__/record_ask.py ask-robustness.json "Is the AHCY result robust?"`                                                                                                                   |
| `ask-study.json`           | `python frontend/src/features/ask/__recorded__/record_ask.py ask-study.json "How many plates, samples and genes are in this study?" study`                                                                                       |
| `ask-request.json`         | `python frontend/src/features/ask/__recorded__/record_ask.py ask-request.json "Normalise to HMBS alone"` (a change request: Ask writes nothing and names the card)                                                               |
| `model-not-answering.json` | as `model-none.json`, with the server started with `QPILOT_MODEL_PROVIDER=openai_compatible QPILOT_MODEL_ENDPOINT=http://127.0.0.1:9 QPILOT_MODEL_NAME=qwen2.5:7b` (nothing listens there)                                       |
| `ask-model-down.json`      | `python frontend/src/features/ask/__recorded__/record_ask.py ask-model-down.json "Is the BIRC5 result robust?"` on that server (the model is tried, fails, a template answers)                                                   |
| `model-seen-shown.json`    | `curl -s -H "x-qpilot-token: $QPILOT_APP_TOKEN" "$QPILOT_API/api/model/seen?study=bc1d233e3866"` right after it (the payload that was attempted)                                                                                 |
| `ask-audit-first.json`     | `python frontend/src/features/ask/__recorded__/record_ask.py ask-audit-first.json "What should I check first in this data?" audit` (the audit's issue queue)                                                                     |
| `ask-audit-whatif.json`    | `python frontend/src/features/ask/__recorded__/record_ask.py ask-audit-whatif.json "What if I normalise to HMBS alone?"` (auto: the audit's live what-if)                                                                        |

Each `ask-*.json` is the finished job (`GET /api/jobs/{id}`), its `result` the `AskAnswer`.
