"""Rule packs: named, sourced, versioned acceptance rules, and the verdicts they give.

Domain-agnostic. A rule pack is a YAML file that a scientist (or an auditor, or an agent) can
read without reading Python::

    pack: research-default
    version: 1.0.0
    label: "Research use only. Lab-editable example rules with sources; not clinical rules."
    sources:
      miqe2: {citation: "Bustin et al. 2025, MIQE 2.0", url: "https://doi.org/..."}
    rules:
      - id: G-NTC-1
        name: No-template control amplification near the unknowns
        check: ntc_gap                  # the plugin's evaluator for this rule
        applies_to: {sample_types: [ntc], per: [plate, target]}
        params: {k_cycles: 5}
        severity: {tainted: fail, amplified_clear: warn}
        consequence_scope: [exclude_flagged]
        default_action: card
        statement: An unknown counts as positive only if it amplifies well before the control.
        sources: [miqe2]

What the core knows, and what it does not:

* A rule names a ``check``; the plugin registers an evaluator for it (a function from the rule
  and the plugin's own context to :class:`RuleEval` results). The core never interprets a
  threshold. A rule whose check this build does not have evaluates ``not_applicable`` with that
  reason, never ``pass``.
* An evaluator reports an **outcome** (``clean``, ``tainted`` ...); the pack's ``severity`` maps
  outcomes to ``pass | warn | fail``, so a lab can downgrade a failure to a warning without code.
  ``not_applicable`` is a first-class verdict and can never be mapped to anything else.
* ``consequence_scope`` lists the options the consequence test (``core/gate.py``) tries, e.g.
  "exclude the flagged wells"; an empty list means the rule is informational.
* The **pack hash** is sha256 of the canonical JSON of the validated pack (comments and
  whitespace do not count; any changed threshold does). It goes into every record that used it.
  A lab's edit is a new pack (same name, new version, ``based_on`` the old hash), never an edit
  in place; :func:`diff_packs` shows what changed.

Loading is hardened: size cap, ``yaml.safe_load`` semantics with aliases and duplicate keys
refused, a nesting-depth cap, unknown fields refused, bounded strings and lists.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

Verdict = Literal["pass", "warn", "fail", "not_applicable"]
Severity = Literal["pass", "warn", "fail"]
Action = Literal["log", "card", "invalidate_plate"]
Scope = Literal["study", "plate", "target", "sample", "well"]

VERDICTS: tuple[str, ...] = ("pass", "warn", "fail", "not_applicable")
NOT_APPLICABLE = "not_applicable"
MAX_PACK_BYTES = 256 * 1024
MAX_RULES = 200
MAX_DEPTH = 12
MAX_TEXT = 2000
RULE_ID = re.compile(r"^[A-Z][A-Z0-9]*(-[A-Z0-9]+)*$")
NAME = re.compile(r"^[a-z][a-z0-9_]*(-[a-z0-9_]+)*$")
VERSION = re.compile(r"^\d+(\.\d+){0,2}([-+][0-9A-Za-z.]+)?$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
BANNER = "research use"  # every pack's label must say so (W2 spec F.2)

ParamValue = float | int | str | bool | list[float | int | str | bool]


class RulePackError(ValueError):
    """A rule pack that cannot be read or does not follow the pack format."""


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Source(_Strict):
    """One citation a rule's threshold comes from (or ``lab_default`` for an unsourced default)."""

    citation: str = Field(min_length=1, max_length=MAX_TEXT)
    url: str | None = Field(default=None, max_length=500)
    note: str = Field(default="", max_length=MAX_TEXT)

    @field_validator("url")
    @classmethod
    def _https(cls, value: str | None) -> str | None:
        if value is not None and not re.fullmatch(r"https://[^\s<>\"']+", value):
            raise ValueError("a source url must be an https:// link without spaces or quotes")
        return value


class AppliesTo(_Strict):
    """Which wells a rule looks at (sample types) and how its verdicts are grouped."""

    sample_types: list[str] = Field(default_factory=list, max_length=20)
    per: list[Scope] = Field(default_factory=lambda: ["plate", "target"], max_length=5)
    chemistry: list[str] = Field(default_factory=list, max_length=10)


