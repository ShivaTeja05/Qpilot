"""The one Gate line shape every gate returns (G-RT, G-INSTR; BUILD-DESIGN §2.3).

A line is a reported check: a rule id, a status word, a code the wording is chosen by, the facts
behind every number it shows, and the cycles to look at. A line never changes a conclusion.

Deterministic: no model call and no network.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from qpilot.schemas import Fact

GateStatus = Literal["pass", "info", "warn", "not_applicable"]


class GateLine(BaseModel):
    """One Gate line: a rule, a status, a code for the wording, its facts and cycles.

    ``rule_id`` names the gate (``G-RT``, ``G-INSTR``); each gate sets it on the lines it makes.
    """

    rule_id: str = ""
    status: GateStatus
    code: str
    facts: dict[str, Fact] = Field(default_factory=dict)
    cycles: list[int] = Field(default_factory=list)


__all__ = ["GateLine", "GateStatus"]
