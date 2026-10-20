"""History: a study's decision chain replayed step by step, as a time machine.

The decision chain (``decisions.jsonl``) says who decided what and why; this package shows what
each decision *changed*. At every step the Decision Cards are replayed from the log alone
(:func:`qpilot.core.store.replay_cards`), the analysis in force is the cell of the study's own
robustness grid that those choices name (found by value, exactly as the Results views find it),
and the conclusions are read from that cell — never estimated. Step 0 is the study as analysed.

* :func:`history_view` — every step, the analysis in force, its calls, and the Studio log
  around the chain (for a study made in a Studio session).
* :func:`diff_steps` — what changed between any two steps.
* :func:`compare_studies` — two analyses of the same input file (before and after a Prism
  round trip, say): which conclusions differ, and whether the design or the choices did it.
"""

from qpilot.history.compare import compare_studies
from qpilot.history.replay import diff_steps, history_view

__all__ = ["compare_studies", "diff_steps", "history_view"]
