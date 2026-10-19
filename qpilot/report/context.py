"""What every section builder shares: the record, its facts, the names prose may use.

:class:`Ctx` wraps a :class:`~qpilot.report.record_view.RecordView` with the report's fact
registry (:class:`~qpilot.report.text.ReportFacts`) and helpers that register derived facts the
same way every time (group names, per-gene n, versions), so two sections that show the same
value cite the same fact id.
"""

from __future__ import annotations

from functools import cached_property

from qpilot.core.validator import method_constants
from qpilot.report.record_view import RecordView
from qpilot.report.text import ReportFacts, Text, fact_text, safe_slug, tok

#: How each analysis dimension is named in a sentence ("the answer rests on …").
DIM_LABELS = {
    "refs": "the control-gene set",
    "cut": "the group cut-off",
    "undetermined": "how wells without a quantity are handled",
    "amp_call": "which curves count as amplified",
    "efficiency": "the efficiency model",
    "nondetect": "how non-detects are handled",
}
#: The dimension each legacy card kind decides (newer kinds are looked up by their dimension).
CARD_DIMENSION = {
    "reference_set": "refs",
    "group_cutoff": "cut",
    "undetermined": "undetermined",
    "amp_call": "amp_call",
}


#: Method names with digits that prose may use verbatim (they name a method, not a result).
METHOD_NAMES = {"MIQE 2.0", "SHA-256", "log2", "N0", "21 CFR Part 11"}


def dim_label(dim: str) -> str:
    """A dimension's name in words; unknown dimensions keep their id, underscores as spaces."""
    return DIM_LABELS.get(dim, dim.replace("_", " ").replace(".", " "))


class Ctx:
    """The record plus the report's facts and allowed names."""

    def __init__(self, view: RecordView) -> None:
        self.view = view
        self.result = view.results
        self.facts = ReportFacts(view.facts)
        names = set(self.result.contrasts) | set(self.result.robustness)
        names |= set(self.result.genorm.M_initial) | set(self.result.design.refs_primary)
        names |= set(self.result.efficiency) | {self.result.design.group_var}
        names |= method_constants(self.result) | METHOD_NAMES
        self.names: set[str] = {n for n in names if n}

    def t(self, tokens: str) -> Text:
        """Fact-bound text (validated; raises ``ProseError`` on a naked number)."""
        return fact_text(tokens, self.facts, self.names)

    def has(self, *fids: str) -> bool:
        """True when every one of these facts exists."""
        return all(fid in self.facts for fid in fids)

    # ---- derived facts used by several sections ----------------------------------------

    @cached_property
    def group_a(self) -> str:
        """Fact id of the first group's name (the "high" group of an expression split)."""
        if "f_group_a" in self.facts:
            return "f_group_a"
        return self.facts.derive(
            "group_a", self.result.design.group_var, path="design.json:group_var"
        )

    @cached_property
    def group_b(self) -> str:
        """Fact id of the second group's name ("rest" for an expression split)."""
        if "f_group_b" in self.facts:
            return "f_group_b"
        return self.facts.derive("group_b", "rest", path="design.json:note (the other samples)")

    def gene_n(self, gene: str) -> tuple[str, str]:
        """Fact ids of a gene's biological n in each group (from its primary comparison)."""
        contrast = self.result.contrasts[gene]
        s = safe_slug(gene)
        path = f"results.json:contrasts.{gene}"
        return (
            self.facts.derive(f"n_a_{s}", int(contrast.n_hi), path=f"{path}.n_hi"),
            self.facts.derive(f"n_b_{s}", int(contrast.n_lo), path=f"{path}.n_lo"),
        )

    def version(self, key: str) -> str | None:
        """Fact id of one entry of ``versions.json`` (None when the record lacks it)."""
        value = self.view.versions.get(key)
        if not isinstance(value, str) or not value or value == "unknown":
            return None
        return self.facts.derive(f"version_{safe_slug(key)}", value, path=f"versions.json:{key}")

    @cached_property
    def headline(self) -> list[str]:
        """The headline genes: the confirmed design's, else the reference-set card's genes."""
        genes = self.view.study_design.get("headline")
        if not isinstance(genes, list):
            genes = []
            for card in self.view.cards:
                options = card.get("options")
                if isinstance(options, list) and options and isinstance(options[0], dict):
                    per_gene = options[0].get("per_gene")
                    if isinstance(per_gene, dict):
                        genes = list(per_gene)
                        break
        return [g for g in genes if isinstance(g, str) and g in self.result.contrasts]

    def option_of(self, card_id: str) -> str | None:
        """The decided (else recommended) option of a card, from ``choices.json`` or cards."""
        choice = self.view.choices.get("cards", {})
        entry = choice.get(card_id) if isinstance(choice, dict) else None
        if isinstance(entry, dict):
            value = entry.get("decision") or entry.get("recommended")
            return value if isinstance(value, str) else None
        for card in self.view.cards:
            if card.get("id") == card_id:
                value = card.get("decision") or card.get("recommended")
                return value if isinstance(value, str) else None
        return None

    def count(self, name: str, value: int, path: str) -> str:
        """Register a derived count and return its token."""
        return tok(self.facts.derive(name, int(value), path=path))
