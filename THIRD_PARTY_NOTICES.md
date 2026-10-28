# Third-party notices

qPilot is licensed under the Apache License 2.0 (see `LICENSE`). It vendors, depends on, or uses the following third-party works. Python licences were checked with `pip-licenses` on 17 Oct 2026 (generated table at the end); the npm packages and fonts of the page were listed from `frontend/package-lock.json` on 20 Oct 2026 (section "The page"). Re-run both before tagging a release. The tables are the human-readable summary.

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
| fastapi | MIT; serves the page and the API (`qpilot app`) |
| uvicorn | BSD-3-Clause; the server process |
| python-multipart | Apache-2.0; reads the page's file uploads |
| gradio | Apache-2.0; only the old pages use it, and it is removed with them |
| plotly | MIT |
| PyYAML | MIT |
| filelock | MIT |
| matplotlib | Matplotlib License (PSF-based, BSD-compatible); required by the vendored rdmlpython import |
| pyarrow | Apache-2.0; the Decision Simulator's analysis grid is written as parquet |
| openpyxl | MIT; reads and writes the `.xlsx` files of Studio, Sheet Check and the Excel export |

## Optional dependencies
| Package | Extra | Licence |
|---|---|---|
| anthropic | `ai` | MIT |
| httpx | `ai` | BSD-3-Clause |

## The page: npm packages and fonts
The page is built from `frontend/` (React, TypeScript, Vite, Tailwind CSS) into `qpilot/web/static/`, which is part of the `qpilot` Python package, so installing qPilot never needs Node. Everything the page runs is bundled with it: it loads no script, style, font or image from the internet (its Content-Security-Policy refuses it; see `THREAT_MODEL.md`).

### What is listed, and how it was generated
The list below is the **production dependency closure** of `frontend/package.json` (its `dependencies`, with everything they depend on), exactly as pinned in `frontend/package-lock.json`: **110 packages**, 20 of them direct (in bold). The bundler leaves out code the page does not import, so the JavaScript that ships is a subset of this list; the list is the upper bound, and nothing outside it ships. Packages used only to build and test the page (TypeScript, ESLint, Vitest, Playwright, the type packages, …) are not shipped and are not listed, except the two build tools in the last table of this section, whose own code ends up in the output.

Licences present: MIT (95), ISC (11), OFL-1.1 (2, the fonts), 0BSD (1), Unlicense (1). No package declares GPL, LGPL, AGPL or any other copyleft licence.

It was generated on 20 Oct 2026 with the script below, which takes the packages of `package-lock.json` that are not marked `dev` or `devOptional`, reads each one's `node_modules/<name>/package.json` for name, version and licence, and takes the copyright notice from the first line of the package's own licence file that starts with "Copyright" (or `(c)`, or ©). A package whose licence file has no such line (or that has no licence file) shows its `package.json` author instead, and says so. The script also checks that the licence in `package.json` equals the one in the lockfile (it did, for all 110), and the list agrees with `npm ls --omit=dev --all` apart from three type-only packages (`@types/react`, `@types/react-dom`, `csstype`) that npm counts as peer dependencies and the lockfile marks as development-only. Re-run it after `npm ci` whenever `frontend/package-lock.json` changes.

<details>
<summary>The generator (Python 3, standard library only; run as <code>python3 -I gen_npm_notices.py frontend</code> after <code>npm ci</code>)</summary>

