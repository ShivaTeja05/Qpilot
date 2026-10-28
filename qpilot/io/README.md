# `qpilot/io` — getting data in

This package is the only code in qPilot that opens files from outside. Owner: Dev 1.

| Module | What it does |
|---|---|
| `rdml_io.py` | `load(path)` opens an RDML file safely (size caps, hardened XML parser, migration to RDML 1.4, schema validation) and returns the vendored `rdml.Rdml` document; `runs(doc, experiment_id)` lists its plates. Real files need repairs, each only when its defect is there and said in `load_notes(doc)`: the archive's one XML member whatever its name (CFX Manager 3.0), rdmlpython's upgrade writing elements outside the RDML namespace (StepOne 1.0 `dye`, LinRegPCR 1.3 `Ncopy`), RDML 1.0 wells named `A1` numbered on a standard plate, elements out of schema order, LightCycler 96 GUID samples named by their description and `<dye>@<target>` targets by their own name (`names_key` keys the curve cache for those files). Every refusal has a `kind` (`intake.unreadable` says it in words). |
| `datasets.py` | `fetch_vermeulen()` downloads the public demo dataset with a SHA-256 pin (added in Task 2). |
| `connectors/` | Instrument exports → deterministic RDML: `detect(path)` (by content, ≤ 256 KB read), `capture(paths)`, `materialise(paths, cache_dir=)` → `Materialised(rdml_path, meta, sources)`. Connectors: `rdml` (used as it is), `cfx` (CFX Manager / Maestro sheets, grouped by run stem), `quantstudio` (QuantStudio / ViiA 7 / StepOne / 7500: `*` and `#` headers, `[Sections]`, section files), `lightcycler480` (raw-data text, Abs Quant Cp table, both joined by plate), `rdes`, `tidy` (long table or Cq table; a person's own Cq table with Sample / Gene / Condition / Gene Type / Cq columns is `tidy.cq.design`: its gene type becomes each target's declared role, and the page opens it with its own sample columns as the sheet; a table naming a group, animal or biological replicate but no target is a sample sheet and is not claimed). Contract: `agent-bus/contracts/capture-connectors.md`; tests: `tests/capture/` (public corpus in `tests/fixtures/corpus/`). |
| `inputs.py` | `input_files(path)` / `input_label(path)`: the files a person opened, by their own names, from the path qPilot kept them under (a converted export's every file from its capture record; an upload's remembered name). Used wherever a report or an audit names its source. |
| `rawness.py` | `assess(plates)`: were the curves raw, Rn, baseline-subtracted, rescaled or Cq only (per well, plate and study, with evidence). |
| `sheets.py` | `read_sheet` / `sheet_table`: a sample sheet, every cell quarantined. |

The page opens exports through `qpilot/web/intake.py` (`POST /api/workspaces` with `files`): it
sorts dropped files by `detect()`, stages the export under the person's file names (plate names
and CFX fluorophores come from names; the cache key counts them), materialises it into the study
store and keeps the `CaptureMeta` with the session.

## Adding a connector (another instrument or file format)

New vendor formats go in `connectors/` (a class with `id`, `version`, `label`, `suffixes`,
`sniff(probe)` and `read(sources) -> list[PlateData]`, registered in `connectors/registry.py`);
the builder writes the RDML. The older suffix shim below still works for a plain loader.

A connector is **a function `path -> rdml.Rdml`**. Write it in a new module here, convert the vendor's export into an RDML document (rdmlpython can build one: `Rdml()`, `new_experiment()`, `new_run()`, `import_table()`), and register it:

```python
# qpilot/io/quantstudio_txt.py
def load_quantstudio_txt(path):
    ...
    return doc


# qpilot/io/rdml_io.py
CONNECTORS[".txt"] = load_quantstudio_txt
```

Rules for every connector:
1. Treat the file as untrusted: check its size before parsing, never resolve XML entities, never fetch URLs found inside it.
2. Validate names (targets, samples, runs) at this boundary; the engine assumes clean identifiers.
3. Add a small fixture under `tests/fixtures/` (with its licence in `tests/fixtures/README.md`) and a test in `tests/engine/`.
4. Do not edit anything under `qpilot/vendor/`.
