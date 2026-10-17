# Test fixtures

| File | What it is | Source / licence |
|---|---|---|
| `results.json`, `cards.json`, `facts.json` | The T0 contract fixtures (`qpilot.schemas.StudyResult`, `list[DecisionCard]`, `dict[str, Fact]`) for the 64-plate Vermeulen demo study. Both developers build against these until the 16:30 checkpoint, when Dev 1 regenerates them from the real engine. | Generated at T0 from the oracle cache (rdmlpython @ `fce7a44` LinRegPCR output on `data_vermeulen_raw.rdml`) with the logic of `planning/verification/verify.py`. Numbers reproduce the locked plan §6. |
| `test_mca_1_raw_data.rdml` | Small real RDML file (32 KB) for unit tests that must run without the demo dataset. | rdmlpython repository @ `fce7a44`, `test/`, MIT. |
| `vermeulen_std_150000.rdml` | 54 KB subset of the demo study: the same 64 plates and experiment id (`biomarker_set`) but only the 150,000-copy dilution-standard wells (192 rows). Lets the curve code run on real LinRegPCR input in CI without the 7 MB download. | Vermeulen et al. 2009 / Ruijter et al. 2013, CC BY 4.0; file `experiments/vermeulen/data_vermeulen_std_150000_150000.rdml` from the rdmlpython repository @ `fce7a44`. |
| `xxe.rdml` | Three-line RDML with an external entity declaration (`canary.txt`), used to prove the loader never resolves external entities. | Written for qPilot. |

Do not add the demo dataset here; it is fetched at runtime and never committed.
