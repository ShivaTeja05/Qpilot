# qPilot

qPilot reads a qPCR instrument's raw amplification curves, analyses every plate with the same published method and the same settings, and shows which of your analysis choices could change your conclusion. Those choices stay with a person: the software decides only what changes no conclusion (with the other choices at their recommended settings), and writes every decision, with its reason and who made it, into a record whose analysis anyone can re-run.

**For research use only. Not for clinical or diagnostic use.**

Built at the *Reinvent the Wheel: A Tools for Science Hack* (London, 16–18 Oct 2026). Licence: Apache-2.0.

## In 60 seconds

```bash
pip install -e .
qpilot fetch-demo        # the 64-plate demo study, SHA-256 pinned (7 MB, once)
qpilot run --out results # numbers, robustness, confidence and Decision Cards
qpilot app               # the one-page app on 127.0.0.1 (or: python -m qpilot.app)
```

`qpilot doctor` shows what qPilot will use and whether anything can leave the machine (`outbound: none` without a model). `qpilot validate` reproduces the published benchmark below. For a clean demo run, `qpilot app --fresh-demo` moves earlier decisions aside (they are kept, never deleted).

In the app: **Analyse** opens the study; the left column shows the study summary and, for the four headline genes, how often each conclusion holds across every reasonable analysis and a confidence verdict with its reasons (every gene is in the *All genes* table below); the centre shows one **Decision Card** at a time, ranked by how many conclusions the choice can change. Pick an option, type a reason, **Decide**; the next card appears. **Export** writes the Analysis Record as one zip.

## Use from an AI agent

```bash
claude mcp add qpilot -- qpilot serve
```

The MCP server reads and writes the same study store as the app. An agent can read the study, ask what each choice would change, and request a decision. A choice that can change a conclusion (with the other choices at their recommended settings) becomes a request that waits for a person, whatever the agent says; that check is made once, when the study is analysed. The full guide, including models inside qPilot and how to test a model before trusting it, is [`docs/agents.md`](docs/agents.md).

## The engine

All maths is ordinary, deterministic Python; no language model is involved. Steps, method cards and limitations: [`docs/engine.md`](docs/engine.md).

1. **Curves**: LinRegPCR, vendored unchanged from the RDML consortium's rdmlpython, on every plate ([method card](methods/linregpcr.md)).
2. **Control genes**: geNorm stability and the pairwise ratio check between the groups ([method card](methods/genorm.md)).
3. **Comparison**: Welch's t-test on log2 relative quantities, with a stated rule: *up or down only if p < 0.05 and the change is at least 2-fold; otherwise no call* ([method card](methods/contrast.md)).
4. **Robustness**: every reasonable analysis of the same plates (31 control-gene sets × 3 group cut-offs × 2 rules for empty wells on the demo), and which choices flip which conclusions.

### Validation

`qpilot validate` compares the engine with the RDML consortium's own published results for the demo study's dilution standards (tables fetched SHA-256-pinned). Generated lines, exactly as `qpilot validate` prints them from the numbers in `validation/validation.json`:

- N0 on 930 standard wells (62 genes) vs RDML-Tools: 99.6 % identical to 4 significant figures, 100.0 % within 5 % (largest difference 0.05 %)
- Dilution-series bias over 62 genes vs LinRegPCR (2013): median |difference| 0.021 (ours 0.961 vs published 0.947 on average)
- Cq on 945 standard wells (63 genes) vs LinRegPCR (2013): offset +0.97 cycles on average (SD 0.17), a change in how LinRegPCR defines Cq, disclosed

Full table and sources: [`validation/validation_table.md`](validation/validation_table.md).

## The Analysis Record

Export writes one zip: the input RDML (byte for byte, when the original file is still on disk; the export message says so), the results, the cards, the robustness grid (`grid.csv`), the facts every sentence cites, the design, every decision with its reason and who made it (`human`, `agent` or `system`), the software versions and the vendored method's commit, and a `CHECKSUMS.sha256`.

```bash
qpilot verify qpilot-record-<study>.zip   # checksums and the decision chain
qpilot rerun <unzipped record folder>     # re-runs the analysis from the record's input; compares results.json
```

