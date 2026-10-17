"""The Design Interpreter: a model reads names, a sheet and one sentence, and PROPOSES a design.

Deterministic code reads declared types, vendor task words and name patterns
(:mod:`qpilot.qpcr.design_rules`); a language model can read what rules cannot: a lab's own
abbreviations, a merged header, a sentence such as "LPS vs PBS, three mice each". This module
asks the model for a :class:`~qpilot.schemas_studio.DesignProposal`, checks every field, and
merges what survives with the rule fields. Nothing here accepts, applies or stores anything:
each returned field becomes a proposal that only a person accepts.

**What the model sees.** The :class:`~qpilot.schemas_studio.InspectSummary` without free text:
samples and targets by an opaque ``ref`` (their ``text_id``), declared types, well counts,
efficiency summaries, experiments as ``x1``, ``x2``... Free text is shown only inside the fenced
blocks of :func:`qpilot.core.firewall.as_quoted`, under generic origins (never a file or sheet
name): one *sample record* per sample under the sample's ref (its name and the cells of its
sample-sheet row, by column number), one block per target name, the sheet's header rows and the
scientist's sentence (quarantined with origin ``studio:sentence``). Text the firewall flags
``instruction_like`` (the sentence excepted: the person typed it) is withheld from the model.
Large files are sent in parts (:data:`SAMPLES_PER_CALL` samples or :data:`TARGETS_PER_CALL`
targets per call, replies of at most :data:`MAX_TOKENS` tokens), so each call fits a small
local model inside the client's timeout. An unreachable server (a refused connection) stops the
model at once and the rules answer alone; a call that times out costs only its part (the rules
answer for those samples), and :data:`MAX_READ_TIMEOUTS` timeouts stop the model for the rest,
so a slow server adds at most that many client timeouts, never a hang.

**Remote providers.** When the backend is not on this machine
(:func:`qpilot.core.pseudonym.endpoint_is_local`; a test double says so with a ``remote``
attribute and counts as remote without one), a :class:`~qpilot.core.pseudonym.Pseudonymiser`
is required: sample and target names become keyed tokens, every name inside a sheet row or the
sentence is replaced by its token, ``text_id`` refs are replaced by keyed aliases (a plain
``text_id`` can be recomputed from a guessed name), and labels in the rule proposals shown are
tokens too. The reply is mapped back before it is checked. Without a pseudonymiser nothing is
sent and the rules answer alone.

**Rules every model field must pass** (a field that fails is dropped and listed in
``rejected`` with why; any failure gets the reply one retry with the validator's message):

* the reply is JSON ``{"fields": [...]}`` and every field validates as a
  :class:`~qpilot.schemas_studio.DesignField` (a reply cut off at the token limit is read up
  to its last complete field and counts as a problem);
* ``kind`` is a ``design.*`` kind allowed in that call (never ``curve.*``, ``prism.*`` or
  ``stage.*``);
* ``subject`` is a sample or target shown in that call (or ``comparison``, ``design``, a series
  name), and ``value`` has exactly the payload shape of its kind with contract enums only;
* every cite is a ref shown in that call and maps to a ``text_id`` or sheet cell that exists;
  at most :data:`MAX_CITES`; nothing cited reads like instructions;
* a field about a sample cites that sample's own name or sheet row (a target: its name);
* group, biological-unit and comparison labels are found in a sheet cell or the sentence the
  field cites (never only in a sample or target name; a sample's group or unit only in its own
  sheet row or in a sentence that names the sample), and are not role codes;
* a sample declared ``ntc``, ``nrt`` or ``nac`` is never given a non-control role (the core's
  hard ban would refuse it too), a group, a biological unit or a place in a dilution series;
* a dilution series has at least three positive quantities, in one experiment;
* reasons are qPilot-checkable prose: no digit and no spelled amount
  (:func:`qpilot.core.validator.validate`), no text copied from the file, nothing that reads
  like instructions; others are dropped from the field.

**Merge policy.** Rule fields always come through unchanged, tagged ``MadeBy(kind="rule")``.
A model field identical in kind, subject and value to a rule field is dropped and the rule
field's reasons gain "the model reached the same reading". A model field that differs is kept
beside it, tagged ``MadeBy(kind="model", ...)``: the person sees both, and the core never lets
one maker supersede another. A model role that only repeats the declared type of a sample no
rule spoke about is left out. If no model reply is usable (no model, unreachable, invalid after
the retry) the result is the rule fields alone, ``fallback=True``, with a note asking the
scientist to type their controls.

``InterpretResult.fields`` and ``InterpretResult.makers`` are parallel lists: ``makers[i]`` made
``fields[i]``. :meth:`InterpretResult.proposals` turns them into
:class:`~qpilot.schemas_studio.Proposal` objects for the caller to submit; ``meta`` holds one
payload record per model call for the caller's ``ai_calls.jsonl`` (:func:`log_lines`).
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ValidationError, model_validator

from qpilot.ai import payload_log
from qpilot.ai.client import ModelClient, ModelUnavailable
from qpilot.ai.prompts import INTERPRET_KINDS, SYSTEM_INTERPRET
from qpilot.core.firewall import as_quoted, flags_for
from qpilot.core.pseudonym import TOKEN as PSEUDONYM_TOKEN
from qpilot.core.pseudonym import endpoint_is_local
from qpilot.core.validator import validate
from qpilot.schemas_studio import (
    CONTROL_ROLES,
    TEXT_ID,
    DesignField,
    Evidence,
    InspectSample,
    InspectSummary,
    InspectTarget,
    MadeBy,
    Proposal,
    QuarantineEntry,
    SheetCell,
    WellRole,
    text_id_for,
)

SENTENCE_ORIGIN = "studio:sentence"
MAX_SENTENCE_CHARS = 2_000
SAMPLES_PER_CALL = 15
TARGETS_PER_CALL = 15
MAX_TOKENS = 700
MAX_READ_TIMEOUTS = 2
MAX_FIELDS = 400
MAX_CITES = 50
MAX_ALTERNATIVES = 10
MAX_REASONS = 5
MAX_REASON_CHARS = 200
MAX_LABEL_CHARS = 64
MIN_SERIES_LEVELS = 3
ROW_CHARS = 400
HEADER_ROWS = 5
OTHER_ROWS = 20
INSTRUCTION_LIKE = "instruction_like"
WELL_ROLES: tuple[str, ...] = WellRole.__args__  # type: ignore[attr-defined]
SAMPLE_KINDS = ("design.well_role", "design.group", "design.bio_unit", "design.dilution_series")
STUDY_KINDS = ("design.target_role", "design.gene_symbol", "design.comparison", "design.preset")
SAME_READING = "the model reached the same reading"
WITHHELD = "(withheld by qPilot: this text reads like instructions to a model)"
NO_REASON = "the model gave no reason qPilot can show"
TYPE_YOUR_CONTROLS = (
    "Only qPilot's rules are proposed{where}. Please type your controls: check every "
    "no-template, no-RT and no-amplification control before you confirm the design."
)
PROMPT_SHA256 = hashlib.sha256(SYSTEM_INTERPRET.encode("utf-8")).hexdigest()
_LABEL = re.compile(r"^[A-Za-z0-9 _\-.()]{1,64}$")
_SYMBOL = re.compile(r"^[A-Z0-9][A-Za-z0-9\-]{0,19}$")
_SQUASH = re.compile(r"[^a-z0-9]+")
_WORD = "A-Za-z0-9_"


class InterpretResult(BaseModel):
    """What the interpreter proposes, who made each field, and how the model's reply fared.

    ``fields`` and ``makers`` are parallel: ``makers[i]`` made ``fields[i]`` (rule fields first,
    in the order given, then the model's). ``validated`` is True only when at least one model
    reply was used and every reply used passed every check; ``fallback`` is True when the rules
    alone answer for some or all of the input. ``quarantine`` holds new text the caller must
    store before submitting proposals that cite it (the scientist's sentence).
    ``numbers_caught`` counts model reasons dropped because they wrote a number (none is shown).
    """

    fields: list[DesignField] = []
    makers: list[MadeBy] = []
    fallback: bool
    validated: bool
    error: str | None = None
    notes: list[str] = []
    rejected: list[dict[str, Any]] = []
    meta: list[dict[str, Any]] = []
    prompt_sha256: str | None = None
    quarantine: list[QuarantineEntry] = []
    numbers_caught: int = 0

    @model_validator(mode="after")
    def _parallel(self) -> InterpretResult:
        if len(self.fields) != len(self.makers):
            raise ValueError("fields and makers must be parallel lists")
        return self

    def tagged(self) -> list[tuple[DesignField, MadeBy]]:
        """Each field with its maker."""
        return list(zip(self.fields, self.makers, strict=True))

    def proposals(self, study_id: str) -> list[Proposal]:
        """The fields as proposals for ``study_id``, ready for ``ProposalStore.propose``.

        Nothing is stored here; the store re-checks every proposal, assigns ids and attaches
        the engine's own check.
        """
        out = []
        for item, maker in self.tagged():
            evidence = [
                Evidence(kind="text" if TEXT_ID.match(ref) else "cell", ref=ref)
                for ref in item.cites
            ]
            out.append(
                Proposal(
                    study_id=study_id,
                    kind=item.kind,
                    subject=item.subject,
                    payload=dict(item.value),
                    evidence=evidence,
                    alternatives=list(item.alternatives),
                    level=item.level,
                    reasons=list(item.reasons),
                    made_by=maker,
                )
            )
        return out


# ---------------------------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------------------------


def squash(text: str) -> str:
    """Lower case with everything but letters and digits removed (for tolerant matching)."""
    return _SQUASH.sub("", str(text).lower())


def sentence_entry(sentence: str) -> QuarantineEntry | None:
    """The scientist's sentence as quarantined text (origin ``studio:sentence``), or None."""
    text = (sentence or "").strip()[:MAX_SENTENCE_CHARS]
    if not text:
        return None
    return QuarantineEntry(
        text_id=text_id_for(SENTENCE_ORIGIN, text),
        origin=SENTENCE_ORIGIN,
        value=text,
        flags=flags_for(text),
    )


def client_is_remote(client: ModelClient) -> bool:
    """Whether calls through ``client`` can leave this machine.

    A backend may say so itself with a boolean ``remote`` attribute (test doubles do); any
    other backend is judged by :func:`~qpilot.core.pseudonym.endpoint_is_local` on its provider
    and URL, so an unknown backend counts as remote.
    """
    flag = getattr(client.backend, "remote", None)
    if isinstance(flag, bool):
        return flag
    return not endpoint_is_local(client.provider, getattr(client.backend, "url", None))


def _declared_labels(sample: InspectSample) -> list[str]:
    return [label.split("@", 1)[0] for label in sample.declared_type.split(",") if label]


def declared_control(sample: InspectSample) -> bool:
    """True when the file declares the sample a control (``ntc``/``nrt``/``nac``) for any target.

    A sample with any declared control type is treated as a control: re-typing the sample would
    re-type those wells too.
    """
    return any(label in CONTROL_ROLES for label in _declared_labels(sample))


def _single_declared(sample: InspectSample) -> str | None:
    labels = set(_declared_labels(sample))
    return labels.pop() if len(labels) == 1 else None


def _safe_label(text: str) -> str | None:
    """A label as a plain identifier (the engine's own rule), or None when nothing is left."""
    from qpilot.qpcr.curves import safe_name  # the engine's identifier rule

    label = str(text).strip()
    if not label or len(label) > 4 * MAX_LABEL_CHARS:
        return None
    safe = safe_name(label, "label")
    return safe if _LABEL.match(safe) else None


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float | str):
        return None
    try:
        number = float(value)
    except ValueError:
        return None
    return number if math.isfinite(number) and number > 0 else None


# ---------------------------------------------------------------------------------------------
# What the model is shown, and how its refs map back
# ---------------------------------------------------------------------------------------------


@dataclass
class _Row:
    """One sample-sheet row, shown to the model as one quoted entry."""

    handle: str
    sheet: int
    row: int
    cells: list[SheetCell]


@dataclass
class _Part:
    """One model call: some samples and/or the study level, and the kinds it may propose.

    ``study`` parts show the targets, the sheet rows no sample claims and the study-level rule
    proposals (comparison, preset).
    """

    samples: list[InspectSample]
    targets: list[InspectTarget]
    kinds: tuple[str, ...]
    study: bool
    rows: list[_Row] = field(default_factory=list)


class _Shield:
    """Pseudonyms for a remote call (identity for a local one)."""

    def __init__(self, pseudonymiser: Any | None, names: Iterable[str]) -> None:
        self.pseudonymiser = pseudonymiser
        self.active = pseudonymiser is not None
        self.to_name: dict[str, str] = {}
        self._pattern: re.Pattern[str] | None = None
        self._tokens: dict[str, str] = {}
        if not self.active:
            return
        unique = sorted({n for n in names if n and n.strip()}, key=lambda n: (-len(n), n))
        for name in unique:
            token = self.token(name)
            self._tokens.setdefault(name.lower(), token)
        if unique:
            alternatives = "|".join(re.escape(n) for n in unique)
            self._pattern = re.compile(
                rf"(?<![{_WORD}])({alternatives})(?![{_WORD}])", re.IGNORECASE
            )

    def token(self, name: str) -> str:
        """The keyed token for a name (remembered for mapping back)."""
        if not self.active:
            return name
        token = self.pseudonymiser.pseudonymise(name)
        self.to_name.setdefault(token, name)
        return token

    def alias(self, text_id: str) -> str:
        """A keyed alias for a ``text_id`` (the id itself for a local call)."""
        if not self.active:
            return text_id
        keyed = self.pseudonymiser.pseudonymise("\x00text_id\x00" + text_id)
        return "t_" + hashlib.sha256(keyed.encode("utf-8")).hexdigest()[:12]

    def scrub(self, text: str) -> str:
        """``text`` with every known name replaced by its token."""
        if not self.active or self._pattern is None:
            return text
        return self._pattern.sub(lambda m: self._tokens[m.group(1).lower()], text)

    def unscrub(self, text: str) -> str:
        """``text`` with tokens mapped back to the names they stand for."""
        if not self.active:
            return text
        return re.sub(r"s_[0-9a-f]{10}", lambda m: self.to_name.get(m.group(0), m.group(0)), text)


class _Context:
    """Everything one interpretation needs: lookups, the shown views and the ref maps."""

    def __init__(
        self,
        summary: InspectSummary,
        quarantine: Sequence[QuarantineEntry],
        sentence: QuarantineEntry | None,
        pseudonymiser: Any | None,
        rules: Sequence[DesignField] = (),
    ) -> None:
        self.summary = summary
        self.rules = list(rules)
        self._file_text: set[str] | None = None
        self.numbers_caught = 0
        self.entries: dict[str, QuarantineEntry] = {}
        for entry in quarantine:
            flags = sorted(set(entry.flags) | set(flags_for(entry.value)))
            self.entries.setdefault(entry.text_id, entry.model_copy(update={"flags": flags}))
        self.sentence = sentence
        if sentence is not None:
            self.entries[sentence.text_id] = sentence
        self.samples = {s.sample: s for s in summary.samples}
        self.targets = {t.target: t for t in summary.targets}
        self.experiments = {e: f"x{i}" for i, e in enumerate(sorted(summary.experiments), 1)}
        self.cells = {c.cell: c for c in summary.sheet}
        self.name_ids = {s.text_id for s in summary.samples} | {t.text_id for t in summary.targets}
        self.known_refs = {s.text_id for s in summary.samples}
        self.known_refs |= {t.text_id for t in summary.targets}
        self.known_refs |= {c.text_id for c in summary.sheet} | set(self.cells)
        self.known_refs |= set(self.entries)
        names = [self.name_of(s) for s in summary.samples] + [s.sample for s in summary.samples]
        names += [self.target_name(t) for t in summary.targets] + list(self.targets)
        self.shield = _Shield(pseudonymiser, names)
        self.rows, self.rows_by_sample, self.header_rows, self.other_rows = self._rows()
        # model-facing ref -> (real cites, text_ids behind them)
        self.sample_ref = {s.sample: self.shield.alias(s.text_id) for s in summary.samples}
        self.target_ref = {t.target: self.shield.alias(t.text_id) for t in summary.targets}
        self.by_sample_ref = {ref: s for s, ref in self.sample_ref.items()}
        self.by_target_ref = {ref: t for t, ref in self.target_ref.items()}
        self.by_experiment_ref = {ref: e for e, ref in self.experiments.items()}
        self.sentence_ref = self.shield.alias(sentence.text_id) if sentence else None

    # ---- names and flags --------------------------------------------------------------------

    def value(self, text_id: str) -> str | None:
        entry = self.entries.get(text_id)
        return entry.value if entry is not None else None

    def name_of(self, sample: InspectSample) -> str:
        return self.value(sample.text_id) or sample.sample

    def target_name(self, target: InspectTarget) -> str:
        return self.value(target.text_id) or target.target

    def instruction_like(self, text_id: str) -> bool:
        """Flagged file text (the scientist's sentence is the person's own words)."""
        entry = self.entries.get(text_id)
        if entry is None or entry.origin == SENTENCE_ORIGIN:
            return False
        return INSTRUCTION_LIKE in entry.flags

    # ---- the sample sheet, by row -------------------------------------------------------------

    def _rows(self) -> tuple[list[_Row], dict[str, list[_Row]], list[_Row], list[_Row]]:
        sheets: dict[str, int] = {}
        grouped: dict[tuple[int, int], list[SheetCell]] = {}
        for cell in self.summary.sheet:
            title = cell.cell.rsplit("!", 1)[0]
            index = sheets.setdefault(title, len(sheets) + 1)
            grouped.setdefault((index, cell.row), []).append(cell)
        exact: dict[str, str] = {}
        loose: dict[str, set[str]] = {}
        for sample in self.summary.samples:
            for name in (self.name_of(sample), sample.sample):
                exact.setdefault(name.strip(), sample.sample)
                loose.setdefault(squash(name), set()).add(sample.sample)
        rows, by_sample = [], {}
        first_data: dict[int, int] = {}
        matched: dict[tuple[int, int], str] = {}
        for (sheet, row), cells in sorted(grouped.items()):
            cells = sorted(cells, key=lambda c: c.column)
            joined = "\x00".join(c.text_id for c in cells)
            digest = hashlib.sha256(f"studio:sheet_row\x00{joined}".encode()).hexdigest()
            item = _Row(self.shield.alias(f"t_{digest[:12]}"), sheet, row, cells)
            rows.append(item)
            for cell in cells:
                text = (self.value(cell.text_id) or "").strip()
                hit = exact.get(text)
                if hit is None and len(loose.get(squash(text), ())) == 1 and squash(text):
                    hit = next(iter(loose[squash(text)]))
                if hit is not None:
                    matched[(sheet, row)] = hit
                    self.name_ids.add(cell.text_id)  # the sheet's copy of the name
                    by_sample.setdefault(hit, []).append(item)
                    first_data.setdefault(sheet, row)
                    break
        header = [
            r
            for r in rows
            if (r.sheet, r.row) not in matched and r.row < first_data.get(r.sheet, 0)
        ][:HEADER_ROWS]
        other = [r for r in rows if (r.sheet, r.row) not in matched and r not in header]
        return rows, by_sample, header, other[:OTHER_ROWS]

    def row_text_ids(self, row: _Row) -> list[str]:
        return [c.text_id for c in row.cells]

    def row_flags(self, row: _Row) -> list[str]:
        flags: set[str] = set()
        for cell in row.cells:
            entry = self.entries.get(cell.text_id)
            if entry is not None:
                flags |= set(entry.flags)
        return sorted(flags)

    @property
    def file_text(self) -> set[str]:
        """Lower-cased file text of four characters or more (reasons may not copy it)."""
        if self._file_text is None:
            self._file_text = {
                e.value.lower()
                for e in self.entries.values()
                if e.origin != SENTENCE_ORIGIN and len(e.value.strip()) >= 4
            }
        return self._file_text

    def cell_shown(self, cell: SheetCell) -> str:
        """One cell as the model sees it (withheld, or with names pseudonymised)."""
        if self.instruction_like(cell.text_id):
            return WITHHELD
        return self.shield.scrub(self.value(cell.text_id) or "")

    def row_value(self, row: _Row) -> str:
        """The row as the model sees it: column number -> value."""
        return json.dumps(
            {str(c.column): self.cell_shown(c) for c in row.cells}, ensure_ascii=False
        )

    def sample_record(self, sample: InspectSample) -> str:
        """The sample's name and its sheet row(s), as one quoted value."""
        if self.instruction_like(sample.text_id):
            name = WITHHELD
        elif self.shield.active:
            name = self.shield.token(self.name_of(sample))
        else:
            name = self.name_of(sample)
        record: dict[str, Any] = {"name": name}
        rows = [
            {str(c.column): self.cell_shown(c) for c in row.cells}
            for row in self.rows_by_sample.get(sample.sample, [])
        ]
        if rows:
            record["sheet_row"] = rows[0] if len(rows) == 1 else rows
        return json.dumps(record, ensure_ascii=False)

    def sample_cells(self, sample: InspectSample) -> list[SheetCell]:
        return [c for row in self.rows_by_sample.get(sample.sample, []) for c in row.cells]

    def sample_flags(self, sample: InspectSample) -> list[str]:
        flags = set(self.entries[sample.text_id].flags) if sample.text_id in self.entries else set()
        for cell in self.sample_cells(sample):
            entry = self.entries.get(cell.text_id)
            if entry is not None:
                flags |= set(entry.flags)
        return sorted(flags)


# ---------------------------------------------------------------------------------------------
# Building one call
# ---------------------------------------------------------------------------------------------


def _parts(ctx: _Context) -> list[_Part]:
    """The calls: one when the file is small; else target chunks, then sample chunks.

    The first call (``study``) also carries the study-level kinds (comparison, preset), the
    sheet rows no sample claims and the study-level rule proposals.
    """
    samples = list(ctx.summary.samples)
    targets = list(ctx.summary.targets)
    if len(samples) <= SAMPLES_PER_CALL and len(targets) <= TARGETS_PER_CALL:
        return [_Part(samples, targets, INTERPRET_KINDS, study=True)]
    parts = []
    for start in range(0, max(len(targets), 1), TARGETS_PER_CALL):
        first = start == 0
        kinds = STUDY_KINDS if first else ("design.target_role", "design.gene_symbol")
        parts.append(_Part([], targets[start : start + TARGETS_PER_CALL], kinds, study=first))
    for start in range(0, len(samples), SAMPLES_PER_CALL):
        chunk = samples[start : start + SAMPLES_PER_CALL]
        parts.append(_Part(chunk, [], SAMPLE_KINDS, study=False))
    return parts


def _declared_view(ctx: _Context, label: str) -> str:
    parts = []
    for item in label.split(","):
        if "@" in item:
            role, target = item.split("@", 1)
            parts.append(f"{role}@{ctx.target_ref.get(target, 'a target')}")
        else:
            parts.append(item)
    return ",".join(parts)


def _rule_view(ctx: _Context, rules: Sequence[DesignField], part: _Part) -> list[dict]:
    """The rule fields that concern this call, with refs instead of names."""
    in_part = {s.sample for s in part.samples}
    targets = {t.target for t in part.targets}
    shown = []
    for i, item in enumerate(rules, 1):
        subject: str | None = None
        value: Any = item.value
        if item.kind in ("design.well_role", "design.group", "design.bio_unit"):
            if item.subject not in in_part:
                continue
            subject = ctx.sample_ref[item.subject]
        elif item.kind == "design.dilution_series":
            members = dict(item.value.get("samples") or {})
            if not set(members) & in_part:
                continue
            subject = f"series_{i}"
            value = {
                "experiment_id": ctx.experiments.get(str(item.value.get("experiment_id")), ""),
                "samples": {ctx.sample_ref.get(s, "another sample"): q for s, q in members.items()},
            }
        elif item.kind in ("design.target_role", "design.gene_symbol"):
            if item.subject not in targets:
                continue
            subject = ctx.target_ref[item.subject]
        elif part.study:
            subject = item.subject if item.subject in ("comparison", "design") else None
        if subject is None:
            continue
        if ctx.shield.active and item.kind in (
            "design.group",
            "design.bio_unit",
            "design.gene_symbol",
            "design.comparison",
        ):
            value = {k: ctx.shield.token(str(v)) for k, v in item.value.items()}
        shown.append({"kind": item.kind, "subject": subject, "value": value, "level": item.level})
    return shown


def _prompt(ctx: _Context, part: _Part, rules: Sequence[DesignField]) -> tuple[str, set[str]]:
    """The user message for one call, and the refs the model may cite in it."""
    shown: list[QuarantineEntry] = []
    sample_views = []
    for sample in part.samples:
        ref = ctx.sample_ref[sample.sample]
        shown.append(
            QuarantineEntry(
                text_id=ref,
                origin="sample record",
                value=ctx.sample_record(sample),
                flags=ctx.sample_flags(sample),
            )
        )
        sample_views.append(
            {
                "ref": ref,
                "declared_type": _declared_view(ctx, sample.declared_type),
                "wells": sample.n_wells,
                "experiments": [ctx.experiments.get(e, "") for e in sample.experiments],
            }
        )
    target_views = []
    for target in part.targets:
        entry = ctx.entries.get(target.text_id)
        name = ctx.target_name(target)
        shown.append(
            QuarantineEntry(
                text_id=ctx.target_ref[target.target],
                origin="target name",
                value=WITHHELD if ctx.instruction_like(target.text_id) else ctx.shield.token(name),
                flags=list(entry.flags) if entry is not None else [],
            )
        )
        target_views.append(
            {
                "ref": ctx.target_ref[target.target],
                "declared_type": target.declared_type,
                "wells": target.n_wells,
                "wells_with_cq": target.n_with_cq,
                "efficiency_median": target.eff_median,
            }
        )
    rows: list[_Row] = list(ctx.header_rows)
    if part.study:
        rows += [r for r in ctx.other_rows if r not in rows]
    part.rows = rows
    row_entries = [
        QuarantineEntry(
            text_id=r.handle,
            origin="sample sheet row",
            value=ctx.row_value(r),
            flags=ctx.row_flags(r),
        )
        for r in rows
    ]
    view: dict[str, Any] = {
        "study": {
            "samples": ctx.summary.n_samples,
            "declared_types": {
                _declared_view(ctx, k): v for k, v in sorted(ctx.summary.declared_types.items())
            },
            "experiments": [
                {"ref": ref, "runs": ctx.summary.experiments[e]}
                for e, ref in ctx.experiments.items()
            ],
            "targets": len(ctx.summary.targets),
            "sheet_header_rows": [r.handle for r in ctx.header_rows],
            "sentence_ref": ctx.sentence_ref,
        },
        "allowed_kinds": list(part.kinds),
    }
    if target_views:
        view["targets"] = target_views
    if part.study and ctx.other_rows:
        view["other_sheet_rows"] = [r.handle for r in ctx.other_rows]
    if sample_views:
        view["samples"] = sample_views
    view["rule_proposals"] = _rule_view(ctx, rules, part)
    blocks = [as_quoted(shown, max_chars=ROW_CHARS)] if shown else []
    if row_entries:
        blocks.append(as_quoted(row_entries, max_chars=ROW_CHARS))
    if ctx.sentence is not None:
        sentence = ctx.sentence.model_copy(
            update={
                "text_id": ctx.sentence_ref,
                "origin": "the scientist's sentence",
                "value": ctx.shield.scrub(ctx.sentence.value),
            }
        )
        blocks.append(as_quoted([sentence], max_chars=MAX_SENTENCE_CHARS))
    content = (
        "Study summary (JSON):\n"
        + json.dumps(view, ensure_ascii=False, separators=(",", ":"))
        + "\n\nQuoted data (sample records, target names, sheet rows, the scientist's sentence):\n"
        + "\n".join(b for b in blocks if b)
    )
    citable = {e.text_id for e in shown} | {r.handle for r in rows}
    if ctx.sentence_ref:
        citable.add(ctx.sentence_ref)
    return content, citable


# ---------------------------------------------------------------------------------------------
# Checking the model's reply
# ---------------------------------------------------------------------------------------------


@dataclass
class _Cited:
    """What a field's cites resolve to."""

    refs: list[str]  # real text_ids and sheet cells, in order
    text_ids: set[str]  # the quarantined text behind them
    shown: set[str]  # the model-facing refs, as given


def _resolve_cites(ctx: _Context, part: _Part, cites: list[str], citable: set[str]):
    if not cites:
        return None, "cites nothing; every field cites the quoted data it reads"
    if len(cites) > MAX_CITES:
        return None, f"cites more than {MAX_CITES} refs"
    rows = {r.handle: r for r in part.rows}
    resolved = _Cited([], set(), set())
    for raw in cites:
        ref = str(raw).strip()
        if ref not in citable:
            return None, f"cites {ref[:40]!r}, which is not a ref of the quoted data shown"
        resolved.shown.add(ref)
        if ref in rows:
            cells = rows[ref].cells
        elif ref in ctx.by_sample_ref:
            sample = ctx.samples[ctx.by_sample_ref[ref]]
            resolved.refs.append(sample.text_id)
            resolved.text_ids.add(sample.text_id)
            cells = ctx.sample_cells(sample)
        elif ref in ctx.by_target_ref:
            resolved.refs.append(ctx.targets[ctx.by_target_ref[ref]].text_id)
            cells = []
        elif ref == ctx.sentence_ref and ctx.sentence is not None:
            resolved.refs.append(ctx.sentence.text_id)
            cells = []
        else:
            return None, f"cites {ref[:40]!r}, which qPilot cannot find"
        resolved.refs += [c.cell for c in cells]
        resolved.text_ids |= {c.text_id for c in cells}
    resolved.text_ids |= {r for r in resolved.refs if TEXT_ID.match(r)}
    missing = [r for r in resolved.refs if r not in ctx.known_refs]
    if missing:
        return None, f"cites {missing[0][:40]!r}, which qPilot cannot find"
    if any(ctx.instruction_like(t) for t in resolved.text_ids):
        return None, "cites text that reads like instructions; qPilot never acts on it"
    resolved.refs = list(dict.fromkeys(resolved.refs))
    return resolved, None


def _sample(ctx: _Context, part: _Part, subject: str) -> InspectSample | None:
    in_part = {s.sample for s in part.samples}
    found = ctx.by_sample_ref.get(subject)
    if found is None and not ctx.shield.active and subject in ctx.samples:
        found = subject  # a local model may name the sample by its id
    if found is None and ctx.shield.active and PSEUDONYM_TOKEN.match(subject):
        name = ctx.shield.to_name.get(subject)
        found = next((s.sample for s in ctx.summary.samples if ctx.name_of(s) == name), None)
    return ctx.samples[found] if found in in_part else None


def _target(ctx: _Context, part: _Part, subject: str) -> InspectTarget | None:
    in_part = {t.target for t in part.targets}
    found = ctx.by_target_ref.get(subject)
    if found is None and not ctx.shield.active and subject in ctx.targets:
        found = subject
    return ctx.targets[found] if found in in_part else None


def _own_cited(ctx: _Context, sample: InspectSample, cited: _Cited) -> bool:
    """Whether a field cites the sample's own record (its name or its sheet row)."""
    if sample.text_id in cited.text_ids:
        return True
    own = {c.text_id for c in ctx.sample_cells(sample)}
    return bool(own & cited.text_ids)


def _grounded(
    ctx: _Context, label: str, cited: _Cited, sample: InspectSample | None = None
) -> bool:
    """Whether ``label`` appears in a sheet cell or the sentence the field cites.

    Sample and target names do not count: a group or unit read off a name pattern is exactly
    what the rules leave to a person. For one sample's group or unit the cell must be in that
    sample's own sheet row, or the sentence must name the sample as well as the label.
    """
    key = squash(label)
    if not key:
        return False
    own = {c.text_id for c in ctx.sample_cells(sample)} if sample is not None else None
    for text_id in cited.text_ids - ctx.name_ids:
        value = ctx.value(text_id)
        if value is None or key not in squash(value):
            continue
        if sample is None or text_id in own:
            return True
        if ctx.sentence is not None and text_id == ctx.sentence.text_id:
            for name in {ctx.name_of(sample), sample.sample}:
                pattern = rf"(?<![{_WORD}]){re.escape(name.lower())}(?![{_WORD}])"
                if name and re.search(pattern, value.lower()):
                    return True
    return False


def _label(
    ctx: _Context, raw: Any, cited: _Cited, what: str, sample: InspectSample | None = None
) -> tuple[str | None, str | None]:
    if not isinstance(raw, str):
        return None, f"{what} must be text"
    label = _safe_label(ctx.shield.unscrub(raw))
    if label is None:
        return None, f"{what} is not a usable label"
    if not _grounded(ctx, label, cited, sample):
        if sample is None:
            return None, f"{what} is not found in the sheet cells or sentence the field cites"
        return None, f"{what} is not found in the sample's sheet row or a sentence naming it"
    return label, None


def _shape(value: Any, keys: set[str]) -> str | None:
    if not isinstance(value, dict) or set(value) != keys:
        return f"value must have exactly the keys {sorted(keys)}"
    return None


def _check_value(
    ctx: _Context,
    part: _Part,
    kind: str,
    subject: str,
    value: Any,
    cited: _Cited,
) -> tuple[str | None, dict[str, Any] | None, str | None]:
    """(real subject, real value, None) or (None, None, why it is refused)."""
    if kind in ("design.well_role", "design.group", "design.bio_unit"):
        sample = _sample(ctx, part, subject)
        if sample is None:
            return None, None, "subject is not a sample shown in this call"
        if ctx.instruction_like(sample.text_id):
            return None, None, "the sample's name reads like instructions; only people type it"
        if not _own_cited(ctx, sample, cited):
            return None, None, "a field about a sample must cite its own name or sheet row"
        key = {"design.well_role": "role", "design.group": "group"}.get(kind, "biological_unit")
        problem = _shape(value, {key})
        if problem:
            return None, None, problem
        if kind == "design.well_role":
            role = value["role"]
            if role not in WELL_ROLES:
                return None, None, f"role must be one of {', '.join(WELL_ROLES)}"
            if declared_control(sample) and role not in CONTROL_ROLES:
                return None, None, "ban: a control declared in the file is never given another role"
            return sample.sample, {"role": role}, None
        if declared_control(sample):
            return None, None, "a control declared in the file belongs to no group or unit"
        label, problem = _label(ctx, value[key], cited, key, sample)
        if problem:
            return None, None, problem
        if label.lower() in WELL_ROLES:
            return None, None, f"{label} is a role code, not a {key}; roles are design.well_role"
        return sample.sample, {key: label}, None
    if kind in ("design.target_role", "design.gene_symbol"):
        target = _target(ctx, part, subject)
        if target is None:
            return None, None, "subject is not a target shown in this call"
        if ctx.instruction_like(target.text_id):
            return None, None, "the target's name reads like instructions; only people type it"
        if target.text_id not in cited.text_ids:
            return None, None, "a field about a target must cite its name"
        if kind == "design.target_role":
            problem = _shape(value, {"role"})
            if problem or value["role"] not in ("ref", "toi"):
                return None, None, problem or "role must be ref or toi"
            return target.target, {"role": value["role"]}, None
        problem = _shape(value, {"symbol"})
        if problem:
            return None, None, problem
        symbol = value["symbol"]
        why = _symbol_problem(symbol)
        if why:
            return None, None, why
        return target.target, {"symbol": symbol}, None
    if kind == "design.comparison":
        if subject != "comparison":
            return None, None, 'the subject of a comparison is "comparison"'
        problem = _shape(value, {"group_a", "group_b"})
        if problem:
            return None, None, problem
        a, problem = _label(ctx, value["group_a"], cited, "group_a")
        if problem:
            return None, None, problem
        b, problem = _label(ctx, value["group_b"], cited, "group_b")
        if problem:
            return None, None, problem
        if a == b:
            return None, None, "group_a and group_b are the same group"
        return "comparison", {"group_a": a, "group_b": b}, None
    if kind == "design.preset":
        from qpilot.qpcr.designs import PRESETS  # the engine's own list of presets

        problem = _shape(value, {"preset"})
        if problem or subject != "design" or value["preset"] not in PRESETS:
            return None, None, problem or 'unknown preset, or the subject is not "design"'
        return "design", {"preset": value["preset"]}, None
    if kind == "design.dilution_series":
        return _check_series(ctx, part, subject, value, cited)
    return None, None, f"kind {kind} is not allowed"


def _symbol_problem(symbol: Any) -> str | None:
    if not isinstance(symbol, str) or not _SYMBOL.match(symbol):
        return "symbol must be an HGNC symbol"
    try:
        from qpilot.io.symbols import check_symbol  # the shipped HGNC table, when present
    except ImportError:
        return None
    finding = check_symbol(symbol)
    if getattr(finding, "status", None) != "approved" or getattr(finding, "case_changed", False):
        return "symbol is not an approved HGNC symbol"
    return None


def _check_series(ctx: _Context, part: _Part, subject: str, value: Any, cited: _Cited):
    problem = _shape(value, {"experiment_id", "samples"})
    if problem:
        return None, None, problem
    shown = re.fullmatch(r"series_(\d+)", str(subject))
    if shown and 0 < int(shown.group(1)) <= len(ctx.rules):
        name = ctx.rules[int(shown.group(1)) - 1].subject  # a rule's series, by its shown handle
    else:
        name = _safe_label(ctx.shield.unscrub(str(subject)))
    if name is None:
        return None, None, "the series needs a short name"
    experiment = ctx.by_experiment_ref.get(str(value["experiment_id"]))
    if experiment is None and not ctx.shield.active and value["experiment_id"] in ctx.experiments:
        experiment = value["experiment_id"]
    if experiment is None:
        return None, None, "experiment_id is not an experiment ref of the summary"
    members = value["samples"]
    if not isinstance(members, dict) or not members:
        return None, None, "samples must map sample refs to quantities"
    out: dict[str, float] = {}
    for ref, quantity in members.items():
        sample = _sample(ctx, part, str(ref))
        if sample is None:
            return None, None, "a series member is not a sample shown in this call"
        if declared_control(sample):
            return None, None, "ban: a control declared in the file cannot join a series"
        if ctx.instruction_like(sample.text_id):
            return None, None, "a member's name reads like instructions; only people type it"
        if sample.experiments and experiment not in sample.experiments:
            return None, None, "a series member is not in that experiment"
        number = _number(quantity)
        if number is None:
            return None, None, "every quantity must be a positive number"
        out[sample.sample] = number
    if len(set(out.values())) < MIN_SERIES_LEVELS:
        return None, None, f"a series needs at least {MIN_SERIES_LEVELS} different quantities"
    if not any(_own_cited(ctx, ctx.samples[s], cited) for s in out):
        return None, None, "a series must cite the name or sheet row of a member"
    ordered = dict(sorted(out.items(), key=lambda kv: (kv[1], kv[0])))
    return name, {"experiment_id": experiment, "samples": ordered}, None


def _reasons(ctx: _Context, reasons: list[str]) -> list[str]:
    """The model's reasons that qPilot can show; the rest are dropped."""
    file_text = ctx.file_text
    kept = []
    for reason in reasons[: MAX_REASONS * 2]:
        text = " ".join(str(reason).split())
        if not text or len(text) > MAX_REASON_CHARS:
            continue
        if not validate(text, {}).ok:
            ctx.numbers_caught += 1  # an invented number, caught before anyone sees it
            continue
        if INSTRUCTION_LIKE in flags_for(text):
            continue
        lowered = text.lower()
        if any(value in lowered for value in file_text):
            continue
        kept.append(text)
        if len(kept) == MAX_REASONS:
            break
    return kept or [NO_REASON]


def _alternatives(ctx, part, kind, subject, alternatives, cited) -> list[dict[str, Any]]:
    kept: list[dict[str, Any]] = []
    for alternative in alternatives[:MAX_ALTERNATIVES]:
        _, value, problem = _check_value(ctx, part, kind, subject, alternative, cited)
        if problem is None and value is not None and value not in kept:
            kept.append(value)
    return kept


def _check_field(
    ctx: _Context, part: _Part, raw: Any, citable: set[str]
) -> tuple[DesignField | None, str]:
    """A model field mapped to real ids, or None and why it is refused."""
    try:
        item = DesignField.model_validate(raw)
    except ValidationError as err:
        where = ".".join(str(x) for x in err.errors()[0].get("loc", ())) or "field"
        return None, f"not a valid field ({where}: {err.errors()[0].get('msg', 'invalid')})"
    if item.kind not in part.kinds:
        if not item.kind.startswith("design."):
            return None, f"{item.kind}: the interpreter proposes design kinds only"
        return None, f"{item.kind} is not allowed in this call"
    cited, problem = _resolve_cites(ctx, part, [str(c) for c in item.cites], citable)
    if problem:
        return None, problem
    subject, value, problem = _check_value(
        ctx, part, item.kind, str(item.subject), item.value, cited
    )
    if problem:
        return None, problem
    alternatives = _alternatives(ctx, part, item.kind, str(item.subject), item.alternatives, cited)
    alternatives = [a for a in alternatives if a != value]
    return (
        DesignField(
            kind=item.kind,
            subject=subject,
            value=value,
            cites=cited.refs,
            alternatives=alternatives,
            level=item.level,
            reasons=_reasons(ctx, [str(r) for r in item.reasons]),
        ),
        "",
    )


def _fields_of(text: str) -> list[Any] | None:
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, RecursionError):
        return None
    if not isinstance(data, dict) or not isinstance(data.get("fields"), list):
        return None
    return data["fields"]


