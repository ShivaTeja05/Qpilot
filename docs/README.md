# qPilot's documentation

Start with the [user guide](user-guide.md) if you are a scientist using the page, with
[install](install.md) if qPilot is not installed yet, and with [agents](agents.md) if you are
connecting an AI agent. The repository's [README](../README.md) is the overview.

## For scientists

| Page | Read it for |
|---|---|
| [install.md](install.md) | installing on Windows, macOS or Linux (pipx or uv), offline installs, where your data lives |
| [user-guide.md](user-guide.md) | the page, section by section, and how to do each task ("How do I …") |
| [conformance.md](conformance.md) | which instrument files qPilot reads, set by set, from a corpus of real lab files |
| [design-editor.md](design-editor.md) | setting the design on the page with no model: targets, samples, a pasted list, the comparison, the sample sheet |
| [quantities.md](quantities.md) | absolute quantification: standard curves, LOD, LOQ and copies |
| [exports.md](exports.md) | what the workbook, the CSV tables, the figures and the journal supplement hold |
| [prism.md](prism.md) | the Prism project (`.pzfx`) and its round trip |
| [studio.md](studio.md) | qPilot Studio, from the instrument export to Prism, step by step |

## How it works

| Page | Read it for |
|---|---|
| [engine.md](engine.md) | the engine's steps, its method cards and its limits |
| [integration.md](integration.md) | the nine-stage workflow, the robustness audit and their numbers |
| [studio-measured.md](studio-measured.md) | model runs measured on the demo, 7B to 32B |
| [../validation/validation_table.md](../validation/validation_table.md) | the published benchmark the engine reproduces |
| [../sim/README.md](../sim/README.md) | the Decision Simulator (the robustness audit) |

## For developers and agents

| Page | Read it for |
|---|---|
| [agents.md](agents.md) | the 32 MCP tools, what each refuses, models inside qPilot, the harness |
| [app.md](app.md) | the page's build spec: principles, sections, design system, API conventions |
| [release.md](release.md) | how a release is made |
| [../CONTRIBUTING.md](../CONTRIBUTING.md) | how to contribute |
| [../THREAT_MODEL.md](../THREAT_MODEL.md) and [../SECURITY.md](../SECURITY.md) | threats, mitigations, reporting a vulnerability |
| [../CHANGELOG.md](../CHANGELOG.md) | what changed in each version |
| [../tests/fixtures/corpus/README.md](../tests/fixtures/corpus/README.md) | the public instrument-file corpus and its rules |

## Method cards

Each method card says what a step computes, from which source, with which settings, how it was
checked and where it stops.

| Card | Method |
|---|---|
| [linregpcr.md](../methods/linregpcr.md) | LinRegPCR curve analysis: amplification curve → starting quantity |
| [amp_call.md](../methods/amp_call.md) | which curves count as amplified (the Cq cut-off choice) |
| [curve_judge.md](../methods/curve_judge.md) | the Curve Judge, a learned second opinion on each curve ([its model card](../qpilot/models/curve_judge/METHOD_CARD.md)) |
| [efficiency_model.md](../methods/efficiency_model.md) | which efficiency turns Cq into quantity |
| [genorm.md](../methods/genorm.md) | geNorm control-gene stability |
| [normfinder.md](../methods/normfinder.md) | NormFinder, and what to normalise each gene to |
| [inter_run_calibration.md](../methods/inter_run_calibration.md) | correcting differences between plates |
| [contrast.md](../methods/contrast.md) | the group comparison: Welch's t-test on log2 relative quantities |
| [comparisons.md](../methods/comparisons.md) | several comparisons, Holm and Benjamini–Hochberg, paired designs |
| [absolute_quantification.md](../methods/absolute_quantification.md) | standard curves, LOD, LOQ and each unknown's copies |
| [melt_curve.md](../methods/melt_curve.md) | melt curves of DNA-binding-dye assays and the G-MELT rule |
| [design_checks.md](../methods/design_checks.md) | the engine's refute-only checks of a proposed design |
| [evidence.md](../methods/evidence.md) | the Evidence Ledger, the G-RT rule and the Run Review |
| [trace.md](../methods/trace.md) | Trace: from a result back to the wells to look at |
| [sheetcheck.md](../methods/sheetcheck.md) | the Spreadsheet Check of a lab's own ΔΔCq sheet |
| [replicate_budget.md](../methods/replicate_budget.md) | the replicate budget: biological, RT and technical replicates |
| [routes.md](../methods/routes.md) | the usual route from the instrument to Prism, and what it changes |
| [instrument_context.md](../methods/instrument_context.md) | what a run file says about the instrument, and G-INSTR |
| [lookback.md](../methods/lookback.md) | the instrument logbook, incidents and the lookback |

The Run Gate's rules, their thresholds and their sources are in
[`packs/research-default.yaml`](../packs/research-default.yaml).
