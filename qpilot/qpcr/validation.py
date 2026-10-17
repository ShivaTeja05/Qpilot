"""Reproduce the RDML consortium's published benchmark on the demo study's standard wells.

Every plate of the demo study carries a dilution series of known input (five concentrations,
three wells each). The consortium published its own results for those wells, and this module
compares the engine against three of their tables, all fetched SHA-256-pinned from the
rdmlpython repository (:data:`qpilot.io.datasets.BENCHMARK_TABLES`):

1. **N0 per standard well** vs RDML-Tools (``RDML_Tools_bias.tsv``): the share identical to four
   significant figures (the precision of the published table) and the share within 5 %.
2. **Dilution-series bias per gene** (Ruijter 2013: the slope of log10 N0 on log10 input copies;
   1 means unbiased) vs the "LinRegPCR (old)" row of ``data_vermeulen_methods_results.tsv``.
3. **Cq per standard well** vs the 2013 "LinRegPCR" block of ``data_vermeulen_methods_cq.tsv``:
   reported as a signed offset, because LinRegPCR's quantification threshold has been defined
   differently since 2013. qPilot's comparisons use N0 (line 1), never Cq.

Genes are matched by exact name, and a gene that exists on only one side is listed rather than
guessed (``PRKACB`` in the published tables; the plate in the RDML file is ``PRKACB_20080311_bis``).
Within each (gene, concentration) both sides are sorted and paired, as in the validation oracle;
published wells with no value on our side count as disagreements.
"""

from __future__ import annotations

import csv
import json
import math
import re
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from qpilot.io.datasets import BENCHMARK_TABLES, VERMEULEN_COMMIT

WellValues = dict[tuple[str, str], list[float]]  # (gene, "STD_15") -> values of its wells

_STD_LABEL = re.compile(r"^STD_(\d+(?:\.\d+)?)$")
WITHIN = 0.05  # "within 5 %"
BIAS_BLOCK = "slope = bias"
BIAS_METHOD = "LinRegPCR (old)"
CQ_METHOD = "LinRegPCR"


# ---------- the published tables ----------


def read_rdml_tools_n0(path: str | Path) -> WellValues:
    """Published N0 per standard well from ``RDML_Tools_bias.tsv``.

    The first row names the genes from the third column on; each following row is one standard
    well (column 2 is its input copies, e.g. ``15``) until the first row without a concentration.
    """
    with Path(path).open(newline="") as handle:
        rows = list(csv.reader(handle, delimiter="\t"))
    genes = rows[0][2:]
    out: WellValues = {}
    for row in rows[1:]:
        if len(row) < 3 or not _is_number(row[1]):
            break
        for gene, value in zip(genes, row[2:], strict=False):
            if gene and _is_number(value):
                out.setdefault((gene, f"STD_{row[1]}"), []).append(float(value))
    return out


def read_methods_cq(path: str | Path, method: str = CQ_METHOD) -> WellValues:
    """Published Cq per standard well for one method from ``data_vermeulen_methods_cq.tsv``.

    Semicolon-separated; ``method;<name>;;<genes...>`` starts a method's block and names its
    columns, and ``;;STD_15;<cq...>`` rows are standard wells.
    """
    out: WellValues = {}
    genes: list[str] = []
    current = None
    with Path(path).open() as handle:
        for line in handle:
            cells = line.rstrip("\r\n").split(";")
            if cells[0] == "method":
                current, genes = cells[1], cells[3:]
            elif current == method and len(cells) > 3 and _STD_LABEL.match(cells[2]):
                for gene, value in zip(genes, cells[3:], strict=False):
                    if gene and _is_number(value):
                        out.setdefault((gene, cells[2]), []).append(float(value))
    return out


def read_methods_results(
    path: str | Path, block: str = BIAS_BLOCK, method: str = BIAS_METHOD
) -> dict[str, float]:
    """One method's per-gene values from one block of ``data_vermeulen_methods_results.tsv``.

    Tab-separated blocks: a header row (block title, then gene names) followed by one row per
    method. Only the first ``method`` row after the ``block`` header is read.
    """
    genes: list[str] | None = None
    with Path(path).open(newline="") as handle:
        for cells in csv.reader(handle, delimiter="\t"):
            if not cells:
                continue
            if cells[0] == block:
                genes = cells[1:]
            elif genes is not None and cells[0] == method:
                return {
                    gene: float(value)
                    for gene, value in zip(genes, cells[1:], strict=False)
                    if gene and _is_number(value)
                }
    raise ValueError(f"no {method!r} row in block {block!r} of {Path(path).name}")


