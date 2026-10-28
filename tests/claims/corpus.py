"""Tricky results sentences about the demo study, each with the verdict the record supports.

The study (Vermeulen 2013, 64 plates) compares neuroblastoma tumours by MYCN **expression**: the
top 15 % by MYCN expression (MYCN-high) against the rest. Its record: BIRC5 (survivin) and ODC1
up, NTRK1 (TrkA), CD44, DDC and MAPT down, NM23A up but not robust, CAMTA2 significant but under
the 2-fold line (no call), ARHGEF7 unchanged; the controls are ALUsq, HMBS, HPRT1, SDHA and UBC;
GAPDH and B2M were not measured. No value below is data: each sentence is the claim a reader
might write, and each verdict follows from the record (``tests/fixtures/results.json``).

``verdicts`` lists the verdict of each gene/normaliser/n claim in reading order. ``grid`` is
False when qPilot's choice grid may turn a verdict into "holds only under some choices" (the
real study has a grid; the fixture-only record has none). The other keys check how the sentence
was read: ``p`` names the gene the p-value belongs to, ``normaliser`` maps a gene to the control
genes its claim was read with (and ``scope`` to where they were read).
"""

from __future__ import annotations

from typing import Any

CORPUS: list[dict[str, Any]] = [
    # ---- groups the study does not compare (amplification is not high expression) ---------
    {
        "text": "Survivin was 4-fold higher in MYCN-amplified tumours (p < 0.001).",
        "verdicts": ["mismatch"],
        "p": "BIRC5",
        "why": "MYCN amplification is a genomic grouping; the study groups by MYCN expression",
    },
    {
        "text": "In MYCN-amplified tumours, ODC1 was up-regulated.",
        "verdicts": ["mismatch"],
    },
    {
        "text": "ODC1 was higher in tumours with MYCN amplification than in the others.",
        "verdicts": ["mismatch"],
    },
    {
        "text": "ODC1 was up-regulated in MYCN-non-amplified tumours.",
        "verdicts": ["mismatch"],
    },
    {
        "text": "BIRC5 was higher in MYCN-positive tumours.",
        "verdicts": ["mismatch"],
    },
    {
        "text": "BIRC5 was up-regulated in high-risk neuroblastoma.",
        "verdicts": ["mismatch"],
    },
    {
        "text": "NTRK1 was lower in stage 4 tumours.",
        "verdicts": ["mismatch"],
    },
    {
        "text": "CD44 was down-regulated in ALK-mutated tumours.",
        "verdicts": ["mismatch"],
    },
    {
        "text": "BIRC5 was higher in TP53-mutant tumours.",
        "verdicts": ["mismatch"],
    },
    {
        "text": "Survivin was 4-fold higher in MYCN-amplified tumours, and ODC1 was higher in "
        "MYCN-high tumours.",
        "verdicts": ["mismatch", "supported"],
        "why": "the grouping belongs to the claim whose words name it",
    },
    {
        "text": "ODC1 was 3-fold higher in KO mice than in WT mice.",
        "verdicts": ["mismatch"],
        "why": "a genotype comparison, where the study splits tumours by MYCN expression",
    },
    {
        "text": "ODC1 was up-regulated in BIRC5-high tumours.",
        "verdicts": ["mismatch"],
        "why": "grouped by another gene's expression",
    },
    {
        "text": "BIRC5 expression correlated with MYCN expression (p < 0.001).",
        "verdicts": ["unchecked"],
        "p": "BIRC5",
        "why": "the study compares groups and computes no correlation",
    },
    # ---- the study's own groups, however they are written ---------------------------------
    {
        "text": "Survivin was 4-fold higher in MYCN-high tumours (p < 0.001).",
        "verdicts": ["supported"],
        "p": "BIRC5",
    },
    {
        "text": "BIRC5 was higher in neuroblastoma tumours with high MYCN expression.",
        "verdicts": ["supported"],
    },
    {
        "text": "BIRC5 was higher in MYCN-high (MYCN-amplified) tumours.",
        "verdicts": ["supported"],
        "why": "the study's group is named; the other grouping is noted, not used",
    },
    {
        "text": "NTRK1 was lower in MYCN-high tumours than in the rest.",
        "verdicts": ["supported"],
    },
    {
        "text": "NTRK1 was higher in the rest than in MYCN-high tumours.",
        "verdicts": ["supported"],
        "why": "the words compare the second group with the first",
    },
    {
        "text": "NTRK1 was higher in MYCN-high tumours.",
        "verdicts": ["contradicted"],
        "grid": False,
    },
    # ---- p-values and folds with their own subject -----------------------------------------
    {
        "text": "Survivin was 4-fold higher in tumours expressing high levels of MYCN (p < 0.001).",
        "verdicts": ["supported"],
        "p": "BIRC5",
        "why": "MYCN here describes the tumours; the p-value is survivin's",
    },
    {
        "text": "ODC1 was up-regulated (p < 0.001), whereas NTRK1 was down-regulated "
        "(p < 0.001) in MYCN-high tumours.",
        "verdicts": ["supported", "supported"],
    },
    {
        "text": "TrkA was more than 5-fold lower in MYCN-high tumours (p < 0.001).",
        "verdicts": ["supported"],
        "p": "NTRK1",
    },
    {
        "text": "CD44 showed a 71 % decrease in MYCN-high tumours.",
        "verdicts": ["supported"],
    },
    {
        "text": "AHCY was up-regulated (log2 FC = 1.4) in MYCN-high tumours.",
        "verdicts": ["supported"],
    },
    {
        "text": "ODC1 was more than 10-fold higher in MYCN-high tumours.",
        "verdicts": ["overstated"],
        "grid": False,
    },
    {
        "text": "DDC and MAPT were both down-regulated in MYCN-high tumours.",
        "verdicts": ["supported", "supported"],
    },
    {
        "text": "ODC1 was higher in MYCN-high than in MYCN-low tumours (n = 53 vs 294).",
        "verdicts": ["supported", "supported"],
    },
    # ---- hedges, no-change and robustness words --------------------------------------------
    {
        "text": "CAMTA2 tended to be lower in MYCN-high tumours.",
        "verdicts": ["supported"],
        "why": "a hedge claims a direction, not a call",
    },
    {
        "text": "CAMTA2 was significantly down-regulated in MYCN-high tumours.",
        "verdicts": ["overstated"],
        "grid": False,
        "why": "significant, but under the 2-fold line: qPilot calls no change",
    },
    {
        "text": "ARHGEF7 did not differ between MYCN-high tumours and the rest.",
        "verdicts": ["supported"],
    },
    {
        "text": "NM23A was robustly up-regulated in MYCN-high tumours.",
        "verdicts": ["overstated"],
        "grid": False,
    },
    {
        "text": "BIRC5 was up-regulated in MYCN-high tumours (q < 0.05).",
        "verdicts": ["supported"],
        "why": "an adjusted p cannot be checked; the direction can",
    },
    # ---- genes the study cannot answer about -----------------------------------------------
    {
        "text": "GAPDH was unchanged between MYCN-high tumours and the rest.",
        "verdicts": ["unchecked"],
    },
    {
        "text": "HMBS was lower in MYCN-high tumours.",
        "verdicts": ["unchecked"],
    },
    # ---- where a normaliser sentence applies ----------------------------------------------
    {
        "text": "BIRC5 was higher in MYCN-high tumours. Expression was normalised to GAPDH and "
        "B2M.",
        "verdicts": ["supported", "contradicted"],
        "normaliser": {"BIRC5": ("GAPDH", "B2M")},
        "scope": {"BIRC5": "text"},
        "why": "stated for all the data: applies to every claim, and the claim says so",
    },
    {
        "text": "BIRC5 was higher in MYCN-high tumours. ODC1 was up-regulated in MYCN-high "
        "tumours. These values were normalised to HPRT1.",
        "verdicts": ["supported", "supported", "unchecked"],
        "normaliser": {"BIRC5": (), "ODC1": ("HPRT1",)},
        "scope": {"ODC1": "previous"},
        "why": "'These values' refers to the sentence before it only",
    },
    {
        "text": "ODC1 was up-regulated in MYCN-high tumours. Normalised to GAPDH.",
        "verdicts": ["supported", "contradicted"],
        "normaliser": {"ODC1": ("GAPDH",)},
        "scope": {"ODC1": "previous"},
    },
    {
        "text": "ODC1 values were normalised to HMBS. BIRC5 and ODC1 were higher in MYCN-high "
        "tumours.",
        "verdicts": ["unchecked", "supported", "supported"],
        "normaliser": {"ODC1": ("HMBS",), "BIRC5": ()},
        "scope": {"ODC1": "gene"},
        "why": "a sentence that names its gene applies to that gene only",
    },
    {
        "text": "Expression was normalised to HMBS. Expression was normalised to UBC. ODC1 was "
        "higher in MYCN-high tumours.",
        "verdicts": ["unchecked", "unchecked", "supported"],
        "normaliser": {"ODC1": ()},
        "why": "two sets stated for all the data: which one applies is not said",
    },
    {
        "text": "BIRC5 was higher in MYCN-high tumours (normalised to UBC), and ODC1 was "
        "up-regulated in MYCN-high tumours.",
        "verdicts": ["supported", "supported", "unchecked"],
        "normaliser": {"BIRC5": ("UBC(2)",), "ODC1": ()},
        "scope": {"BIRC5": "own"},
    },
]
