"""Gate vs detector classification. Pure data, no order path."""

from __future__ import annotations

from ceminiparlays.controls import (
    Control,
    ControlKind,
    classify_controls,
    describe_control_set,
)


def _gate(name: str) -> Control:
    return Control(name=name, kind=ControlKind.GATE, description=f"{name} gate")


def _detector(name: str) -> Control:
    return Control(name=name, kind=ControlKind.DETECTOR, description=f"{name} detector")


def test_classification_preserves_input_order_within_each_kind() -> None:
    controls = [
        _detector("clv"),
        _gate("stake-cap"),
        _detector("late-swap"),
        _gate("leg-count"),
    ]
    grouped = classify_controls(controls)
    assert [control.name for control in grouped["gate"]] == ["stake-cap", "leg-count"]
    assert [control.name for control in grouped["detector"]] == ["clv", "late-swap"]


def test_an_empty_list_yields_both_keys_with_empty_lists() -> None:
    assert classify_controls([]) == {"gate": [], "detector": []}


def test_describe_control_set_counts_match_the_input() -> None:
    controls = [_gate("stake-cap"), _detector("clv"), _gate("leg-count")]
    line = describe_control_set(controls)
    assert line.startswith("gates=2 detectors=1")
    assert "stake-cap" in line
    assert "leg-count" in line
    assert "clv" in line
    assert "\n" not in line
