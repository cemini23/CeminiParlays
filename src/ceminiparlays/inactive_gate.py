"""Pre-lock inactive check for a Hard Rock card and entered tickets.

``inactives_diff`` used to look only at DFS lineups. A card leg could stay
live after the player was out. This module reads the card, the entered
tickets, ``scratches.md``, and the inactives file. It flags Out, Inactive,
and Doubtful. It does not flag questionable, and it does not place a bet.
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from pathlib import Path

from ceminiparlays.io import OUT_STATUSES
from ceminiparlays.names import fold_name

_DATE = re.compile(r"(20\d{2}-\d{2}-\d{2})")
_STATUS = re.compile(r"\b(out|ir|inactive|doubtful|nfi|pup|suspended)\b", re.IGNORECASE)
_STATUS_COLUMNS = ("to_status", "status", "injury_status", "label", "from_status")


@dataclass(frozen=True)
class InactiveHit:
    player_name: str
    status: str
    source: str
    ticket_id: str
    market: str
    where: str


def _date_in(name: str) -> str:
    match = _DATE.search(name)
    return match.group(1) if match else ""


def _keys_for(name: str, player_key: str = "", gsis_id: str = "") -> set[str]:
    keys: set[str] = set()
    folded = fold_name(name)
    if folded:
        keys.add(folded)
    if player_key.strip():
        keys.add(player_key.strip().lower())
        keys.add(fold_name(player_key))
    if gsis_id.strip():
        keys.add(gsis_id.strip().lower())
    return {key for key in keys if key}


def _status_from_row(raw: dict[str, str]) -> str:
    for column in _STATUS_COLUMNS:
        token = (raw.get(column) or "").strip().lower()
        if token in OUT_STATUSES:
            return token
    return ""


def _add_status(found: dict[str, tuple[str, str]], key: str, status: str, source: str) -> None:
    if key and status in OUT_STATUSES and key not in found:
        found[key] = (status, source)


def load_status_file(path: Path) -> dict[str, tuple[str, str]]:
    """Map a folded name or id to ``(status, source)`` from one CSV."""

    resolved = Path(path)
    if not resolved.is_file():
        raise FileNotFoundError(f"inactives file missing: {resolved}")
    found: dict[str, tuple[str, str]] = {}
    with resolved.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for raw in reader:
            status = _status_from_row(raw)
            if not status:
                continue
            name = (raw.get("player") or raw.get("player_name") or "").strip()
            player_key = (raw.get("player_key") or "").strip()
            gsis = (raw.get("gsis_id") or raw.get("player_id") or "").strip()
            for key in _keys_for(name, player_key, gsis):
                _add_status(found, key, status, resolved.name)
    return found


def load_scratches(path: Path, names: list[str]) -> dict[str, tuple[str, str]]:
    """Flag a listed player when the same line carries an out-family status."""

    resolved = Path(path)
    if not resolved.is_file():
        raise FileNotFoundError(f"scratches file missing: {resolved}")
    text = resolved.read_text(encoding="utf-8")
    if resolved.suffix.lower() == ".csv":
        return load_status_file(resolved)
    found: dict[str, tuple[str, str]] = {}
    lines = text.splitlines()
    for name in names:
        folded = fold_name(name)
        needle = name.strip().lower()
        if not folded or not needle:
            continue
        for index, line in enumerate(lines):
            lowered = line.lower()
            if needle not in lowered and folded.replace("_", " ") not in lowered:
                continue
            window = " ".join(lines[index : index + 2])
            match = _STATUS.search(window)
            if match is None:
                continue
            status = match.group(1).lower()
            if status in OUT_STATUSES:
                _add_status(found, folded, status, resolved.name)
                break
    return found


def _read_rows(path: Path) -> list[dict[str, str]]:
    resolved = Path(path)
    if not resolved.is_file():
        raise FileNotFoundError(f"card file missing: {resolved}")
    with resolved.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _leg_names(row: dict[str, str]) -> list[tuple[str, str, str]]:
    """Return ``(player_name, player_key, gsis_id)`` for one card or ticket row."""

    raw_name = (row.get("player_name") or row.get("player") or "").strip()
    raw_key = (row.get("player_key") or "").strip()
    raw_gsis = (row.get("gsis_id") or "").strip()
    if "|" in raw_name or "|" in raw_key:
        names = [part.strip() for part in raw_name.split("|")]
        keys = [part.strip() for part in raw_key.split("|")]
        gsis = [part.strip() for part in raw_gsis.split("|")]
        width = max(len(names), len(keys), len(gsis))
        legs: list[tuple[str, str, str]] = []
        for index in range(width):
            legs.append(
                (
                    names[index] if index < len(names) else "",
                    keys[index] if index < len(keys) else "",
                    gsis[index] if index < len(gsis) else "",
                )
            )
        return [leg for leg in legs if any(leg)]
    if raw_name or raw_key or raw_gsis:
        return [(raw_name, raw_key, raw_gsis)]
    legs_cell = (row.get("legs") or "").strip()
    if legs_cell:
        return [(part.strip(), "", "") for part in legs_cell.split("|") if part.strip()]
    return []


def discover_sidecars(card: Path) -> tuple[Path | None, Path | None]:
    """Find ``entered_tickets_DATE.csv`` and ``scratches.md`` beside the card."""

    slate_date = _date_in(card.name)
    entered: Path | None = None
    scratches: Path | None = None
    if not slate_date:
        return None, None
    parents = [card.parent, *list(card.parents)[:4]]
    entered_name = f"entered_tickets_{slate_date}.csv"
    for parent in parents:
        candidate = parent / entered_name
        if candidate.is_file():
            entered = candidate
            break
        nested = parent / "parlays-slate" / slate_date / entered_name
        if nested.is_file():
            entered = nested
            break
    for parent in parents:
        for candidate in (
            parent / "scratches.md",
            parent / "parlays-slate" / slate_date / "scratches.md",
            parent / slate_date / "scratches.md",
        ):
            if candidate.is_file():
                scratches = candidate
                break
        if scratches is not None:
            break
    return entered, scratches


def _resolve_sidecars(
    card: Path, entered: Path | None, scratches: Path | None
) -> tuple[Path | None, Path | None]:
    """The caller's paths win. Only the missing one is discovered."""

    if entered is not None and scratches is not None:
        return entered, scratches
    found_entered, found_scratches = discover_sidecars(card)
    return (
        entered if entered is not None else found_entered,
        scratches if scratches is not None else found_scratches,
    )