The re-run reproduces the results at the recommended choices (a decision is recorded with its reason; it does not change `results.json`; each option's consequences are in `cards.json` and `grid.csv`). It reuses the local curve cache; set `QPILOT_CACHE_DIR` to an empty folder to re-fit every curve.

Decisions are a hash chain: each entry carries the hash of the one before, so an entry edited or removed without recomputing the hashes is detected (a removed last entry through `CHECKSUMS.sha256`). Nothing is signed: someone who recomputes every hash is not detected unless the record id is compared with a copy kept elsewhere. That makes the record tamper-evident against accidental or naive edits, not tamper-proof; it is not a 21 CFR Part 11 system.

## Where to look, and what the data cannot show

```bash
qpilot trace --gene CAMTA2            # from a result back to the wells to look at (reads only)
qpilot trace --well HMBS_20080318:K22 # does this one well matter?
qpilot evidence                       # what this study cannot tell you (Evidence Ledger)
qpilot report run-review --out review.html
qpilot check sheet analysis.xlsx      # recompute your own ΔΔCq sheet; the file is never edited
qpilot plan --sd 0.5 --sd-rt 0.4 --sd-well 0.3 --n 6   # biological, RT and technical replicates together
qpilot instrument inspect run.eds     # what the run file says about the instrument
qpilot export excel --out results.xlsx  # results plus a "Where to look" sheet
```

- **Trace** walks from a gene's conclusion, a sample or a well back through the normaliser, the reference wells and the plate controls. It stops at a plate and well, and says what each one does to the conclusion. On the demo, CAMTA2's first place to look is tumour 2016 on plate HMBS_20080318, well K22: one HMBS well reads Cq 46.1 while the tumour's other four reference wells read normally. Reading that well from the other four changes CAMTA2 from no call to down. A trace that would change a call opens a decision only a person can take. Method: [methods/trace.md](methods/trace.md).
- **Evidence Ledger** lists the controls and annotations a study has and lacks: NTCs, no-RT, reference-gene stability, efficiency source, RNA integrity, RT replicates, biological units, inter-run calibrators, lots, instrument dates. Absent items never change a conclusion. Method: [methods/evidence.md](methods/evidence.md).
- **Spreadsheet Check** recomputes a lab's own analysis sheet from its Cq values. It names the first column that differs and the known slip that reproduces it, such as an inverted sign, the exponent applied twice, or statistics run on fold changes. Tested on generated sheets only so far. Method: [methods/sheetcheck.md](methods/sheetcheck.md).
- **Instrument Logbook** reads calibration dates, run state and log events from QuantStudio `.eds` and export headers. It keeps a hash-chained logbook per instrument, with events inferred from successive files and incidents a person confirms. Lookback answers "which of my conclusions used this period?". The formats are tested on synthetic files built to the layouts seen in public files; several are unverified (see [methods/instrument_context.md](methods/instrument_context.md) and [methods/lookback.md](methods/lookback.md)).

## Demo dataset

Vermeulen J *et al.* (2009) *Lancet Oncology* 10:663–671 and Ruijter JM *et al.* (2013) *Methods* 59:32–46; CC BY 4.0 (the licence of the CRAN `vermeulen` and `ruijter` packages that redistribute the data). qPilot downloads the copy in the RDML consortium's rdmlpython repository at a pinned commit. 64 plates (one gene per plate), 366 neuroblastoma tumours, 24,576 reactions, 5 candidate control genes. The demo groups are **MYCN-high (the top 15 % by MYCN expression) versus the rest**: expression-defined, not the clinical MYCN amplification call.

## Limitations

- The analysis is set up for the demo study's design: the study must contain the marker gene `MYCN(4)` and the demo's candidate control genes. The command line can change the control genes, the cut-off and the experiment; the app cannot yet. Your own design is on the roadmap; `qpilot plan` sizes a design before the first plate.
- One gene per plate in the demo, so plate effects cannot be separated from gene effects; no mixed model.
- Technical replicates are not supported: a sample with more than one well for a gene is refused (in the demo each tumour has one well per gene; only standards and controls are in triplicate). No melt-curve analysis; no kinetic outlier test.
- Curve analysis (N0, Cq, dilution bias) is validated against published results on the standards of one study from one instrument platform (LightCycler 480, SYBR Green I). The later steps (geNorm, the contrast, robustness) are tested against reproduced numbers, not a published benchmark.
- No correction for testing many genes: the robustness check measures sensitivity to analysis choices, not significance.
- Results are not yet written back into the RDML file (roadmap).

## Built and borrowed

**Borrowed, credited, unchanged:** LinRegPCR (rdmlpython, MIT, vendored at `fce7a44`); the RDML format and schemas; the geNorm method (Vandesompele *et al.* 2002, reimplemented from the paper); SciPy's t distribution; the demo data and the published benchmark tables.

**Built here:** the hardened RDML loader and pinned downloads; the per-plate curve table; quantities, groups, geNorm, the contrast and its rule; the reference-gene group check; the decision space and robustness grid; Decision Cards and the escalation rule; the on-disk study store; the Analysis Record and its hash chain; confidence grades; templated explanations whose numbers are all facts; the one-page app; the MCP server; the model layer and its test harness; `qpilot plan`; the validation script.

## Related tools

- **Clarida** ([clarida.bio](https://clarida.bio)), from the authors of geNorm, qbase+ and the MIQE guidelines: analysis from Cq values with geNorm, a MIQE compliance score and methods text. qPilot uses their method and starts one step earlier, from the raw curves.
- **LinRegPCR web / RDML-Tools** ([rdml.org](https://www.rdml.org)): the reference curve-analysis method, file by file, which qPilot ships unchanged and runs on every plate of a study.
- **AnnealIQ**: a conversational qPCR analysis assistant (closed beta) working from Ct values.

## What the qPCR analysis step costs today

For the analysis-and-statistics step: Clarida's Lab plan is listed at €4,800–9,600 a year ([clarida.bio/pricing](https://clarida.bio/pricing); academic pricing is lower and not listed), and GraphPad Prism at $260–520 per seat a year ([graphpad.com/how-to-buy](https://www.graphpad.com/how-to-buy)). qPilot is Apache-2.0 and runs on a laptop. It does not replace the instrument's own software, validated (Part 11) editions, or Prism for non-qPCR work.

## Will it work in my lab?

| | |
|---|---|
| RDML export from the instrument | ◐ RDML 1.3 and 1.4 tested; 1.0–1.2 are migrated by the vendored code but untested |
| QuantStudio `.eds` | ◐ export to RDML with Thermo's own tools first for the analysis (not tested here); `qpilot instrument inspect` reads the file's calibration dates, run state and log events (synthetic test files only) |
| QuantStudio TXT, other native formats | ✘ roadmap |
| Offline on a laptop, no account | ✔ (macOS: full analysis tested with the network off; Linux: unit tests in CI, without the demo study; Windows untested) |
| Reproduces my lab's numbers | ◐ reproduces the published benchmark above; your own instrument is untested |
| Results as CSV | ◐ the robustness grid (`grid.csv`); `qpilot export excel` writes results with a "Where to look" sheet; a per-gene CSV is on the roadmap |
| Prism export | ◐ `qpilot export prism` / Studio's Send to Prism write log2 tables per biological unit, a Prism script (`run.pzc`) and provenance (Mode S: Prism itself reads and writes its files). **Not yet run in a real Prism**: the script commands follow GraphPad's documentation, the templates must be made once by hand, see [docs/prism.md](docs/prism.md). Not affiliated with GraphPad Software or Dotmatics |
| Results written back into RDML | ✘ roadmap |
| Hash-chained record of every decision | ✔ (tamper-evident; not Part 11) |
| My own study design | ✔ `qpilot run --design study.yaml --samples sheet.csv`, or in qPilot Studio, where the AI proposes the design from your file, sheet and one sentence and you confirm each item; the demo is one preset (tested on synthetic designs and on the demo re-entered as two named groups, which reproduces it exactly) |
| Technical replicates | ✔ averaged per biological unit (mean of log2 quantities); never counted as n; a group with fewer than two biological units gets no p-value |
| Which curves count as amplified | ✔ LinRegPCR by default; "Cq ≤ 40 / 38 / 35" are shown as choices with their consequences (on the demo, "Cq > 35 = not detected" changes 10 of 58 conclusions); the learned Curve Judge is a second opinion whose disagreements a person resolves (validated on the demo's LightCycler 480 SYBR only) |

## Security

The app binds to `127.0.0.1` only, is never shared, refuses requests for any other host name, turns telemetry off before the UI library loads, and serves files only from a private export folder and Gradio's own upload folder; the study store and the dataset cache are blocked. The whole analysis runs with the network switched off (`tests/core/test_offline.py`). RDML files are parsed without external entities or network access and with size caps. Threats and mitigations: [`THREAT_MODEL.md`](THREAT_MODEL.md); reporting a vulnerability: [`SECURITY.md`](SECURITY.md).

## Roadmap (not built)

Your own design in the app (genes, groups, control-gene candidates) · technical replicates · QuantStudio TXT and other native importers · results written back into RDML and a per-gene CSV · Prism export · replicate-outlier and melt-peak cards on data that has them · a mixed model with plate as a random effect once a gene spans two or more plates · NormFinder, reimplemented from the paper.

## Licence and citation

qPilot is Apache-2.0 ([`LICENSE`](LICENSE)); third-party licences, data and the generated package list are in [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md), and a CycloneDX bill of materials can be generated with `cyclonedx-py environment -o sbom.json` (not committed; it will be attached to tagged releases, none yet). To cite qPilot and the methods it builds on, see [`CITATION.cff`](CITATION.cff). Contributions: [`CONTRIBUTING.md`](CONTRIBUTING.md).
