# Recorded from the real API (no hand-written numbers)

Recorded 20 Oct 2026 from `qpilot app` on the curves agent's seeded store (session
`bc1d233e3866`, the demo study with design and curves confirmed):

```bash
source "/Users/gangadhara/Documents/Wheel Hack/agent-bus/ui-env.sh" curves
qpilot app --no-open --port $APP_PORT &
H=(-H "x-qpilot-token: qpilot-dev" -H "origin: $QPILOT_API")
for w in N14 E1; do
  curl -s "${H[@]}" "$QPILOT_API/api/sessions/bc1d233e3866/curve?well=CDH5_20080305/$w" \
    | python3 -m json.tool --indent 1 > curve-CDH5_20080305-$w.json
done
```

N14 is a standard (STD_150000) with two replicates on the plate (N16, N18); E1 is a study
sample with a late Cq that LinRegPCR calls amplified and the Curve Judge does not.
