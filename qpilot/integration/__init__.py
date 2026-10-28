"""qPilot integration: the whole qPCR workflow, end to end, as one pipeline.

This package joins the parts that were built separately, without changing any of them:

* **qPilot engine** (``qpilot.qpcr``): LinRegPCR on every raw curve, geNorm, the conclusion rule,
  the robustness grid and the Decision Cards.
* **qPilot Studio** (``qpilot.studio_service``): intake, the Design Interpreter and the Curve
  Judge in blind stages, the analysis choices, the Prism draft, Send to Prism and the round
  trip. The AI proposes, the engine checks, a person decides.
* **Decision Simulator** (``qsim``, a separate package): the robustness audit of the analysis a
  person confirmed. Every combination of the audit's analysis decisions, per-gene verdicts, the
  samples a call leans on, the fewest moves that change a call, what to lock in advance.
* **Analysis Record** (``qpilot.core.record``) and the **MCP server** (``qpilot.mcp_server``).

Modules:

* :mod:`qpilot.integration.simulator`: the adapter that runs the simulator on a stored study,
  refuses when it would not reproduce qPilot's numbers, and binds the audit to the study.
* :mod:`qpilot.integration.workflow`: the pipeline itself, stage by stage, with every person's
  action passed in explicitly (``actor="human"``) and logged.
* :mod:`qpilot.integration.mcp_tools`: read-only simulator tools for agents, added to the
  existing MCP server.

Run ``python -m qpilot.integration --help``. Research use only.
"""
