"""Independent oracles for the science review of October 2026 (``docs/science-review-2026-10.md``).

Each module recomputes one of qPilot's analyses from first principles with numpy, scipy and
statsmodels, written from the published method and never by calling qPilot's own arithmetic, so
that ``tests/science/`` can compare the two on real lab files from ``tests/fixtures/corpus/``.
The only qPilot code an oracle may use is a reader that turns a file into a per-well table (the
data, not a statistic); where even that matters, the oracle reads the file itself.
"""