def _is_number(text: str) -> bool:
    try:
        return math.isfinite(float(text))
    except ValueError:
        return False


# ---------- our side ----------


def standard_wells(curves: pd.DataFrame, column: str) -> WellValues:
    """Our values of one column (``n0`` or ``cq``) per (gene, concentration), NaN dropped."""
    std = curves[(curves["sample_type"] == "std") & curves["sample"].str.match(_STD_LABEL)]
    out: WellValues = {}
    for (gene, label), values in std.groupby(["target", "sample"])[column]:
        out[(gene, label)] = [float(v) for v in values.dropna()]
    return out


def _pairs(published: WellValues, ours: WellValues) -> tuple[list[tuple[float, float]], int]:
    """Sorted (published, ours) pairs for keys on both sides, and the published well count."""
    pairs: list[tuple[float, float]] = []
    wells = 0
    for key, pub in published.items():
        if key not in ours:
            continue
        wells += len(pub)
        pairs.extend(zip(sorted(pub), sorted(ours[key]), strict=False))
    return pairs, wells


def _genes(values: Mapping[tuple[str, str], object]) -> set[str]:
    return {gene for gene, _ in values}


def _copies(label: str) -> float:
    match = _STD_LABEL.match(label)
    if match is None:
        raise ValueError(f"not a standard label: {label!r}")
    return float(match.group(1))


def _names(genes: tuple[str, ...] | list[str]) -> str:
    return ", ".join(f"`{gene}`" for gene in genes) or "none"


def _pct(share: float, digits: int = 1) -> str:
    return f"{100 * share:.{digits}f} %"


# ---------- the three comparisons ----------


@dataclass(frozen=True)
class N0Line:
    """Line 1: N0 per standard well vs RDML-Tools."""

    wells: int
    genes: int
    identical_4sf: int
    within_5pct: int
    max_rel_diff: float
    published_only: tuple[str, ...]
    ours_only: tuple[str, ...]

    @property
    def share_identical(self) -> float:
        """Share of published wells whose N0 we reproduce to four significant figures."""
        return self.identical_4sf / self.wells

    @property
    def share_within(self) -> float:
        """Share of published wells whose N0 we reproduce within 5 %."""
        return self.within_5pct / self.wells


@dataclass(frozen=True)
class BiasLine:
    """Line 2: dilution-series bias per gene vs the published LinRegPCR row."""

    genes: int
    median_abs_diff: float
    max_abs_diff: float
    ours_mean: float
    published_mean: float
    published_only: tuple[str, ...]


@dataclass(frozen=True)
class CqLine:
    """Line 3: signed Cq offset per standard well (ours minus the 2013 LinRegPCR table)."""

    wells: int
    genes: int
    mean_offset: float
    sd_offset: float
    min_offset: float
    max_offset: float
    published_only: tuple[str, ...]


def compare_n0(curves: pd.DataFrame, published: WellValues) -> N0Line:
    """Compare our standard-well N0 with the RDML-Tools table."""
    ours = standard_wells(curves, "n0")
    pairs, wells = _pairs(published, ours)
    identical = sum(f"{pub:.3e}" == f"{our:.3e}" for pub, our in pairs)
    rel = [abs(our - pub) / pub for pub, our in pairs]
    return N0Line(
        wells=wells,
        genes=len(_genes(published) & _genes(ours)),
        identical_4sf=identical,
        within_5pct=sum(r <= WITHIN for r in rel),
        max_rel_diff=max(rel),
        published_only=tuple(sorted(_genes(published) - _genes(ours))),
        ours_only=tuple(sorted(_genes(ours) - _genes(published))),
    )


