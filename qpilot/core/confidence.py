"""An ordinal confidence grade with every downgrade named: a verdict, never a probability.

Domain-agnostic, in the spirit of GRADE: start at a level, move down one level for each failed
check that is allowed to downgrade, and up at most one level when the plugin's upgrade rule
holds. There is no weighted sum and no percentage; the reasons are the failed checks' notes, so a
reader can see exactly why a result is not graded higher. Plugins supply the checks.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable

from qpilot.schemas import Check, Grade, Level

LEVELS: tuple[Level, ...] = ("High", "Moderate", "Low", "Very low")
DOWNGRADING_CHECKS: frozenset[str] = frozenset({"precision", "robustness", "normalisation"})

UpgradeRule = Callable[[list[Check]], bool]


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
    """
    rule = upgrade_rule or _never
    down = set(downgrading)
    failed = [c for c in checks if c.id in down and not c.passed]
    position = LEVELS.index(start) + len(failed)
    blocked = any(c.id == blocking and not c.passed for c in checks)
    if not blocked and rule(checks):
        position -= 1
    position = max(0, min(position, len(LEVELS) - 1))
    return Grade(
        level=LEVELS[position],
        reasons=[c.note for c in failed],
        checks=checks,
        min_flip_changes=min_flip_changes,
    )
