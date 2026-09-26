from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from ceminiparlays import STANDARD_DISCLAIMER, __version__
from ceminiparlays.bankroll import flat_stake, kelly_cap_stake
from ceminiparlays.catalog import thin_catalog_games
from ceminiparlays.ceminidfs import exposure_notes, load_ceminidfs_handoff, merge_implied_totals
from ceminiparlays.compose import (
    TICKET_FIELDS,
    compose_tickets,
    concentration_warnings,
    estimate_multiplier,
    player_stat_ticket_counts,
    ticket_rows,
)
from ceminiparlays.diff import (
    ACCEPTED,
    BOOKED_WINS,
    diff_ticket_lines,
    read_ticket_table,
    write_booked_ledger,
)
from ceminiparlays.environment import (
    env_for,
    env_rows_for_games,
    missing_env_games,
    read_environment,
    write_compose_itt,
)
from ceminiparlays.late_active import late_active_alerts
from ceminiparlays.fair import p_over_line, side_probability
from ceminiparlays.fetch import load_fixture, rows_from_events, write_fetch_csv
from ceminiparlays.grade import grade_ledger, write_grade
from ceminiparlays.io import read_distributions, read_games, read_manual_lines, write_csv
from ceminiparlays.markets import AUTO_MARKETS, parse_markets
from ceminiparlays.odds_api import (
    DEFAULT_REGIONS,
    STAT_TO_MARKET,
    bookmakers_for_platforms,
    et_slate_window,
    parse_books,
    parse_fetch_date,
    pull_event_odds,
    resolve_api_key,
    sport_key_for,
    utc_day_window,
)
from ceminiparlays.odds import american_to_decimal, devig_spread, devig_two_way
from ceminiparlays.compare import pickem_gap
from ceminiparlays.payouts import (
    PREDICTION_PLATFORMS,
    SPORTSBOOK_PLATFORMS,
    breakeven_per_leg,
    display_name,
    implied_slip_win,
    normalize_platform,
    resolve_payout,
)
from ceminiparlays.report import PREDICTION_BANNER, fair_card, slip_card
from ceminiparlays.roster import load_roster, lookup_player
from ceminiparlays.slips import (
    EDGE_FIELDS,
    evaluate_legs,
    rank_slip_sizes,
    rank_slips,
    resolve_slip_sizes,
    slip_as_row,
)

UNCONFIRMED_BANNER = "UNCONFIRMED TABLE MULTIPLIER — confirm in-app"
#: Fill-in slate columns the reader accepts (blank until the operator types).
SLATE_FIELDS = [
    "slate_id",
    "platform",
    "player_name",
    "player_key",
    "team",
    "opp",
    "stat_type",
    "line",
    "side",
    "line_type",
    "captured_at",
    "injury_status",
    "book_over",
    "book_under",
    "leg_odds",
    "slip_odds",
    "slip_multiplier",
    "ticket_id",
    "fair_p",
    "contract_price",
]
PLATFORM_CHOICES = [
    "hardrock",
    "fanduel",
    "draftkings",
    "betmgm",
    "polymarket",
    "kalshi",
    "underdog",
    "prizepicks",
]


def _add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--platform", default="hardrock", choices=PLATFORM_CHOICES)
    parser.add_argument("--profile-dir", type=Path, default=None)


