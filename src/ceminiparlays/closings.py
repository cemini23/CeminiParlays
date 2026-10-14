from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Tuple


from ceminiparlays.odds import DevigMethod, devig_two_way

MORE_SIDES = {"more", "over", "higher", "o"}
LESS_SIDES = {"less", "under", "lower", "u"}
#: Closing-snapshot columns. One row per (platform, player, stat, side).
PROP_CLOSE_FIELDS = [
    "platform",
    "player_key",
    "stat_type",
    "side",
    "line",
    "over",
    "under",
    "captured_at",
]


@dataclass(frozen=True)
class PropClose:
    """A per-prop closing line and its two-way price."""

    platform: str
    player_key: str
    stat_type: str
    side: str
    line: float
    over: int | None
    under: int | None
    captured_at: str


def _optional_int(value: str | None) -> int | None:
    text = (value or "").strip()
    if not text:
        return None
    return int(text)


def read_prop_closes(
    path: Path,
) -> Dict[Tuple[str, str, str, str], PropClose]:
    """Read a per-prop closing snapshot.

    Required columns: platform, player_key, stat_type, side, line.
    ``over``, ``under``, and ``captured_at`` are optional. Keyed by
    (platform, player_key, stat_type, side). Raises on a duplicate key.
    """

    if not path.is_file():
        raise FileNotFoundError(f"Prop closing file not found: {path}")
    required = {"platform", "player_key", "stat_type", "side", "line"}
    result: Dict[Tuple[str, str, str, str], PropClose] = {}
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"Missing required columns: {sorted(missing)}")
        for row_num, raw in enumerate(reader, start=2):
            key = (
                (raw.get("platform") or "").strip(),
                (raw.get("player_key") or "").strip(),
                (raw.get("stat_type") or "").strip(),
                (raw.get("side") or "").strip().lower(),
            )
            if key in result:
                raise ValueError(f"Duplicate key {key} at row {row_num}")
            result[key] = PropClose(
                platform=key[0],
                player_key=key[1],
                stat_type=key[2],
                side=key[3],
                line=float((raw.get("line") or "").strip()),
                over=_optional_int(raw.get("over")),
                under=_optional_int(raw.get("under")),
                captured_at=(raw.get("captured_at") or "").strip(),
            )
    return result


def write_prop_closes(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=PROP_CLOSE_FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def side_implied(
    side: str,
    over: int | None,
    under: int | None,
    method: DevigMethod = "power",
) -> float | None:
    """De-vigged implied probability for one side of a two-way market."""

    if over is None or under is None:
        return None
    result = devig_two_way(over, under, method=method)
    if side in MORE_SIDES:
        return result.p_over
    if side in LESS_SIDES:
        return result.p_under
    return None


def line_clv(side: str, bet_line: float, close_line: float) -> float:
    """Signed line move in the bettor's favor.

    An over leg gains when the closing line is higher. An under leg gains when
    the closing line is lower. Positive is good.
    """

    delta = close_line - bet_line
    return -delta if side in LESS_SIDES else delta