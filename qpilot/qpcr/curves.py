"""Turn every amplification curve of a study into a starting quantity, one method for all plates.

For each plate (an RDML "run") this calls the vendored LinRegPCR exactly as the validation oracle
did (``run.linRegPCR(updateRDML=False, saveResultsCSV=True)`` with the library's default analysis
settings) and parses its tab-separated result table **by header name**, never by column position.
The plates are concatenated into one tidy table, one row per well:

==================  =================================================================
column              meaning
==================  =================================================================
run_id              plate id (validated identifier)
well                well position, named by :func:`well_label` (``A1``; ``AA1`` from row 27)
sample              sample name (validated identifier)
sample_type         ``unkn`` (study sample), ``std`` (dilution standard) or ``ntc``
target              gene name with its ``_20YYMMDD`` date token removed
target_raw          gene name exactly as written in the file
target_type         ``ref`` for the reference (control) genes, else ``toi``
excluded, note      LinRegPCR's exclusion flag and note (``""`` when none)
baseline            fitted baseline fluorescence
eff_indiv           this well's own amplification efficiency
r2                  fit quality of the window of linearity
eff_target          mean efficiency of the gene on this plate (used for quantities)
eff_target_sd       its standard deviation
cq                  LinRegPCR's Cq (``TD0``: third derivative of the curve = 0); NaN if none
n0                  efficiency-corrected starting quantity (``Ncopy``); NaN = undetermined
amplification       whether LinRegPCR saw amplification
plateau             whether the curve reached a plateau
==================  =================================================================

Every well-level decision (an exclusion, a well role, a person's amplification call) is keyed
``run_id/well``, so the table never holds two rows with the same key: a table where they would
collide is refused.

Results are cached as CSV in the cache directory, keyed by the input file's SHA-256, the
experiment, the reference genes and the analysis settings, so a second analysis of the same file
takes about a second. Cache files are written to a temporary name and renamed into place.
"""

from __future__ import annotations

import hashlib
import io
import json
import logging
import os
import re
import tempfile
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
from pathlib import Path

import pandas as pd

from qpilot.io.datasets import default_cache_dir
from qpilot.io.rdml_io import load, runs
from qpilot.vendor.rdmlpython import rdml

log = logging.getLogger(__name__)

REFERENCE_TARGETS: tuple[str, ...] = ("ALUsq(Eurogentec)", "HMBS", "HPRT1", "SDHA(1)", "UBC(2)")
DEMO_EXPERIMENT = "biomarker_set"

#: LinRegPCR result header -> qPilot column. Parsed by name; extra upstream columns are ignored.
RESULT_COLUMNS: Mapping[str, str] = {
    "well": "well",
    "sample": "sample",
    "sample type": "sample_type",
    "target": "target_raw",
    "excluded": "excluded",
    "note": "note",
    "baseline": "baseline",
    "indiv PCR eff": "eff_indiv",
    "R2": "r2",
    "PCR eff": "eff_target",
    "STD PCR eff": "eff_target_sd",
    "TD0": "cq",
    "Ncopy": "n0",
    "amplification": "amplification",
    "plateau": "plateau",
}
NUMERIC_COLUMNS = ("baseline", "eff_indiv", "r2", "eff_target", "eff_target_sd", "cq", "n0")
TEXT_COLUMNS = (
    "run_id",
    "well",
    "sample",
    "sample_type",
    "target",
    "target_raw",
    "target_type",
    "excluded",
    "note",
)
BOOL_COLUMNS = ("amplification", "plateau")
COLUMN_ORDER = (
    "run_id",
    "well",
    "sample",
    "sample_type",
    "target",
    "target_raw",
    "target_type",
    "excluded",
    "note",
    "baseline",
    "eff_indiv",
    "r2",
    "eff_target",
    "eff_target_sd",
    "cq",
    "n0",
    "amplification",
    "plateau",
)

