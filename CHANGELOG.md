# Changelog

All notable changes to qPilot are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html). qPilot is research software:
research use only, not for clinical decisions.

## [Unreleased]

### Added
- `scripts/gate.sh`: the merge gate in one command (ruff, format check, the full test suite and
  the demo regression), one summary line; `--heavy` adds the Studio demo check, the integration
  demo and the MCP tool list.
- `scripts/demo_regression.py` + `scripts/demo_fingerprint.json`: the locked demo numbers, the
  legacy robustness grid (byte-identical), every baseline fact and card option (bit-identical,
  additive changes allowed), run-to-run determinism and the benchmark validation, checked end to
  end through the CLI with freshly computed curves.

## [0.1.0] — baseline `81484f7`

The state of `main` when the agent team started: 14 CLI commands, 16 MCP tools, qPilot Studio,
the Decision Simulator (`qsim`), the Prism bridge, the model layer and its harness, and the
hash-chained Analysis Record with `verify` and `rerun`.
