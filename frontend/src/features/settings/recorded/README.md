# Recorded API answers (settings)

`model-test.json`: the `result` of a real `model.test` job (`POST /api/model/test`, no model
configured, so the templates answer) on the home agent's seeded store, recorded on 20 Oct 2026.
Tests read it; nobody edits it by hand.

```bash
source "/Users/gangadhara/Documents/Wheel Hack/agent-bus/ui-env.sh" home
H="X-Qpilot-Token: $QPILOT_APP_TOKEN"
JOB=$(curl -s -X POST -H "$H" -H "Origin: $QPILOT_API" -H 'content-type: application/json' -d '{}' \
  $QPILOT_API/api/model/test | python3 -c "import json,sys; print(json.load(sys.stdin)['job']['id'])")
# once GET /api/jobs/$JOB says "done":
curl -s -H "$H" $QPILOT_API/api/jobs/$JOB | python3 -c "import json,sys; print(json.dumps(json.load(sys.stdin)['result'], indent=2))" \
  > frontend/src/features/settings/recorded/model-test.json
```
