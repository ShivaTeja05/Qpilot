# Recorded API answers for the Audit section's tests

Real answers of the audit routes (api-audit's `qpilot/web/routers/audit.py`, ui/api-audit @ 74e23de)
over the audit agent's seeded store (the Studio walk of the demo, study `e300000d4f9a`, and the
same file analysed outside a session, study `cf49ccd72052`). Never edited by hand.

```bash
qpilot app --no-open --port 7986          # the store above
H=(-H "x-qpilot-token: qpilot-dev" -H "origin: http://127.0.0.1:7986")
curl -s "${H[@]}" http://127.0.0.1:7986/api/studies/e300000d4f9a/audit > status-ready.json
curl -s "${H[@]}" -X POST -H "content-type: application/json" -d '{"bind_to_record":true}' \
  http://127.0.0.1:7986/api/studies/e300000d4f9a/audit/verify > verify.json
# while POST /api/studies/cf49ccd72052/audit was running:
curl -s "${H[@]}" http://127.0.0.1:7986/api/studies/cf49ccd72052/audit > status-running.json
```

The audit's views (overview, study, how, what-if) are insight's recordings in `src/test/recorded`.