_SAFE_NAME = re.compile(r"^[\w()\-. ]{1,64}$")
_DATE_TOKEN = re.compile(r"_20\d{6}(?=_|$)")
_WELL_LABEL = re.compile(r"^[A-Z]+[1-9][0-9]*$")
_LINREGPCR_WELL = re.compile(r"^(.)([1-9][0-9]*)$", re.DOTALL)
WELL_KEY = ("run_id", "well")


class CurveAnalysisError(Exception):
    """LinRegPCR could not analyse a plate, or its output was not in the expected shape."""


@dataclass(frozen=True)
class CurveSettings:
    """LinRegPCR analysis settings: the library defaults, exactly as the validation oracle used."""

    pcrEfficiencyExl: float = 0.05  # noqa: N815 (vendored keyword name)
    excludeNoPlateau: bool = True  # noqa: N815
    excludeEfficiency: str = "outlier"  # noqa: N815
    maxCycExpPhase: int = 9  # noqa: N815
    ignoreExclusion: bool = False  # noqa: N815

    def key(self) -> str:
        """Short stable hash of the settings, used in cache file names and records."""
        payload = json.dumps(asdict(self), sort_keys=True).encode()
        return hashlib.sha256(payload).hexdigest()[:12]


def normalise_target(name: str) -> str:
    """Remove the ``_20YYMMDD`` date token from a target name.

    ``PRKACB_20080311`` -> ``PRKACB``; ``PRKACB_20080311_bis`` (a repeat assay) -> ``PRKACB_bis``.
    """
    return _DATE_TOKEN.sub("", name)


def slug(name: str) -> str:
    """Lowercase identifier for fact ids: ``ALUsq(Eurogentec)`` -> ``alusq_eurogentec``."""
    words = re.split(r"[^0-9a-z]+", name.lower())
    return "_".join(word for word in words if word)


def safe_name(name: str, kind: str) -> str:
    """Return ``name`` if it is a plain identifier; otherwise its slug, with a warning.

    Names from the file reach model prompts, MCP results and HTML later, so anything that is not
    letters, digits, spaces, ``_ - . ( )`` and at most 64 characters is replaced here.
    """
    if _SAFE_NAME.match(name):
        return name
    replacement = slug(name)[:64] or "unnamed"
    log.warning("unsafe %s name %r replaced by %r", kind, name, replacement)
    return replacement


def well_label(row: int, column: int) -> str:
    """The one name qPilot gives the well at ``row`` and ``column`` (both counted from 1).

    Rows 1-26 are ``A`` to ``Z``, as LinRegPCR names them, so a plate of up to 26 rows keeps
    LinRegPCR's names (the demo's ``A1`` ... ``P24``). From row 27 the rows go on as on a
    1536-well plate: ``AA``, ``AB`` ... ``AZ``, ``BA`` ... There LinRegPCR writes the characters
    after ``Z`` (``[``, a backslash, ``]`` ...), which :func:`safe_name` would turn into one
    name for five different wells.

    Raises:
        CurveAnalysisError: ``row`` or ``column`` is below 1.
    """
    if row < 1 or column < 1:
        raise CurveAnalysisError(f"no well at row {row}, column {column}")
    letters = ""
    while row:
        row, rest = divmod(row - 1, 26)
        letters = chr(ord("A") + rest) + letters
    return f"{letters}{column}"


