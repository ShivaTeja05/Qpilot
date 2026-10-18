# Third-party notices

qPilot is licensed under the Apache License 2.0 (see `LICENSE`). It vendors, depends on, or uses the following third-party works. Licences were checked with `pip-licenses` on 17 Oct 2026 (generated table at the end); re-run it before tagging a release. This table is the human-readable summary.

## Vendored code
| Component | Version / commit | Licence | Where | Notes |
|---|---|---|---|---|
| rdmlpython (`rdml.py`, LinRegPCR implementation) and the RDML schemas | `rdml.py`, `LICENSE`: RDML-consortium/rdmlpython @ `fce7a44e8b47b90759c646b557de568f7af77e75` (2 May 2026); `schema/*.xsd`, `schema/LICENSE`: RDML-consortium/rdml-schema @ `e127cd010c5cf535f63db0ea2d28064851ef8b91` (the submodule pinned by that commit) | MIT, Copyright (c) 2019 the RDML-consortium (code); MIT, Copyright (c) 2008-2022 the RDML-consortium (schemas) | `qpilot/vendor/rdmlpython/` | Copied verbatim; not modified; hashes in `README_VENDOR.md`. Cite Ruijter et al. 2009 and Untergasser et al. 2021. |

## Runtime dependencies (installed, not vendored)
| Package | Licence |
|---|---|
| lxml | BSD-3-Clause |
| numpy | BSD-3-Clause (with bundled 0BSD, MIT, Zlib and CC0-1.0 components) |
| scipy | BSD-3-Clause |
| pandas | BSD-3-Clause |
| pydantic | MIT |
| mcp (Model Context Protocol Python SDK) | MIT |
| gradio | Apache-2.0 |
| plotly | MIT |
| PyYAML | MIT |
| filelock | MIT |
| matplotlib | Matplotlib License (PSF-based, BSD-compatible); required by the vendored rdmlpython import |
| pyarrow | Apache-2.0; the Decision Simulator's analysis grid is written as parquet |

## Optional dependencies
| Package | Extra | Licence |
|---|---|---|
| anthropic | `ai` | MIT |
| httpx | `ai` | BSD-3-Clause |
| openpyxl | `xlsx` | MIT |

## Data
| Dataset | Licence | How it is used |
|---|---|---|
| Vermeulen et al. 2009 / Ruijter et al. 2013 neuroblastoma qPCR benchmark (`data_vermeulen_raw.rdml`, 64 plates) | CC BY 4.0 (as redistributed by the CRAN `vermeulen` / `ruijter` packages; hosted in the MIT rdmlpython repository) | Downloaded at runtime by `qpilot fetch-demo` with a SHA-256 pin. **Never committed to this repository.** |
| `tests/fixtures/test_mca_1_raw_data.rdml` | MIT (rdmlpython repository @ `fce7a44`, `test/`) | Small smoke-test fixture. |
| `tests/fixtures/vermeulen_std_150000.rdml` | CC BY 4.0 (Vermeulen et al. 2009 / Ruijter et al. 2013; from the rdmlpython repository @ `fce7a44`, `experiments/vermeulen/`) | 54 KB standards-only subset of the demo study for curve-analysis unit tests. |
| RDML consortium benchmark tables (`RDML_Tools_bias.tsv`, `data_vermeulen_methods_cq.tsv`, `data_vermeulen_methods_results.tsv`) | as the rdmlpython repository (MIT) and the study (CC BY 4.0) | Downloaded at runtime by `qpilot fetch-demo` / `qpilot validate` with SHA-256 pins; never committed. Only the generated comparison (`validation/validation_table.md` and its summary statistics in `validation/validation.json`) is in the repository. |

