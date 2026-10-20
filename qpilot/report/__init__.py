"""The study report: Methods, the MIQE 2.0 checklist, a reviewer's report and a passport.

Everything here reads a study from the store (and its audit, when one was run) and writes
**facts, never typed numbers**: every number in a sentence is a fact token bound to the engine's
result, the store or the audit (:mod:`qpilot.report.text`), and a sentence that would show a
number from nowhere is a bug that raises, never output. Strings from the study's files (gene,
sample and option names, a person's reasons) travel as quoted data and every renderer escapes them.

Modules: :mod:`~qpilot.report.inputs` (what the store holds about one study),
:mod:`~qpilot.report.text` (facts and fact-bound text), :mod:`~qpilot.report.methods`,
:mod:`~qpilot.report.miqe`, :mod:`~qpilot.report.review`, :mod:`~qpilot.report.build` (the
report as data, cached), :mod:`~qpilot.report.render` (Markdown and printable HTML) and
:mod:`~qpilot.report.passport` (one self-contained offline HTML file with inline SVG charts).

Ported from the work in progress on branch ``agents/report`` (the fact registry, the MIQE 2.0
item map and its resolvers, the RDML metadata reader and the reviewer's rule list), re-tested and
re-pointed at the live store instead of an exported record.
"""
