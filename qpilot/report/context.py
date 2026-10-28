"""What every part of the report shares: the study, its facts and the names prose may use.

:class:`Ctx` wraps :class:`~qpilot.report.inputs.StudyInputs` with the report's fact registry and
helpers that register derived facts the same way every time (group sizes, versions, counts, the
audit's numbers), so two sections that show one value cite one fact id.
"""

from __future__ import annotations

from collections import Counter
from functools import cached_property
from typing import Any

from qpilot.core.validator import method_constants
from qpilot.report.inputs import StudyInputs
from qpilot.report.text import Part, ReportFacts, pointer, safe_slug, tok
from qpilot.schemas import DecisionCard

#: How each analysis choice is named in a sentence.
DIM_LABELS = {
    "refs": "the control genes",
    "cut": "the group cut-off",
    "undetermined": "how wells without a quantity are handled",
    "amp_call": "which curves count as amplified",
    "efficiency": "which efficiency turns Cq into quantity",
}
#: The choice each Decision Card kind decides.
KIND_DIMENSION = {
    "reference_set": "refs",
    "group_cutoff": "cut",
    "undetermined": "undetermined",
    "amp_call": "amp_call",
    "numbers.efficiency_model": "efficiency",
}
#: Method names with digits that prose may quote (they name a method, not a result).
METHOD_NAMES = {"MIQE 2.0", "SHA-256", "log2", "N0", "TD0", "RFC 6901"}
#: How absolute quantities are computed (``report/methods.py`` quantities): method, not data.
METHOD_NAMES |= {"log10", "10^(−1/slope) − 1", "95 % prediction interval", "R²"}


def dim_label(dim: str) -> str:
    """A choice's name in words; unknown ones keep their id, underscores as spaces."""
    return DIM_LABELS.get(dim, dim.replace("_", " "))


class Ctx:
    """The study plus the report's facts and allowed names."""

    def __init__(self, inputs: StudyInputs) -> None:
        self.inputs = inputs
        self.result = inputs.result
        self.facts = ReportFacts(inputs.result.facts)
        r = self.result
        names = set(r.contrasts) | set(r.robustness) | set(r.genorm.M_initial)
        names |= set(r.design.refs_primary) | set(r.efficiency) | {r.design.group_var}
        names |= method_constants(r) | METHOD_NAMES
        self.facts.names = {n for n in names if n}

    # ---- text --------------------------------------------------------------------------------

    def t(self, *parts: Part) -> Any:
        """Fact-bound text (see :meth:`ReportFacts.text`)."""
        return self.facts.text(*parts)

    def has(self, *fids: str) -> bool:
        """True when every one of these facts exists."""
        return self.facts.has(*fids)

    def count(self, name: str, value: int, path: str, fmt: str = "{}") -> str:
        """A derived count's token (``fmt="{:,}"`` groups thousands, as the engine's counts)."""
        return tok(self.facts.derive(name, int(value), path, fmt=fmt))

    def num(self, name: str, value: float, path: str, fmt: str = "{:.2f}", unit: str = "") -> str:
        """A derived number's token."""
        return tok(self.facts.derive(name, value, path, fmt=fmt, unit=unit))

    def word(self, name: str, value: str, path: str) -> str:
        """A derived string's token (a version, a hash: text with digits that is not prose)."""
        return tok(self.facts.derive(name, value, path))

    # ---- the study ---------------------------------------------------------------------------

    @cached_property
    def marker_mode(self) -> bool:
        """Groups split by a marker gene's expression (not from a confirmed design's groups)."""
        return "f_group_a" not in self.facts

    @cached_property
    def group_names(self) -> tuple[str, str]:
        """The compared group's name and the reference group's."""
        if not self.marker_mode:
            return str(self.facts.value("f_group_a")), str(self.facts.value("f_group_b"))
        var = self.result.design.group_var
        marker = var.removesuffix("_high") or var
        return f"{marker}-high", "rest"

    @cached_property
    def marker(self) -> str | None:
        """The marker gene a marker split ranks by (from the confirmed design, when known)."""
        design = self.inputs.design
        if design is not None and design.marker_split is not None:
            return design.marker_split.marker
        return None

    def gene_n(self, gene: str) -> tuple[str, str]:
        """Tokens of a gene's biological n in each group (from its comparison)."""
        c = self.result.contrasts[gene]
        s = safe_slug(gene)
        return (
            self.count(f"n_hi_{s}", c.n_hi, f"results.json:{pointer('contrasts', gene, 'n_hi')}"),
            self.count(f"n_lo_{s}", c.n_lo, f"results.json:{pointer('contrasts', gene, 'n_lo')}"),
        )

    def version(self, key: str) -> str | None:
        """Token of one software version (None when it is unknown)."""
        value = self.inputs.versions.get(key)
        if not isinstance(value, str) or not value or value == "unknown":
            return None
        return self.word(f"version_{safe_slug(key)}", value, f"versions:{pointer(key)}")

    @property
    def headline(self) -> list[str]:
        """The headline genes, lead gene first (as the Results section ranks them)."""
        return self.inputs.headline

    @cached_property
    def calls(self) -> Counter[str]:
        """Genes by conclusion at the primary analysis."""
        return Counter(c.conclusion for c in self.result.contrasts.values())

    def call_count(self, call: str) -> str:
        """Token of how many genes have this conclusion."""
        path = f"results.json:{pointer('contrasts')}@count=conclusion:{call}"
        return self.count(f"n_{call}", self.calls[call], path)

    # ---- cards and decisions -------------------------------------------------------------------

    def card_title(self, card: DecisionCard) -> str:
        """A card's question in words."""
        from qpilot.ai.explain import KIND_TITLE

        return KIND_TITLE.get(card.kind, card.kind.replace("_", " "))

    def option_label(self, card: DecisionCard, option: str | None) -> str | None:
        """An option's label as the card shows it."""
        if option is None:
            return None
        return next((o.label for o in card.options if o.id == option), option)

    @cached_property
    def open_cards(self) -> list[DecisionCard]:
        """Cards still open or waiting for a person."""
        return [c for c in self.inputs.cards if c.status in ("open", "pending_human")]

    @cached_property
    def open_flipping(self) -> list[DecisionCard]:
        """Open cards where some option changes a conclusion."""
        return [c for c in self.open_cards if c.impact.get("flips")]

    # ---- the audit -----------------------------------------------------------------------------

    def audit_num(
        self, name: str, file: str, *keys: object, fmt: str = "{}", unit: str = ""
    ) -> str:
        """Token of one number read from the audit's files (KeyError when it is absent)."""
        audit = self.inputs.audit
        if audit is None:
            raise KeyError("no audit")
        data: Any = {
            "audit_manifest.json": audit.manifest,
            "summary.json": audit.summary,
        }[file]
        for key in keys:
            data = data[key]
        if isinstance(data, bool) or not isinstance(data, int | float | str):
            raise KeyError(f"{file}{pointer(*keys)} is not a number")
        path = f"audit:{file}:{pointer(*keys)}"
        return tok(self.facts.derive(f"audit_{name}", data, path, fmt=fmt, unit=unit))

    @cached_property
    def audit_current(self) -> bool:
        """The audit was run at the decision log's current head."""
        audit = self.inputs.audit
        return bool(audit and audit.manifest.get("chain_head") == self.inputs.head)
