from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Tuple

import numpy as np

from ceminiparlays.copula import nearest_correlation


@dataclass(frozen=True)
class ClosingLine:
    season: int
    week: int
    game: str
    closing_spread: float
    closing_total: float


def read_closing_lines(path: Path) -> Dict[Tuple[int, int, str], ClosingLine]:
    """Read historical closing lines from a CSV file.

    Required columns: season, week, game, closing_spread, closing_total.
    Returns a dict keyed by (season, week, game).
    Raises ValueError on missing column, blank number, or duplicate key.
    Raises FileNotFoundError if path does not exist.
    """
    if not path.is_file():
        raise FileNotFoundError(f"Closing lines file not found: {path}")

    required_columns = {"season", "week", "game", "closing_spread", "closing_total"}
    result: Dict[Tuple[int, int, str], ClosingLine] = {}

    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        fieldnames = reader.fieldnames or []
        missing = required_columns - set(fieldnames)
        if missing:
            raise ValueError(f"Missing required columns: {sorted(missing)}")

        for row_num, raw in enumerate(reader, start=2):
            season_text = (raw.get("season") or "").strip()
            week_text = (raw.get("week") or "").strip()
            game = (raw.get("game") or "").strip()
            spread_text = (raw.get("closing_spread") or "").strip()
            total_text = (raw.get("closing_total") or "").strip()

            if not season_text:
                raise ValueError(f"Row {row_num}: blank season")
            if not week_text:
                raise ValueError(f"Row {row_num}: blank week")
            if not game:
                raise ValueError(f"Row {row_num}: blank game")
            if not spread_text:
                raise ValueError(f"Row {row_num}: blank closing_spread")
            if not total_text:
                raise ValueError(f"Row {row_num}: blank closing_total")

            try:
                season = int(season_text)
            except ValueError:
                raise ValueError(f"Row {row_num}: invalid season '{season_text}'")
            try:
                week = int(week_text)
            except ValueError:
                raise ValueError(f"Row {row_num}: invalid week '{week_text}'")
            try:
                closing_spread = float(spread_text)
            except ValueError:
                raise ValueError(f"Row {row_num}: invalid closing_spread '{spread_text}'")
            try:
                closing_total = float(total_text)
            except ValueError:
                raise ValueError(f"Row {row_num}: invalid closing_total '{total_text}'")

            key = (season, week, game)
            if key in result:
                raise ValueError(f"Duplicate key {key} at row {row_num}")

            result[key] = ClosingLine(
                season=season,
                week=week,
                game=game,
                closing_spread=closing_spread,
                closing_total=closing_total,
            )

    return result


def closing_correlation(rows: Dict[Tuple[int, int, str], ClosingLine]) -> np.ndarray:
    """Compute 2x2 correlation matrix from closing spread and total.

    Requires at least 3 finite pairs. Raises ValueError if either column
    has zero variance. Returns nearest_correlation of [[1, rho], [rho, 1]].
    """
    if len(rows) < 3:
        raise ValueError("Need at least 3 rows to compute correlation")

    spreads = np.array([row.closing_spread for row in rows.values()], dtype=float)
    totals = np.array([row.closing_total for row in rows.values()], dtype=float)

    if not np.all(np.isfinite(spreads)) or not np.all(np.isfinite(totals)):
        raise ValueError("All closing_spread and closing_total values must be finite")

    spread_var = np.var(spreads, ddof=1)
    total_var = np.var(totals, ddof=1)
    if spread_var == 0.0 or total_var == 0.0:
        raise ValueError("closing_spread or closing_total has zero variance")

    rho = float(np.corrcoef(spreads, totals)[0, 1])
    matrix = np.array([[1.0, rho], [rho, 1.0]], dtype=float)
    return nearest_correlation(matrix)