| Brintz et al. 2025, qPCR amplification-curve training data (`bbrintz/qPCR-amp-call` @ v1.0.0 `191675bd`; Zenodo doi:10.5281/zenodo.13798821) | CC0 1.0 on GitHub, CC BY 4.0 on Zenodo; treated as **CC BY 4.0** (the stricter) | Used **only to train** the Curve Judge (`training/curve_judge/`, never shipped). The trained model (`qpilot/models/curve_judge/model.json`) is a derived work: attribution to Brintz B.J., et al., *Gates Open Research* 9:1 (2025), doi:10.12688/gatesopenres.16313.1. |
| HGNC gene symbols (`qpilot/data/hgnc/hgnc_symbols.tsv`, from `hgnc_complete_set.txt` of 16 Oct 2026) | CC0 ("all data is released under the Creative Commons Public Domain (CC0) License", genenames.org/about/license) | Shipped: approved, previous and alias symbols only, to catch Excel-mangled gene names. |
| Decision Simulator validation plates, `sim/data/untergasser/` (Untergasser, van der Hoff, Benes; RDML files and pipetting tables) | MIT, Copyright (c) 2019 the RDML-consortium (RDML-consortium/rdmlpython @ `fce7a44` and `e9f936b`, `experiments/untergasser/`) | Committed unchanged for `qsim validate` / `qsim external`; per-file SHA-256 and provenance in `sim/data/untergasser/README.md`. The MIT notice is the one in `qpilot/vendor/rdmlpython/LICENSE`. |
| Decision Simulator results, `sim/results/` (per-gene, per-sample and per-well summaries such as `one_sample_flips.csv` and `reference_wells_top50.csv`) | CC BY 4.0, as adaptations of Vermeulen et al. 2009 / Ruijter et al. 2013 (attribution as in the first row of this table) | Committed outputs of `qsim run` on the demo study. The raw RDML is still never committed. |
| RDML technical test files, `sim/data/technical/` | MIT (RDML-consortium/rdmlpython @ `e9f936b`, `experiments/technical/`) | Committed unchanged for `qsim external`; provenance in `sim/data/technical/README.md`. |
| Ruijter et al. 2013 `ds_380`, `ds_94_4`, `ds_competimer`, `sim/data/ruijter/` (R package `ruijter` 0.1.3 by Ramiro Magno, commit `f9d2df4`) | CC BY 4.0 | Committed for the no-difference and external tests; attribution: Ruijter J.M. et al., *Methods* 59:32-46 (2013), doi:10.1016/j.ymeth.2012.08.011. `ds_380.rdml` is converted from the CSV by `qsim.nodiff`. Provenance and SHA-256 in `sim/data/ruijter/README.md`. |

## Not used (deliberately)
`qslib` (EUPL-1.2, copyleft), GPL-licensed R packages (`qpcR`, `chipPCR`), and NormFinder's original code (redistribution not permitted). None of these is imported or bundled.

## Every installed package (generated)

Generated on 17 Oct 2026 with `pip-licenses --format=markdown --order=name --with-urls` in the development environment (123 packages listed; pip-licenses leaves out pip, itself and its dependencies prettytable and wcwidth; the SBOM lists all 127 installed packages, including test and lint tools). No package declares GPL, LGPL or AGPL in its metadata; scipy's binary wheel bundles the GCC runtime (libgfortran, libgcc_s: GPL-3.0-or-later WITH GCC-exception-3.1) and libquadmath (LGPL-2.1-or-later) as dynamically linked libraries, which qPilot neither modifies nor redistributes. Five packages are MPL-2.0 (certifi, fqdn, orjson, pathspec, tqdm), a file-level copyleft that allows use as unmodified dependencies. The machine-readable bill of materials (CycloneDX 1.6, `cyclonedx-py environment -o sbom.json`) is attached to each release rather than committed.

