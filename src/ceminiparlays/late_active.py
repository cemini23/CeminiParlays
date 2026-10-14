"""Late-status ingest (``--alert-late-active``).

The operator passes a status file (an inactives list). A player who is listed
``out`` / ``inactive`` / ``ir`` / ``doubtful`` for the game is scratched before
any pricing runs, so an inactive player can never land on a card.

An in-game ``exit`` / ``left`` token on a typed row is a warning only: it never
voids, scratches, or reprices the leg.
"""

from __future__ import annotations

import csv
from pathlib import Path

from ceminiparlays.io import OUT_STATUSES, LineRow
from ceminiparlays.names import fold_name

#: In-game exit / left tokens. A warning only: never a void, scratch, or reprice.
IN_GAME_EXIT_STATUSES = {"exit", "left"}


def _line_keys(row: LineRow) -> set[str]:
    keys: set[str] = set()
    if row.player_key:
        keys.add(row.player_key.strip().lower())
    folded = fold_name(row.player_name)
    if folded:
        keys.add(folded)
    return keys


def _read_status_keys(path: Path, statuses: set[str]) -> set[str]:
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
            if status not in statuses:
                continue
            player_key = (raw.get("player_key") or "").strip()
            name = (raw.get("player_name") or "").strip()
            if player_key:
                keys.add(player_key.lower())
            if name:
                keys.add(fold_name(name))
    return keys


def read_out_keys(path: Path) -> set[str]:
    """Keys for rows the status file marks out / inactive / ir / doubtful."""

    return _read_status_keys(path, OUT_STATUSES)


def apply_inactive_scratch(lines: list[LineRow], path: Path) -> list[str]:
    """Scratch every line whose player the status file marks out.

    Mutates ``LineRow.injury_status`` to ``"inactive"`` so ``evaluate_legs``
    drops the leg as a scratch. Returns the scratched player names, in order.
    A row already marked out keeps its own status.
    """

    out = read_out_keys(path)
    scratched: list[str] = []
    for row in lines:
        if (row.injury_status or "").strip().lower() in OUT_STATUSES:
            continue
        if _line_keys(row) & out:
            row.injury_status = "inactive"
            scratched.append(row.player_name)
    return scratched


def in_game_exit_warnings(lines: list[LineRow]) -> list[str]:
    """``IN_GAME_EXIT`` notes for a row already carrying an exit / left token."""

    alerts: list[str] = []
    seen: set[str] = set()
    for row in lines:
        status = (row.injury_status or "").strip().lower()
        if status not in IN_GAME_EXIT_STATUSES:
            continue
        marker = row.player_key.strip().lower() if row.player_key else fold_name(row.player_name)
        if marker in seen:
            continue
        seen.add(marker)
        alerts.append(
            f"IN_GAME_EXIT: {row.player_name} status {status} — review, "
            "leg stays live. No cashout."
        )
    return alerts
