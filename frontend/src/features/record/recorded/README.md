# Recorded from the real API (no hand-written data)

Recorded on 20 Oct 2026 from `qpilot app` serving a copy of the seeded demo store: the Studio
session `bc1d233e3866` → study `e300000d4f9a`, and study `cf49ccd72052` decided by the scripted
walk. What happened on `e300000d4f9a` is told in `../../agents/recorded/README.md`.

```bash
# with the team's env script sourced (agent-bus/ui-env.sh <name>: this worktree's store, ports, key)
H="x-qpilot-token: $QPILOT_APP_TOKEN"
for s in e300000d4f9a cf49ccd72052; do
  curl -s "http://127.0.0.1:$APP_PORT/api/studies/$s/decisions" -H "$H" \
    | python -m json.tool --indent 1 --no-ensure-ascii > decisions-$s.json
done
curl -s "http://127.0.0.1:$APP_PORT/api/studies/e300000d4f9a/records" -H "$H" \
  | python -m json.tool --indent 1 --no-ensure-ascii > records-e300000d4f9a.json
# verified-*.json: the record exported on the Record page (Export the Analysis Record), and a
# copy with the first decision's reason edited (unzip, edit decisions.jsonl line 1, zip again)
curl -s -X POST "http://127.0.0.1:$APP_PORT/api/records/verify" -H "$H" \
  -H "origin: http://127.0.0.1:$APP_PORT" -F "record=@qpilot-record-e300000d4f9a.zip" \
  | python -m json.tool --indent 1 --no-ensure-ascii > verified-ok.json
# … the same with the edited copy > verified-tampered.json
```

This machine's home folder is shortened to `~` in the recorded paths (where a record is kept);
nothing else is changed.