def _parse(text: str) -> tuple[list[Any] | None, bool]:
    """The reply's fields, and whether it was cut off (only its complete fields are read).

    A reply that hit the token limit is read up to its last complete field; every field read
    is still checked like any other, and the reply counts as a problem (so it is retried).
    """
    start = (text or "").find("{")
    if start < 0:
        return None, False
    match = re.search(r"\{.*\}", text[start:], re.S)
    if match:
        fields = _fields_of(match.group(0))
        if fields is not None:
            return fields, False
    body = text[start:]
    for cut in reversed([m.start() for m in re.finditer(r"\}\s*,\s*\{", body)]):
        fields = _fields_of(body[: cut + 1] + "]}")
        if fields is not None:
            return fields, True
    return None, False


def _check_reply(ctx, part, text, citable, attempt, index, rejected):
    """(accepted fields, problems, parsed?) for one reply."""
    raws, cut_off = _parse(text)
    if raws is None:
        return [], ['the reply is not JSON of the form {"fields": [...]}'], False
    if len(raws) > MAX_FIELDS:
        return [], [f"more than {MAX_FIELDS} fields"], False
    accepted: list[DesignField] = []
    problems = ["the reply was cut off at the length limit; send fewer fields"] if cut_off else []
    for position, raw in enumerate(raws, 1):
        checked, why = _check_field(ctx, part, raw, citable)
        if checked is not None:
            accepted.append(checked)
            continue
        kind = raw.get("kind") if isinstance(raw, dict) else None
        subject = raw.get("subject") if isinstance(raw, dict) else None
        rejected.append(
            {
                "part": index,
                "attempt": attempt,
                "field": position,
                "kind": str(kind)[:40] if kind is not None else None,
                "subject": str(subject)[:64] if subject is not None else None,
                "reason": why,
            }
        )
        problems.append(f"field {position} ({str(kind)[:40]}): {why}")
    return accepted, problems, True