def _add_rank_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--mode", default="standard", choices=["standard", "power", "flex"])
    parser.add_argument("--slip-size", type=int, default=2)
    parser.add_argument(
        "--legs",
        default=None,
        help="Leg counts to rank: 4 or 2,3,4 or 2-4. Overrides --slip-size when set.",
    )
    parser.add_argument(
        "--min-odds",
        type=int,
        default=None,
        help="Keep slips at least this long (American), e.g. +150",
    )
    parser.add_argument(
        "--max-odds",
        type=int,
        default=None,
        help="Keep slips no longer than this (American), e.g. +400",
    )
    parser.add_argument(
        "--markets",
        default=None,
        help="Comma list of market tokens: pass_yds,rush_yds,rec_yds,receptions,"
        "rush_att,pass_tds,first_td,anytime_td,h2h,spreads,totals",
    )
    parser.add_argument(
        "--ticket-id",
        default=None,
        help="Only rank rows carrying this ticket_id.",
    )
    parser.add_argument(
        "--bankroll",
        type=float,
        default=None,
        help="Optional bankroll for a per-ticket flat / quarter-Kelly note.",
    )
    parser.add_argument(
        "--roster",
        type=Path,
        default=None,
        help="Player-to-team JSON. Default is the packaged NFL roster.",
    )
    parser.add_argument(
        "--no-roster",
        action="store_true",
        help="Skip the roster team check (not recommended).",
    )
    parser.add_argument("--n-sims", type=int, default=20_000)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--displayed-multiplier", type=float, default=None)
    parser.add_argument(
        "--displayed-odds",
        type=int,
        default=None,
        help="In-app American parlay/SGP price, e.g. +260 or -120",
    )
    parser.add_argument("--devig-method", default="power", choices=["power", "multiplicative", "additive"])
    parser.add_argument("--max-slips", type=int, default=25)
    parser.add_argument("--allow-large-enum", action="store_true")
    parser.add_argument("--allow-integer-lines", action="store_true")
    parser.add_argument("--shade-pp", type=float, default=0.0)
    parser.add_argument(
        "--strict",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Abort (exit 2) when any leg is dropped. Default on; use --no-strict to rank anyway.",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ceminiparlays",
        description=(
            "Local sportsbook parlay / pick'em research CLI. "
            "Licensed Odds API fetch is allowed; book-site scrapers and auto-submit are not."
        ),
    )
    parser.add_argument("--version", action="version", version=f"ceminiparlays {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    fair = sub.add_parser("fair", help="Fair P(stat > line) from a median and sigma")
    fair.add_argument("--player", required=True)
    fair.add_argument("--stat", required=True)
    fair.add_argument("--line", type=float, required=True)
    fair.add_argument("--median", type=float, required=True)
    fair.add_argument("--sd", type=float, required=True)
    fair.add_argument("--side", default="more")
    fair.add_argument("--family", default=None, choices=["lognormal", "normal", "poisson"])
    fair.add_argument("--show-dist", action="store_true")

    rank = sub.add_parser("rank", help="Rank slips from manual lines + distributions")
    _add_common(rank)
    _add_rank_options(rank)
    rank.add_argument("--lines", type=Path, required=True)
    rank.add_argument("--distributions", type=Path, required=True)
    rank.add_argument("--out", type=Path, default=Path("runs/edges.csv"))
    rank.add_argument("--report", type=Path, default=None)

    grade = sub.add_parser("grade", help="Grade a personal ledger")
    _add_common(grade)
    grade.add_argument("--ledger", type=Path, required=True)
    grade.add_argument("--out", type=Path, default=Path("runs/grade.json"))

    devig = sub.add_parser("devig", help="De-vig a two-way American market")
    devig.add_argument("--over", type=int, required=True)
    devig.add_argument("--under", type=int, required=True)
    devig.add_argument("--method", default="power", choices=["power", "multiplicative", "additive"])

    compare = sub.add_parser(
        "compare",
        help="Compare de-juiced fair price vs fixed pick'em multiplier (gap report)",
    )
    compare.add_argument("--over", type=int, required=True)
    compare.add_argument("--under", type=int, required=True)
    compare.add_argument("--platform", required=True, choices=["prizepicks", "underdog"])
    compare.add_argument("--legs", type=int, required=True, choices=[2, 3, 4, 5, 6, 7, 8])
    compare.add_argument("--mode", default="standard", choices=["standard", "power", "flex"])
    compare.add_argument("--method", default="power", choices=["power", "multiplicative", "additive"])
    compare.add_argument("--side", default="over", choices=["over", "under"])
    compare.add_argument("--displayed-multiplier", type=float, default=None)

    run = sub.add_parser("run", help="Write edges.csv + report under runs/{slate}")
    _add_common(run)
    _add_rank_options(run)
    run.add_argument("--lines", type=Path, required=True)
    run.add_argument("--distributions", type=Path, required=True)
    run.add_argument("--slate-id", default="demo")
    run.add_argument("--out-dir", type=Path, default=None)

    slate = sub.add_parser(
        "slate", help="Write a fill-in lines CSV from a games file + packaged roster"
    )
    slate.add_argument(
        "--games",
        type=Path,
        default=Path("examples/games_sunday_afternoon.csv"),
    )
    slate.add_argument("--roster", type=Path, default=None)
    slate.add_argument(
        "--environment",
        type=Path,
        default=None,
        help=(
            "Optional env CSV. Warn ENVIRONMENT_MISSING_GAME for games missing "
            "a team row. Missing file skips the warn. Exit 0."
        ),
    )
    slate.add_argument("--platform", default="hardrock", choices=PLATFORM_CHOICES)
    slate.add_argument("--slate-id", default=None)
    slate.add_argument("--out", type=Path, default=Path("runs/slate/lines_fill_in.csv"))

    compose = sub.add_parser(
        "compose",
        help="Pick diversified tickets inside an odds window and write ticket CSVs",
    )
    _add_common(compose)
    compose.add_argument("--lines", type=Path, required=True)
    compose.add_argument("--distributions", type=Path, default=None)
    compose.add_argument("--roster", type=Path, default=None)
    compose.add_argument("--no-roster", action="store_true")
    compose.add_argument("--auto", action="store_true")
    compose.add_argument("--markets", default=None)
    compose.add_argument("--legs", default=None)
    compose.add_argument("--slip-size", type=int, default=2)
    compose.add_argument("--min-odds", type=int, default=None)
    compose.add_argument("--max-odds", type=int, default=None)
    compose.add_argument("--n-tickets", type=int, default=5)
    compose.add_argument(
        "--max-exposure-per-player",
        type=int,
        default=None,
        help=(
            "Exit 2 when the same player+stat_type appears on more than N tickets. "
            "Default unset: concentration warning only."
        ),
    )
    compose.add_argument("--environment", type=Path, default=None)
    compose.add_argument(
        "--max-legs-per-market",
        type=int,
        default=None,
        help=(
            "Skip a combo when one stat_type appears more than N times. "
            "--auto uses 2 when this flag is omitted. Pass 0 to turn the cap off."
        ),
    )
    compose.add_argument(
        "--from-ceminidfs",
        type=Path,
        default=None,
        help=(
            "Local CeminiDFS handoff CSV. Missing file prints "
            "CEMINIDFS_HANDOFF_MISSING and continues. FanDuel FPPG projection "
            "is not a prop fair."
        ),
    )
    compose.add_argument(
        "--enforce-market-depth",
        action="store_true",
        help=(
            "TG-04: exit 2 with CATALOG_THIN_MANUAL_INPUT_REQUIRED when a game "
            "on the lines file is missing moneyline/h2h or spread/spreads"
        ),
    )
    compose.add_argument(
        "--allow-thin-catalog",
        action="store_true",
        help="print CATALOG_THIN_MANUAL_INPUT_REQUIRED and continue composing",
    )
    compose.add_argument(
        "--alert-late-active",
        type=Path,
        default=None,
        help=(
            "TG-03: CSV of player_name/player_key + status; FLAG/OUT later "
            "ACTIVE prints OPERATOR_ACTION_REQUIRED (no void)"
        ),
    )
    compose.add_argument("--ticket-id", default=None)
    compose.add_argument("--mode", default="standard", choices=["standard", "power"])
    compose.add_argument("--devig-method", default="power", choices=["power", "multiplicative", "additive"])
    compose.add_argument("--bankroll", type=float, default=None)
    compose.add_argument("--out-dir", type=Path, default=None)
    compose.add_argument(
        "--card-md",
        nargs="?",
        const="card.md",
        default=None,
        help="Write a redacted markdown card (default name card.md under --out-dir)",
    )
    compose.add_argument(
        "--strict",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Abort (exit 2) when any leg is dropped. Default on.",
    )

    diff = sub.add_parser(
        "diff",
        help="TG-06 `--diff-card-booked`: print card vs booked stake/line/multiplier deltas",
        description="TG-06 `--diff-card-booked`: print card vs booked stake/line/multiplier deltas",
    )
    diff.add_argument("--card", type=Path, required=True, help="Ledger-shaped compose card CSV")
    diff.add_argument("--booked", type=Path, required=True, help="Ledger-shaped booked ticket CSV")
    diff.add_argument(
        "--accept-booked",
        action="store_true",
        help="print the same table and exit 0; never writes the card",
    )
    diff.add_argument(
        "--emit-ledger",
        type=Path,
        default=None,
        help=(
            "Write booked rows to PATH. Requires --accept-booked. "
            "Never overwrites the card."
        ),
    )

    bankroll = sub.add_parser(
        "bankroll", help="Print flat and quarter-Kelly stake sizes"
    )
    bankroll.add_argument("--bankroll", type=float, required=True)
    bankroll.add_argument("--n-tickets", type=int, default=5)

    fetch = sub.add_parser(
        "fetch",
        help="Pull two-way player-prop odds from The Odds API into a lines CSV",
    )
    fetch.add_argument("--sport", default="nfl")
    fetch.add_argument(
        "--date",
        default=None,
        help=(
            "America/New_York slate day (YYYY-MM-DD). Midnight ET to next midnight ET, "
            "converted to UTC (DST from zoneinfo). Default is today in America/New_York. "
            "Sunday includes SNF."
        ),
    )
    fetch.add_argument(
        "--utc-date",
        default=None,
        help="UTC calendar day (YYYY-MM-DD). Uses utc_day_window instead of the ET slate.",
    )
    fetch.add_argument(
        "--books",
        default="hardrock,fanduel,draftkings",
        help="Comma list of platforms: hardrock,fanduel,draftkings,betmgm",
    )
    fetch.add_argument(
        "--markets",
        default="pass_yds,rush_yds,rec_yds,first_td,anytime_td",
        help=(
            "Comma list of market tokens (same as compose/rank). "
            "Game markets: h2h,spreads,totals (aliases moneyline,spread,total). "
            "Default stays player props."
        ),
    )
    fetch.add_argument("--regions", default=DEFAULT_REGIONS)
    fetch.add_argument("--slate-id", default=None)
    fetch.add_argument("--out", type=Path, default=Path("runs/slate/lines.csv"))
    fetch.add_argument(
        "--fixture",
        type=Path,
        default=None,
        help="Local Odds API JSON. Skips HTTP. No API key required.",
    )
    fetch.add_argument("--force", action="store_true", help="Overwrite --out if it exists")
    fetch.add_argument("--roster", type=Path, default=None)
    fetch.add_argument("--no-roster", action="store_true")
    return parser


def _cmd_fair(args: argparse.Namespace) -> int:
    result = p_over_line(args.line, args.median, args.sd, family=args.family, stat_type=args.stat)
    fair_p = side_probability(result, args.side)
    print(fair_card(args.player, args.stat, args.line, result, args.side, fair_p))
    if args.show_dist:
        print(json.dumps(result.__dict__, indent=2))
    return 0


def _effective_multiplier(
    lines, displayed_multiplier: float | None
) -> tuple[float | None, bool]:
    """Best slate-wide M for the implied/breakeven banner.

    Returns ``(multiplier, unconfirmed)``. Per-combo row M still overrides this
    inside ``rank_slips``.
    """

    if displayed_multiplier is not None:
        return displayed_multiplier, False
    row_ms = sorted(
        {row.displayed_multiplier for row in lines if row.displayed_multiplier is not None}
    )
    if row_ms:
        return row_ms[0], False
    all_slip = [row.slip_odds for row in lines]
    if all_slip and all(value is not None for value in all_slip):
        distinct = sorted(set(all_slip))
        if len(distinct) == 1:
            return american_to_decimal(int(distinct[0])), False
    return None, True


def _cli_displayed_multiplier(args: argparse.Namespace) -> float | None:
    decimal = args.displayed_multiplier
    american = getattr(args, "displayed_odds", None)
    if american is not None:
        from_odds = american_to_decimal(american)
        if decimal is not None and abs(decimal - from_odds) > 1e-9:
            raise ValueError("conflicting --displayed-multiplier and --displayed-odds")
        return from_odds
    return decimal


def _bankroll_note(bankroll: float | None, n_tickets: int) -> str | None:
    if bankroll is None:
        return None
    cap = kelly_cap_stake(bankroll)
    if n_tickets < 1:
        return f"bankroll ${bankroll:.2f}; quarter-Kelly cap ${cap:.2f} per ticket"
    flat = flat_stake(bankroll, n_tickets)
    return (
        f"bankroll ${bankroll:.2f} over {n_tickets} tickets: flat ${flat:.2f} each; "
        f"quarter-Kelly cap ${cap:.2f} per ticket"
    )


def _rank_and_write(args: argparse.Namespace, out_csv: Path, report_path: Path | None) -> int:
    strict = getattr(args, "strict", True)
    platform = normalize_platform(args.platform)
    priced_venue = platform in SPORTSBOOK_PLATFORMS or platform in PREDICTION_PLATFORMS
    if priced_venue and args.mode.lower() == "flex":
        raise ValueError(
            f"{display_name(platform)} Flex is not modeled. Use --mode standard "
            "and pass the displayed price from the app."
        )
    sizes = resolve_slip_sizes(args.slip_size, getattr(args, "legs", None))
    displayed_m = _cli_displayed_multiplier(args)
    if priced_venue and displayed_m is not None and len(sizes) != 1:
        raise ValueError(
            "--displayed-odds prices one ticket. Pass a single --legs / --slip-size."
        )
    lines = read_manual_lines(args.lines, strict=strict)
    lines = [
        row
        for row in lines
        if (not row.platform or normalize_platform(row.platform) == platform)
    ]
    ticket_id = getattr(args, "ticket_id", None)
    if ticket_id:
        lines = [row for row in lines if row.ticket_id == str(ticket_id)]
    market_filter = parse_markets(getattr(args, "markets", None))
    if market_filter:
        lines = [row for row in lines if row.stat_type in market_filter]
    if not lines:
        raise ValueError(
            f"no rows for platform {platform}; set the CSV platform column, clear "
            "--ticket-id / --markets, or leave the column blank"
        )
    slate_ids = {row.slate_id for row in lines if row.slate_id}
    if len(slate_ids) > 1:
        raise ValueError(f"mixed slate_id values in lines file: {sorted(slate_ids)}")

    effective_m, unconfirmed_slate = _effective_multiplier(lines, displayed_m)
    if unconfirmed_slate and platform in PREDICTION_PLATFORMS:
        print(PREDICTION_BANNER)
    elif unconfirmed_slate and platform not in SPORTSBOOK_PLATFORMS:
        print(UNCONFIRMED_BANNER)
    elif unconfirmed_slate:
        print(
            f"{display_name(platform).upper()}: no slate-wide displayed price — ranking "
            "uses per-row slip_odds / product of leg_odds. Confirm the ticket "
            "in-app."
        )

    dists = read_distributions(args.distributions)
    banner_size = sizes[0]
    if priced_venue and effective_m is None:
        implied = 0.0
        per_leg = 0.0
    elif len(sizes) > 1:
        implied = 0.0
        per_leg = 0.0
    else:
        table = resolve_payout(
            platform,
            args.mode,
            banner_size,
            displayed_multiplier=effective_m,
            profile_dir=args.profile_dir,
        )
        implied = implied_slip_win(table.all_hit)
        per_leg = breakeven_per_leg(table.all_hit, banner_size)
    roster = None if getattr(args, "no_roster", False) else load_roster(args.roster)
    live, excluded = evaluate_legs(
        lines,
        dists,
        implied_p=per_leg,
        method=args.devig_method,
        allow_integer_lines=args.allow_integer_lines,
        platform=platform,
        roster=roster,
    )
    dropped = [leg for leg in excluded if leg.warn not in {"scratch"}]
    scratched = [leg for leg in excluded if leg.warn == "scratch"]
    print(
        f"lines={len(lines)} live={len(live)} dropped={len(dropped)} "
        f"scratched={len(scratched)}"
    )
    if roster is not None:
        print(f"roster=NFL {roster.season} ({roster.retrieved})")
    for leg in dropped:
        extra = ""
        if roster is not None and leg.warn == "wrong-team":
            found = lookup_player(leg.line, roster)
            if found:
                extra = f" (roster {found.team}, csv {leg.line.team})"
        print(f"  dropped {leg.line.player_name}: {leg.warn}{extra}")
    for leg in scratched:
        print(f"  scratched {leg.line.player_name}")

    if strict and dropped:
        print("strict mode: refusing to rank with dropped legs; fix the rows or pass --no-strict")
        return 2

    notes: list[str] = []
    slips = rank_slip_sizes(
        live,
        platform=platform,
        mode=args.mode,
        sizes=sizes,
        n_sims=args.n_sims,
        seed=args.seed,
        displayed_multiplier=displayed_m,
        profile_dir=args.profile_dir,
        max_slips=args.max_slips,
        allow_large_enum=args.allow_large_enum,
        shade_pp=args.shade_pp,
        notes=notes,
        min_odds=getattr(args, "min_odds", None),
        max_odds=getattr(args, "max_odds", None),
    )
    for note in notes:
        print(f"  {note}")
    write_csv(out_csv, [slip_as_row(slip, i) for i, slip in enumerate(slips, start=1)], EDGE_FIELDS)
    bankroll_note = _bankroll_note(getattr(args, "bankroll", None), 1)
    card = slip_card(slips, bankroll_note=bankroll_note)
    target = report_path or out_csv.with_suffix(".report.txt")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(card + "\n", encoding="utf-8")
    print(card)
    print(f"wrote {out_csv}")
    if implied > 0:
        print(f"implied slip win {implied:.4f}; per-leg breakeven {per_leg:.4f}")
    return 0


def _cmd_rank(args: argparse.Namespace) -> int:
    return _rank_and_write(args, args.out, args.report)


def _cmd_grade(args: argparse.Namespace) -> int:
    summary = grade_ledger(
        args.ledger,
        profile_dir=args.profile_dir,
        default_platform=normalize_platform(args.platform),
    )
    write_grade(summary, args.out)
    print(json.dumps(summary.__dict__, indent=2))
    print(STANDARD_DISCLAIMER)
    return 0


def _cmd_devig(args: argparse.Namespace) -> int:
    result = devig_two_way(args.over, args.under, method=args.method)
    spread = devig_spread(args.over, args.under)
    print(
        json.dumps(
            {
                "p_over": round(result.p_over, 6),
                "p_under": round(result.p_under, 6),
                "method": result.method,
                "k_exponent": round(result.k_exponent, 6),
                "market_width_cents": result.market_width_cents,
                "raw_overround": round(result.raw_overround, 6),
                "multiplicative_p_over": round(float(spread["multiplicative_p_over"]), 6),
                "additive_p_over": round(float(spread["additive_p_over"]), 6),
                "spread_pp": round(float(spread["spread_pp"]), 4),
                "unstable_devig": bool(spread["unstable"]),
            },
            indent=2,
        )
    )
    if spread["unstable"]:
        print("UNSTABLE_DEVIG")
    return 0


def _cmd_compare(args: argparse.Namespace) -> int:
    report = pickem_gap(
        odds_over=args.over,
        odds_under=args.under,
        platform=args.platform,
        legs=args.legs,
        mode=args.mode,
        method=args.method,
        side=args.side,
        displayed_multiplier=args.displayed_multiplier,
    )
    print(report)
    print()
    print(STANDARD_DISCLAIMER)
    return 0


def _cmd_run(args: argparse.Namespace) -> int:
    out_dir = args.out_dir or Path("runs") / args.slate_id
    out_dir.mkdir(parents=True, exist_ok=True)
    return _rank_and_write(args, out_dir / "edges.csv", out_dir / "report.txt")


def _cmd_slate(args: argparse.Namespace) -> int:
    platform = normalize_platform(args.platform)
    games = read_games(args.games)
    if not games:
        raise ValueError(f"no games in {args.games}")
    if getattr(args, "environment", None) is not None:
        environment = read_environment(args.environment)
        for game_id in missing_env_games(games, environment):
            print(f"ENVIRONMENT_MISSING_GAME: {game_id}")
    roster = load_roster(args.roster)
    slate_id = args.slate_id or next((game.slate_id for game in games if game.slate_id), "")
    rows: list[dict[str, object]] = []
    for game in games:
        for team, opp in ((game.away, game.home), (game.home, game.away)):
            for player in sorted(
                (entry for entry in roster.players.values() if entry.team == team),
                key=lambda entry: entry.name,
            ):
                rows.append(
                    {
                        "slate_id": slate_id,
                        "platform": platform,
                        "player_name": player.name,
                        "player_key": player.player_key,
                        "team": player.team,
                        "opp": opp,
                        "stat_type": "",
                        "line": "",
                        "side": "more",
                        "line_type": "standard",
                        "captured_at": "",
                        "injury_status": "",
                        "book_over": "",
                        "book_under": "",
                        "leg_odds": "",
                        "slip_odds": "",
                        "slip_multiplier": "",
                        "ticket_id": "",
                        "fair_p": "",
                        "contract_price": "",
                    }
                )
    if not rows:
        raise ValueError(
            "roster has no players on these games; pass --roster or update the games file"
        )
    write_csv(args.out, rows, SLATE_FIELDS)
    print(f"slate rows={len(rows)} games={len(games)} roster=NFL {roster.season}")
    print(f"wrote {args.out}")
    print("fill in stat_type, line, side, and your book odds, then run compose/rank")
    print("do not submit — type the ticket in-app")
    return 0


def _weather_market_reviews(tickets: list, environment: dict) -> list[str]:
    """Warn on windy ``first_td`` / ``pass_yds`` legs. The leg stays."""

    notes: list[str] = []
    for ticket in tickets:
        for leg in ticket:
            stat = leg.line.stat_type
            if stat not in {"first_td", "pass_yds"}:
                continue
            row = env_for(environment, leg.line.team, leg.line.opponent)
            if row is None or row.wind_mph is None or row.wind_mph < 10:
                continue
            notes.append(
                f"WEATHER_MARKET_REVIEW: {row.team}@{row.opponent} "
                f"wind {row.wind_mph:g} {stat} {leg.line.player_name}"
            )
    return notes


def _cmd_compose(args: argparse.Namespace) -> int:
    captured_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    strict = getattr(args, "strict", True)
    platform = normalize_platform(args.platform)
    auto = bool(getattr(args, "auto", False))
    markets_text = getattr(args, "markets", None)
    if markets_text is None and auto:
        markets_text = ",".join(AUTO_MARKETS)
    market_filter = parse_markets(markets_text) or None
    legs_text = getattr(args, "legs", None)
    if legs_text is None and auto:
        legs_text = "2"
    sizes = resolve_slip_sizes(args.slip_size, legs_text)
    min_odds = args.min_odds
    max_odds = args.max_odds
    if auto:
        if min_odds is None:
            min_odds = 150
        if max_odds is None:
            max_odds = 400
        # One explicit bound must not fight the other default into an empty
        # window: --min-odds +800 (first-TD longshot) drops the +400 cap,
        # --max-odds +250 keeps the +150 floor.
        if (
            args.min_odds is not None
            and args.max_odds is None
            and american_to_decimal(min_odds) > american_to_decimal(max_odds)
        ):
            max_odds = None
        elif (
            args.max_odds is not None
            and args.min_odds is None
            and american_to_decimal(max_odds) < american_to_decimal(min_odds)
        ):
            min_odds = None
    n_tickets = args.n_tickets
    if n_tickets < 1:
        raise ValueError("--n-tickets must be at least 1")

    late_path = getattr(args, "alert_late_active", None)
    if late_path is not None and not Path(late_path).is_file():
        raise FileNotFoundError(f"late-active file missing: {late_path}")

    lines = read_manual_lines(args.lines, strict=strict)
    lines = [
        row
        for row in lines
        if (not row.platform or normalize_platform(row.platform) == platform)
    ]
    ticket_id = getattr(args, "ticket_id", None)
    if ticket_id:
        lines = [row for row in lines if row.ticket_id == str(ticket_id)]
    if late_path is not None:
        for note in late_active_alerts(lines, late_path):
            print(note)
    if getattr(args, "enforce_market_depth", False):
        thin = thin_catalog_games(lines)
        if thin:
            print("CATALOG_THIN_MANUAL_INPUT_REQUIRED")
            for game in thin:
                print(f"  {game.label}")
            if not getattr(args, "allow_thin_catalog", False):
                return 2
    if market_filter:
        lines = [row for row in lines if row.stat_type in market_filter]
    if not lines:
        raise ValueError(
            f"no rows for platform {platform}; check --lines, --ticket-id, --markets"
        )
    slate_ids = {row.slate_id for row in lines if row.slate_id}
    if len(slate_ids) > 1:
        raise ValueError(f"mixed slate_id values in lines file: {sorted(slate_ids)}")

    effective_m, unconfirmed_slate = _effective_multiplier(lines, None)
    if unconfirmed_slate and platform in PREDICTION_PLATFORMS:
        print(PREDICTION_BANNER)
    priced_venue = platform in SPORTSBOOK_PLATFORMS or platform in PREDICTION_PLATFORMS
    if effective_m is not None and priced_venue:
        table = resolve_payout(
            platform,
            args.mode,
            sizes[0],
            displayed_multiplier=effective_m,
            profile_dir=args.profile_dir,
        )
        per_leg = breakeven_per_leg(table.all_hit, sizes[0])
    else:
        per_leg = 0.0
    dists = read_distributions(args.distributions) if args.distributions else {}
    roster = None if getattr(args, "no_roster", False) else load_roster(args.roster)
    live, excluded = evaluate_legs(
        lines,
        dists,
        implied_p=per_leg,
        method=args.devig_method,
        allow_integer_lines=False,
        platform=platform,
        roster=roster,
    )
    dropped = [leg for leg in excluded if leg.warn not in {"scratch"}]
    print(
        f"lines={len(lines)} live={len(live)} dropped={len(dropped)} "
        f"scratch={len(excluded) - len(dropped)}"
    )
    for leg in dropped:
        print(f"  dropped {leg.line.player_name}: {leg.warn}")
    if strict and dropped:
        print("strict mode: refusing to compose with dropped legs; fix the rows")
        return 2

    environment = read_environment(args.environment)
    handoff = None
    dfs_path = getattr(args, "from_ceminidfs", None)
    if dfs_path is not None:
        handoff = load_ceminidfs_handoff(dfs_path)
        if handoff.missing:
            print(handoff.note)
        else:
            environment = merge_implied_totals(environment, handoff.rows)
            for note in exposure_notes(handoff.rows):
                print(note)

    raw_market_cap = getattr(args, "max_legs_per_market", None)
    if raw_market_cap is None and auto:
        max_legs_per_market: int | None = 2
    elif raw_market_cap is None or raw_market_cap == 0:
        max_legs_per_market = None
    else:
        max_legs_per_market = raw_market_cap

    tickets = compose_tickets(
        live,
        n_tickets=n_tickets,
        sizes=sizes,
        min_odds=min_odds,
        max_odds=max_odds,
        markets=market_filter,
        environment=environment,
        max_legs_per_market=max_legs_per_market,
    )
    if args.environment is not None:
        for note in _weather_market_reviews(tickets, environment):
            print(note)
    out_dir = args.out_dir or Path("runs") / (next(iter(slate_ids), "compose"))
    out_dir.mkdir(parents=True, exist_ok=True)
    if args.environment is not None:
        games = {
            tuple(sorted({leg.line.team, leg.line.opponent}))
            for ticket in tickets
            for leg in ticket
            if leg.line.team and leg.line.opponent
        }
        itt_rows = env_rows_for_games(environment, games) if tickets else []
        source = Path(args.environment).name
        if handoff is not None and not handoff.missing:
            source = f"{source}+{Path(dfs_path).name}"
        write_compose_itt(
            out_dir / "compose_itt.json",
            captured_at=captured_at,
            source=source,
            rows=itt_rows,
        )
    slips = []
    for index, ticket_legs in enumerate(tickets, start=1):
        composed_id = f"compose-{index:03d}"
        write_csv(
            out_dir / f"ticket-{index:03d}.csv",
            ticket_rows(ticket_legs, composed_id, platform),
            TICKET_FIELDS,
        )
        estimate, _source, unconfirmed_estimate = estimate_multiplier(ticket_legs)
        priced = rank_slips(
            ticket_legs,
            platform=platform,
            mode=args.mode,
            slip_size=len(ticket_legs),
            displayed_multiplier=estimate,
            profile_dir=args.profile_dir,
            priors_path=None,
            max_slips=1,
            shade_pp=0.0,
            notes=[],
        )
        if not priced:
            print(f"  ticket-{index:03d}: no price available; skipped on the card")
            continue
        slip = priced[0]
        if unconfirmed_estimate and slip.multiplier_source == "cli":
            slip.multiplier_unconfirmed = True
            slip.kelly = 0.0
            slip.notes.append(
                "naive product of typed prices — confirm the ticket price in-app"
            )
        slips.append(slip)

    bankroll_note = _bankroll_note(getattr(args, "bankroll", None), len(tickets) or 1)
    card = slip_card(slips, bankroll_note=bankroll_note)
    card_path = out_dir / "card.txt"
    card_path.write_text(card + "\n", encoding="utf-8")
    card_md = getattr(args, "card_md", None)
    md_path: Path | None = None
    if card_md is not None:
        md_path = Path(card_md)
        if not md_path.is_absolute():
            md_path = out_dir / md_path
        md_path.write_text(_compose_card_md(tickets), encoding="utf-8")
    print(f"composed={len(tickets)} requested={n_tickets} out={out_dir}")
    for warning in concentration_warnings(tickets):
        print(f"warning: {warning}")
    print(card)
    print(f"wrote {card_path}")
    if md_path is not None:
        print(f"wrote {md_path}")
    if args.environment is not None:
        print(f"wrote {out_dir / 'compose_itt.json'}")
    print("do not submit — type every ticket in-app")
    max_n = getattr(args, "max_exposure_per_player", None)
    if max_n is not None:
        counts = player_stat_ticket_counts(tickets)
        if any(count > max_n for count in counts.values()):
            return 2
    return 0


def _compose_card_md(tickets: list) -> str:
    """Redacted markdown card: legs only. No stake, wallets, or API keys."""

    lines = [
        "# CeminiParlays card",
        "",
        "do not submit — type every ticket in-app",
        "",
    ]
    if not tickets:
        lines.append("No tickets composed.")
        return "\n".join(lines) + "\n"
    for index, ticket in enumerate(tickets, start=1):
        lines.append(f"## Ticket {index}")
        for leg in ticket:
            line = leg.line
            lines.append(f"- {line.player_name} {line.stat_type} {line.line}")
        lines.append("")
    lines.append("do not submit — type every ticket in-app")
    return "\n".join(lines) + "\n"


def _cmd_diff(args: argparse.Namespace) -> int:
    card = read_ticket_table(args.card)
    booked = read_ticket_table(args.booked)
    lines = diff_ticket_lines(card, booked)
    for line in lines:
        print(line)
    emit = getattr(args, "emit_ledger", None)
    if emit is not None and not args.accept_booked:
        print("--emit-ledger requires --accept-booked")
        return 2
    if not lines:
        if emit is not None:
            write_booked_ledger(emit, booked)
            print(f"wrote {emit}")
        return 0
    print(BOOKED_WINS)
    if args.accept_booked:
        print(ACCEPTED)
        if emit is not None:
            write_booked_ledger(emit, booked)
            print(f"wrote {emit}")
        return 0
    return 2


def _cmd_fetch(args: argparse.Namespace) -> int:
    notes: list[str] = []
    captured_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    utc_date = getattr(args, "utc_date", None)
    if utc_date:
        day = parse_fetch_date(utc_date)
    else:
        day = parse_fetch_date(args.date, tzinfo=ZoneInfo("America/New_York"))
    slate_id = args.slate_id or day.isoformat()
    platforms = parse_books(args.books)
    stats = parse_markets(args.markets)
    roster = None if args.no_roster else load_roster(args.roster)
    meta: dict[str, str] = {}

    if args.fixture:
        events, meta = load_fixture(args.fixture)
    else:
        api_key = resolve_api_key()
        if utc_date:
            commence_from, commence_to = utc_day_window(day)
        else:
            commence_from, commence_to = et_slate_window(day)
        events, meta = pull_event_odds(
            sport_key_for(args.sport),
            commence_from=commence_from,
            commence_to=commence_to,
            regions=args.regions,
            markets=",".join(STAT_TO_MARKET[stat] for stat in stats),
            bookmakers=",".join(bookmakers_for_platforms(platforms)),
            api_key=api_key,
        )
        remaining = meta.get("x-requests-remaining", "")
        used = meta.get("x-requests-used", "")
        print(f"host=api.the-odds-api.com remaining={remaining} used={used}")

    rows = rows_from_events(
        events,
        platform_filter=set(platforms),
        roster=roster,
        slate_id=slate_id,
        captured_at=captured_at,
        notes=notes,
    )
    if stats:
        rows = [row for row in rows if row["stat_type"] in stats]
    write_fetch_csv(args.out, rows, force=args.force)
    remaining = meta.get("x-requests-remaining", "")
    used = meta.get("x-requests-used", "")
    if remaining or used:
        print(f"x-requests-remaining={remaining} x-requests-used={used}")
    for note in notes:
        print(f"  {note}")
    print(f"rows={len(rows)} events={len(events)} remaining={remaining}")
    print(f"wrote {args.out}")
    print("do not submit — type the ticket in-app")
    return 0


def _cmd_bankroll(args: argparse.Namespace) -> int:
    flat = flat_stake(args.bankroll, args.n_tickets)
    cap = kelly_cap_stake(args.bankroll)
    print(
        f"bankroll ${args.bankroll:.2f} over {args.n_tickets} tickets: "
        f"flat ${flat:.2f} each"
    )
    print(f"quarter-Kelly cap (5% of bankroll): ${cap:.2f} per ticket")
    print("pick one size per ticket; never add Kelly fractions across legs")
    print(STANDARD_DISCLAIMER)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    handlers = {
        "fair": _cmd_fair,
        "rank": _cmd_rank,
        "grade": _cmd_grade,
        "devig": _cmd_devig,
        "compare": _cmd_compare,
        "run": _cmd_run,
        "slate": _cmd_slate,
        "compose": _cmd_compose,
        "diff": _cmd_diff,
        "bankroll": _cmd_bankroll,
        "fetch": _cmd_fetch,
    }
    try:
        return handlers[args.command](args)
    except (ValueError, FileNotFoundError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


def main_fair() -> int:
    return main(["fair", *sys.argv[1:]])


def main_rank() -> int:
    return main(["rank", *sys.argv[1:]])


def main_grade() -> int:
    return main(["grade", *sys.argv[1:]])


if __name__ == "__main__":
    raise SystemExit(main())