class Rule(_Strict):
    """One rule of a pack."""

    id: str
    name: str = Field(min_length=1, max_length=200)
    check: str
    statement: str = Field(min_length=1, max_length=MAX_TEXT)
    applies_to: AppliesTo = Field(default_factory=AppliesTo)
    needs: list[str] = Field(default_factory=list, max_length=50)
    params: dict[str, ParamValue] = Field(default_factory=dict, max_length=50)
    severity: dict[str, Severity] = Field(default_factory=dict, max_length=50)
    consequence_scope: list[str] = Field(default_factory=list, max_length=10)
    default_action: Action = "card"
    sources: list[str] = Field(min_length=1, max_length=20)
    enabled: bool = True

    @field_validator("id")
    @classmethod
    def _rule_id(cls, value: str) -> str:
        if len(value) > 40 or not RULE_ID.fullmatch(value):
            raise ValueError("a rule id is upper-case words joined by '-', e.g. G-NTC-1")
        return value

    @field_validator("check")
    @classmethod
    def _check_name(cls, value: str) -> str:
        if len(value) > 64 or not NAME.fullmatch(value):
            raise ValueError("a check name is lower-case snake_case, e.g. ntc_gap")
        return value

    @field_validator("severity")
    @classmethod
    def _outcomes(cls, value: dict[str, str]) -> dict[str, str]:
        for outcome in value:
            if outcome == NOT_APPLICABLE:
                raise ValueError("not_applicable is a verdict of its own and cannot be remapped")
            if len(outcome) > 64 or not NAME.fullmatch(outcome):
                raise ValueError(f"outcome {outcome[:40]!r} is not lower-case snake_case")
        return value

    @field_validator("params")
    @classmethod
    def _param_names(cls, value: dict[str, Any]) -> dict[str, Any]:
        for key, item in value.items():
            if len(key) > 64 or not NAME.fullmatch(key):
                raise ValueError(f"parameter {key[:40]!r} is not lower-case snake_case")
            if isinstance(item, str) and len(item) > 200:
                raise ValueError(f"parameter {key!r} is longer than 200 characters")
            if isinstance(item, float) and item != item:  # NaN
                raise ValueError(f"parameter {key!r} is not a number")
        return value

    @field_validator("consequence_scope", "needs", "sources")
    @classmethod
    def _names(cls, value: list[str]) -> list[str]:
        for item in value:
            if len(item) > 64 or not NAME.fullmatch(item):
                raise ValueError(f"{item[:40]!r} is not lower-case snake_case")
        if len(set(value)) != len(value):
            raise ValueError("an entry appears twice")
        return value

    def verdict_for(self, outcome: str, default: Mapping[str, str] | None = None) -> str:
        """The verdict an evaluator's outcome gives under this rule's severity map.

        ``not_applicable`` stays ``not_applicable``. An outcome the pack does not map takes the
        evaluator's default; one that neither maps is a ``warn`` (never a silent ``pass``).
        """
        if outcome == NOT_APPLICABLE:
            return NOT_APPLICABLE
        if outcome in self.severity:
            return self.severity[outcome]
        return (default or {}).get(outcome, "warn")


class BasedOn(_Strict):
    """The pack a lab's edit was made from."""

    pack: str
    version: str
    hash: str

    @field_validator("hash")
    @classmethod
    def _sha(cls, value: str) -> str:
        if not SHA256.fullmatch(value):
            raise ValueError("based_on.hash must be a sha256 hex digest")
        return value


class ConsequenceParams(_Strict):
    """Thresholds of the consequence test (project conventions, unsourced; lab-editable)."""

    magnitude_log2: float = Field(default=0.5, ge=0, le=10)
    magnitude_agreement: float = Field(default=0.10, ge=0, le=1)


class RulePack(_Strict):
    """A validated rule pack."""

    pack: str
    version: str
    label: str = Field(min_length=1, max_length=MAX_TEXT)
    based_on: BasedOn | None = None
    consequence: ConsequenceParams = Field(default_factory=ConsequenceParams)
    sources: dict[str, Source] = Field(min_length=1, max_length=200)
    rules: list[Rule] = Field(min_length=1, max_length=MAX_RULES)

    @field_validator("pack")
    @classmethod
    def _pack_name(cls, value: str) -> str:
        if len(value) > 64 or not NAME.fullmatch(value):
            raise ValueError("a pack name is lower-case words joined by '-', e.g. research-default")
        return value

    @field_validator("version")
    @classmethod
    def _version(cls, value: str) -> str:
        if len(value) > 40 or not VERSION.fullmatch(value):
            raise ValueError("a pack version looks like 1.0.0 (optionally -lab.1)")
        return value

    @field_validator("label")
    @classmethod
    def _banner(cls, value: str) -> str:
        if BANNER not in value.lower():
            raise ValueError(
                "the pack label must say 'Research use' (packs are not clinical rules)"
            )
        return value

    @model_validator(mode="after")
    def _consistent(self) -> RulePack:
        for key in self.sources:
            if len(key) > 64 or not NAME.fullmatch(key):
                raise ValueError(f"source key {key[:40]!r} is not lower-case snake_case")
        ids = [rule.id for rule in self.rules]
        twice = sorted({i for i in ids if ids.count(i) > 1})
        if twice:
            raise ValueError(f"rule ids appear twice: {twice}")
        for rule in self.rules:
            missing = [s for s in rule.sources if s not in self.sources]
            if missing:
                raise ValueError(f"rule {rule.id} cites sources the pack does not list: {missing}")
        return self

    @property
    def hash(self) -> str:
        """sha256 of the canonical JSON of the pack (what a record stores)."""
        return pack_hash(self)

    def rule(self, rule_id: str) -> Rule:
        """The rule with this id; ``KeyError`` when the pack has none."""
        for rule in self.rules:
            if rule.id == rule_id:
                return rule
        raise KeyError(rule_id)

    def ref(self) -> dict[str, str]:
        """``{pack, version, hash}``: how a record names the pack it used."""
        return {"pack": self.pack, "version": self.version, "hash": self.hash}


