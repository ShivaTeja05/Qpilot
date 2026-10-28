"""A study's several comparisons, recomputed from a per-well table with :mod:`.stats_oracle`.

The input is one row per well (``sample``, ``target``, ``n0``): qPilot's curve table, or the
quantities LinRegPCR itself wrote into an RDML file (:func:`linregpcr_wells`, read here with
lxml, not with qPilot's loader). From there every step is this module's own:

1. a biological unit's value of a gene is the mean ``log2 N0`` of its wells that have a positive
   quantity (technical replicates are averaged, never counted as n);
2. its relative value is that minus the mean of its control genes (a unit missing one is out);
3. each comparison is Welch's t-test (or the paired t-test of within-pair differences, or a
   pooled-variance t-test for Dunnett and Tukey) on those relative values;
4. Holm's correction runs within a gene across its comparisons, Benjamini-Hochberg q-values
   within a comparison across its genes (raw p), Welch's ANOVA per gene across the plan's groups.
"""

from __future__ import annotations

import math
import zipfile
from collections import defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path

import pandas as pd
from lxml import etree

from validation.excellence import stats_oracle as so


def linregpcr_wells(path: str | Path) -> pd.DataFrame:
    """Every reaction's sample, target, Cq and N0 as LinRegPCR wrote them into an RDML file."""
    with zipfile.ZipFile(path) as archive:
        member = next(n for n in archive.namelist() if n.endswith(".xml"))
        xml = archive.read(member)
    parser = etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=False)
    root = etree.fromstring(xml, parser)
    ns = {"r": root.nsmap[None]}
    rows = []
    for run in root.iterfind(".//r:run", ns):
        for react in run.iterfind("r:react", ns):
            sample = react.find("r:sample", ns).get("id")
            for data in react.iterfind("r:data", ns):
                n0 = data.findtext("r:N0", namespaces=ns)
                cq = data.findtext("r:cq", namespaces=ns)
                rows.append(
                    {
                        "run_id": run.get("id"),
                        "react": react.get("id"),
                        "sample": sample,
                        "target": data.find("r:tar", ns).get("id"),
                        "cq": float(cq) if cq else math.nan,
                        "n0": float(n0) if n0 else math.nan,
                    }
                )
    return pd.DataFrame(rows)


def unit_values(wells: pd.DataFrame, units: Mapping[str, str] | None = None) -> pd.DataFrame:
    """Units x genes: the mean ``log2 N0`` of each unit's wells with a positive quantity."""
    sums: dict[tuple[str, str], list[float]] = defaultdict(list)
    for row in wells.itertuples(index=False):
        if not (isinstance(row.n0, float) and math.isfinite(row.n0) and row.n0 > 0):
            continue
        unit = (units or {}).get(row.sample, row.sample)
        sums[(unit, row.target)].append(math.log2(row.n0))
    data = {key: sum(v) / len(v) for key, v in sums.items()}
    frame = pd.Series(data).unstack()
    return frame.sort_index().sort_index(axis=1)


def relative(values: pd.DataFrame, refs: Sequence[str]) -> pd.DataFrame:
    """Each gene minus the mean of the control genes, per unit (a unit missing one is left out)."""
    out = {}
    for unit, row in values.iterrows():
        ref_values = [row[r] for r in refs]
        if any(not math.isfinite(v) for v in ref_values):
            continue
        norm = sum(ref_values) / len(ref_values)
        out[unit] = {g: row[g] - norm for g in values.columns if g not in refs}
    return pd.DataFrame(out).T.sort_index()


def _column(rel: pd.DataFrame, gene: str, units: Sequence[str]) -> list[float]:
    return [
        float(rel.at[u, gene]) for u in units if u in rel.index and math.isfinite(rel.at[u, gene])
    ]