# ---------------------------------------------------------------------------------------------
# Merging
# ---------------------------------------------------------------------------------------------


def _same(a: DesignField, b: DesignField) -> bool:
    return a.kind == b.kind and a.subject == b.subject and a.value == b.value


def _merge(
    ctx: _Context, rules: Sequence[DesignField], model: list[DesignField], maker: MadeBy
) -> tuple[list[DesignField], list[MadeBy], int]:
    fields = [r.model_copy(deep=True) for r in rules]
    makers = [MadeBy(kind="rule") for _ in fields]
    ruled_roles = {r.subject for r in rules if r.kind == "design.well_role"}
    repeats = 0
    kept: list[DesignField] = []
    for item in model:
        twin = next((f for f in fields[: len(rules)] if _same(f, item)), None)
        if twin is not None:
            if SAME_READING not in twin.reasons:
                twin.reasons.append(SAME_READING)
            continue
        if item.kind == "design.well_role" and item.subject not in ruled_roles:
            declared = _single_declared(ctx.samples[item.subject])
            if declared == item.value["role"]:
                repeats += 1
                continue
        if any(k.kind == item.kind and k.subject == item.subject for k in kept):
            continue  # one model reading per kind and subject; the first one stands
        kept.append(item)
    return fields + kept, makers + [maker] * len(kept), repeats


