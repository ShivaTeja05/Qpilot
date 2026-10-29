"""Prism's XML project format (.pzfx): what qPilot writes is well-formed Prism XML whose tables
hold the engine's numbers, and what Prism saves reads back strictly (exclusions, deletions, comma
decimals, the binary part skipped, hostile files refused).

The reading tests use minimal files built by hand (``tests/fixtures/prism/prism*_style_*.pzfx``)
in the shapes real Prism files have (Prism 6 without a namespace, Prism 8 with a comma decimal
separator, Prism 10 with the default namespace, ``SubColumnTitles``, ``HugeTable`` and a binary
``Template`` block); no file from elsewhere is copied.
"""

from __future__ import annotations

import csv
import io

import pytest
from lxml import etree

from qpilot.prism import pzfx
from qpilot.prism.project import (
    GROUPED_NAME,
    grouped_title,
    info_sheet,
    project_tables,
    render_project_tables,
    tables_digest,
)
from qpilot.schemas_studio import PrismBundle
from tests.prism.conftest import FIXTURES, TOY_CHAIN, toy_curves, toy_inputs

NS = {"p": pzfx.NAMESPACE}


def _bundle(inputs, genes=("T", "T2"), ref="toyref"):
    rendered = render_project_tables(inputs, genes, record_ref=ref, chain_head=TOY_CHAIN)
    bundle = PrismBundle(
        study_id=inputs.study_id,
        record_ref=ref,
        chain_head=TOY_CHAIN,
        design_hash=inputs.design_hash,
        template_id="two_groups_log2",
        test="Welch",
        tables=[t for t, _ in rendered],
        info={"grouped_title": grouped_title(ref, TOY_CHAIN), "caption": "toy caption"},
        files={t.csv: t.csv_sha256 for t, _ in rendered},
        mode="xml",
    )
    return bundle, {t.csv: text for t, text in rendered}, rendered


def _written(inputs=None):
    inputs = inputs or toy_inputs()
    bundle, texts, rendered = _bundle(inputs)
    main, nested = project_tables(bundle, texts)
    info = info_sheet(bundle, inputs)
    return inputs, bundle, rendered, pzfx.write_project(main, info, version="0.1.0"), nested


# ---- what qPilot writes -------------------------------------------------------------------------


def test_the_project_is_well_formed_prism_xml():
    _, _, _, data, _ = _written()
    assert data.startswith(b'<?xml version="1.0" encoding="UTF-8"?>\n')
    root = etree.fromstring(data)
    assert root.tag == f"{{{pzfx.NAMESPACE}}}GraphPadPrismFile"
    assert root.get("PrismXMLVersion") == "5.00"
    children = [etree.QName(c).localname for c in root]
    assert children == ["Created", "InfoSequence", "Info", "TableSequence", *["Table"] * 3]
    refs = root.findall("p:TableSequence/p:Ref", NS)
    assert [r.get("ID") for r in refs] == [t.get("ID") for t in root.findall("p:Table", NS)]
    assert refs[0].get("Selected") == "1"
    assert root.find("p:Created/p:OriginalVersion", NS).get("CreatedByProgram") == "qPilot"
    assert b"Template" not in data  # qPilot never writes Prism's binary part
    assert b"DateTime" not in data and b"Login" not in data  # deterministic


