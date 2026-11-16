"""Order-path control kinds: pre-trade gates and post-trade detectors.

A gate rejects an order before it leaves. A detector flags an order after the
fact. They carry different costs and different failure modes, so a report that
cannot name which is which cannot tell a quiet detector from an effective gate.

This module only describes and groups controls. It does not run them and it
does not touch the order path.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ControlKind(Enum):
    """The two control types on the order path."""

    GATE = "gate"
    DETECTOR = "detector"


@dataclass(frozen=True)
class Control:
    """One named order-path control."""

    name: str
    kind: ControlKind
    description: str


def classify_controls(controls: list[Control]) -> dict[str, list[Control]]:
    """Group controls by kind, preserving input order within each group."""

    grouped: dict[str, list[Control]] = {"gate": [], "detector": []}
    for control in controls:
        grouped[control.kind.value].append(control)
    return grouped


def describe_control_set(controls: list[Control]) -> str:
    """Return a one-line summary of the counts and names in a control set."""

    grouped = classify_controls(controls)
    gates = grouped["gate"]
    detectors = grouped["detector"]
    gate_names = ", ".join(control.name for control in gates)
    detector_names = ", ".join(control.name for control in detectors)
    return (
        f"gates={len(gates)} detectors={len(detectors)} "
        f"gate_names=[{gate_names}] detector_names=[{detector_names}]"
    )
