"""A toy study Trace can follow, put into a store (no download, no RDML file).

Built on the Trace engine's own toy table (``tests/engine/test_trace.py``): 40 samples, four
references, a marker and three genes, with one reference well of sample ``s12`` planted eight
cycles late. Measured: tracing ``DOWN`` ranks that well first, and setting the sample aside
changes the call (``changes_call``), so the app shows one Decide… button for it.
"""

from qpilot.core.store import StudyStore
from qpilot.qpcr.study import study_from_curves
from tests.engine.test_trace import TOY, context, plant, toy_table

TOY_SHA = "ab" * 32
PLANTED = "s12"
GENE = "DOWN"


def toy_trace_table(sample_name: str | None = None):
    """The toy per-well table with the planted well; ``sample_name`` renames the planted sample."""
    table = toy_table(n=40)
    table = plant(table, (table["sample"] == PLANTED) & (table["target"] == "R1"), 8.0)
    if sample_name is not None:
        table.loc[table["sample"] == PLANTED, "sample"] = sample_name
    return table


def toy_store(root, sample_name: str | None = None):
    """A store holding the toy study: ``(store, study_id, trace context, result)``."""
    table = toy_trace_table(sample_name)
    result, cards, _ = study_from_curves(table, TOY_SHA, TOY)
    store = StudyStore(root)
    store.put(result, cards)
    return store, result.study_id, context(table), result
