from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

from ceminiparlays.names import resolve_player_key

OUT_STATUSES = {"out", "ir", "inactive", "doubtful"}


@dataclass
class LineRow:
    slate_id: str
    platform: str
    player_name: str
    player_key: str
    team: str
    opponent: str
    stat_type: str
    line: float
    side: str
    line_type: str
    captured_at: str
    displayed_multiplier: float | None
    injury_status: str
    book_over: int | None
    book_under: int | None


@dataclass
class DistRow:
    player_key: str
    player_name: str
    stat_type: str
    median: float
    sigma: float
    family: str


def _optional_int(value: str) -> int | None:
    text = (value or "").strip()
    if not text:
        return None
    return int(text)


def _optional_float(value: str) -> float | None:
    text = (value or "").strip()
    if not text:
        return None
    return float(text)


def read_manual_lines(path: Path, overrides: dict[str, str] | None = None) -> list[LineRow]:
    rows: list[LineRow] = []
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        required = {"player_name", "stat_type", "line", "side"}
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"{path} missing columns: {sorted(missing)}")
        for raw in reader:
            name = raw["player_name"]
            rows.append(
                LineRow(
                    slate_id=raw.get("slate_id", ""),
                    platform=raw.get("platform", "underdog"),
                    player_name=name,
                    player_key=resolve_player_key(
                        name, overrides, raw.get("player_key")
                    ),
                    team=raw.get("team", "").upper(),
                    opponent=raw.get("opp", raw.get("opponent", "")).upper(),
                    stat_type=raw["stat_type"].strip(),
                    line=float(raw["line"]),
                    side=raw["side"].strip().lower(),
                    line_type=raw.get("line_type", "standard") or "standard",
                    captured_at=raw.get("captured_at", ""),
                    displayed_multiplier=_optional_float(raw.get("slip_multiplier", "")),
                    injury_status=(raw.get("injury_status") or "").strip().lower(),
                    book_over=_optional_int(raw.get("book_over", "")),
                    book_under=_optional_int(raw.get("book_under", "")),
                )
            )
    return rows


def read_distributions(path: Path, overrides: dict[str, str] | None = None) -> dict[tuple[str, str], DistRow]:
    out: dict[tuple[str, str], DistRow] = {}
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for raw in reader:
            name = raw.get("player_name", "")
            key = resolve_player_key(name, overrides, raw.get("player_key"))
            stat = raw["stat_type"].strip()
            out[(key, stat)] = DistRow(
                player_key=key,
                player_name=name,
                stat_type=stat,
                median=float(raw["median"]),
                sigma=float(raw.get("sd", raw.get("sigma", 0.0))),
                family=raw.get("family", ""),
            )
    return out


def is_scratched(status: str) -> bool:
    return status.lower() in OUT_STATUSES


def write_csv(path: Path, rows: list[dict[str, object]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
