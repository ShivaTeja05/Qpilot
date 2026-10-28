"""prism/tables.py: the CSVs Prism receives read back to the engine's values, bit for bit."""

import csv
import hashlib
import io
import json
import re

import pytest

from qpilot.core.store import canonical_json
from qpilot.prism import tables
from qpilot.prism.tables import (
    PrismExportError,
    build_bundle,
    bundle_digest,
    render_tables,
    sequential_pseudonyms,
)
from qpilot.qpcr.quant import log2_matrix, relative
from tests.prism.conftest import TOY_CHAIN, TOY_GROUPS, toy_inputs
from tests.prism.test_export_table import COLUMN_T, NESTED_T

HEADLINE = ["ODC1", "BIRC5", "NTRK1", "NM23A"]


def _rows(path):
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.reader(fh))


def _build(inputs, out, template="two_groups_log2", genes=("T", "T2"), **kw):
    return build_bundle(
        inputs,
        list(genes),
        template,
        out,
        record_ref="toy-001",
        chain_head=TOY_CHAIN,
        design_hash="d0" * 32,
        **kw,
    )


# ---------- gate: read back exactly ----------


@pytest.mark.demo_data
def test_gate_demo_csvs_read_back_to_the_engine_values_exactly(demo_inputs, tmp_path):
    bundle = build_bundle(
        demo_inputs,
        HEADLINE,
        "two_groups_log2",
        tmp_path,
        record_ref=demo_inputs.study_id,
        chain_head=demo_inputs.chain_head,
        design_hash=demo_inputs.design_hash,
    )
    matrix = log2_matrix(demo_inputs.data)
    in_comparison = set(demo_inputs.groups)
    for table in bundle.tables:
        rows = _rows(tmp_path / table.csv)
        assert rows[0] == ["Sample", "MYCN-high", "rest"]
        read = {}
        for title, high, rest in rows[1:]:
            assert (high == "") != (rest == "")  # each unit in exactly one group's column
            group = "MYCN-high" if high else "rest"
            assert demo_inputs.groups[title] == group
            read[title] = float(high or rest).hex()
        engine = relative(matrix, table.gene, demo_inputs.refs, demo_inputs.undetermined)
        expected = {s: float(v).hex() for s, v in engine.items() if s in in_comparison}
        assert read == expected, table.gene
        assert table.n_rows == len(expected)


def test_gate_toy_nested_csv_reads_back_exactly(tmp_path):
    inputs = toy_inputs()
    bundle = _build(inputs, tmp_path, "nested_superplot", genes=("T",))
    (table,) = bundle.tables
    assert table.layout == "nested"
    rows = _rows(tmp_path / table.csv)
    assert rows[0] == ["Replicate", "A/a1", "A/a2", "A/a3", "B/b1", "B/b2", "B/b3"]
    assert [r[0] for r in rows[1:]] == ["rep 1", "rep 2", "rep 3"]
    expected = inputs.table("nested", ["T"])
    for c, header in enumerate(rows[0][1:], start=1):
        unit = header.split("/")[1]
        read = [float(r[c]).hex() for r in rows[1:]]
        engine = expected[expected["biological_unit"] == unit]["log2_rq"].tolist()
        assert read == [float(v).hex() for v in engine]
        assert [float.fromhex(h) for h in read] == NESTED_T[unit]


def test_toy_column_layout_never_writes_replicates_as_n(tmp_path):
    bundle = _build(toy_inputs(), tmp_path, genes=("T",))
    rows = _rows(tmp_path / bundle.tables[0].csv)
    assert rows[0] == ["Sample", "A", "B"]
    assert len(rows) - 1 == 6  # six biological units, not eighteen wells
    read = {r[0]: float(r[1] or r[2]) for r in rows[1:]}
    assert read == COLUMN_T


