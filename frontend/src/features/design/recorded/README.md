# Recorded API answers for the Design tests

From the design agent's store: a Studio session of `sim/data/untergasser/large_DNA_dilutions.rdml`
(Untergasser et al., CC BY 4.0) opened through `POST /api/workspaces` and proposed in the page
(see `src/ui/proposal/recorded/README.md`). Nothing is hand-written. Re-record with the design
agent's server running (`qpilot app --port 7881`; the key is in `$QPILOT_APP_TOKEN`):

```bash
curl -s -H "x-qpilot-token: $QPILOT_APP_TOKEN" http://127.0.0.1:7881/api/sessions/2529de8272eb/plate > untergasser-plate.json
curl -s -H "x-qpilot-token: $QPILOT_APP_TOKEN" http://127.0.0.1:7881/api/sessions/2529de8272eb > untergasser-session.json  # "summary" dropped
```