| Name                      | Version     | License                                            | URL                                                                                |
|---------------------------|-------------|----------------------------------------------------|------------------------------------------------------------------------------------|
| Jinja2                    | 3.1.6       | BSD License                                        | https://github.com/pallets/jinja/                                                  |
| MarkupSafe                | 3.0.4       | BSD-3-Clause                                       | https://github.com/pallets/markupsafe/                                             |
| PyJWT                     | 2.15.1      | MIT                                                | https://github.com/jpadilla/pyjwt                                                  |
| PyYAML                    | 6.0.3       | MIT License                                        | https://pyyaml.org/                                                                |
| Pygments                  | 2.21.0      | BSD-2-Clause                                       | https://pygments.org                                                               |
| annotated-doc             | 0.0.5       | MIT                                                | https://github.com/fastapi/annotated-doc                                           |
| annotated-types           | 0.8.0       | MIT                                                | https://github.com/annotated-types/annotated-types                                 |
| anthropic                 | 1.15.0      | MIT License                                        | https://github.com/anthropics/anthropic-sdk-python                                 |
| anyio                     | 4.15.1      | MIT                                                | https://anyio.readthedocs.io/en/stable/versionhistory.html                         |
| arrow                     | 1.4.0       | Apache Software License                            | https://github.com/arrow-py/arrow                                                  |
| ast_serialize             | 0.13.1      | MIT                                                | https://github.com/mypyc/ast_serialize                                             |
| attrs                     | 26.1.0      | MIT                                                | https://www.attrs.org/en/stable/changelog.html                                     |
| boolean.py                | 5.0         | BSD-2-Clause                                       | https://github.com/bastikr/boolean.py                                              |
| brotli                    | 1.2.0       | MIT                                                | https://github.com/google/brotli                                                   |
| certifi                   | 2026.7.22   | Mozilla Public License 2.0 (MPL 2.0)               | https://github.com/certifi/python-certifi                                          |
| cffi                      | 2.1.1       | MIT-0                                              | https://cffi.readthedocs.io/en/latest/whatsnew.html                                |
| cfgv                      | 3.5.0       | MIT                                                | https://github.com/asottile/cfgv                                                   |
| chardet                   | 7.6.0       | 0BSD                                               | https://github.com/chardet/chardet                                                 |
| click                     | 8.5.0       | BSD-3-Clause                                       | https://github.com/pallets/click/                                                  |
| contourpy                 | 1.4.0       | BSD-3-Clause                                       | https://github.com/contourpy/contourpy                                             |
| cryptography              | 50.0.2      | Apache-2.0 OR BSD-3-Clause                         | https://github.com/pyca/cryptography                                               |
| cycler                    | 0.12.1      | BSD License                                        | https://matplotlib.org/cycler/                                                     |
| cyclonedx-bom             | 7.5.0       | Apache Software License                            | https://github.com/CycloneDX/cyclonedx-python/#readme                              |
| cyclonedx-python-lib      | 11.12.0     | Apache Software License                            | https://github.com/CycloneDX/cyclonedx-python-lib/#readme                          |
| defusedxml                | 0.7.1       | Python Software Foundation License                 | https://github.com/tiran/defusedxml                                                |
| distlib                   | 0.4.4       | Python Software Foundation License                 | https://github.com/pypa/distlib                                                    |
| docstring_parser          | 0.18.0      | MIT License                                        | https://github.com/rr-/docstring_parser                                            |
| fastapi                   | 0.143.3     | MIT                                                | https://github.com/fastapi/fastapi                                                 |
| filelock                  | 4.2.0       | MIT                                                | https://github.com/tox-dev/py-filelock                                             |
| fonttools                 | 4.67.0      | MIT                                                | http://github.com/fonttools/fonttools                                              |
| formulaic                 | 1.2.2       | MIT                                                | https://github.com/matthewwardrop/formulaic                                        |
| fqdn                      | 1.6.0       | MPL-2.0                                            | https://github.com/ypcrts/fqdn                                                     |
| fsspec                    | 2026.9.0    | BSD-3-Clause                                       | https://github.com/fsspec/filesystem_spec                                          |
| gradio                    | 6.30.0      | Apache-2.0                                         | https://github.com/gradio-app/gradio                                               |
| gradio_client             | 2.7.2       | Apache-2.0                                         | https://github.com/gradio-app/gradio                                               |
| groovy                    | 0.1.2       | MIT License                                        | https://github.com/gradio-app/groovy                                               |
| h11                       | 0.16.0      | MIT License                                        | https://github.com/python-hyper/h11                                                |
| hf-gradio                 | 0.4.1       | MIT                                                | https://github.com/gradio-app/hf-gradio#                                           |
| hf-xet                    | 1.7.0       | Apache-2.0                                         | https://github.com/huggingface/xet-core                                            |
| httpcore                  | 1.0.9       | BSD-3-Clause                                       | https://www.encode.io/httpcore/                                                    |
| httpcore2                 | 2.13.1      | BSD-3-Clause                                       | https://github.com/pydantic/httpx2                                                 |
| httpx                     | 0.28.1      | BSD License                                        | https://github.com/encode/httpx                                                    |
| httpx2                    | 2.13.1      | BSD-3-Clause                                       | https://github.com/pydantic/httpx2                                                 |
| huggingface_hub           | 2.2.0       | Apache Software License                            | https://github.com/huggingface/huggingface_hub                                     |
| identify                  | 2.6.20      | MIT                                                | https://github.com/pre-commit/identify                                             |
| idna                      | 3.20        | BSD-3-Clause                                       | https://github.com/kjd/idna                                                        |
| iniconfig                 | 2.3.1       | MIT                                                | https://github.com/pytest-dev/iniconfig                                            |
| interface_meta            | 2.0.1       | MIT                                                | https://github.com/matthewwardrop/interface_meta                                   |
| isoduration               | 20.11.0     | ISC License (ISCL)                                 | https://github.com/bolsote/isoduration                                             |
| jiter                     | 0.17.0      | MIT                                                | https://github.com/pydantic/jiter/                                                 |
| jsonpointer               | 3.2.1       | BSD License                                        | https://github.com/stefankoegl/python-json-pointer                                 |
| jsonschema                | 4.26.0      | MIT                                                | https://github.com/python-jsonschema/jsonschema                                    |
| jsonschema-specifications | 2025.9.1    | MIT                                                | https://github.com/python-jsonschema/jsonschema-specifications                     |
| kiwisolver                | 1.5.1       | BSD License                                        | https://github.com/nucleic/kiwi                                                    |
| lark                      | 1.3.1       | MIT License                                        | https://github.com/lark-parser/lark                                                |
| librt                     | 0.16.0      | MIT                                                | https://github.com/mypyc/librt                                                     |
| license-expression        | 30.4.4      | Apache-2.0                                         | https://github.com/aboutcode-org/license-expression                                |
| lxml                      | 6.1.3       | BSD-3-Clause                                       | https://lxml.de/                                                                   |
| markdown-it-py            | 4.2.0       | MIT License                                        | https://github.com/executablebooks/markdown-it-py                                  |
| matplotlib                | 3.11.2      | Python Software Foundation License                 | https://matplotlib.org                                                             |
| mcp                       | 2.3.0       | MIT License                                        | https://modelcontextprotocol.io                                                    |
| mcp-types                 | 2.3.0       | MIT License                                        | https://modelcontextprotocol.io                                                    |
| mdurl                     | 0.1.2       | MIT License                                        | https://github.com/executablebooks/mdurl                                           |
| mypy                      | 2.4.0       | MIT                                                | https://www.mypy-lang.org/                                                         |
| mypy_extensions           | 1.1.0       | MIT                                                | https://github.com/python/mypy_extensions                                          |
| narwhals                  | 2.27.1      | MIT                                                | https://github.com/narwhals-dev/narwhals                                           |
| nodeenv                   | 1.11.0      | BSD License                                        | https://github.com/ekalinin/nodeenv                                                |
| numpy                     | 2.5.4       | BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0 | https://numpy.org                                                                  |
| opentelemetry-api         | 1.45.1      | Apache-2.0                                         | https://github.com/open-telemetry/opentelemetry-python/tree/main/opentelemetry-api |
| orjson                    | 3.13.0      | MPL-2.0 AND (Apache-2.0 OR MIT)                    | https://github.com/ijl/orjson                                                      |
| packageurl-python         | 0.17.6      | MIT License                                        | https://github.com/package-url/packageurl-python                                   |
| packaging                 | 26.3        | Apache-2.0 OR BSD-2-Clause                         | https://github.com/pypa/packaging                                                  |
| pandas                    | 3.0.6       | BSD License                                        | https://pandas.pydata.org                                                          |
| pathspec                  | 1.1.1       | Mozilla Public License 2.0 (MPL 2.0)               | https://python-path-specification.readthedocs.io/en/latest/index.html              |
| patsy                     | 1.0.3       | BSD License                                        | https://github.com/pydata/patsy                                                    |
| pillow                    | 12.3.0      | MIT-CMU                                            | https://python-pillow.github.io                                                    |
| pip-requirements-parser   | 32.0.1      | MIT                                                | https://github.com/nexB/pip-requirements-parser                                    |
| platformdirs              | 4.13.3      | MIT                                                | https://github.com/tox-dev/platformdirs                                            |
| plotly                    | 7.1.0       | MIT                                                | https://plotly.com/python/                                                         |
| pluggy                    | 1.7.0       | MIT License                                        | https://github.com/pytest-dev/pluggy                                               |
| pre_commit                | 4.7.0       | MIT                                                | https://github.com/pre-commit/pre-commit                                           |
| py-serializable           | 2.1.0       | Apache Software License                            | https://github.com/madpah/serializable#readme                                      |
| pycparser                 | 3.11        | BSD-3-Clause                                       | https://github.com/eliben/pycparser                                                |
| pydantic                  | 2.14.1      | MIT                                                | https://github.com/pydantic/pydantic                                               |
| pydantic_core             | 2.50.1      | MIT                                                | https://github.com/pydantic                                                        |
| pydub                     | 0.25.1      | MIT License                                        | http://pydub.com                                                                   |
| pyparsing                 | 3.3.3       | MIT                                                | https://github.com/pyparsing/pyparsing/                                            |
| pytest                    | 9.1.1       | MIT                                                | https://docs.pytest.org/en/latest/                                                 |
| pytest-socket             | 0.8.1       | MIT                                                | https://pypi.org/project/pytest-socket/                                            |
| python-dateutil           | 2.9.0.post0 | Apache Software License; BSD License               | https://github.com/dateutil/dateutil                                               |
| python-discovery          | 1.6.3       | MIT License                                        | https://github.com/tox-dev/python-discovery                                        |
| python-multipart          | 0.0.32      | Apache-2.0                                         | https://github.com/Kludex/python-multipart                                         |
| pytz                      | 2026.5      | MIT License                                        | http://pythonhosted.org/pytz                                                       |
| qpilot                    | 0.1.0       | Apache-2.0                                         | UNKNOWN                                                                            |
| referencing               | 0.37.0      | MIT                                                | https://github.com/python-jsonschema/referencing                                   |
| rfc3339-validator         | 0.1.4       | MIT License                                        | https://github.com/naimetti/rfc3339-validator                                      |
| rfc3986-validator         | 0.1.1       | MIT License                                        | https://github.com/naimetti/rfc3986-validator                                      |
| rfc3987-syntax            | 1.1.0       | MIT                                                | https://github.com/willynilly/rfc3987-syntax                                       |
| rich                      | 15.0.0      | MIT License                                        | https://github.com/Textualize/rich                                                 |
| rpds-py                   | 2026.9.1    | MIT                                                | https://github.com/crate-py/rpds                                                   |
| ruff                      | 0.17.1      | MIT                                                | https://docs.astral.sh/ruff                                                        |
| safehttpx                 | 0.1.7       | MIT License                                        | https://github.com/gradio-app/safehttpx                                            |
| scipy                     | 1.18.1      | BSD License                                        | https://scipy.org/                                                                 |
| semantic-version          | 2.10.0      | BSD License                                        | https://github.com/rbarrois/python-semanticversion                                 |
| shellingham               | 1.5.4       | ISC License (ISCL)                                 | https://github.com/sarugaku/shellingham                                            |
| six                       | 1.17.0      | MIT License                                        | https://github.com/benjaminp/six                                                   |
| sniffio                   | 1.3.1       | Apache Software License; MIT License               | https://github.com/python-trio/sniffio                                             |
| sortedcontainers          | 2.4.0       | Apache Software License                            | http://www.grantjenks.com/docs/sortedcontainers/                                   |
| sse-starlette             | 3.5.0       | BSD-3-Clause                                       | https://github.com/sysid/sse-starlette                                             |
| starlette                 | 1.8.0       | BSD-3-Clause                                       | https://github.com/Kludex/starlette                                                |
| statsmodels               | 0.15.0      | BSD-3-Clause                                       | https://www.statsmodels.org                                                        |
| tomlkit                   | 0.14.0      | MIT License                                        | https://github.com/sdispater/tomlkit                                               |
| tqdm                      | 4.70.1      | MPL-2.0 AND MIT                                    | https://tqdm.github.io                                                             |
| truststore                | 0.10.5      | MIT                                                | https://github.com/sethmlarson/truststore                                          |
| typer                     | 0.27.3      | MIT                                                | https://github.com/fastapi/typer                                                   |
| typing-inspection         | 0.4.4       | MIT                                                | https://github.com/pydantic/typing-inspection                                      |
| typing_extensions         | 4.16.0      | PSF-2.0                                            | https://github.com/python/typing_extensions                                        |
| tzdata                    | 2026.5      | Apache-2.0                                         | https://github.com/python/tzdata                                                   |
| uri-template              | 1.3.0       | MIT License                                        | https://gitlab.linss.com/open-source/python/uri-template                           |
| uvicorn                   | 0.54.0      | BSD-3-Clause                                       | https://uvicorn.dev/                                                               |
| virtualenv                | 21.14.8     | MIT                                                | https://github.com/pypa/virtualenv                                                 |
| webcolors                 | 25.10.0     | BSD License                                        | https://webcolors.readthedocs.io                                                   |
| wrapt                     | 2.5.1       | BSD-2-Clause                                       | https://github.com/GrahamDumpleton/wrapt                                           |