def test_nested_groups_are_padded_to_the_same_number_of_subcolumns(tmp_path):
    groups = {"a1": "A", "a2": "A", "a3": "A", "b1": "B", "b2": "B"}
    bundle = _build(toy_inputs(groups=groups), tmp_path, "nested_superplot", genes=("T",))
    assert bundle.tables[0].columns == [
        "Replicate",
        "A/a1",
        "A/a2",
        "A/a3",
        "B/b1",
        "B/b2",
        "B/empty_1",
    ]
    rows = _rows(tmp_path / bundle.tables[0].csv)
    assert all(r[-1] == "" for r in rows[1:])


# ---------- format ----------


def test_csv_format_is_fixed_and_deterministic(tmp_path):
    first = _build(toy_inputs(), tmp_path / "one")
    second = _build(toy_inputs(), tmp_path / "two")
    assert first == second
    for table in first.tables:
        data = (tmp_path / "one" / table.csv).read_bytes()
        assert data == (tmp_path / "two" / table.csv).read_bytes()
        assert b"\r" not in data and data.endswith(b"\n")
        data.decode("utf-8")
        assert hashlib.sha256(data).hexdigest() == table.csv_sha256
        assert first.files[table.csv] == table.csv_sha256


def test_values_are_repr_floats():
    assert tables.format_value(0.1 + 0.2) == "0.30000000000000004"
    assert float(tables.format_value(-1.8439368467258772)).hex() == (-1.8439368467258772).hex()
    with pytest.raises(PrismExportError):
        tables.format_value(float("nan"))


def test_titles_carry_the_record_ref_and_short_chain_head(tmp_path):
    bundle = _build(toy_inputs(), tmp_path)
    for table in bundle.tables:
        assert "toy-001" in table.title and TOY_CHAIN[:12] in table.title
        assert table.title.startswith(f"{table.gene} log2 RQ")


def test_bundle_sha256_is_the_canonical_json_without_itself(tmp_path):
    bundle = _build(toy_inputs(), tmp_path)
    data = bundle.model_dump(mode="json")
    del data["bundle_sha256"]
    digest = hashlib.sha256(canonical_json(data).encode("utf-8")).hexdigest()
    assert bundle.bundle_sha256 == digest == bundle_digest(bundle)
    assert json.loads(canonical_json(data))["mode"] == "script"


# ---------- refusals ----------


def test_more_than_1023_data_sets_is_refused(monkeypatch):
    monkeypatch.setattr(tables, "MAX_DATA_SETS", 1)
    with pytest.raises(PrismExportError, match="data sets"):
        render_tables(toy_inputs(), ["T"], "two_groups_log2", record_ref="r", chain_head=TOY_CHAIN)


def test_the_real_limit_is_1023():
    assert tables.MAX_DATA_SETS == 1023


def test_many_genes_template_needs_a_contract_change():
    with pytest.raises(PrismExportError, match="PrismLayout"):
        render_tables(toy_inputs(), ["T"], "many_genes_log2", record_ref="r", chain_head=TOY_CHAIN)


def test_nested_template_without_replicates_is_refused():
    from tests.prism.conftest import toy_curves

    inputs = toy_inputs(toy_curves(replicates=False))
    with pytest.raises(PrismExportError, match="technical replicates"):
        render_tables(inputs, ["T"], "nested_superplot", record_ref="r", chain_head=TOY_CHAIN)


@pytest.mark.parametrize(
    "kwargs, message",
    [
        ({"template_id": "nope"}, "unknown template"),
        ({"record_ref": 'x"y'}, "record ref"),
        ({"chain_head": "short"}, "chain head"),
        ({"genes": ["R1"]}, "not analysed genes"),
        ({"genes": []}, "no genes"),
    ],
)
def test_bad_requests_are_refused(kwargs, message):
    args = {
        "genes": ["T"],
        "template_id": "two_groups_log2",
        "record_ref": "r",
        "chain_head": TOY_CHAIN,
    }
    args.update(kwargs)
    genes, template = args.pop("genes"), args.pop("template_id")
    with pytest.raises(PrismExportError, match=message):
        render_tables(toy_inputs(), genes, template, **args)


