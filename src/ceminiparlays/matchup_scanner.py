"""Print this week's matchup flags. A fail cell is not a bet.

The default command does not start Jev. ``--with-jev`` stays fail-closed
when no fixture is attached. A qualified line needs ``ev_after_vig >= 0.02``.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from ceminiparlays.book_team import teams_disagree
from ceminiparlays.feature_cache import load_feature_cache, resolve_feature_cache
from ceminiparlays.matchup_math import PRINT_EV, WARN_EV
from ceminiparlays.matchup_score import format_table, score_paths

DEFAULT_LINES = Path("data/cache/hardrock_nfl_20261018_expanded.csv")
DEFAULT_PLAYERS = Path("data/cache/matchup_players_2026w06.csv")
DEFAULT_TEAMS = Path("data/cache/matchup_teams_2026w06.csv")
DEFAULT_EV = Path("data/cache/matchup_ev.csv")
DEFAULT_LEGS = Path("data/cache/matchup_legs.csv")
DEFAULT_HIST = Path("data/cache/matchup_hist.csv")


def jev_route_status(enabled: bool) -> str:
    """Offline status. This function does not construct a Jev client."""

    if not enabled:
        return "not_called"
    return "fail_closed"


def _ev(leg: dict[str, str]) -> float:
    try:
        return float(leg.get("ev") or 0)
    except (TypeError, ValueError):
        return 0.0


def format_flags(
    summaries: list[dict[str, object]],
    legs: list[dict[str, str]],
    *,
    with_jev: bool = False,
) -> str:
    """Qualified legs only. ``ev <= 0`` is never printed."""

    passed = [str(row["market"]) for row in summaries if row.get("verdict") == "pass"]
    passed_set = set(passed)
    qualified = [
        leg
        for leg in legs
        if str(leg.get("market")) in passed_set and _ev(leg) >= PRINT_EV
    ]
    qualified.sort(key=lambda leg: (-_ev(leg), str(leg.get("player_key"))))
    if with_jev:
        jev = jev_route_status(True)
    elif not qualified:
        jev = "not_called"
    else:
        jev = "fail_closed"
    warned = any(_ev(leg) > WARN_EV for leg in qualified)
    warn_legs = sum(1 for leg in qualified if _ev(leg) > WARN_EV)
    mismatches = sum(
        1
        for leg in legs
        if teams_disagree(str(leg.get("team") or ""), str(leg.get("offense_team") or ""))
    )
    lines = [
        f"qualified={len(qualified)}",
        "promoted=" + (",".join(passed) if passed else "none"),
        f"jev={jev}",
        f"calibration_warning={1 if warned else 0}",
        f"warn_legs={warn_legs}",
        f"team_mismatch={mismatches}",
    ]
    if not qualified:
        lines.append("note=no cell cleared both the history key and the live key")
        return "\n".join(lines)
    lines.append("player market side line price ev player_pct def_pct signal")
    for leg in qualified:
        lines.append(
            " ".join(
                [
                    str(leg.get("player_name") or ""),
                    str(leg.get("market") or ""),
                    str(leg.get("side") or ""),
                    str(leg.get("line") or ""),
                    str(leg.get("price") or ""),
                    str(leg.get("ev") or ""),
                    str(leg.get("player_pct") or ""),
                    str(leg.get("def_pct") or ""),
                    str(leg.get("signal") or ""),
                ]
            )
        )
    return "\n".join(lines)


def _qualified(summaries: list[dict[str, object]], legs: list[dict[str, str]]) -> list[dict[str, str]]:
    passed = {str(row["market"]) for row in summaries if row.get("verdict") == "pass"}
    qualified = [
        leg for leg in legs if str(leg.get("market")) in passed and _ev(leg) >= PRINT_EV
    ]
    qualified.sort(key=lambda leg: (-_ev(leg), str(leg.get("player_key"))))
    return qualified


def _sgp_line(row: dict) -> str:
    parts = [
        f"{leg.get('player_name')}|{leg.get('market')}|{leg.get('side')}|{leg.get('line')}"
        for leg in row["legs"]
    ]
    return (
        " + ".join(parts)
        + f" joint={float(row['joint_p']):.6f} indep={float(row['indep_p']):.6f}"
        + f" naive_joint_ev={float(row['naive_joint_ev']):.6f}"
        + f" tax_adjusted_sgp_ev={float(row['tax_adjusted_sgp_ev']):.6f}"
    )


def format_same_game(legs: list[dict[str, str]]) -> str:
    """Top same-game joints after the book SGP haircut.

    Same-player receptions and receiving yards in one quarter are absent.
    The print ranks on ``tax_adjusted_sgp_ev``. The price source stays
    ``leg_odds_naive``.
    """

    from ceminiparlays.compose import rank_same_game

    # Rank only a positive correlation that still pays after the book haircut.
    # A same-game product with rho at or below 0.15 keeps the naive decimal
    # and stays off this table.
    priced = [
        row
        for row in rank_same_game(legs)
        if row["sgp_tax_applied"] and float(row["tax_adjusted_sgp_ev"]) > 0
    ]
    pairs = [row for row in priced if int(row["n_legs"]) == 2][:10]
    triples = [row for row in priced if int(row["n_legs"]) == 3][:5]
    lines = ["sgp_price_source=leg_odds_naive unconfirmed=yes sgp_rank=tax_adjusted rho_gt=0.15"]
    if not pairs:
        lines.append("sgp_2leg=none")
    else:
        lines.append("sgp_2leg")
        lines.extend(_sgp_line(row) for row in pairs)
    if not triples:
        lines.append("sgp_3leg=none")
    else:
        lines.append("sgp_3leg")
        lines.extend(_sgp_line(row) for row in triples)
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m ceminiparlays.matchup_scanner")
    parser.add_argument("--lines", type=Path, default=DEFAULT_LINES)
    parser.add_argument("--players", type=Path, default=DEFAULT_PLAYERS)
    parser.add_argument("--teams", type=Path, default=DEFAULT_TEAMS)
    parser.add_argument("--out", type=Path, default=DEFAULT_EV)
    parser.add_argument("--legs", type=Path, default=DEFAULT_LEGS)
    parser.add_argument("--hist", type=Path, default=DEFAULT_HIST)
    parser.add_argument("--feature-cache", type=Path, default=None)
    parser.add_argument("--with-jev", action="store_true")
    args = parser.parse_args(argv)
    cache_path = resolve_feature_cache(args.feature_cache)
    loaded = load_feature_cache(cache_path)
    print(f"feature_cache={loaded['status']}")
    frames = loaded["frames"] if loaded["status"] == "ready" else None
    summaries = score_paths(
        args.lines, args.players, args.teams, args.out, args.legs, args.hist, frames=frames
    )
    print(format_table(summaries))
    legs = _read_legs(args.legs)
    print(format_flags(summaries, legs, with_jev=bool(args.with_jev)))
    print(format_same_game(_qualified(summaries, legs)))
    return 0


def _read_legs(path: Path) -> list[dict[str, str]]:
    import csv

    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


if __name__ == "__main__":
    raise SystemExit(main())