def dilution_bias(curves: pd.DataFrame) -> dict[str, float]:
    """Per gene: least-squares slope of log10 N0 on log10 input copies over its standard wells."""
    out = {}
    by_gene: dict[str, list[tuple[float, float]]] = {}
    for (gene, label), values in standard_wells(curves, "n0").items():
        x = math.log10(_copies(label))
        by_gene.setdefault(gene, []).extend((x, math.log10(v)) for v in values)
    for gene, points in by_gene.items():
        x, y = np.array(points).T
        out[gene] = float(np.sum((x - x.mean()) * (y - y.mean())) / np.sum((x - x.mean()) ** 2))
    return out


def compare_bias(curves: pd.DataFrame, published: Mapping[str, float]) -> BiasLine:
    """Compare our per-gene dilution-series bias with the published LinRegPCR row."""
    ours = dilution_bias(curves)
    genes = sorted(set(ours) & set(published))
    diffs = np.array([abs(ours[g] - published[g]) for g in genes])
    return BiasLine(
        genes=len(genes),
        median_abs_diff=float(np.median(diffs)),
        max_abs_diff=float(diffs.max()),
        ours_mean=float(np.mean([ours[g] for g in genes])),
        published_mean=float(np.mean([published[g] for g in genes])),
        published_only=tuple(sorted(set(published) - set(ours))),
    )


def compare_cq(curves: pd.DataFrame, published: WellValues) -> CqLine:
    """Signed per-well Cq difference, ours minus the published 2013 LinRegPCR values."""
    ours = standard_wells(curves, "cq")
    pairs, wells = _pairs(published, ours)
    diffs = np.array([our - pub for pub, our in pairs])
    return CqLine(
        wells=wells,
        genes=len(_genes(published) & _genes(ours)),
        mean_offset=float(diffs.mean()),
        sd_offset=float(diffs.std(ddof=1)),
        min_offset=float(diffs.min()),
        max_offset=float(diffs.max()),
        published_only=tuple(sorted(_genes(published) - _genes(ours))),
    )


# ---------- the report ----------


