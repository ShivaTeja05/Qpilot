# Vendored: rdmlpython (LinRegPCR)

**Do not edit any file in this directory.** It is a verbatim copy of upstream so that qPilot's numbers never change underneath us and can be validated against the RDML consortium's published results.

| | |
|---|---|
| Upstream | https://github.com/RDML-consortium/rdmlpython |
| Commit | `fce7a44e8b47b90759c646b557de568f7af77e75` (2 May 2026) |
| Copied | 17 Oct 2026 |
| Licence | MIT (`LICENSE`, Copyright (c) 2019 the RDML-consortium; `schema/LICENSE`, Copyright (c) 2008-2022 the RDML-consortium) |
| Files | `rdml.py` (LinRegPCR and the RDML object model), `schema/RDML_v1_{0,1,2,3}_REC.xsd`, `schema/RDML_v1_4_CR.xsd` (used by `Rdml.validate()`) |
| Not copied | Upstream tests, experiments, schema PNG diagrams, RDES specs |

## SHA-256
```
132160290a7811b7484d0c274a6221b971013a7686b0895e4ac92e124693c5df  rdml.py
b3adcb055525c3bf94b143015b3c57cdc4aaa1584d75fc9946b6d4c096de5a51  LICENSE
393a0a7dd83d5faef80bba4666d8da920f9deb44c90a6cef0d8a11fc2b1926c0  schema/LICENSE
c6a07cd22f827022ee646f7c69378d1a168428db94f1490516f30de80be993d6  schema/RDML_v1_0_REC.xsd
d1a197323856287553724901513e9bf009886e918ce007eb5bd1db0aafeab2a4  schema/RDML_v1_1_REC.xsd
5ec7bb1e0c333a9ac5f31b881b205d1521ba315e2e0b9071d858c78fc98defb6  schema/RDML_v1_2_REC.xsd
47e635039c64804b44c7f31e1957be954776a4c9bbf29f207fa7ee66ad8885d6  schema/RDML_v1_3_REC.xsd
83f376f5abe50b135f85f95cc9762b1cbb1e6e322168dae75f0aa8f6e7c58f7d  schema/RDML_v1_4_CR.xsd
```
`tests/engine/test_rdml_io.py::test_vendored_files_unchanged` fails if any of these hashes change.

## Why not `pip install rdmlpython`?
PyPI's latest release (1.7.2, 2023) cannot read RDML 1.4; the upstream `main` branch at the commit above can.

## How qPilot uses it safely
`rdml.py` parses XML with lxml's default parser (`et.fromstring` without a parser argument). qPilot never imports it directly: `qpilot.io.rdml_io.load()` first checks file sizes and installs a hardened default parser (entity resolution and network access off), then calls `rdml.Rdml(path)`. Upstream also strips `<!ENTITY>` declarations before parsing; we rely on both layers.

`rdml.py` imports matplotlib at module level for melt-curve SVG plots; qPilot never calls those, but matplotlib is a declared dependency so the import works.

## Updating
Replace the files from a new upstream commit, update the commit and every hash above and in `THIRD_PARTY_NOTICES.md`, and re-run the validation script (`validation/run_validation.py`) before merging.