def react_well_label(react_id: str | int, n_columns: int) -> str:
    """:func:`well_label` of RDML reaction ``react_id`` on a plate ``n_columns`` wide.

    RDML numbers the reactions of a plate row by row from 1, as LinRegPCR reads them: on a
    24-column plate, reaction 25 is ``B1``.
    """
    position, columns = int(react_id), int(n_columns)
    if position < 1 or columns < 1:
        raise CurveAnalysisError(f"no well for reaction {react_id} on a {n_columns}-column plate")
    return well_label((position - 1) // columns + 1, (position - 1) % columns + 1)


def _from_linregpcr(name: str) -> str:
    """LinRegPCR's well name (``chr(ord("A") + row)``, then the column) as :func:`well_label`."""
    match = _LINREGPCR_WELL.match(name)
    if match is None or ord(match.group(1)) < ord("A"):
        raise CurveAnalysisError(f"LinRegPCR returned an unexpected well name {name!r}")
    return well_label(ord(match.group(1)) - ord("A") + 1, int(match.group(2)))


def _check_run_ids(raw_ids: list[str]) -> None:
    """Refuse two runs whose ids become the same safe name (their wells would share keys)."""
    seen: dict[str, str] = {}
    for raw in raw_ids:
        safe = safe_name(raw, "run")
        if safe in seen and seen[safe] != raw:
            raise CurveAnalysisError(
                f"runs {seen[safe]!r} and {raw!r} both become {safe!r}, so their wells would "
                "share run_id/well keys; qPilot keys every well-level decision by run_id/well, "
                "so this file is refused (rename one run)"
            )
        seen[safe] = raw


def _check_well_keys(table: pd.DataFrame) -> None:
    """Refuse a table in which two curves of the same target share a ``run_id/well`` key.

    Two runs whose ids become the same safe name, or two wells whose names collide, would share
    it, and one person's exclusion or call would then apply to wells nobody chose. A multiplex
    well (several targets in one well) is legitimate and keeps one key for the well; decisions
    that would hit more than one of its targets are refused where they are applied
    (``qpcr/designs.py``).
    """
    shared = table.duplicated([*WELL_KEY, "target_raw"], keep=False)
    if shared.any():
        run_id, well = table.loc[shared, list(WELL_KEY)].iloc[0]
        raise CurveAnalysisError(
            f"run {run_id} well {well}: {int(shared.sum())} curves of one target share a "
            "run_id/well key (runs or wells whose names become the same safe name); qPilot keys "
            "every well-level decision by run_id/well, so this table is refused"
        )


def analyse_run(run: rdml.Run, settings: CurveSettings | None = None) -> pd.DataFrame:
    """Run LinRegPCR on one plate and return its wells as a tidy table (see module docstring)."""
    settings = settings or CurveSettings()
    run_id = safe_name(str(run["id"]), "run")
    try:
        result = run.linRegPCR(**asdict(settings), updateRDML=False, saveResultsCSV=True)
    except rdml.RdmlError as err:
        raise CurveAnalysisError(f"run {run_id}: {err}") from err
    table = pd.read_csv(
        io.StringIO(result["resultsCSV"]), sep="\t", dtype=str, keep_default_na=False
    )
    missing = [header for header in RESULT_COLUMNS if header not in table.columns]
    if missing:
        raise CurveAnalysisError(f"run {run_id}: LinRegPCR output lacks columns {missing}")
    table = table[list(RESULT_COLUMNS)].rename(columns=RESULT_COLUMNS)
    table.insert(0, "run_id", run_id)
    return table


def _tidy(table: pd.DataFrame, reference_targets: Iterable[str]) -> pd.DataFrame:
    """Name the wells, validate names, add derived columns, type and order the columns."""
    references = set(reference_targets)
    table = table.copy()
    table["well"] = table["well"].map({w: _from_linregpcr(w) for w in table["well"].unique()})
    for column, kind in (("sample", "sample"), ("target_raw", "target")):
        unique = {value: safe_name(value, kind) for value in table[column].unique()}
        table[column] = table[column].map(unique)
    table["target"] = table["target_raw"].map(normalise_target)
    table["target_type"] = table["target"].map(lambda t: "ref" if t in references else "toi")
    for column in NUMERIC_COLUMNS:
        table[column] = pd.to_numeric(table[column], errors="coerce")
    for column in ("cq", "n0"):  # LinRegPCR reports "no value" as 0 or negative
        table.loc[~(table[column] > 0), column] = float("nan")
    for column in BOOL_COLUMNS:
        table[column] = table[column].str.strip().str.lower().eq("yes")
    for column in TEXT_COLUMNS:
        table[column] = table[column].fillna("").astype(str)
    return table[list(COLUMN_ORDER)].reset_index(drop=True)


def file_sha256(path: str | Path) -> str:
    """SHA-256 of a file's bytes, read in chunks."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 16), b""):
            digest.update(chunk)
    return digest.hexdigest()


def cache_path(
    input_sha256: str,
    experiment_id: str,
    reference_targets: Iterable[str],
    settings: CurveSettings,
    cache_dir: Path,
) -> Path:
    """Where the analysed table for this exact input and configuration is cached."""
    config = json.dumps(
        {
            "experiment": experiment_id,
            "refs": sorted(reference_targets),
            "settings": asdict(settings),
        },
        sort_keys=True,
    )
    config_key = hashlib.sha256(config.encode()).hexdigest()[:12]
    return cache_dir / f"{input_sha256}.{config_key}.curves.csv"


def _read_cache(path: Path) -> pd.DataFrame:
    table = pd.read_csv(path, dtype={c: str for c in TEXT_COLUMNS}, keep_default_na=False)
    for column in NUMERIC_COLUMNS:
        table[column] = pd.to_numeric(table[column], errors="coerce")
    for column in BOOL_COLUMNS:
        table[column] = table[column].astype(str).eq("True")
    return table[list(COLUMN_ORDER)]


def _write_cache(table: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        "w", dir=path.parent, suffix=".tmp", delete=False, newline=""
    )
    try:
        with handle:
            table.to_csv(handle, index=False)
        os.replace(handle.name, path)
    except BaseException:
        Path(handle.name).unlink(missing_ok=True)
        raise


def analyse_study(
    source: str | Path | rdml.Rdml,
    experiment_id: str = DEMO_EXPERIMENT,
    reference_targets: Iterable[str] = REFERENCE_TARGETS,
    settings: CurveSettings | None = None,
    *,
    cache_dir: str | Path | None = None,
    use_cache: bool = True,
) -> pd.DataFrame:
    """Analyse every plate of one experiment and return one row per well.

    Args:
        source: Path to an RDML file (cached by content hash) or an already loaded document
            (never cached).
        experiment_id: Which experiment's plates to analyse.
        reference_targets: Gene names (after date-suffix removal) to mark as ``ref``.
        settings: LinRegPCR settings; defaults to the library defaults used by the oracle.
        cache_dir: Cache directory (default ``$QPILOT_CACHE_DIR`` or ``~/.cache/qpilot``).
        use_cache: Read and write the cache when ``source`` is a path.

    Returns:
        The tidy per-well table described in the module docstring.

    Raises:
        CurveAnalysisError: A plate could not be analysed, or two curves share a
            ``run_id/well`` key.
        qpilot.io.rdml_io.RdmlLoadError: The file could not be loaded safely.
    """
    settings = settings or CurveSettings()
    references = tuple(reference_targets)
    cached: Path | None = None
    if isinstance(source, rdml.Rdml):
        doc = source
    else:
        path = Path(source)
        if use_cache:
            directory = Path(cache_dir) if cache_dir is not None else default_cache_dir()
            cached = cache_path(file_sha256(path), experiment_id, references, settings, directory)
            if cached.exists():
                table = _read_cache(cached)
                named = table["well"].str.fullmatch(_WELL_LABEL).all()
                if named and not table.duplicated(list(WELL_KEY)).any():
                    return table
                # written before every well had its own name (plates over 26 rows)
                log.warning("cached curve table %s predates unique well names", cached.name)
        doc = load(path)
    found = runs(doc, experiment_id)
    _check_run_ids([str(run["id"]) for run in found])
    plates = [analyse_run(run, settings) for run in found]
    if not plates:
        raise CurveAnalysisError(f"experiment {experiment_id!r} has no runs")
    table = _tidy(pd.concat(plates, ignore_index=True), references)
    _check_well_keys(table)
    if cached is not None:
        _write_cache(table, cached)
    return table
