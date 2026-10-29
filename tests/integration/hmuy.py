"""A real plate with technical replicates: P. endodontalis hmuY RT-qPCR, LightCycler 96.

Śmiga M, Olczak T (2025), Zenodo doi:10.5281/zenodo.14965510 (CC BY 4.0; the corpus set
``rdml/lightcycler96-lc96p-hmuy``): bacteria grown in heme (Hm) or after a passage with the iron
chelator 2,2'-dipyridyl (DIP), three biological replicates each, hmuY and 16S rRNA in triplicate
wells (36 study wells on one 96-well run). qPilot names the file's samples
from their ``<description>`` in the RDML (Hm_1 ... DIP_3), not their ids.
"""

from __future__ import annotations

from pathlib import Path

from qpilot.schemas_studio import Comparison, SampleDesign, StudyDesign, TargetDesign

HMUY = (
    Path(__file__).resolve().parents[1]
    / "fixtures/corpus/rdml/lightcycler96-lc96p-hmuy/hmuy_hm_vs_dip_r123.lc96p"
)
GENE = "HmuYPe"
REFERENCE = "16S rRNA"
RUN = "99caca4d-c437-48dc-ad56-7c6954ead2e8"
NAMES = {name: name for name in ("Hm_1", "Hm_2", "Hm_3", "DIP_1", "DIP_2", "DIP_3")}


def hmuy_design(excluded_wells: tuple[str, ...] = ()) -> StudyDesign:
    """DIP against Hm, the 16S rRNA as the control gene (the depositors' own analysis)."""
    return StudyDesign(
        design_id="hmuy_dip_vs_hm",
        mode="groups",
        comparison=Comparison(group_a="DIP", group_b="Hm"),
        samples={s: SampleDesign(sample=s, group=n.split("_")[0]) for s, n in NAMES.items()},
        targets={
            GENE: TargetDesign(target=GENE, role="toi"),
            REFERENCE: TargetDesign(target=REFERENCE, role="ref"),
        },
        reference_candidates=(REFERENCE,),
        excluded_wells=excluded_wells,
    )