# ---------------------------------------------------------------------------------------------
# The entry point
# ---------------------------------------------------------------------------------------------


def interpret(
    summary: InspectSummary,
    quarantine: Sequence[QuarantineEntry],
    sentence: str,
    client: ModelClient,
    *,
    rule_fields: Sequence[DesignField] = (),
    pseudonymiser: Any | None = None,
) -> InterpretResult:
    """Propose a study design from a file summary, its quoted text and the scientist's sentence.

    Args:
        summary: From ``qpilot.qpcr.inspect.inspect`` (ids, declared types, counts; no text).
        quarantine: The quarantined names and sheet cells the summary cites.
        sentence: One sentence from the scientist (may be empty); quarantined here with origin
            ``studio:sentence`` and returned in ``InterpretResult.quarantine``.
        client: The model client; a ``none`` client gives the rule fields alone.
        rule_fields: What the deterministic rules already propose (always kept unchanged).
        pseudonymiser: Required for a remote backend (``core.pseudonym.Pseudonymiser``).

    Returns:
        An :class:`InterpretResult`; nothing is stored or accepted.
    """
    entry = sentence_entry(sentence)
    rules = list(rule_fields)
    new_text = [entry] if entry is not None else []
    remote = client_is_remote(client) if client.available else False
    notes: list[str] = []

    def rules_only(error: str | None, where: str = "") -> InterpretResult:
        fields = [r.model_copy(deep=True) for r in rules]
        return InterpretResult(
            fields=fields,
            makers=[MadeBy(kind="rule") for _ in fields],
            fallback=True,
            validated=False,
            error=error,
            notes=[*notes, TYPE_YOUR_CONTROLS.format(where=where)],
            quarantine=new_text,
        )

    if not client.available:
        return rules_only(None)
    if remote and pseudonymiser is None:
        return rules_only("a remote model needs a pseudonymiser; nothing was sent")
    ctx = _Context(summary, quarantine, entry, pseudonymiser if remote else None, rules)
    if any(ctx.instruction_like(t) for t in ctx.entries):
        notes.append(
            "Some names or cells read like instructions to a model; they were withheld from the "
            "model and it may not propose anything that cites them."
        )
    maker = MadeBy(
        kind="model", provider=client.provider, model=client.model, prompt_sha256=PROMPT_SHA256
    )
    first_call = len(client.metas)
    calls: list[dict[str, Any]] = []
    model_fields: list[DesignField] = []
    rejected: list[dict[str, Any]] = []
    error: str | None = None
    used, failed, clean = 0, 0, True
    unavailable = False
    timeouts = 0
    for index, part in enumerate(_parts(ctx), 1):
        content, citable = _prompt(ctx, part, rules)
        messages = [{"role": "user", "content": content}]
        for attempt in (1, 2):
            try:
                text = client.complete(SYSTEM_INTERPRET, messages, max_tokens=MAX_TOKENS)
            except ModelUnavailable as err:
                error = str(err)
                calls.append(
                    {"part": index, "attempt": attempt, "response_bytes": 0, "validated": False}
                )
                slow = error.endswith("ReadTimeout")  # reachable, but this call was too slow
                timeouts += slow
                if slow and timeouts < MAX_READ_TIMEOUTS:
                    failed += 1  # this part gets the rules alone; the next part is tried
                else:
                    unavailable = True
                break
            accepted, problems, parsed = _check_reply(
                ctx, part, text, citable, attempt, index, rejected
            )
            calls.append(
                {
                    "part": index,
                    "attempt": attempt,
                    "response_bytes": len(text.encode("utf-8")),
                    "validated": parsed and not problems,
                }
            )
            if parsed and not problems:
                model_fields += accepted
                used += 1
                break
            error = "; ".join(problems[:10])
            if attempt == 2:
                if parsed and accepted:
                    model_fields += accepted
                    used += 1
                    clean = False
                else:
                    failed += 1
                break
            messages = [
                *messages,
                {"role": "assistant", "content": text},
                {
                    "role": "user",
                    "content": f"Rejected: {error}. Reply again with JSON only, following the "
                    "rules; leave out any field you cannot support from the quoted data.",
                },
            ]
        if unavailable:
            break
    metas = client.metas[first_call:]
    meta = [{**m, **c} for m, c in zip(metas, calls, strict=False)]
    if unavailable and used == 0:
        result = rules_only(error)
        return result.model_copy(update={"meta": meta, "prompt_sha256": PROMPT_SHA256})
    fields, makers, repeats = _merge(ctx, rules, model_fields, maker)
    if repeats:
        notes.append(
            "Some model readings only repeated the type the file declares and were left out."
        )
    fallback = unavailable or failed > 0 or used == 0
    if fallback:
        where = "" if used == 0 else " for part of the file"
        notes.append(TYPE_YOUR_CONTROLS.format(where=where))
    return InterpretResult(
        fields=fields,
        makers=makers,
        fallback=fallback,
        validated=used > 0 and clean and not fallback,
        error=error if (fallback or not clean or rejected) else None,
        notes=notes,
        rejected=rejected,
        meta=meta,
        prompt_sha256=PROMPT_SHA256,
        quarantine=new_text,
        numbers_caught=ctx.numbers_caught,
    )


