"""An ordinal confidence grade with every downgrade named: a verdict, never a probability.

Domain-agnostic, in the spirit of GRADE: start at a level, move down one level for each failed
check that is allowed to downgrade, and up at most one level when the plugin's upgrade rule
holds. There is no weighted sum and no percentage; the reasons are the failed checks' notes, so a
reader can see exactly why a result is not graded higher. Plugins supply the checks.

A plugin may also put a **cap** on a grade (:class:`Cap`): a ceiling with a named reason, for
something about the input that no check of the result can see (curves processed before they
reached the engine, an efficiency assumed rather than measured). A capped grade is never above
the cap's level, whatever the checks and the upgrade rule say; the cap is reported among the
checks (failed, under its own id), and its note is one of the reasons whenever it is what holds
the grade down.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass

from qpilot.schemas import Check, Grade, Level

LEVELS: tuple[Level, ...] = ("High", "Moderate", "Low", "Very low")
DOWNGRADING_CHECKS: frozenset[str] = frozenset({"precision", "robustness", "normalisation"})

UpgradeRule = Callable[[list[Check]], bool]


@dataclass(frozen=True)
class Cap:
    """The highest level a grade may have, and why, in a sentence a reader can act on.

    ``check_id`` names the cap among the grade's checks; it is never one of the downgrading
    checks (a cap is a ceiling, not one more level down).
    """

    level: Level
    check_id: str
    note: str


def _never(_: list[Check]) -> bool:
    return False


def grade(
    start: Level,
    checks: list[Check],
    upgrade_rule: UpgradeRule | None = None,
    *,
    downgrading: Iterable[str] = DOWNGRADING_CHECKS,
    blocking: str = "normalisation",
    min_flip_changes: int | None = None,
    cap: Cap | None = None,
) -> Grade:
    """Grade a result from named checks.

    Args:
        start: the level a result starts at before any check.
        checks: every check, reported and downgrading alike.
        upgrade_rule: returns True when the result earns one level up; ignored when the
            ``blocking`` check failed.
        downgrading: ids of the checks that move the level down by one each when failed.
        blocking: id of the check whose failure forbids an upgrade.
        min_flip_changes: fragility, reported on the grade and never counted as a downgrade.
        cap: the highest level the result may have (an upgrade never lifts it above). It is
            added to the checks as a failed check, and its note is a reason when the cap
            lowered the level.

    Raises:
        ValueError: The cap's id is the id of a downgrading check.
    """
    rule = upgrade_rule or _never
    down = set(downgrading)
    if cap is not None and cap.check_id in down:
        raise ValueError(f"cap {cap.check_id!r} has the id of a downgrading check")
    failed = [c for c in checks if c.id in down and not c.passed]
    position = LEVELS.index(start) + len(failed)
    blocked = any(c.id == blocking and not c.passed for c in checks)
    if not blocked and rule(checks):
        position -= 1
    position = max(0, min(position, len(LEVELS) - 1))
    reasons = [c.note for c in failed]
    if cap is not None:
        ceiling = LEVELS.index(cap.level)
        if position < ceiling:
            position = ceiling
            reasons.append(cap.note)
        checks = [*checks, Check(id=cap.check_id, passed=False, note=cap.note)]
    return Grade(
        level=LEVELS[position],
        reasons=reasons,
        checks=checks,
        min_flip_changes=min_flip_changes,
    )
