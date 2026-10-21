"""Map the vendors' task / content names to RDML sample types, as guesses a person confirms.

QuantStudio calls a well's role its *Task* (``UNKNOWN``, ``NTC``, ``STANDARD``), CFX its
*Content* (``Unkn-01``, ``Std-03``, ``NTC``, ``NRT``, ``Pos Ctrl``, ``Neg Ctrl``), LightCycler
software its sample *Type*. RDML has eight sample types (``unkn``, ``ntc``, ``nac``, ``std``,
``ntp``, ``nrt``, ``pos``, ``opt``). The mapping is deterministic and deliberately narrow: a
name qPilot does not know stays ``unkn`` and is flagged ``unmapped`` so the Run Gate's
"type your controls" step can ask a person; nothing is guessed from sample *names*.
"""

from __future__ import annotations

import re

from qpilot.io.connectors.tables import squash

#: squashed vendor name -> RDML sample type.
VENDOR_TYPES: dict[str, str] = {
    # study samples
    "unknown": "unkn",
    "unkn": "unkn",
    "unk": "unkn",
    "sample": "unkn",
    "unknownsample": "unkn",
    "target": "unkn",
    # no-template controls
    "ntc": "ntc",
    "notemplatecontrol": "ntc",
    "notemplate": "ntc",
    "negctrl": "ntc",
    "negativecontrol": "ntc",
    "negcontrol": "ntc",
    "negative": "ntc",
    "neg": "ntc",
    "blank": "ntc",
    "water": "ntc",
    "h2o": "ntc",
    # no-RT controls
    "nrt": "nrt",
    "nort": "nrt",
    "minusrt": "nrt",
    "nrtcontrol": "nrt",
    "noreversetranscriptase": "nrt",
    "noamplificationcontrol": "nac",
    "nac": "nac",
    "ntp": "ntp",
    "notemplateprotein": "ntp",
    # standards
    "standard": "std",
    "std": "std",
    "stds": "std",
    "standards": "std",
    "calibrator": "std",
    # positive controls
    "posctrl": "pos",
    "positivecontrol": "pos",
    "poscontrol": "pos",
    "positive": "pos",
    "pos": "pos",
    "opt": "opt",
}

#: Vendor roles that are real but have no RDML sample type; kept ``unkn`` and flagged.
FLAGGED_ROLES = frozenset({"ipc", "internalpositivecontrol", "irc", "interruncalibrator"})

_REPLICATE_SUFFIX = re.compile(r"[\s_-]*\d+$")


def _strip(name: str) -> str:
    text = name.strip()
    if text.startswith("-") and squash(text) in ("rt", "nort"):
        return "nrt"
    return squash(_REPLICATE_SUFFIX.sub("", text)) or squash(text)


def map_vendor_type(name: str) -> tuple[str, bool]:
    """``(RDML sample type, recognised)`` for a vendor task / content name.

    ``Unkn-01`` -> ``("unkn", True)``; ``NTC`` -> ``("ntc", True)``; ``Std-3`` ->
    ``("std", True)``; ``""`` -> ``("unkn", True)`` (no task given is an ordinary sample);
    ``IPC`` or anything unknown -> ``("unkn", False)``.
    """
    if not name or not name.strip():
        return "unkn", True
    key = _strip(name)
    if key in FLAGGED_ROLES:
        return "unkn", False
    mapped = VENDOR_TYPES.get(key)
    if mapped is None:
        return "unkn", False
    return mapped, True


def known_token(name: str) -> str | None:
    """The canonical spelling to record for a recognised vendor name (``Unkn-01`` -> ``unkn``).

    ``None`` for a name qPilot does not know (record its ``text_id`` instead).
    """
    if not name or not name.strip():
        return None
    key = _strip(name)
    return key if key in VENDOR_TYPES or key in FLAGGED_ROLES else None


__all__ = ["FLAGGED_ROLES", "VENDOR_TYPES", "known_token", "map_vendor_type"]