def canonical_pack_json(pack: RulePack) -> str:
    """The pack as canonical JSON (sorted keys, no spaces): the bytes the hash is taken of."""
    data = pack.model_dump(mode="json")
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def pack_hash(pack: RulePack) -> str:
    """sha256 hex digest of :func:`canonical_pack_json`."""
    return hashlib.sha256(canonical_pack_json(pack).encode("utf-8")).hexdigest()


# ---------- reading ----------


class _PackLoader(yaml.SafeLoader):
    """``yaml.safe_load`` that also refuses aliases and duplicate keys."""

    def compose_node(self, parent, index):  # noqa: D102 - PyYAML hook
        if self.check_event(yaml.AliasEvent):
            mark = self.peek_event().start_mark
            raise RulePackError(f"line {mark.line + 1}: YAML aliases are not allowed in a pack")
        return super().compose_node(parent, index)

    def construct_mapping(self, node, deep=False):  # noqa: D102 - PyYAML hook
        seen = set()
        for key_node, _ in node.value:
            key = self.construct_object(key_node, deep=deep)
            if key in seen:
                raise RulePackError(f"line {key_node.start_mark.line + 1}: key {key!r} twice")
            seen.add(key)
        return super().construct_mapping(node, deep=deep)


def _depth(data: Any, level: int = 0) -> int:
    if level > MAX_DEPTH:
        return level
    if isinstance(data, Mapping):
        return max((_depth(v, level + 1) for v in data.values()), default=level)
    if isinstance(data, list):
        return max((_depth(v, level + 1) for v in data), default=level)
    return level


def parse_pack(text: str, where: str = "rule pack") -> RulePack:
    """Parse and validate a pack from YAML text; :class:`RulePackError` on any problem."""
    if len(text.encode("utf-8")) > MAX_PACK_BYTES:
        raise RulePackError(f"{where} is larger than {MAX_PACK_BYTES:,} bytes")
    try:
        data = yaml.load(text, Loader=_PackLoader)  # noqa: S506 - a SafeLoader subclass
    except RulePackError:
        raise
    except yaml.YAMLError as err:
        raise RulePackError(f"{where} is not valid YAML: {str(err)[:300]}") from None
    if not isinstance(data, dict):
        raise RulePackError(f"{where}: expected a mapping at the top level")
    if _depth(data) > MAX_DEPTH:
        raise RulePackError(f"{where} nests deeper than {MAX_DEPTH} levels")
    try:
        return RulePack.model_validate(data)
    except ValidationError as err:
        first = err.errors()[0]
        loc = ".".join(str(p) for p in first["loc"]) or "pack"
        raise RulePackError(
            f"{where}: {loc}: {first['msg']} ({err.error_count()} problem(s))"
        ) from None


def load_pack(path: str | Path) -> RulePack:
    """Read and validate a pack file (UTF-8 YAML, at most :data:`MAX_PACK_BYTES`)."""
    path = Path(path)
    try:
        size = path.stat().st_size
    except OSError as err:
        raise RulePackError(f"rule pack {path.name}: {err.strerror or err}") from None
    if not path.is_file():
        raise RulePackError(f"rule pack {path.name} is not a file")
    if size > MAX_PACK_BYTES:
        raise RulePackError(f"rule pack {path.name} is larger than {MAX_PACK_BYTES:,} bytes")
    try:
        text = path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        raise RulePackError(f"rule pack {path.name} is not UTF-8 text") from None
    return parse_pack(text, f"rule pack {path.name}")


