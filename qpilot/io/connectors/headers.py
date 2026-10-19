"""qPilot's names for the header lines of vendor exports (the values stay quarantined text).

QuantStudio writes ``* Instrument Serial Number = 272310579``; CFX's Run Information sheet
writes ``Base Serial Number,CT012345``. :func:`canonical_header` gives such keys one name
(``instrument_serial``), so the Import Trust Card and, later, the instrument logbook can find
them; the value itself is file text and is only ever cited by ``text_id``.
"""

from __future__ import annotations

import re

from qpilot.io.connectors.tables import squash

#: squashed vendor key -> qPilot key.
HEADER_KEYS: dict[str, str] = {
    "instrumenttype": "instrument_type",
    "instrumentname": "instrument_name",
    "instrumentserialnumber": "instrument_serial",
    "baseserialnumber": "instrument_serial",
    "opticalheadserialnumber": "optical_head_serial",
    "blockserialnumber": "block_serial",
    "heatedcoverserialnumber": "heated_cover_serial",
    "blocktype": "block_type",
    "passivereference": "passive_reference",
    "experimentname": "experiment_name",
    "experimenttype": "experiment_type",
    "chemistry": "chemistry",
    "quantificationcyclemethod": "cq_method",
    "signalsmoothingon": "signal_smoothing",
    "experimentrunendtime": "run_end",
    "runenddatetime": "run_end",
    "runenddatatime": "run_end",
    "runended": "run_end",
    "runstarted": "run_start",
    "runstartdatetime": "run_start",
    "runstartdatatime": "run_start",
    "softwarenameandversion": "software",
    "softwareversion": "software",
    "cfxmanagerversion": "software",
    "cfxmaestroversion": "software",
    "experimentfilename": "file_name",
    "filename": "file_name",
    "username": "operator",
    "createdbyuser": "operator",
    "operator": "operator",
    "experimentbarcode": "barcode",
    "barcode": "barcode",
    "experimentcomment": "comment",
    "comment": "comment",
    "notes": "comment",
    "samplevolume": "sample_volume",
    "samplevol": "sample_volume",
    "lidtemp": "lid_temperature",
    "covertemperature": "lid_temperature",
    "protocolfilename": "protocol_file",
    "platesetupfilename": "plate_setup_file",
    "stagecyclewhereanalysisisperformed": "analysis_stage",
    "pcrstagestepnumber": "analysis_stage",
    "analysisdatetime": "analysis_date",
    "exportedon": "export_date",
    "datecreated": "date_created",
}


def canonical_header(key: str) -> str:
    """QPilot's key for a vendor header key (``other_<slug>`` for keys it does not know).

    Calibration lines keep their meaning: ``Calibration Background is expired`` ->
    ``calibration_background_is_expired``.
    """
    squashed = squash(key)
    if squashed in HEADER_KEYS:
        return HEADER_KEYS[squashed]
    slug = re.sub(r"[^a-z0-9]+", "_", key.lower()).strip("_")[:48] or "key"
    if squashed.startswith("calibration"):
        return slug
    return f"other_{slug}"


__all__ = ["HEADER_KEYS", "canonical_header"]
