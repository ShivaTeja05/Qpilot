# HGNC symbol table

`hgnc_symbols.tsv` is the data behind qPilot's gene-symbol gate (`qpilot/io/symbols.py`). It
lets qPilot tell an approved human gene symbol from a previous symbol, an alias, a name Excel
turned into a date (`MARCH1` -> `1-Mar`) and a name it does not know.

## Source

| | |
|---|---|
| Publisher | HUGO Gene Nomenclature Committee (HGNC), <https://www.genenames.org> |
| File | `hgnc_complete_set.txt` (the "current tab separated hgnc_complete_set file") |
| Downloaded from | <https://storage.googleapis.com/public-download-files/hgnc/tsv/tsv/hgnc_complete_set.txt> |
| Downloaded on | 17 October 2026 |
| Version | HGNC has no release numbers; the file's `Last-Modified` header was `Fri, 16 Oct 2026 13:36:15 GMT` (16,982,321 bytes, sha256 `12363916be36f8f6f91879b0faade4eeaac973722de7136ec61329b77f2c2f91`) |
| Records | 45,277 approved genes (19,299 protein-coding, 14,671 pseudogenes, 10,304 non-coding RNA, 1,003 other) |

## Licence

CC0 (public domain dedication). The HGNC licence page,
<https://www.genenames.org/about/license/>, read on 17 October 2026, says:

> "all data is released under the Creative Commons Public Domain (CC0) License. This means
> that any form of reuse of the content is permitted."

Attribution is not required; HGNC recommends it, so: *HGNC (RRID:SCR_002827); Seal RL et al.,
"Genenames.org: the HGNC resources in 2023", Nucleic Acids Research (Database issue).*

## What is kept

Only three columns of the complete set, one line per approved gene, sorted by symbol:

```
<approved symbol> TAB <previous symbols, '|'-separated> TAB <alias symbols, '|'-separated>
```

The file starts with two comment lines (`#`); empty trailing columns are left off. Names,
locations, identifiers and every other column are dropped. The file is 0.83 MB, so it is kept
as plain text (it would be gzipped above 1 MB).

## How it was built

```python
import csv

rows = list(csv.DictReader(open("hgnc_complete_set.txt", encoding="utf-8"), delimiter="\t"))
assert {r["status"] for r in rows} == {"Approved"}


def split(v):
    items = [x.strip().strip('"') for x in v.split("|")]
    return "|".join(dict.fromkeys(x for x in items if x and "\t" not in x and "|" not in x))


for r in sorted(rows, key=lambda r: r["symbol"]):
    line = f"{r['symbol']}\t{split(r['prev_symbol'])}\t{split(r['alias_symbol'])}"
    print(line.rstrip("\t"))
```

## Updating

Download the current complete set, check the licence page still says CC0, rebuild with the
snippet above, update the table in "Source", and run `pytest tests/engine/test_symbols.py`.
HGNC renames genes over time (in 2020 `MARCH1` became `MARCHF1` and `SEPT2` became `SEPTIN2`
because Excel turned them into dates), so an older table can call a current symbol unknown.
