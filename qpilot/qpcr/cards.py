"""The qPCR plugin's Decision Card kinds, registered whenever ``qpilot.qpcr`` is imported.

Light on purpose (it imports only the core registry), and imported by ``qpilot/qpcr/__init__.py``,
so every process that touches the plugin (CLI, MCP server, Studio, a record re-run) knows the same
kinds and so applies the same escalation rule to the same card. A kind a process does not know is
treated as human-only (``core/card_kinds.py``); registering here keeps that from depending on which
module happened to be imported first.

Owners add their kind here (one line each) instead of registering it again elsewhere: registering
one name twice with different titles is an error. The original four kinds (``reference_set``,
``group_cutoff``, ``undetermined``, ``amp_call``) and gate's ``gate.*`` kinds are registered in
the core.
"""

from __future__ import annotations

from qpilot.core.card_kinds import register_card_kind

# numbers (agents/numbers): the efficiency-model axis of the decision space.
register_card_kind(
    "numbers.efficiency_model",
    "Which efficiency turns Cq into quantity",
    "numbers",
    dimension="efficiency",
)
# norm (ex/norm): the normaliser axis (NormFinder's / geNorm's best pair, the global mean) and
# the correction between plates (inter-run calibrator, factor correction).
register_card_kind(
    "numbers.normaliser",
    "What to normalise each gene to",
    "numbers",
    dimension="normaliser",
)
register_card_kind(
    "numbers.interrun",
    "How to correct differences between plates",
    "numbers",
    dimension="interrun",
)
# capture (agents/capture): the Import Trust Card. Its options have no grid dimension, so the
# consequence cannot be measured: every card of the kind is a human decision.
register_card_kind(
    "capture.import_trust",
    "Whether the imported curves can be analysed as they are",
    "capture",
    always_human=True,
)
# quantonly (ex/quantonly): a study whose purpose is to quantify samples (qpcr/quantify_study.py).
# Each card is a choice that can change what is reported for a sample (its class: quantified,
# below the LOQ or the LOD, not detected; or its number by more than 2-fold).
register_card_kind(
    "quantity.amp_call",
    "Which wells count as detected, for the quantities",
    "quantity",
    dimension="amp_call",
)
register_card_kind(
    "quantity.loq_cv",
    "How precise a quantity must be to be reported",
    "quantity",
    dimension="loq_cv",
)
