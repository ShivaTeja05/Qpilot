# Third-party notices

qPilot is licensed under the Apache License 2.0 (see `LICENSE`). It vendors, depends on, or uses the following third-party works. Licences of runtime dependencies are re-checked with `pip-licenses` before each tagged release; this table is the human-readable summary.

## Vendored code
| Component | Version / commit | Licence | Where | Notes |
|---|---|---|---|---|
| rdmlpython (`rdml.py`, LinRegPCR implementation) | RDML-consortium/rdmlpython @ `fce7a44e8b47b90759c646b557de568f7af77e75` (2 May 2026) | MIT, Copyright (c) 2019 the RDML-consortium | `qpilot/vendor/rdmlpython/` (`rdml.py`, `LICENSE`, `schema/*.xsd`, `schema/LICENSE` — schemas Copyright (c) 2008-2022 the RDML-consortium, MIT) | Copied verbatim; not modified; hashes in `README_VENDOR.md`. Cite Ruijter et al. 2009 and Untergasser et al. 2021. |

## Runtime dependencies (installed, not vendored)
| Package | Licence |
|---|---|
| lxml | BSD-3-Clause |
| numpy | BSD-3-Clause |
| scipy | BSD-3-Clause |
| pandas | BSD-3-Clause |
| pydantic | MIT |
| mcp (Model Context Protocol Python SDK) | MIT |
| gradio | Apache-2.0 |
| plotly | MIT |
| PyYAML | MIT |
| filelock | Unlicense |
| matplotlib | Matplotlib License (PSF-based, BSD-compatible); required by the vendored rdmlpython import |

## Optional dependencies
| Package | Extra | Licence |
|---|---|---|
| anthropic | `ai` | MIT |
| httpx | `ai` | BSD-3-Clause |
| pyarrow | `parquet` | Apache-2.0 |
| openpyxl | `xlsx` | MIT |

## Data
| Dataset | Licence | How it is used |
|---|---|---|
| Vermeulen et al. 2009 / Ruijter et al. 2013 neuroblastoma qPCR benchmark (`data_vermeulen_raw.rdml`, 64 plates) | CC BY 4.0 (as redistributed by the CRAN `vermeulen` / `ruijter` packages; hosted in the MIT rdmlpython repository) | Downloaded at runtime by `qpilot fetch-demo` with a SHA-256 pin. **Never committed to this repository.** |
| `tests/fixtures/test_mca_1_raw_data.rdml` | MIT (rdmlpython repository @ `fce7a44`, `test/`) | Small smoke-test fixture. |
| `tests/fixtures/vermeulen_std_150000.rdml` | CC BY 4.0 (Vermeulen et al. 2009 / Ruijter et al. 2013; from the rdmlpython repository @ `fce7a44`, `experiments/vermeulen/`) | 54 KB standards-only subset of the demo study for curve-analysis unit tests. |

## Not used (deliberately)
`qslib` (EUPL-1.2, copyleft), GPL-licensed R packages (`qpcR`, `chipPCR`, `PCRedux`), and NormFinder's original code (redistribution not permitted). None of these is imported or bundled.
