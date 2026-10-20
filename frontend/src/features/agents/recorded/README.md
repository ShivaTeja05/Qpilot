# Recorded from the real API (no hand-written data)

`agents.json` is `GET /api/agents` from `qpilot app` serving this worktree's seeded store
(20 Oct 2026). Its two waiting requests were made through qPilot's MCP tool code
(`QpilotTools.qpcr_decide`, actor agent) on the demo study `e300000d4f9a`.

```bash
source "/Users/gangadhara/Documents/Wheel Hack/agent-bus/ui-env.sh" record
curl -s "http://127.0.0.1:$APP_PORT/api/agents" -H "x-qpilot-token: $QPILOT_APP_TOKEN" \
  | python -m json.tool --indent 1 --no-ensure-ascii > frontend/src/features/agents/recorded/agents.json
```