```python
"""Generate the npm table of THIRD_PARTY_NOTICES.md from frontend/package-lock.json + node_modules.

Usage: python3 -I gen_npm_notices.py <frontend dir>   (stdlib only; table on stdout, notes on stderr)
"""

import json
import re
import sys
from pathlib import Path

front = Path(sys.argv[1])
lock = json.loads((front / "package-lock.json").read_text(encoding="utf-8"))
root_deps = set(lock["packages"][""].get("dependencies", {}))
COPYRIGHT = re.compile(r"^\s*(copyright|\(c\)|©)", re.IGNORECASE)
LICENCE_FILE = re.compile(r"^(licen[sc]e|copying)", re.IGNORECASE)
rows = []
problems = []
for path, entry in sorted(lock["packages"].items()):
    if not path or entry.get("dev") or entry.get("devOptional"):
        continue  # the root, or a package only the build and the tests use
    pkg_json = front / path / "package.json"
    if not pkg_json.is_file():
        problems.append(f"{path}: not installed")
        continue
    meta = json.loads(pkg_json.read_text(encoding="utf-8"))
    name, version = meta["name"], meta["version"]
    lic = meta.get("license")
    if isinstance(lic, dict):
        lic = lic.get("type")
    if lic != entry.get("license"):
        problems.append(f"{name}: lock says {entry.get('license')}, package says {lic}")
    holder = ""
    for f in sorted((front / path).iterdir()):
        if f.is_file() and LICENCE_FILE.match(f.name):
            for line in f.read_text(encoding="utf-8", errors="replace").splitlines():
                if COPYRIGHT.match(line):
                    holder = re.sub(r"\s+", " ", line).strip()
                    break
            if holder:
                break
    if not holder:
        author = meta.get("author")
        author = author.get("name") if isinstance(author, dict) else author
        if author:
            author = re.sub(r"\s*<[^>]*>|\s*\([^)]*\)", "", author).strip()
            holder = f"none in the licence file; package.json author: {author}"
        else:
            holder = "none in the package"
    rows.append((name, version, lic or "UNKNOWN", holder, name in root_deps))

print(
    "| Package | Version | Licence | Copyright notice (first line in the package's licence file) |"
)
print("|---|---|---|---|")
for name, version, lic, holder, direct in rows:
    bold = "**" if direct else ""
    print(f"| {bold}{name}{bold} | {version} | {lic} | {holder.replace('|', chr(92) + '|')} |")
print(f"{len(rows)} packages", file=sys.stderr)
for p in problems:
    print("PROBLEM:", p, file=sys.stderr)
```

</details>

### Fonts (shipped with the page)
Both fonts are the Fontsource packages' variable WOFF2 files (not modified by qPilot), bundled into `qpilot/web/static/assets/` (the page uses them through `@font-face`; nothing is fetched from a font service). Both are under the SIL Open Font License 1.1, whose full text follows; the licence requires that each copy of the font carries its copyright notice and this licence, which this file does.

