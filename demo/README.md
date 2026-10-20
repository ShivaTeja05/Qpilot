# Demo

The demo is the public Vermeulen et al. 2009 / Ruijter et al. 2013 neuroblastoma benchmark: 64 plates, 366 tumours, 58 genes compared (MYCN-high, the top 15 % by MYCN expression, against the rest; expression-defined, not the clinical MYCN amplification call). It is downloaded once, 7 MB, checked against a pinned SHA-256, and never committed to this repository.

Every number below was produced by qPilot's engine on a real run of this dataset; none is written by hand. Two ways to run the demo:

* **On the page** (below): the path a person takes, about 6 minutes on a laptop with no model.
* **Scripted, no browser:** the same stages with a scripted person, each result checked against the measured number (exit code 1 when one differs).

```bash
qpilot studio demo --check                       # Studio end to end: 28 checks, about 90 s
python -m qpilot.integration demo --out demo-run # all 9 stages, audit and record included: 30 checks, 3–6 min (--out must be new or empty)
```

## In this folder

* `vermeulen.study.yaml`: the demo's design as a study file. `qpilot run --design demo/vermeulen.study.yaml` gives the same output as `qpilot run`, byte for byte.
* `demo_study.yaml`: the demo's facts (study, groups, control-gene candidates, headline genes) and the question asked of the model. Its `path:` list is the click path of the earlier pages; the path of the page is below.
* `demo.mp4`: a 1 min 50 s recording (no sound, captions on screen) of the earlier pages, made before the one page existed. It shows screens that no longer exist; it is kept as a record of the earlier version, not as a guide to the page.

## The path on the page

Before: `qpilot fetch-demo` (once), `qpilot doctor` (expect `outbound: none` and `OK`), then

```bash
qpilot app --fresh-demo      # moves earlier demo work aside (kept, never deleted) and starts clean
```

Open the link it prints, then:

1. **Open → Open the demo study.** (If the demo is not downloaded the page asks first.)
2. **Design → Propose the design** (about 9 s). The rules make 131 proposals, among them the demo's published design. **Accept all consistent…** lists 121; the other 9 are contradicted by the engine: seven competimer standards that never amplified, one competimer series with R² 0.707, and one standard series with R² 0.694. **Reject** them with a reason, then **Confirm this stage…** and **Yes, confirm**.
3. **Curves → Check the curves** (about 15 s). The Curve Judge disagrees with LinRegPCR on 166 study wells; 110 early ALUsq curves could change a conclusion, each contradicted by LinRegPCR's complete fit. **Reject contradicted AI calls…** with one reason, accept LinRegPCR's call rule, confirm.
4. **Results** (about 30 s to analyse). ODC1 is called up at 3.59×. Look at the robustness map and the flip matrix, then decide the **Decision Cards**, with a reason each, and press **Confirm the analysis choices…** and **Yes, confirm** (this opens Prism). The usual Excel route (2^-ΔΔCq, Welch on the linear scale) would change 14 of the 58 conclusions.
5. **Audit → Run the audit** (about 50 s). 90,396 analyses; its baseline reproduces qPilot's. On this study: 23 solid, 7 holds with caveats, 3 depends on your choices, 5 fragile, 2 check data first, 18 no change called.
6. **Gene → ODC1** (click it on the map). What holds, one choice at a time, your samples.
7. **Prism → Draft the Prism project**, accept it, then **Send to Prism**: a bundle (one table per gene, the Prism scripts, provenance and a README) is written into a new folder and offered as a zip. Prism itself is not needed to see the bundle (the page says whether it started Prism); the script has not yet been run in a real Prism ([`docs/prism.md`](../docs/prism.md)).
8. **Record → Export the Analysis Record**, then in a terminal:

```bash
qpilot verify qpilot-record-<study id>.zip   # checksums and the decision chain
```

With a model configured (`QPILOT_MODEL_PROVIDER` and the variables in [`docs/agents.md`](../docs/agents.md)), ask the open study: "Is ODC1 up in MYCN-high tumours, and does it depend on the reference genes?" (the Ask drawer, ⌘J); and **Test this model** in Settings shows a scorecard from a live run.

<!-- screenshots: the coordinator adds them here (docs/images/), one per step above -->