def log_lines(result: InterpretResult, client: ModelClient) -> list[dict[str, Any]]:
    """One ``ai_calls.jsonl`` line per model call of an interpretation (the caller writes them)."""
    lines = []
    for i, meta in enumerate(result.meta, 1):
        last = i == len(result.meta)
        entry = payload_log.log_entry(
            "interpret",
            client.provider,
            client.model,
            meta,
            "",
            bool(meta.get("validated")),
            result.fallback if last else False,
        )
        entry |= {
            "call": i,
            "of": len(result.meta),
            "part": meta.get("part"),
            "attempt": meta.get("attempt"),
            "response_bytes": meta.get("response_bytes", 0),
            "prompt_sha256": result.prompt_sha256,
        }
        lines.append(entry)
    return lines


def fields_by_subject(result: InterpretResult) -> Mapping[str, list[tuple[DesignField, MadeBy]]]:
    """Every field and its maker, grouped by subject (for display and the harness)."""
    out: dict[str, list[tuple[DesignField, MadeBy]]] = {}
    for item, maker in result.tagged():
        out.setdefault(item.subject, []).append((item, maker))
    return out


__all__ = [
    "MAX_CITES",
    "PROMPT_SHA256",
    "SAME_READING",
    "SAMPLES_PER_CALL",
    "SENTENCE_ORIGIN",
    "InterpretResult",
    "client_is_remote",
    "declared_control",
    "fields_by_subject",
    "interpret",
    "log_lines",
    "sentence_entry",
    "squash",
]
