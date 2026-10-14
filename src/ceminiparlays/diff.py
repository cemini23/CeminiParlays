"""Card vs booked ledger diff (TG-06 ``--diff-card-booked``).

Never writes the card. ``--emit-ledger`` may write booked rows after
``--accept-booked``. The operator still types the booked ticket.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

COMPARE_FIELDS = ("stake", "lines", "multiplier")
BOOKED_WINS = (
    "booked wins after you accept the delta; type the booked ticket into the ledger"
)
ACCEPTED = "accepted booked deltas (ledger not written)"


def _card_json_rows(path: Path) -> dict[str, dict[str, str]]:
    """One ledger-shaped row per ticket from a ``compose`` ``card.json``."""

    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} is not a card.json object")
    rows: dict[str, dict[str, str]] = {}
    for index, ticket in enumerate(payload.get("tickets") or [], start=1):
        if not isinstance(ticket, dict):
            continue
        ticket_id = str(ticket.get("ticket_id") or f"compose-{index:03d}").strip()
        legs = [leg for leg in (ticket.get("legs") or []) if isinstance(leg, dict)]
        lines = " | ".join(str(leg.get("line", "")) for leg in legs)
        sides = " | ".join(str(leg.get("side", "")) for leg in legs)
        stake = ticket.get("stake")
        rows[ticket_id] = {
            "ticket_id": ticket_id,
            "stake": "" if stake is None else str(stake),
            "lines": lines,
            "sides": sides,
            "multiplier": str(ticket.get("multiplier", "")),
        }
    return rows


def read_ticket_table(path: Path) -> dict[str, dict[str, str]]:
    """Read a ticket table keyed by ``ticket_id``.

    Accepts a ledger-shaped CSV (one row per ticket) or a ``compose``
    ``card.json`` (one entry per ticket). A CSV with one row per leg would
    otherwise keep only the last leg of each ticket (A-09).
    """

    resolved = Path(path)
    if resolved.suffix.lower() == ".json":
        return _card_json_rows(resolved)
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


def write_booked_ledger(path: Path, booked: dict[str, dict[str, str]]) -> None:
    """Write booked rows. Fieldnames are the union of keys in encounter order."""

    fieldnames: list[str] = []
    seen: set[str] = set()
    for row in booked.values():
        for key in row:
            if key not in seen:
                seen.add(key)
                fieldnames.append(key)
    resolved = Path(path)
    resolved.parent.mkdir(parents=True, exist_ok=True)
    with resolved.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames or ["ticket_id"])
        writer.writeheader()
        for ticket_id in sorted(booked):
            writer.writerow(booked[ticket_id])