def test_each_gene_is_a_column_table_with_the_engines_values_bit_for_bit():
    inputs, _, _, data, _ = _written()
    root = etree.fromstring(data)
    tables = {t.find("p:Title", NS).text: t for t in root.findall("p:Table", NS)}
    engine = inputs.table("column", ["T", "T2"])
    for gene in ("T", "T2"):
        table = tables[f"{gene} log2 RQ - qPilot toyref - chain {TOY_CHAIN[:12]}"]
        assert table.get("TableType") == "OneWay" and table.get("XFormat") == "none"
        assert table.get("EVFormat") == "AsteriskAfterNumber" and table.get("YFormat") is None
        units = [d.text for d in table.findall("p:RowTitlesColumn/p:Subcolumn/p:d", NS)]
        columns = table.findall("p:YColumn", NS)
        assert [c.find("p:Title", NS).text for c in columns] == ["A", "B"]
        assert all(c.get("Subcolumns") == "1" for c in columns)
        rows = engine[engine["gene"] == gene]
        assert units == list(rows["biological_unit"])
        for unit, group, value in zip(
            rows["biological_unit"], rows["group"], rows["log2_rq"], strict=True
        ):
            i = units.index(unit)
            for column in columns:
                cell = column.findall("p:Subcolumn/p:d", NS)[i]
                if column.find("p:Title", NS).text == group:
                    assert float(cell.text).hex() == float(value).hex()
                else:
                    assert cell.text is None and len(cell) == 0  # <d/>: empty
                assert cell.get("Excluded") is None


def test_the_grouped_table_has_genes_as_rows_and_units_as_titled_subcolumns():
    inputs, _, _, data, _ = _written()
    project = pzfx.read_project(data)
    grouped = next(t for t in project.tables if t.kind == "grouped")
    assert grouped.title == grouped_title("toyref", TOY_CHAIN)
    assert grouped.table_type == "TwoWay" and grouped.row_titles == ("T", "T2")
    assert [ds.title for ds in grouped.data_sets] == ["A", "B"]
    assert [ds.subcolumn_titles for ds in grouped.data_sets] == [
        ("a1", "a2", "a3"),
        ("b1", "b2", "b3"),
    ]
    engine = inputs.table("column", ["T", "T2"])
    for r, gene in enumerate(grouped.row_titles):
        for ds in grouped.data_sets:
            for k, unit in enumerate(ds.subcolumn_titles):
                want = engine[(engine["gene"] == gene) & (engine["biological_unit"] == unit)]
                assert float(ds.subcolumns[k][r].text) == float(want["log2_rq"].iloc[0])
    root = etree.fromstring(data)
    table = next(t for t in root.findall("p:Table", NS) if t.get("TableType") == "TwoWay")
    assert table.get("YFormat") == "replicates" and table.get("Replicates") == "3"
    assert table.find("p:SubColumnTitles", NS).get("OwnSet") == "1"


def test_replicates_go_to_nested_tables_named_by_unit():
    inputs, _, _, _, nested = _written()
    assert [t.name for t in nested] == ["T_replicates", "T2_replicates"]
    data = pzfx.write_project(nested, pzfx.ProjectInfo())
    root = etree.fromstring(data)
    table = root.find("p:Table", NS)
    assert table.get("ExtTableType") == "Nested" and table.get("Replicates") == "3"
    back = pzfx.read_project(data).tables[0]
    assert back.kind == "nested"
    assert back.data_sets[0].subcolumn_titles == ("a1", "a2", "a3")
    engine = inputs.table("nested", ["T"])
    a1 = engine[engine["biological_unit"] == "a1"].sort_values("well_rep")["log2_rq"]
    assert [float(c.text) for c in back.data_sets[0].subcolumns[0]] == list(a1)


def test_unequal_groups_are_padded_with_untitled_subcolumns():
    groups = {"a1": "A", "a2": "A", "a3": "A", "b1": "B"}
    inputs = toy_inputs(groups=groups)
    bundle, texts, _ = _bundle(inputs, genes=("T",))
    _, nested = project_tables(bundle, texts)
    back = pzfx.read_project(pzfx.write_project(nested, pzfx.ProjectInfo())).tables[0]
    assert [ds.subcolumn_titles for ds in back.data_sets] == [("a1", "a2", "a3"), ("b1", "", "")]


