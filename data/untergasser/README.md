# Untergasser validation data

Copied unchanged from the RDML consortium repository, `experiments/untergasser/`
(https://github.com/RDML-consortium/rdmlpython/tree/main/experiments/untergasser), where the
data were created by Andreas Untergasser with Maurice van der Hoff (AMC, Amsterdam) and
Vladimir Benes (EMBL, Heidelberg). Licence: that of the rdmlpython repository (MIT).

Used by `qsim validate`: the "DNA Dilution - AMC" experiment in `amplicon_primer_mix.rdml`
(human genomic DNA at 20, 7, 2, 0.7, 0.2 and 0 ng in triplicate, 16 primer pairs, LightCycler 480,
Roche SYBR, SensiFast and LC Green mixes). The true fold change between two DNA amounts is their
ratio. `dna_dilution_amc_curves.csv` is qPilot's LinRegPCR output for that experiment.