def pack_from_json(text: str) -> RulePack:
    """A pack from its canonical JSON (as a record stores it); :class:`RulePackError` if bad."""
    if len(text.encode("utf-8")) > MAX_PACK_BYTES:
        raise RulePackError(f"rule pack JSON is larger than {MAX_PACK_BYTES:,} bytes")
    try:
        return RulePack.model_validate_json(text)
    except ValidationError as err:
        raise RulePackError(
            f"rule pack JSON does not follow the pack format: {err.error_count()} problem(s)"
        ) from None


# ---------- editing (a lab override is a new version) ----------


def override(
    base: RulePack,
    version: str,
    params: Mapping[str, Mapping[str, ParamValue]] | None = None,
    severity: Mapping[str, Mapping[str, Severity]] | None = None,
    enabled: Mapping[str, bool] | None = None,
    label: str | None = None,
) -> RulePack:
    """A lab's edit of ``base`` as a new pack version, ``based_on`` the base's hash.

    ``params`` / ``severity`` map rule id -> the entries to change; ``enabled`` switches rules
    on or off. The base is never modified. The version must differ from the base's.
    """
    if version == base.version:
        raise RulePackError("an edited pack needs a new version")
    unknown = sorted(
        {*(params or {}), *(severity or {}), *(enabled or {})} - {r.id for r in base.rules}
    )
    if unknown:
        raise RulePackError(f"no such rule(s) in {base.pack}: {unknown}")
    rules = []
    for rule in base.rules:
        data = rule.model_dump(mode="json")
        data["params"] = {**data["params"], **dict((params or {}).get(rule.id, {}))}
        data["severity"] = {**data["severity"], **dict((severity or {}).get(rule.id, {}))}
        if enabled and rule.id in enabled:
            data["enabled"] = bool(enabled[rule.id])
        rules.append(data)
    data = base.model_dump(mode="json")
    data.update(
        version=version,
        rules=rules,
        based_on={"pack": base.pack, "version": base.version, "hash": base.hash},
    )
    if label is not None:
        data["label"] = label
    try:
        return RulePack.model_validate(data)
    except ValidationError as err:
        raise RulePackError(f"edited pack is not valid: {err.errors()[0]['msg']}") from None


def dump_pack_yaml(pack: RulePack) -> str:
    """The pack as YAML (keys in model order), for a lab to save its edited version."""
    return yaml.safe_dump(
        pack.model_dump(mode="json"), sort_keys=False, allow_unicode=True, width=100
    )


def diff_packs(old: RulePack, new: RulePack) -> list[dict[str, Any]]:
    """What changed between two packs: one entry per changed field, rules matched by id."""
    out: list[dict[str, Any]] = []
    for field in ("pack", "version", "label"):
        if getattr(old, field) != getattr(new, field):
            out.append({"what": field, "old": getattr(old, field), "new": getattr(new, field)})
    before = {r.id: r.model_dump(mode="json") for r in old.rules}
    after = {r.id: r.model_dump(mode="json") for r in new.rules}
    for rule_id in sorted(before.keys() - after.keys()):
        out.append({"what": "rule removed", "rule": rule_id})
    for rule_id in sorted(after.keys() - before.keys()):
        out.append({"what": "rule added", "rule": rule_id})
    for rule_id in sorted(before.keys() & after.keys()):
        a, b = before[rule_id], after[rule_id]
        for key in sorted(a.keys() | b.keys()):
            if isinstance(a.get(key), dict) and isinstance(b.get(key), dict):
                for sub in sorted(a[key].keys() | b[key].keys()):
                    if a[key].get(sub) != b[key].get(sub):
                        out.append(
                            {
                                "what": f"{key}.{sub}",
                                "rule": rule_id,
                                "old": a[key].get(sub),
                                "new": b[key].get(sub),
                            }
                        )
            elif a.get(key) != b.get(key):
                out.append({"what": key, "rule": rule_id, "old": a.get(key), "new": b.get(key)})
    old_src, new_src = old.sources, new.sources
    for key in sorted(old_src.keys() | new_src.keys()):
        if old_src.get(key) != new_src.get(key):
            out.append({"what": "source", "source": key})
    return out


# ---------- evaluation ----------


