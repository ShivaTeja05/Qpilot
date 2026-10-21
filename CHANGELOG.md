# Changelog

All notable changes to qPilot are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html). qPilot is research software:
research use only, not for clinical decisions.

## [Unreleased]

### Added
- **The efficiency models, opt-in** (`qpilot/qpcr/axes/`, merged from `agents/numbers`, with the
  axis registry, stage caches and grid cap): which efficiency turns each Cq into a quantity
  (LinRegPCR's mean per assay and plate, each well's own, one per assay over its plates, an
  assumed 2.0, the dilution series') as one more choice of the robustness grid, screened first,
  with its own Decision Card (`numbers.efficiency_model`). Asked for in Studio (Results → "Also
  test efficiency models": a `choice.axis` proposal the rule makes, D-AXIS checks and a person
  accepts; `POST /api/sessions/{sid}/propose/axis`) or with `qpilot run --efficiency all|LIST`.
  The request lives in the design (`StudyDesign.axes`; absent by default, so every existing
  design hash, study id and the locked demo output are unchanged), so `qpilot verify` and
  `qpilot rerun` reproduce it. Trace, the Prism export, the robustness audit's "your choices",
  Report and History follow the model in use. Method card `methods/efficiency_model.md`; on the
  demo it changes 6 of 58 calls (each well's own 5, an assumed 2.0 4, the dilution series 3).
- **Instrument exports on Open** (`qpilot/io/connectors/`, `qpilot/web/intake.py`): drop a Bio-Rad
  CFX export set, a QuantStudio / StepOne / 7500 export, a LightCycler 480 raw-data text or Cp
  table, an RDES or a tidy table; qPilot sorts the files by content, reads them once into
  deterministic RDML and opens that as a Studio session. The Design section shows what was read
  (plates, wells, sample types, vendor Cq, omitted wells) and whether the curves look raw,
  baseline-subtracted or normalised (`qpilot/io/rawness.py`).
- **Run Gate, the Controls section** (`qpilot/core/rules.py`, `qpilot/core/gate.py`,
  `qpilot/qpcr/gate_rules.py`, `packs/research-default.yaml`, `GET /api/studies/{id}/gate`): every
  plate's controls checked against a rule pack (G-TYPED, G-NTC-1, G-NAC, G-NRT, G-POS, G-STD,
  G-REP), and for each rule that warns or fails, whether leaving out the wells it points at would
  change a conclusion. Rules label; nothing is applied. Agreement with an independent oracle on
  the demo: `validation/scientist/`.
- Open Decision Card kinds (`qpilot/core/card_kinds.py`): a validated registry; a kind this build
  does not know is a human decision (fail closed).
- Public instrument-export corpus for tests (`tests/fixtures/corpus/`, 18 real sets with
  manifests and SHA-256, 2 synthetic sets with known truth) and red-team reader tests
  (`tests/redteam/`).
- `scripts/gate.sh`: the merge gate in one command (ruff, format check, the full test suite and
  the demo regression), one summary line; `--heavy` adds the Studio demo check, the integration
  demo and the MCP tool list.
- `scripts/demo_regression.py` + `scripts/demo_fingerprint.json`: the locked demo numbers, the
  legacy robustness grid (byte-identical), every baseline fact and card option (bit-identical,
  additive changes allowed), run-to-run determinism and the benchmark validation, checked end to
  end through the CLI with freshly computed curves.

### Fixed
- RT-001: with `QPILOT_DATA_ROOTS` unset, `qpilot serve` no longer shares the filesystem root or
  the home folder as a data root when an MCP client starts it there.
- RT-003/004/005: package docstring vocabulary; name and id patterns end at `\Z`; an unsafe
  member in a record zip is refused, not a traceback.

## [0.1.0] — baseline `81484f7`

The state of `main` when the agent team started: 14 CLI commands, 16 MCP tools, qPilot Studio,
the Decision Simulator (`qsim`), the Prism bridge, the model layer and its harness, and the
hash-chained Analysis Record with `verify` and `rerun`.