def test_the_info_sheet_carries_the_provenance():
    inputs, bundle, _, data, _ = _written()
    info = pzfx.read_project(data).infos[0]
    assert info.title == "qPilot provenance"
    constants = dict(info.constants)
    assert constants["qPilot study"] == inputs.study_id
    assert constants["Decision record head (sha256)"] == TOY_CHAIN
    assert constants["Design hash (sha256)"] == bundle.design_hash
    assert constants["Reference genes"] == "R1, R2" and constants["Groups"] == "A vs B"
    assert "Welch" in constants["Test qPilot used"]
    assert any("already log2" in note for note in info.notes)
    assert any(note.startswith("Caption") for note in info.notes)
    assert any("Not affiliated" in note for note in info.notes)


def test_who_decided_each_choice_and_why_is_in_the_info_sheet():
    from types import SimpleNamespace

    from qpilot.qpcr.export import Choice

    choices = (
        Choice("card_refset", "refs", "top2", "recommended", ("R1",), "human", "decided"),
        Choice("card_cutoff", "cut", "cut_15", "cut_15", 0.15, None, "open"),
    )
    inputs = toy_inputs(choices=choices)
    bundle, _, _ = _bundle(inputs)
    entries = [SimpleNamespace(card_id="card_refset", status="applied", reason="protocol p. 4")]
    info = info_sheet(bundle, inputs, entries)
    constants = dict(info.constants)
    assert constants["Choice: Reference genes"] == "top2 (decided by a person)"
    assert constants["Choice: Group cut-off"] == "cut_15 (not decided yet: the recommended option)"
    note = next(n for n in info.notes if n.startswith("Reference genes"))
    assert "qPilot recommended recommended" in note and note.endswith("Reason: protocol p. 4")


def test_writing_refuses_control_characters_and_duplicate_titles():
    table = pzfx.column_table("T", "T", [["Sample", "A"], ["u1", "1"]])
    with pytest.raises(pzfx.PzfxError, match="same title"):
        pzfx.write_project([table, table], pzfx.ProjectInfo())
    bad = pzfx.column_table("T", "T\x07", [["Sample", "A"], ["u1", "1"]])
    with pytest.raises(pzfx.PzfxError, match="control character"):
        pzfx.write_project([bad], pzfx.ProjectInfo())
    with pytest.raises(pzfx.PzfxError, match="at least one table"):
        pzfx.write_project([], pzfx.ProjectInfo())


def test_what_is_written_reads_back_exactly():
    _, _, rendered, data, _ = _written()
    project = pzfx.read_project(data)
    by_name = {t.name: text for t, text in rendered if t.layout == "column"}
    columns = [t for t in project.tables if t.kind == "column"]
    for table, (name, text) in zip(columns, by_name.items(), strict=True):
        assert table.title.startswith(name + " log2")
        want = list(csv.reader(io.StringIO(text)))
        assert [[c.text for c in row] for row in table.grid()] == want
    assert project.created_by == "qPilot 0.1.0" and project.problems == []


def test_the_tables_digest_ignores_titles_but_not_numbers():
    inputs = toy_inputs()
    one = render_project_tables(inputs, ["T"], record_ref="a", chain_head=TOY_CHAIN)
    other = render_project_tables(inputs, ["T"], record_ref="b", chain_head="cd" * 32)
    assert tables_digest(one) == tables_digest(other)  # another analysis, the same numbers
    curves = toy_curves()
    curves.loc[0, "n0"] *= 2  # one well's quantity doubled: a number in the table moves
    moved = toy_inputs(data=curves)
    changed = render_project_tables(moved, ["T"], record_ref="a", chain_head=TOY_CHAIN)
    assert tables_digest(changed) != tables_digest(one)


# ---- what Prism saves ---------------------------------------------------------------------------

PRISM6_STYLE = (FIXTURES / "prism6_style_column.pzfx").read_bytes()

PRISM10_STYLE = (FIXTURES / "prism10_style_grouped.pzfx").read_bytes()


