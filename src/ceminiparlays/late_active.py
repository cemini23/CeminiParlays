"""Late-active operator alert (TG-03 ``--alert-late-active``).

Report only. Never voids, reprices, or haircuts a leg.
"""

from __future__ import annotations

import csv
from pathlib import Path

from ceminiparlays.io import FLAG_STATUSES, OUT_STATUSES, LineRow
from ceminiparlays.names import fold_name

WATCH_STATUSES = OUT_STATUSES | FLAG_STATUSES


def _line_keys(row: LineRow) -> set[str]:
    keys: set[str] = set()
    if row.player_key:
        keys.add(row.player_key.strip().lower())
    folded = fold_name(row.player_name)
    if folded:
        keys.add(folded)
    return keys


def read_active_keys(path: Path) -> set[str]:
    """Keys for rows whose ``status`` is ``active`` (case-insensitive)."""

    resolved = Path(path)
    if not resolved.is_file():
        raise FileNotFoundError(f"late-active file missing: {resolved}")
    keys: set[str] = set()
    with resolved.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        fields = set(reader.fieldnames or [])
        if "status" not in fields:
            raise ValueError(f"{resolved} missing column: status")
        if "player_name" not in fields and "player_key" not in fields:
            raise ValueError(f"{resolved} needs player_name or player_key")
        for raw in reader:
            status = (raw.get("status") or "").strip().lower()
            if status != "active":
                continue
            name = (raw.get("player_name") or "").strip()
            player_key = (raw.get("player_key") or "").strip()
            if player_key:
                keys.add(player_key.lower())
            if name:
                keys.add(fold_name(name))
    return keys


def late_active_alerts(lines: list[LineRow], path: Path) -> list[str]:
    """``OPERATOR_ACTION_REQUIRED`` notes for FLAG/OUT players later ACTIVE."""

    active = read_active_keys(path)
    alerts: list[str] = []
    seen: set[str] = set()
    for row in lines:
        status = (row.injury_status or "").strip().lower()
        if status not in WATCH_STATUSES:
            continue
        keys = _line_keys(row)
        if not keys & active:
            continue
        marker = row.player_key.strip().lower() if row.player_key else fold_name(row.player_name)
        if marker in seen:
            continue
        seen.add(marker)
        alerts.append(
            f"OPERATOR_ACTION_REQUIRED: {row.player_name} excluded as {status} later ACTIVE"
        )
    return alerts
