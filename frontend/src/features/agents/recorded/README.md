# Recorded from the real API (no hand-written data)

`agents.json` is `GET /api/agents` from `qpilot app` serving a copy of the seeded demo store
(20 Oct 2026, after api-ops added `request_state`). The agent requests in it were made through
qPilot's MCP tool code (`QpilotTools.qpcr_decide`, actor agent) on the demo study `e300000d4f9a`.

```bash
# with the team's env script sourced (agent-bus/ui-env.sh <name>: this worktree's store, ports, key)
curl -s "http://127.0.0.1:$APP_PORT/api/agents" -H "x-qpilot-token: $QPILOT_APP_TOKEN" \
  | python -m json.tool --indent 1 --no-ensure-ascii > frontend/src/features/agents/recorded/agents.json
```

What happened on `e300000d4f9a`, in order (all through the real code paths): qPilot decided the
empty-wells card (system); an agent asked for Cq ≤ 35 and for the top-three reference set; a
person turned the first down and approved the second on the Agents page; an agent asked for the
20 % group cut-off; an agent's request with an out-of-date `expected_head` was refused as stale
(logged in `attempts.jsonl`, outside the chain).

This machine's home folder is shortened to `~` in the recorded paths (the connect command names
the store); nothing else is changed.

On 28 Oct 2026 (ex/agents) the `tools` and `rules` were replaced by the real `GET /api/agents` of
the same code on an empty store: the 27 `qpcr_*` tools (the new `qpcr_comparisons`, `qpcr_units`,
`qpcr_melt`, `qpcr_repeat_plan`, `qpcr_export` and `qpcr_request_set_aside` among them) and the
five `sim_*` tools, with what each can change. The connect command, the waiting requests and the
activity are as first recorded.