class RuleEval(BaseModel):
    """One verdict of one rule on one scope (a plate, a plate x target, a sample ...).

    ``reason`` is plain words with ``{{fact_id}}`` tokens for every number (it passes
    ``core/validator.py`` against ``facts``). ``code`` is a machine reason, always set for
    ``not_applicable`` (``no_ntc_typed``, ``processed_input`` ...). ``evidence`` holds the same
    numbers as structured values, keyed by name. ``flagged`` are the item keys (wells, for qPCR)
    the rule points at; ``options`` are the consequence-test options, option id -> the item
    keys it would exclude.
    """

    rule_id: str
    check: str
    scope: dict[str, str]
    outcome: str
    verdict: Verdict
    code: str = ""
    reason: str
    facts: list[str] = []
    evidence: dict[str, float | int | str | bool | None] = {}
    flagged: list[str] = []
    options: dict[str, list[str]] = {}

    @property
    def key(self) -> str:
        """A stable id for this evaluation: rule id and scope values."""
        parts = [self.rule_id, *(f"{k}={self.scope[k]}" for k in sorted(self.scope))]
        return "|".join(parts)


class Finding(BaseModel):
    """What an evaluator returns before the pack's severity turns it into a verdict."""

    scope: dict[str, str]
    outcome: str
    reason: str
    code: str = ""
    facts: list[str] = []
    evidence: dict[str, float | int | str | bool | None] = {}
    flagged: list[str] = []
    options: dict[str, list[str]] = {}

    @model_validator(mode="after")
    def _na_has_code(self) -> Finding:
        if self.outcome == NOT_APPLICABLE and not self.code:
            raise ValueError("a not_applicable finding needs a machine reason (code)")
        return self


#: An evaluator: (rule, plugin context) -> findings. Registered per check name by the plugin.
Evaluator = Callable[[Rule, Any], Iterable[Finding]]


class Check(BaseModel):
    """A plugin's evaluator for one check name, with its outcomes' default verdicts."""

    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True)

    name: str
    evaluate: Evaluator
    outcomes: dict[str, Severity]
    options: tuple[str, ...] = ()
    needs: tuple[str, ...] = ()


def evaluate_pack(
    pack: RulePack,
    checks: Mapping[str, Check],
    context: Any,
    missing: Callable[[Rule], Finding] | None = None,
) -> list[RuleEval]:
    """Every enabled rule of ``pack`` on ``context``, in pack order then evaluator order.

    A rule whose check is not in ``checks`` gives one ``not_applicable`` evaluation (scope
    ``{}``), with ``missing(rule)``'s finding when given. Options an evaluator offers that the
    rule's ``consequence_scope`` does not list are dropped; with an empty scope the rule is
    informational and carries no options.
    """
    out: list[RuleEval] = []
    for rule in pack.rules:
        if not rule.enabled:
            continue
        check = checks.get(rule.check)
        if check is None:
            finding = (
                missing(rule)
                if missing is not None
                else Finding(
                    scope={},
                    outcome=NOT_APPLICABLE,
                    code="no_evaluator",
                    reason=f"This build has no evaluator for the check {rule.check}.",
                )
            )
            out.append(_to_eval(rule, rule.check, finding, {}))
            continue
        for finding in check.evaluate(rule, context):
            out.append(_to_eval(rule, check.name, finding, check.outcomes))
    return out


def _to_eval(rule: Rule, check: str, finding: Finding, defaults: Mapping[str, str]) -> RuleEval:
    allowed = set(rule.consequence_scope)
    options = {k: list(v) for k, v in finding.options.items() if k in allowed}
    verdict = rule.verdict_for(finding.outcome, defaults)
    if verdict in ("pass", NOT_APPLICABLE):
        options = {}
    return RuleEval(
        rule_id=rule.id,
        check=check,
        scope=dict(finding.scope),
        outcome=finding.outcome,
        verdict=verdict,
        code=finding.code,
        reason=finding.reason,
        facts=list(finding.facts),
        evidence=dict(finding.evidence),
        flagged=list(finding.flagged),
        options=options,
    )


def check_pack_against(pack: RulePack, checks: Mapping[str, Check]) -> list[str]:
    """Problems between a pack and the evaluators of this build (empty list = consistent).

    Lists checks that do not exist, severity outcomes a check never reports and consequence
    options a check never offers. A pack with problems still loads; this is what
    ``qpilot gate rules validate`` prints.
    """
    problems = []
    for rule in pack.rules:
        check = checks.get(rule.check)
        if check is None:
            problems.append(f"{rule.id}: no evaluator for check {rule.check!r} in this build")
            continue
        for outcome in rule.severity:
            if outcome not in check.outcomes:
                problems.append(f"{rule.id}: check {check.name} never reports outcome {outcome!r}")
        for option in rule.consequence_scope:
            if option not in check.options:
                problems.append(f"{rule.id}: check {check.name} offers no option {option!r}")
    return problems


def summarise(evals: Iterable[RuleEval]) -> dict[str, int]:
    """Counts of each verdict, always with all four keys."""
    counts = dict.fromkeys(VERDICTS, 0)
    for ev in evals:
        counts[ev.verdict] += 1
    return counts