def test_file_stems_are_safe():
    assert tables.file_stem("SDHA(1)") == "SDHA(1)"
    assert tables.file_stem("PRKACB bis") == "PRKACB_bis"
    assert tables.file_stem("CON") == "CON_gene"
    hidden = tables.file_stem(".hidden")
    assert hidden.startswith("hidden_") and len(hidden) == len("hidden_") + 8
    for name in ("α-syn", "IL-6/ctrl", "KO#2", "Day 3 (50 µM)", "-Mar1"):
        stem = tables.file_stem(name)
        assert re.fullmatch(r"[a-z0-9_]+_[0-9a-f]{8}", stem), (name, stem)
    assert tables.file_stem("IL-6/ctrl") != tables.file_stem("IL-6_ctrl")


# ---------- sharing ----------


def test_share_pseudonymises_row_titles(tmp_path):
    inputs = toy_inputs()
    bundle = _build(inputs, tmp_path, genes=("T",), share=True)
    titles = [r[0] for r in _rows(tmp_path / bundle.tables[0].csv)[1:]]
    assert titles == ["U001", "U002", "U003", "U004", "U005", "U006"]
    assert bundle.info["row_titles"] == "pseudonymised"
    text = (tmp_path / bundle.tables[0].csv).read_text()
    assert not any(unit in text for unit in ("a1", "b3"))


def test_share_uses_the_given_pseudonym_function(tmp_path):
    bundle = _build(
        toy_inputs(), tmp_path, genes=("T",), share=True, pseudonym=lambda u: f"P-{u[::-1]}"
    )
    titles = [r[0] for r in _rows(tmp_path / bundle.tables[0].csv)[1:]]
    assert titles == ["P-1a", "P-2a", "P-3a", "P-1b", "P-2b", "P-3b"]


def test_share_refuses_colliding_or_unsafe_pseudonyms():
    for bad in (lambda u: "same", lambda u: 'x"y'):
        with pytest.raises(PrismExportError):
            render_tables(
                toy_inputs(),
                ["T"],
                "two_groups_log2",
                record_ref="r",
                chain_head=TOY_CHAIN,
                share=True,
                pseudonym=bad,
            )


def test_sequential_pseudonyms_are_stable():
    assert sequential_pseudonyms(["b", "a"]) == {"a": "U001", "b": "U002"}


def test_csv_text_quotes_nothing_for_plain_names():
    text = tables.csv_text([["Sample", "A"], ["x 1", "1.5"]])
    assert text == "Sample,A\nx 1,1.5\n"
    assert list(csv.reader(io.StringIO(text))) == [["Sample", "A"], ["x 1", "1.5"]]


@pytest.mark.parametrize("bad", ["+/+", "=HYPERLINK(A1)", "@SUM(1)"])
def test_a_formula_like_group_is_refused_in_words_for_prism(bad):
    """Prism's CSVs carry names as they are (it reads them back): a group or unit that starts
    like a formula is refused there, in words; a lab's other names go in as they are."""
    groups = {s: (bad if g == "A" else g) for s, g in TOY_GROUPS.items()}
    inputs = toy_inputs(groups=groups, group_order=(bad, "B"))
    with pytest.raises(PrismExportError, match="starts with =, \\+ or @"):
        render_tables(inputs, ["T"], "two_groups_log2", record_ref="r1", chain_head=TOY_CHAIN)
    fine = {s: ("LPS + inhibitor" if g == "A" else "-/-") for s, g in TOY_GROUPS.items()}
    inputs = toy_inputs(groups=fine, group_order=("LPS + inhibitor", "-/-"))
    (table, text), *_ = render_tables(
        inputs, ["T"], "two_groups_log2", record_ref="r1", chain_head=TOY_CHAIN
    )
    assert text.splitlines()[0].split(",")[1:] == ["LPS + inhibitor", "-/-"]
