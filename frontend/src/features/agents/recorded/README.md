# Recorded from the real API (no hand-written data)

`agents.json` is `GET /api/agents` from `qpilot app` serving this worktree's seeded store
(20 Oct 2026, re-recorded after api's chain view gained root, chain_intact, attempts). Its two waiting requests were made through qPilot's MCP tool code
(`QpilotTools.qpcr_decide`, actor agent) on the demo study `e300000d4f9a`.

```bash
source "/Users/gangadhara/Documents/Wheel Hack/agent-bus/ui-env.sh" record
curl -s "http://127.0.0.1:$APP_PORT/api/agents" -H "x-qpilot-token: $QPILOT_APP_TOKEN" \
  | python -m json.tool --indent 1 --no-ensure-ascii > frontend/src/features/agents/recorded/agents.json
```

What happened on `e300000d4f9a`, in order (all through the real code paths): qPilot decided the
empty-wells card (system); an agent asked for Cq ≤ 35 and for the top-three reference set
(`QpilotTools.qpcr_decide`); a person turned the first down and approved the second on the
Agents page; an agent asked for the 20 % group cut-off; an agent's request with an out-of-date
`expected_head` was refused as stale (logged in `attempts.jsonl`, outside the chain).