@dataclass(frozen=True)
class ValidationReport:
    """The three comparison lines plus provenance; rendered to Markdown and JSON."""

    n0: N0Line
    bias: BiasLine
    cq: CqLine

    def to_dict(self) -> dict[str, object]:
        """JSON-ready dict with no timestamps, so a re-run is byte-identical."""
        return {
            "benchmark": {
                "source": "RDML-consortium/rdmlpython experiments/vermeulen",
                "commit": VERMEULEN_COMMIT,
                "tables": {
                    key: {"file": pinned.filename, "sha256": pinned.sha256}
                    for key, pinned in BENCHMARK_TABLES.items()
                },
                "data": "Vermeulen et al. 2009; Ruijter et al. 2013 (CC BY 4.0)",
            },
            "n0": {
                **asdict(self.n0),
                "share_identical": self.n0.share_identical,
                "share_within": self.n0.share_within,
            },
            "bias": asdict(self.bias),
            "cq": asdict(self.cq),
        }

    def to_json(self) -> str:
        """Stable, indented JSON."""
        return json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n"

    def lines(self) -> list[str]:
        """The three claims in one sentence each, for the CLI, slides and README."""
        n0, bias, cq = self.n0, self.bias, self.cq
        return [
            f"N0 on {n0.wells} standard wells ({n0.genes} genes) vs RDML-Tools: "
            f"{_pct(n0.share_identical)} identical to 4 significant figures, "
            f"{_pct(n0.share_within)} within 5 % (largest difference {_pct(n0.max_rel_diff, 2)})",
            f"Dilution-series bias over {bias.genes} genes vs LinRegPCR (2013): "
            f"median |difference| {bias.median_abs_diff:.3f} "
            f"(ours {bias.ours_mean:.3f} vs published {bias.published_mean:.3f} on average)",
            f"Cq on {cq.wells} standard wells ({cq.genes} genes) vs LinRegPCR (2013): "
            f"offset {cq.mean_offset:+.2f} cycles on average (SD {cq.sd_offset:.2f}), "
            "a threshold-definition change, disclosed",
        ]

    def to_markdown(self) -> str:
        """``validation/validation_table.md``: generated, never typed."""
        n0, bias, cq = self.n0, self.bias, self.cq
        tables = {key: pinned.filename for key, pinned in BENCHMARK_TABLES.items()}
        unmatched = sorted({*n0.published_only, *bias.published_only, *cq.published_only})
        rows = [
            (
                "Starting quantity N0, per standard well",
                f"RDML-Tools (`{tables['n0']}`)",
                f"{n0.wells} wells, {n0.genes} genes",
                f"{n0.identical_4sf} ({_pct(n0.share_identical)}) identical to 4 significant "
                f"figures; {n0.within_5pct} ({_pct(n0.share_within)}) within 5 %; largest "
                f"difference {_pct(n0.max_rel_diff, 2)}",
            ),
            (
                "Dilution-series bias, per gene (Ruijter 2013)",
                f'LinRegPCR 2013, row "{BIAS_METHOD}" (`{tables["results"]}`)',
                f"{bias.genes} genes",
                f"median difference {bias.median_abs_diff:.3f} (largest "
                f"{bias.max_abs_diff:.3f}); mean {bias.ours_mean:.3f} here vs "
                f"{bias.published_mean:.3f} published",
            ),
            (
                "Cq, per standard well",
                f'LinRegPCR 2013, block "{CQ_METHOD}" (`{tables["cq"]}`)',
                f"{cq.wells} wells, {cq.genes} genes",
                f"offset {cq.mean_offset:+.2f} cycles on average (SD {cq.sd_offset:.2f}; "
                f"range {cq.min_offset:+.2f} to {cq.max_offset:+.2f})",
            ),
        ]
        table = "\n".join(f"| {' | '.join(row)} |" for row in rows)
        every = f"in all {cq.wells} wells" if cq.min_offset > 0 else "on average"
        return f"""# Validation against the RDML consortium's published benchmark

Generated by `qpilot validate`; do not edit by hand. Engine: LinRegPCR as shipped in rdmlpython
(vendored unchanged at `{VERMEULEN_COMMIT[:7]}`), run on the 64-plate demo study. Published tables:
rdmlpython `experiments/vermeulen` at the same commit, each checked against a pinned SHA-256.
Data: Vermeulen et al. 2009 (Lancet Oncol 10:663-671); Ruijter et al. 2013 (Methods 59:32-46);
CC BY 4.0.

| What is compared | Published reference | Compared | Result |
|---|---|---|---|
{table}

**About the Cq offset.** Our per-well Cq is later than the 2013 table {every} by a similar
amount (SD {cq.sd_offset:.2f} cycles), which points to a change in how LinRegPCR defines its
quantification threshold since 2013, not to noise. qPilot's comparisons use N0, which line 1
checks directly against the consortium's RDML-Tools output.

**Not compared.** Genes are matched by exact name, never guessed.
In the published tables but with no plate of that name in the RDML file: {_names(unmatched)}.
In the RDML file but not in the N0 and bias tables: {_names(n0.ours_only)}.
Within each gene and concentration, both sides are sorted and paired.

Regenerate: `qpilot fetch-demo && qpilot validate` (or `python validation/run_validation.py`).
"""


def validate(curves: pd.DataFrame, tables: Mapping[str, Path]) -> ValidationReport:
    """Run all three comparisons.

    Args:
        curves: The per-well table from :func:`qpilot.qpcr.curves.analyse_study` on the demo study.
        tables: Paths keyed like :data:`qpilot.io.datasets.BENCHMARK_TABLES`
            (``n0``, ``cq``, ``results``).

    Returns:
        The three comparison lines.
    """
    return ValidationReport(
        n0=compare_n0(curves, read_rdml_tools_n0(tables["n0"])),
        bias=compare_bias(curves, read_methods_results(tables["results"])),
        cq=compare_cq(curves, read_methods_cq(tables["cq"])),
    )


def write_report(report: ValidationReport, out_dir: str | Path) -> tuple[Path, Path]:
    """Write ``validation_table.md`` and ``validation.json`` into ``out_dir``."""
    directory = Path(out_dir)
    directory.mkdir(parents=True, exist_ok=True)
    markdown = directory / "validation_table.md"
    data = directory / "validation.json"
    markdown.write_text(report.to_markdown())
    data.write_text(report.to_json())
    return markdown, data
