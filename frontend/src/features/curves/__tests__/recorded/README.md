# Recorded from the real API (no hand-written numbers)

Recorded 20 Oct 2026 from `qpilot app` on a scratch copy of the curves agent's seeded store
whose proposal log was cut right after the design was confirmed (the real walk's first 264
entries), then **Check the curves** run in the page (the real `propose_curves` job):

```bash
source "/Users/gangadhara/Documents/Wheel Hack/agent-bus/ui-env.sh" curves
P="$QP_ROOT/agent-bus/scratch/ui-curves/studies-pending"
cp -R "$QPILOT_STUDIES_DIR" "$P"
S="$P/sessions/bc1d233e3866ad4d32736a9feea832ea6261a9c75d82a78e465d31bad554e151"
head -n 264 "$S/proposals.jsonl" > "$S/p.tmp" && mv "$S/p.tmp" "$S/proposals.jsonl"
QPILOT_STUDIES_DIR="$P" qpilot app --no-open --port $APP_PORT &
# in the page: Curves → Check the curves; when the job is done:
H=(-H "x-qpilot-token: qpilot-dev" -H "origin: $QPILOT_API")
curl -s "${H[@]}" "$QPILOT_API/api/sessions/bc1d233e3866" \
  | python3 -c "import json,sys; d=json.load(sys.stdin); [d.pop(k, None) for k in ('facts', 'summary')]; print(json.dumps(d, indent=1))" \
  > frame-curves-waiting.json
curl -s "${H[@]}" "$QPILOT_API/api/sessions/bc1d233e3866/proposals?stage=curves" \
  | python3 -c "import json,sys; print(json.dumps(json.load(sys.stdin), separators=(',', ':')))" \
  > proposals-curves-waiting.json
```

`frame-curves-waiting.json` drops the frame's `facts` and `summary` (large, unused here). The
inbox holds the call-rule proposal (cannot check) and 110 Curve Judge well calls on
ALUsq(Eurogentec)_20080228 (contradicted).
