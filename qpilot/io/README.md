# `qpilot/io` — getting data in

This package is the only code in qPilot that opens files from outside. Owner: Dev 1.

| Module | What it does |
|---|---|
| `rdml_io.py` | `load(path)` opens an RDML file safely (size caps, hardened XML parser, migration to RDML 1.4, schema validation) and returns the vendored `rdml.Rdml` document; `runs(doc, experiment_id)` lists its plates. |
| `datasets.py` | `fetch_vermeulen()` downloads the public demo dataset with a SHA-256 pin (added in Task 2). |

## Adding a connector (another instrument or file format)

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