def test_a_prism6_style_file_reads_with_exclusions_and_formatting_dropped():
    project = pzfx.read_project(PRISM6_STYLE)
    assert project.created_by == "GraphPad Prism 6.0f.254"
    (table,) = project.tables
    assert table.kind == "column" and table.title == "Data 1"
    assert table.row_titles == ("u1", "u2", "u3")
    assert [ds.title for ds in table.data_sets] == ["Aa", "Bb"]
    cells = table.data_sets[0].subcolumns[0]
    assert [(c.text, c.excluded) for c in cells] == [("1.", False), ("2.", True), ("", False)]
    assert project.infos[0].constants == (("Experiment Date", "2018-07-23"),)


def test_a_prism10_style_grouped_table_reads_with_its_subcolumn_titles():
    project = pzfx.read_project(PRISM10_STYLE)
    (table,) = project.tables  # HugeTable is a table too
    assert table.kind == "grouped" and table.row_titles == ("row1", "row2")
    assert table.data_sets[0].subcolumn_titles == ("s1", "")
    assert table.data_sets[1].subcolumn_titles == ("s3", "s4")
    assert pzfx.number_text(table.data_sets[0].subcolumns[0][0].text) == "3.5"
    assert table.column_names() == ["test1/s1", "test1/", "test2/s3", "test2/s4"]


def test_comma_decimals_read_as_points_and_nothing_else_changes():
    assert pzfx.number_text("3,5") == "3.5"
    assert pzfx.number_text("-1,25e-3") == "-1.25e-3"
    assert pzfx.number_text("1,234,5") == "1,234,5"  # not a number: left for the strict reader
    assert pzfx.number_text(" 2.5 ") == "2.5"


@pytest.mark.parametrize(
    ("data", "words"),
    [
        (
            b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa">]>'
            b"<GraphPadPrismFile>&a;</GraphPadPrismFile>",
            "document type",
        ),
        (b"<GraphPadPrismFile><Table>", "well-formed"),
        (b"<rdml/>", "not a Prism XML project"),
    ],
)
def test_hostile_or_foreign_files_are_refused(data, words):
    with pytest.raises(pzfx.PzfxError, match=words):
        pzfx.read_project(data)


def test_size_and_cell_caps_hold(monkeypatch):
    with pytest.raises(pzfx.PzfxError, match="larger than"):
        pzfx.read_project(b" " * (pzfx.MAX_PROJECT_BYTES + 1))
    monkeypatch.setattr(pzfx, "MAX_CELLS", 3)
    with pytest.raises(pzfx.PzfxError, match="cells"):
        pzfx.read_project(PRISM6_STYLE)


def test_two_tables_with_one_title_are_reported():
    _, _, _, data, _ = _written()
    root = etree.fromstring(data)
    tables = root.findall("p:Table", NS)
    tables[1].find("p:Title", NS).text = tables[0].find("p:Title", NS).text
    project = pzfx.read_project(etree.tostring(root))
    assert any("two tables are titled" in p for p in project.problems)


def test_the_grouped_table_is_left_out_beyond_prisms_subcolumn_limit(monkeypatch):
    from qpilot.prism import project as project_module

    inputs = toy_inputs()
    rendered = render_project_tables(inputs, ["T", "T2"], record_ref="r", chain_head=TOY_CHAIN)
    assert project_module.grouped_width(rendered) == 3 and project_module.grouped_fits(rendered)
    monkeypatch.setattr(pzfx, "MAX_SUBCOLUMNS", 2)
    assert not project_module.grouped_fits(rendered)
    one = render_project_tables(inputs, ["T"], record_ref="r", chain_head=TOY_CHAIN)
    assert project_module.grouped_width(one) == 0  # one gene: no table of all genes


def test_the_grouped_table_name_is_not_a_gene_table():
    bundle, texts, _ = _bundle(toy_inputs())
    main, _ = project_tables(bundle, texts)
    assert [t.name for t in main] == ["T", "T2", GROUPED_NAME]