def _collect_names(groups: list[tuple[str, list[dict[str, str]]]]) -> list[str]:
    names: list[str] = []
    for _where, rows in groups:
        for row in rows:
            for name, _key, _gsis in _leg_names(row):
                if name:
                    names.append(name)
    return names


def _status_index(
    inactives: Path, scratch_path: Path | None, names: list[str]
) -> dict[str, tuple[str, str]]:
    statuses = load_status_file(inactives)
    if scratch_path is not None:
        for key, value in load_scratches(scratch_path, names).items():
            statuses.setdefault(key, value)
    return statuses


def _match_status(
    name: str, player_key: str, gsis: str, statuses: dict[str, tuple[str, str]]
) -> tuple[str, str] | None:
    for key in _keys_for(name, player_key, gsis):
        if key in statuses:
            return statuses[key]
    return None


def _row_hits(
    where: str,
    row: dict[str, str],
    statuses: dict[str, tuple[str, str]],
    seen: set[tuple[str, str, str, str]],
) -> list[InactiveHit]:
    ticket_id = (row.get("ticket_id") or "").strip()
    market = (row.get("market") or "").strip()
    hits: list[InactiveHit] = []
    for name, player_key, gsis in _leg_names(row):
        matched = _match_status(name, player_key, gsis, statuses)
        if matched is None:
            continue
        status, source = matched
        token = (where, ticket_id, name or player_key or gsis, market)
        if token in seen:
            continue
        seen.add(token)
        hits.append(
            InactiveHit(
                player_name=name or player_key or gsis,
                status=status,
                source=source,
                ticket_id=ticket_id,
                market=market,
                where=where,
            )
        )
    return hits


def check_card_inactives(
    card: Path,
    inactives: Path,
    entered: Path | None = None,
    scratches: Path | None = None,
) -> list[InactiveHit]:
    """Return one hit for every Out, Inactive, or Doubtful leg."""

    card_rows = _read_rows(card)
    entered_path, scratch_path = _resolve_sidecars(card, entered, scratches)
    groups: list[tuple[str, list[dict[str, str]]]] = [("card", card_rows)]
    if entered_path is not None:
        groups.append(("entered", _read_rows(entered_path)))
    statuses = _status_index(inactives, scratch_path, _collect_names(groups))
    hits: list[InactiveHit] = []
    seen: set[tuple[str, str, str, str]] = set()
    for where, rows in groups:
        for row in rows:
            hits.extend(_row_hits(where, row, statuses, seen))
    return hits
