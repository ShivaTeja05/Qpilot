# Recorded from the real API (no hand-written data)

Recorded on 20 Oct 2026 from `qpilot app` serving this worktree's seeded store (the Vermeulen
demo study, Studio session `bc1d233e3866` → study `e300000d4f9a`, plus study `cf49ccd72052`
decided by the scripted walk). The two agent requests on `e300000d4f9a` were made through
qPilot's MCP tool code (`QpilotTools.qpcr_decide`, actor agent).

```bash
source "/Users/gangadhara/Documents/Wheel Hack/agent-bus/ui-env.sh" record
H="x-qpilot-token: $QPILOT_APP_TOKEN"
for s in e300000d4f9a cf49ccd72052; do
  curl -s "http://127.0.0.1:$APP_PORT/api/studies/$s/decisions" -H "$H" \
    | python -m json.tool --indent 1 --no-ensure-ascii > decisions-$s.json
done
python frontend/src/features/record/recorded/record_verify.py e300000d4f9a  # verify-*.json
```

`verify-*.json` are `core.record.verify` reports of a record of `e300000d4f9a` written with
`core.record.write_record`, untouched and with one decision line edited.
