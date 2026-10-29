"""Time budgets that hold on a loaded machine.

A test that says "this takes under two seconds" means the work is not too slow: not that the
laptop had a core free while it ran. Wall-clock time measures the second; on a shared machine
(other test runs, a browser, a build) it can be several times the work. :func:`work_time`
measures both the process's CPU time (``time.process_time``: every thread of this process, not
other processes) and the wall-clock time, and its ``seconds`` is the smaller of the two:

* on a busy machine the CPU time stays what the work costs while the wall clock stretches;
* when the work runs on several threads at once (numpy, a server thread and its job pool) the
  CPU time adds them up while the wall clock does not.

A slower algorithm (a quadratic loop, a cache that is not used, a curve analysis that should not
run) raises both, so a budget on ``seconds`` still catches it. Waiting (a sleep, a lock, a
socket) costs no CPU time: a test of "this does not wait" must keep the wall clock.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass


@dataclass
class WorkTime:
    """What one block of work cost: CPU seconds of this process and wall-clock seconds."""

    cpu: float = 0.0
    wall: float = 0.0

    @property
    def seconds(self) -> float:
        """The work's time on an idle machine, as far as can be told (see the module)."""
        return min(self.cpu, self.wall)

    def __repr__(self) -> str:
        return f"{self.seconds:.2f} s (cpu {self.cpu:.2f} s, wall {self.wall:.2f} s)"


@contextmanager
def work_time() -> Iterator[WorkTime]:
    """``with work_time() as t: ...`` then ``assert t.seconds < budget, t``."""
    spent = WorkTime()
    cpu, wall = time.process_time(), time.perf_counter()
    try:
        yield spent
    finally:
        spent.cpu = time.process_time() - cpu
        spent.wall = time.perf_counter() - wall
