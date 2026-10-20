# Recorded API answers (home)

Real answers from `qpilot app` on the home agent's seeded store (the demo study walked through
Studio, plus `quantification_methods.rdml` from `sim/data/untergasser/` opened through the page),
recorded on 20 Oct 2026. Tests read them; nobody edits them by hand.

```bash
source "/Users/gangadhara/Documents/Wheel Hack/agent-bus/ui-env.sh" home
qpilot app --no-open --port $APP_PORT &
curl -s -H "X-Qpilot-Token: $QPILOT_APP_TOKEN" $QPILOT_API/api/workspaces | python3 -m json.tool > frontend/src/features/home/recorded/workspaces.json
curl -s -H "X-Qpilot-Token: $QPILOT_APP_TOKEN" $QPILOT_API/api/system | python3 -m json.tool > frontend/src/features/home/recorded/system.json
```