def compare(
    rel: pd.DataFrame,
    groups: Mapping[str, Sequence[str]],
    plan: Sequence[tuple[str, str]],
    correction: str = "holm",
    pairs: Mapping[str, str] | None = None,
) -> dict[str, dict[str, dict[str, float]]]:
    """Every comparison of ``plan`` for every gene: log2fc, p, p_adjusted, q (and t, df).

    Args:
        rel: Units x genes relative values (:func:`relative`).
        groups: Group label -> its units.
        plan: ``(group a, group b)`` per comparison, the primary first.
        correction: ``holm``, ``none``, ``dunnett`` (each against the plan's group b) or
            ``tukey`` (every pair).
        pairs: Unit -> pair key, for a paired plan.

    Returns:
        ``{comparison id: {gene: numbers}}`` with ids ``"<a> vs <b>"``.
    """
    genes = list(rel.columns)
    out: dict[str, dict[str, dict[str, float]]] = {}
    for a, b in plan:
        cid = f"{a} vs {b}"
        out[cid] = {}
        for gene in genes:
            if pairs is not None:
                by_key_a = {pairs[u]: u for u in groups[a]}
                by_key_b = {pairs[u]: u for u in groups[b]}
                diffs = []
                for key in sorted(set(by_key_a) & set(by_key_b)):
                    ua, ub = by_key_a[key], by_key_b[key]
                    if ua in rel.index and ub in rel.index:
                        va, vb = rel.at[ua, gene], rel.at[ub, gene]
                        if math.isfinite(va) and math.isfinite(vb):
                            diffs.append(float(va - vb))
                r = so.paired(diffs) if len(diffs) >= 2 else None
            else:
                xa, xb = _column(rel, gene, groups[a]), _column(rel, gene, groups[b])
                if correction in ("dunnett", "tukey"):
                    named = {g: _column(rel, gene, units) for g, units in groups.items()}
                    var, df = so.pooled_variance(named)
                    r = so.pooled_t(xa, xb, var, df) if len(xa) >= 2 and len(xb) >= 2 else None
                else:
                    r = so.welch(xa, xb) if len(xa) >= 2 and len(xb) >= 2 else None
            out[cid][gene] = r or {"p": math.nan}
    ids = list(out)
    for gene in genes:  # the correction within a gene, across its comparisons
        raw = [out[c][gene]["p"] for c in ids]
        if correction == "holm" and len(ids) > 1:
            adj = so.holm(raw)
        elif correction == "dunnett":
            control = plan[0][1]
            named = {g: _column(rel, gene, units) for g, units in groups.items()}
            ts = [out[c][gene].get("t", math.nan) for c in ids]
            ok = [i for i, t in enumerate(ts) if math.isfinite(t)]
            n_t = [len(named[plan[i][0]]) for i in ok]
            _, df = so.pooled_variance(named)
            values = so.dunnett_adjusted([ts[i] for i in ok], n_t, len(named[control]), df)
            adj = [math.nan] * len(ids)
            for i, v in zip(ok, values, strict=True):
                adj[i] = v
        elif correction == "tukey":
            named = {g: _column(rel, gene, units) for g, units in groups.items()}
            k = sum(len(v) >= 2 for v in named.values())
            _, df = so.pooled_variance(named)
            adj = [
                so.tukey_adjusted(out[c][gene]["t"], k, df)
                if math.isfinite(out[c][gene]["p"])
                else math.nan
                for c in ids
            ]
        else:
            adj = raw
        for c, v in zip(ids, adj, strict=True):
            out[c][gene]["p_adjusted"] = v
    for c in ids:  # BH within a comparison, across its genes (raw p)
        tested = [g for g in genes if math.isfinite(out[c][g]["p"])]
        q = so.bh([out[c][g]["p"] for g in tested])
        for g, v in zip(tested, q, strict=True):
            out[c][g]["q"] = v
    return out


def omnibus(rel: pd.DataFrame, groups: Mapping[str, Sequence[str]]) -> dict[str, dict[str, float]]:
    """Welch's ANOVA per gene across the groups."""
    return {
        gene: so.welch_anova([_column(rel, gene, units) for units in groups.values()])
        for gene in rel.columns
    }