| Font | npm package | Files in the build of 20 Oct 2026 | Copyright | Licence |
|---|---|---|---|---|
| Inter (variable) | `@fontsource-variable/inter` 5.3.0 | 7 WOFF2 files: latin, latin-ext, cyrillic, cyrillic-ext, greek, greek-ext, vietnamese | Copyright 2016 The Inter Project Authors (https://github.com/rsms/inter) | OFL-1.1 |
| JetBrains Mono (variable) | `@fontsource-variable/jetbrains-mono` 5.3.0 | 6 WOFF2 files: latin, latin-ext, cyrillic, cyrillic-ext, greek, vietnamese | Copyright 2020 The JetBrains Mono Project Authors (https://github.com/JetBrains/JetBrainsMono) | OFL-1.1 |

<details>
<summary>SIL Open Font License, Version 1.1 (copied unchanged from both packages' <code>LICENSE</code> files, which are identical below their copyright lines)</summary>

```text
SIL OPEN FONT LICENSE Version 1.1 - 26 February 2007
-----------------------------------------------------------

PREAMBLE
The goals of the Open Font License (OFL) are to stimulate worldwide
development of collaborative font projects, to support the font creation
efforts of academic and linguistic communities, and to provide a free and
open framework in which fonts may be shared and improved in partnership
with others.

The OFL allows the licensed fonts to be used, studied, modified and
redistributed freely as long as they are not sold by themselves. The
fonts, including any derivative works, can be bundled, embedded,
redistributed and/or sold with any software provided that any reserved
names are not used by derivative works. The fonts and derivatives,
however, cannot be released under any other type of license. The
requirement for fonts to remain under this license does not apply
to any document created using the fonts or their derivatives.

DEFINITIONS
"Font Software" refers to the set of files released by the Copyright
Holder(s) under this license and clearly marked as such. This may
include source files, build scripts and documentation.

"Reserved Font Name" refers to any names specified as such after the
copyright statement(s).

"Original Version" refers to the collection of Font Software components as
distributed by the Copyright Holder(s).

"Modified Version" refers to any derivative made by adding to, deleting,
or substituting -- in part or in whole -- any of the components of the
Original Version, by changing formats or by porting the Font Software to a
new environment.

"Author" refers to any designer, engineer, programmer, technical
writer or other person who contributed to the Font Software.

PERMISSION & CONDITIONS
Permission is hereby granted, free of charge, to any person obtaining
a copy of the Font Software, to use, study, copy, merge, embed, modify,
redistribute, and sell modified and unmodified copies of the Font
Software, subject to the following conditions:

1) Neither the Font Software nor any of its individual components,
in Original or Modified Versions, may be sold by itself.

2) Original or Modified Versions of the Font Software may be bundled,
redistributed and/or sold with any software, provided that each copy
contains the above copyright notice and this license. These can be
included either as stand-alone text files, human-readable headers or
in the appropriate machine-readable metadata fields within text or
binary files as long as those fields can be easily viewed by the user.

3) No Modified Version of the Font Software may use the Reserved Font
Name(s) unless explicit written permission is granted by the corresponding
Copyright Holder. This restriction only applies to the primary font name as
presented to the users.

4) The name(s) of the Copyright Holder(s) or the Author(s) of the Font
Software shall not be used to promote, endorse or advertise any
Modified Version, except to acknowledge the contribution(s) of the
Copyright Holder(s) and the Author(s) or with their explicit written
permission.

5) The Font Software, modified or unmodified, in part or in whole,
must be distributed entirely under this license, and must not be
distributed under any other license. The requirement for fonts to
remain under this license does not apply to any document created
using the Font Software.

TERMINATION
This license becomes null and void if any of the above conditions are
not met.

DISCLAIMER
THE FONT SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO ANY WARRANTIES OF
MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT
OF COPYRIGHT, PATENT, TRADEMARK, OR OTHER RIGHT. IN NO EVENT SHALL THE
COPYRIGHT HOLDER BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY,
INCLUDING ANY GENERAL, SPECIAL, INDIRECT, INCIDENTAL, OR CONSEQUENTIAL
DAMAGES, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
FROM, OUT OF THE USE OR INABILITY TO USE THE FONT SOFTWARE OR FROM
OTHER DEALINGS IN THE FONT SOFTWARE.
```

</details>

### Build tools whose code is in the output
| Tool | Version | Licence | Copyright | What of it is in the page |
|---|---|---|---|---|
| Tailwind CSS (`tailwindcss`) | 4.3.3 | MIT | Copyright (c) Tailwind Labs, Inc. | Its base styles (the "preflight" reset) are compiled into the page's stylesheet |
| Vite (`vite`) | 8.3.4 | MIT | Copyright (c) 2019-present, VoidZero Inc. and Vite contributors | A small module-preloading helper is written into the page's JavaScript |

### Every package in the production closure
| Package | Version | Licence | Copyright notice (first line in the package's licence file) |
|---|---|---|---|
| @floating-ui/core | 1.8.0 | MIT | Copyright (c) 2021-present Floating UI contributors |
| @floating-ui/dom | 1.8.0 | MIT | Copyright (c) 2021-present Floating UI contributors |
| @floating-ui/react-dom | 2.1.9 | MIT | Copyright (c) 2021-present Floating UI contributors |
| @floating-ui/utils | 0.2.12 | MIT | Copyright (c) 2021-present Floating UI contributors |
| **@fontsource-variable/inter** | 5.3.0 | OFL-1.1 | Copyright 2016 The Inter Project Authors (https://github.com/rsms/inter) Inter-Italic[opsz,wght].ttf: Copyright 2016 The Inter Project Authors (https://github.com/rsms/inter) |
| **@fontsource-variable/jetbrains-mono** | 5.3.0 | OFL-1.1 | Copyright 2020 The JetBrains Mono Project Authors (https://github.com/JetBrains/JetBrainsMono) JetBrainsMono-Italic[wght].ttf: Copyright 2020 The JetBrains Mono Project Authors (https://github.com/JetBrains/JetBrainsMono) |
| @radix-ui/number | 1.1.3 | MIT | Copyright (c) 2022 WorkOS |
| @radix-ui/primitive | 1.2.0 | MIT | Copyright (c) 2022 WorkOS |
| @radix-ui/react-accessible-icon | 1.2.0 | MIT | Copyright (c) 2022 WorkOS |
| @radix-ui/react-accordion | 1.3.1 | MIT | Copyright (c) 2022 WorkOS |
| @radix-ui/react-alert-dialog | 1.2.1 | MIT | Copyright (c) 2022 WorkOS |
| @radix-ui/react-arrow | 1.1.17 | MIT | Copyright (c) 2022 WorkOS |
| @radix-ui/react-aspect-ratio | 1.2.0 | MIT | Copyright (c) 2022 WorkOS |
| @radix-ui/react-avatar | 1.3.1 | MIT | Copyright (c) 2022 WorkOS |
| @radix-ui/react-checkbox | 1.4.1 | MIT | Copyright (c) 2022 WorkOS |
| @radix-ui/react-collapsible | 1.2.1 | MIT | Copyright (c) 2022 WorkOS |
| @radix-ui/react-collection | 1.2.0 | MIT | Copyright (c) 2022 WorkOS |
| @radix-ui/react-compose-refs | 1.1.5 | MIT | Copyright (c) 2022 WorkOS |
| @radix-ui/react-context | 1.3.0 | MIT | Copyright (c) 2022 WorkOS |
| @radix-ui/react-context-menu | 2.4.1 | MIT | Copyright (c) 2022 WorkOS |
| @radix-ui/react-dialog | 1.3.1 | MIT | Copyright (c) 2022 WorkOS |
| @radix-ui/react-direction | 1.2.0 | MIT | Copyright (c) 2022 WorkOS |
| @radix-ui/react-dismissable-layer | 1.2.1 | MIT | Copyright (c) 2022 WorkOS |
| @radix-ui/react-dropdown-menu | 2.2.1 | MIT | Copyright (c) 2022 WorkOS |
| @radix-ui/react-focus-guards | 1.2.0 | MIT | Copyright (c) 2022 WorkOS |
| @radix-ui/react-focus-scope | 1.3.1 | MIT | Copyright (c) 2022 WorkOS |
| @radix-ui/react-form | 0.3.0 | MIT | Copyright (c) 2022 WorkOS |
| @radix-ui/react-hover-card | 1.2.1 | MIT | Copyright (c) 2022 WorkOS |
| @radix-ui/react-id | 1.1.4 | MIT | Copyright (c) 2022 WorkOS |
| @radix-ui/react-label | 2.1.17 | MIT | Copyright (c) 2022 WorkOS |
| @radix-ui/react-menu | 2.2.1 | MIT | Copyright (c) 2022 WorkOS |
| @radix-ui/react-menubar | 1.2.1 | MIT | Copyright (c) 2022 WorkOS |
| @radix-ui/react-navigation-menu | 1.4.1 | MIT | Copyright (c) 2022 WorkOS |
| @radix-ui/react-one-time-password-field | 0.2.1 | MIT | Copyright (c) 2022 WorkOS |
| @radix-ui/react-password-toggle-field | 0.2.1 | MIT | Copyright (c) 2022 WorkOS |
| @radix-ui/react-popover | 1.3.1 | MIT | Copyright (c) 2022 WorkOS |
| @radix-ui/react-popper | 1.4.0 | MIT | Copyright (c) 2022 WorkOS |
| @radix-ui/react-portal | 1.2.0 | MIT | Copyright (c) 2022 WorkOS |
| @radix-ui/react-presence | 1.1.11 | MIT | Copyright (c) 2022 WorkOS |
| @radix-ui/react-primitive | 2.2.0 | MIT | Copyright (c) 2022 WorkOS |
| @radix-ui/react-progress | 1.2.1 | MIT | Copyright (c) 2022 WorkOS |
| @radix-ui/react-radio-group | 1.5.1 | MIT | Copyright (c) 2022 WorkOS |
| @radix-ui/react-roving-focus | 1.2.1 | MIT | Copyright (c) 2022 WorkOS |
| @radix-ui/react-scroll-area | 1.4.0 | MIT | Copyright (c) 2022 WorkOS |
| @radix-ui/react-select | 2.4.1 | MIT | Copyright (c) 2022 WorkOS |
| @radix-ui/react-separator | 1.2.0 | MIT | Copyright (c) 2022 WorkOS |
| @radix-ui/react-slider | 1.6.1 | MIT | Copyright (c) 2022 WorkOS |
| @radix-ui/react-slot | 1.5.0 | MIT | Copyright (c) 2022 WorkOS |
| @radix-ui/react-switch | 1.4.1 | MIT | Copyright (c) 2022 WorkOS |
| @radix-ui/react-tabs | 1.2.1 | MIT | Copyright (c) 2022 WorkOS |
| @radix-ui/react-toast | 1.3.1 | MIT | Copyright (c) 2022 WorkOS |
| @radix-ui/react-toggle | 1.2.1 | MIT | Copyright (c) 2022 WorkOS |
| @radix-ui/react-toggle-group | 1.2.1 | MIT | Copyright (c) 2022 WorkOS |
| @radix-ui/react-toolbar | 1.2.1 | MIT | Copyright (c) 2022 WorkOS |
| @radix-ui/react-tooltip | 1.4.1 | MIT | Copyright (c) 2022 WorkOS |
| @radix-ui/react-use-callback-ref | 1.1.5 | MIT | Copyright (c) 2022 WorkOS |
| @radix-ui/react-use-controllable-state | 1.3.0 | MIT | Copyright (c) 2022 WorkOS |
| @radix-ui/react-use-effect-event | 0.0.5 | MIT | Copyright (c) 2022 WorkOS |
| @radix-ui/react-use-escape-keydown | 1.1.6 | MIT | Copyright (c) 2022 WorkOS |
| @radix-ui/react-use-is-hydrated | 0.1.3 | MIT | Copyright (c) 2022 WorkOS |
| @radix-ui/react-use-layout-effect | 1.1.4 | MIT | Copyright (c) 2022 WorkOS |
| @radix-ui/react-use-previous | 1.1.4 | MIT | Copyright (c) 2022 WorkOS |
| @radix-ui/react-use-rect | 1.1.4 | MIT | Copyright (c) 2022 WorkOS |
| @radix-ui/react-use-size | 1.1.5 | MIT | Copyright (c) 2022 WorkOS |
| @radix-ui/react-visually-hidden | 1.2.13 | MIT | Copyright (c) 2022 WorkOS |
| @radix-ui/rect | 1.1.3 | MIT | Copyright (c) 2022 WorkOS |
| @tanstack/query-core | 5.104.5 | MIT | Copyright (c) 2021-present Tanner Linsley |
| **@tanstack/react-query** | 5.104.5 | MIT | Copyright (c) 2021-present Tanner Linsley |
| **@tanstack/react-table** | 8.21.3 | MIT | Copyright (c) 2016 Tanner Linsley |
| **@tanstack/react-virtual** | 3.14.21 | MIT | Copyright (c) 2021-present Tanner Linsley |
| @tanstack/table-core | 8.21.3 | MIT | Copyright (c) 2016 Tanner Linsley |
| @tanstack/virtual-core | 3.19.6 | MIT | Copyright (c) 2021-present Tanner Linsley |
| aria-hidden | 1.2.6 | MIT | Copyright (c) 2017 Anton Korzunov |
| **clsx** | 2.1.1 | MIT | Copyright (c) Luke Edwards <luke.edwards05@gmail.com> (lukeed.com) |
| **cmdk** | 1.1.1 | MIT | Copyright (c) 2022 Paco Coursey |
| **d3-array** | 3.2.4 | ISC | Copyright 2010-2023 Mike Bostock |
| d3-color | 3.1.0 | ISC | Copyright 2010-2022 Mike Bostock |
| d3-format | 3.1.2 | ISC | Copyright 2010-2026 Mike Bostock |
| d3-interpolate | 3.0.1 | ISC | Copyright 2010-2021 Mike Bostock |
| d3-path | 3.1.0 | ISC | Copyright 2015-2022 Mike Bostock |
| **d3-scale** | 4.0.2 | ISC | Copyright 2010-2021 Mike Bostock |
| **d3-shape** | 3.2.0 | ISC | Copyright 2010-2022 Mike Bostock |
| d3-time | 3.1.0 | ISC | Copyright 2010-2022 Mike Bostock |
| d3-time-format | 4.1.0 | ISC | Copyright 2010-2021 Mike Bostock |
| detect-node-es | 1.1.0 | MIT | Copyright (c) 2017 Ilya Kantor |
| framer-motion | 14.4.0 | MIT | Copyright (c) 2018 Framer B.V. |
| get-nonce | 1.0.1 | MIT | Copyright (c) 2020 Anton Korzunov |
| internmap | 2.0.3 | ISC | Copyright 2021 Mike Bostock |
| **lucide-react** | 1.60.0 | ISC | Copyright (c) 2026 Lucide Icons and Contributors |
| **motion** | 14.4.0 | MIT | Copyright (c) 2024 [Motion](https://motion.dev) B.V. |
| motion-dom | 14.4.0 | MIT | Copyright (c) 2024 [Motion](https://motion.dev) B.V. |
| motion-utils | 14.1.1 | MIT | Copyright (c) 2024 [Motion](https://motion.dev) B.V. |
| **openapi-fetch** | 0.17.0 | MIT | Copyright (c) 2023 Drew Powers |
| openapi-typescript-helpers | 0.1.0 | MIT | Copyright (c) 2023 Drew Powers |
| **radix-ui** | 1.8.1 | MIT | Copyright (c) 2022 WorkOS |
| **react** | 19.3.1 | MIT | Copyright (c) Meta Platforms, Inc. and affiliates. |
| **react-dom** | 19.3.1 | MIT | Copyright (c) Meta Platforms, Inc. and affiliates. |
| react-remove-scroll | 2.7.2 | MIT | Copyright (c) 2017 Anton Korzunov |
| react-remove-scroll-bar | 2.3.8 | MIT | none in the licence file; package.json author: Anton Korzunov |
| react-style-singleton | 2.2.3 | MIT | Copyright (c) 2017 Anton Korzunov |
| regexparam | 3.0.0 | MIT | Copyright (c) Luke Edwards <luke.edwards05@gmail.com> (lukeed.com) |
| scheduler | 0.28.0 | MIT | Copyright (c) Meta Platforms, Inc. and affiliates. |
| **sonner** | 2.0.8 | MIT | Copyright (c) 2023 Emil Kowalski |
| **tailwind-merge** | 3.7.0 | MIT | Copyright (c) 2021 Dany Castillo |
| tslib | 2.8.1 | 0BSD | Copyright (c) Microsoft Corporation. |
| **uplot** | 1.6.32 | MIT | Copyright (c) 2022 Leon Sorokin |
| use-callback-ref | 1.3.3 | MIT | Copyright (c) 2017 Anton Korzunov |
| use-sidecar | 1.1.3 | MIT | Copyright (c) 2017 Anton Korzunov |
| use-sync-external-store | 1.7.0 | MIT | Copyright (c) Meta Platforms, Inc. and affiliates. |
| **wouter** | 3.13.0 | Unlicense | none in the licence file; package.json author: Alexey Taktarov |

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
| Public instrument-export corpus, `tests/fixtures/corpus/` (18 real sets, byte-identical to source; per-file SHA-256, source URL and licence evidence in each `MANIFEST.yaml`, list in `tests/fixtures/corpus/README.md`) | CC0-1.0, CC BY 4.0, MIT or Apache-2.0, per set | Test fixtures for the readers, raw-ness detector and Run Gate; never shipped in the package. **CC BY 4.0 attributions:** Grünewald L, Chiocchetti AG, Weber H, Scholz C-J, Schartner C, Freudenberg F, Reif A (2018), Mendeley Data doi:10.17632/rtsx7zpt4w.1 (LightCycler 480 export); Śmiga M, Olczak T (2025), Zenodo doi:10.5281/zenodo.14965510 (LightCycler 96 files; renamed); Humphrey MRH, Nolan KP, Hanner RH, Borealis doi:10.5683/SP3/GFMPYU (QuantStudio 7 Pro RDML); Büchner K, Ludwig C, Kerpes R, Becker T (2025), Figshare doi:10.6084/m9.figshare.29908870.v1 (LinRegPCR RDML); Burgess S (2022), Figshare doi:10.6084/m9.figshare.20247459.v2 (Cq-only RDML). **MIT/Apache notices** (copyright holders): Konstantin A. Blagodatskikh (RDML R package, 2019); ramiromagno (2017; rpa.rdml courtesy of the Raquel P. Andrade Lab, CBMR); Benchling, Inc. (2023, allotropy test data); ZamanianLab (2017); covmatic contributors (affafjunaidMOMIN, 2020); gurtecho (2023); SecureBio / McLaren et al. (LICENSE.md); Opentrons (Apache-2.0); Wellcome Sanger Institute - PSD (2024); NOMADS Community (2026). **CC0:** Hsieh et al. / Wendy Liu lab (WendyLiuLab/Hsieh2016PCR `raw-data/`). |
| Synthetic qPCR exports, `tests/fixtures/corpus/synthetic/` | Apache-2.0 (generated by `tests/fixtures/corpus/_generators/qpcr_synth.py`) | Format-faithful CFX / QuantStudio layouts with known ground truth; labelled SYNTHETIC. |
| Decision Simulator results, `sim/results/` (per-gene, per-sample and per-well summaries such as `one_sample_flips.csv` and `reference_wells_top50.csv`) | CC BY 4.0, as adaptations of Vermeulen et al. 2009 / Ruijter et al. 2013 (attribution as in the first row of this table) | Committed outputs of `qsim run` on the demo study. The raw RDML is still never committed. |
| RDML technical test files, `sim/data/technical/` | MIT (RDML-consortium/rdmlpython @ `e9f936b`, `experiments/technical/`) | Committed unchanged for `qsim external`; provenance in `sim/data/technical/README.md`. |
| Ruijter et al. 2013 `ds_380`, `ds_94_4`, `ds_competimer`, `sim/data/ruijter/` (R package `ruijter` 0.1.3 by Ramiro Magno, commit `f9d2df4`) | CC BY 4.0 | Committed for the no-difference and external tests; attribution: Ruijter J.M. et al., *Methods* 59:32-46 (2013), doi:10.1016/j.ymeth.2012.08.011. `ds_380.rdml` is converted from the CSV by `qsim.nodiff`. Provenance and SHA-256 in `sim/data/ruijter/README.md`. |

## Not used (deliberately)
`qslib` (EUPL-1.2, copyleft), GPL-licensed R packages (`qpcR`, `chipPCR`), and NormFinder's original code (redistribution not permitted). None of these is imported or bundled. No npm package in the page's production closure is GPL, LGPL, AGPL or another copyleft licence (see "The page" above).

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
