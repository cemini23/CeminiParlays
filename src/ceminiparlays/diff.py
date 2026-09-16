"""Card vs booked ledger diff (TG-06 ``--diff-card-booked``).

Report only. Never writes the card or the ledger. The operator types the
booked ticket after they accept the delta.
"""

from __future__ import annotations

import csv
from pathlib import Path

COMPARE_FIELDS = ("stake", "lines", "multiplier")
BOOKED_WINS = (
    "booked wins after you accept the delta; type the booked ticket into the ledger"
)
ACCEPTED = "accepted booked deltas (ledger not written)"


def read_ticket_table(path: Path) -> dict[str, dict[str, str]]:
    """Read a ledger-shaped CSV keyed by ``ticket_id`` (required)."""

    resolved = Path(path)
    with resolved.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        fields = set(reader.fieldnames or [])
        if "ticket_id" not in fields:
            raise ValueError(f"{resolved} missing column: ticket_id")
        rows: dict[str, dict[str, str]] = {}
        for raw in reader:
            ticket_id = (raw.get("ticket_id") or "").strip()
            if not ticket_id:
                raise ValueError(f"{resolved} has a row with blank ticket_id")
            rows[ticket_id] = {key: (value if value is not None else "") for key, value in raw.items()}
    return rows


def diff_ticket_lines(
    card: dict[str, dict[str, str]],
    booked: dict[str, dict[str, str]],
) -> list[str]:
    """One line per changed field (or card-only / booked-only ticket_id)."""

    lines: list[str] = []
    for ticket_id in sorted(set(card) | set(booked)):
        left = card.get(ticket_id)
        right = booked.get(ticket_id)
        if left is None:
            lines.append(f"ticket {ticket_id}: booked only")
            continue
        if right is None:
            lines.append(f"ticket {ticket_id}: card only")
            continue
        for field in COMPARE_FIELDS:
            a = (left.get(field) or "").strip()
            b = (right.get(field) or "").strip()
            if a != b:
                lines.append(f"ticket {ticket_id} {field}: card={a} booked={b}")
        if "sides" in left and "sides" in right:
            a = (left.get("sides") or "").strip()
            b = (right.get("sides") or "").strip()
            if a != b:
                lines.append(f"ticket {ticket_id} sides: card={a} booked={b}")
    return lines
