from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime, timezone
from math import isnan
from pathlib import Path
from zoneinfo import ZoneInfo

from ceminiparlays import STANDARD_DISCLAIMER, __version__
from ceminiparlays.bankroll import flat_stake, kelly_cap_stake
from ceminiparlays.catalog import thin_catalog_games
from ceminiparlays.closings import write_prop_closes
from ceminiparlays.clv import clv_report, collect_legs, format_clv_report, write_clv_json
from ceminiparlays.delta_rho import game_key_for, game_state, score_game
from ceminiparlays.jev_client import DEFAULT_CACHE_DIR, PROVIDERS, JevClient
from ceminiparlays.jev_sizing import (
    DEFAULT_SLATE_PCT,
    DEFAULT_TICKET_CAP_PCT,
    TicketInput,
    size_tickets,
    write_sizing_report,
)
from ceminiparlays.season_ledger import BrierPair, append_ledger, ledger_row
from ceminiparlays.ceminidfs import (
    distribution_index,
    exposure_notes,
    load_ceminidfs_handoff,
    merge_implied_totals,
)
from ceminiparlays.proppricing import (
    BookQuote,
    consensus_fair_p_over,
    disagreement_edge_bps,
    p_dfs_over,
    posterior_fair,
)
from ceminiparlays.compose import (
    TICKET_FIELDS,
    compose_tickets,
    concentration_warnings,
    drop_unavailable_first_td,
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
from ceminiparlays.late_active import (
    apply_inactive_scratch,
    in_game_exit_warnings,
)
from ceminiparlays.fair import p_over_line, side_probability
from ceminiparlays.fetch import load_fixture, rows_from_events, write_fetch_csv
from ceminiparlays.grade import grade_ledger, write_grade
from ceminiparlays.jev_gate import (
    append_card_verdict,
    evaluate_gate,
    format_mark,
    gate_exit_code,
    load_card,
    verdict_line,
    write_jev_gate_report,
)
from ceminiparlays.io import read_distributions, read_games, read_manual_lines, write_csv
from ceminiparlays.kelly import stake_dollars
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
    DEFAULT_MIN_EDGE,
    EDGE_FIELDS,
    edge_failures,
    edge_status,
    evaluate_legs,
    rank_slip_sizes,
    rank_slips,
    resolve_slip_sizes,
    slip_as_row,
)

UNCONFIRMED_BANNER = "UNCONFIRMED TABLE MULTIPLIER — confirm in-app"

#: Synthetic book name for the sharp reference quotes on a line row. It must
#: never collide with a bet platform, or the non-circular de-vig would exclude
#: the only quote it has.
REFERENCE_BOOK_SLOT = "__reference__"
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
    "commence_time",
    "injury_status",
    "book_over",
    "book_under",
    "leg_odds",
    "slip_odds",
    "slip_multiplier",
    "ticket_id",
    "fair_p",
    "contract_price",
    "ref_p",
    "ref_book_over",
    "ref_book_under",
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
        "rush_att,pass_tds (alias pass_td),two_plus_td,first_td,anytime_td,"
        "h2h,spreads,totals",
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
    parser.add_argument(
        "--allow-rec-line",
        action="store_true",
        help="Keep a rec_yds leg at 50 or higher. Default bars 50+ (49.5 stays).",
    )
    parser.add_argument(
        "--min-edge",
        type=float,
        default=None,
        help=(
            "Modeled-edge floor (model P - market implied P). When set, a leg "
            "below it fails closed with exit 2. Omitted means annotate only."
        ),
    )
    parser.add_argument(
        "--require-model",
        action="store_true",
        help=(
            "Drop a leg whose only fair value is a market price (same-book "
            "de-vig, TD leg odds, or a contract mid). Default keeps it and marks "
            "it no-edge."
        ),
    )
    parser.add_argument(
        "--allow-unmodeled-correlation",
        action="store_true",
        help=(
            "Price a same-game pair that has no prior in correlation_priors.json "
            "with the old guessed fallback. Default skips the combo."
        ),
    )
    parser.add_argument(
        "--max-line-age",
        type=float,
        default=None,
        help=(
            "Drop a line whose captured_at is older than this many minutes. "
            "Omitted means no age check. A leg whose game has already kicked "
            "off by commence_time is always dropped."
        ),
    )
    parser.add_argument(
        "--games",
        type=Path,
        default=None,
        help=(
            "Optional games file (away/home). When set, a leg whose team and "
            "opp are not in that file is dropped with warn off-card. Omitted "
            "means no filtering."
        ),
    )
    parser.add_argument(
        "--jev-correlation",
        action="store_true",
        help=(
            "Ask Jev four regime questions per game and perturb the leg-pair "
            "correlations before the copula runs. Needs --environment. Off by "
            "default: the static prior table is used alone."
        ),
    )
    parser.add_argument(
        "--jev-provider",
        default="auto",
        choices=list(PROVIDERS),
        help=(
            "Jev transport for --jev-correlation and jev-gate --size: auto tries "
            "typesafe, then mcp, then openrouter. A named provider never fails over."
        ),
    )
    parser.add_argument(
        "--jev-cache-dir",
        type=Path,
        default=None,
        help=f"Jev answer cache. Default {DEFAULT_CACHE_DIR}.",
    )
    parser.add_argument(
        "--dfs-pricing",
        action="store_true",
        help=(
            "Price every leg from the CeminiDFS split-normal against the "
            "non-circular reference book, and write p_dfs_over / p_market_fair / "
            "p_fair_posterior / disagreement_edge_bps to edges.csv. Needs "
            "--from-ceminidfs and ref_book_over/ref_book_under on the rows "
            "(fetch --reference-book stamps them). Off by default."
        ),
    )
    parser.add_argument(
        "--from-ceminidfs",
        type=Path,
        default=None,
        help="CeminiDFS handoff CSV that supplies the leg distributions for --dfs-pricing.",
    )
    parser.add_argument(
        "--jev-regime-conf",
        type=float,
        default=0.0,
        help=(
            "Jev regime confidence in [0, 1] used to weight the DFS distribution "
            "in --dfs-pricing. 0 keeps the posterior on the market fair while "
            "still measuring disagreement_edge_bps."
        ),
    )
    parser.add_argument("--shade-pp", type=float, default=0.0)
    parser.add_argument(
        "--environment",
        type=Path,
        default=None,
        help=(
            "Optional env CSV. A first_td leg whose game row marks first_td "
            "none/no/false is skipped. Missing file is a no-op."
        ),
    )
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
    grade.add_argument(
        "--season-ledger",
        type=Path,
        default=None,
        help=(
            "Append one row to this persistent season CLV ledger after grading. "
            "Omitted writes nothing. Keeps week-over-week CLV in one file."
        ),
    )
    grade.add_argument(
        "--week",
        default="",
        help="Week label stamped into the --season-ledger row.",
    )
    grade.add_argument(
        "--from-ceminidfs",
        type=Path,
        default=None,
        help=(
            "CeminiDFS handoff CSV. Adds a per-leg dfs_vs_close_brier_delta to "
            "grade.json and a dfs_handoff_brier_lift to the season ledger. "
            "Omitted grades exactly as before."
        ),
    )
    grade.add_argument(
        "--games",
        type=Path,
        default=None,
        help="Slate window. A ticket whose game is outside this file is off_card.",
    )
    grade.add_argument(
        "--card",
        type=Path,
        default=None,
        help=(
            "Compose card CSV or card.json. A ticket_id that is not on this card "
            "is off_card. A null card puts every booked ticket off-card."
        ),
    )
    grade.add_argument(
        "--closings",
        type=Path,
        default=None,
        help=(
            "Per-prop closing snapshot CSV. Fills a blank close_* ledger cell by "
            "(platform, player_key, stat_type, side) and computes CLV."
        ),
    )

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
    compose.add_argument(
        "--allow-rec-line",
        action="store_true",
        help="Keep a rec_yds leg at 50 or higher. Default bars 50+ (49.5 stays).",
    )
    compose.add_argument(
        "--games",
        type=Path,
        default=None,
        help=(
            "Optional games file. When set, a leg whose team and opp are not in "
            "that file is dropped with warn off-card. Omitted means no filter."
        ),
    )
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
    compose.add_argument(
        "--min-edge",
        type=float,
        default=DEFAULT_MIN_EDGE,
        help=(
            "Modeled-edge floor per leg (model P - market implied P). A leg below "
            "the floor is marked on the card and compose exits 2. Default 0.01."
        ),
    )
    compose.add_argument("--bankroll", type=float, default=None)
    compose.add_argument(
        "--require-model",
        action="store_true",
        help=(
            "Drop a leg whose only fair value is a market price (same-book "
            "de-vig, TD leg odds, or a contract mid). Default keeps it and marks "
            "it no-edge."
        ),
    )
    compose.add_argument(
        "--allow-unmodeled-correlation",
        action="store_true",
        help=(
            "Price a same-game pair that has no prior in correlation_priors.json "
            "with the old guessed fallback. Default skips the combo."
        ),
    )
    compose.add_argument(
        "--max-line-age",
        type=float,
        default=None,
        help=(
            "Drop a line whose captured_at is older than this many minutes. A "
            "leg whose game has already kicked off is always dropped."
        ),
    )
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

    closings = sub.add_parser(
        "closings",
        help="Snapshot per-prop closing lines into a CSV (for CLV)",
    )
    _add_common(closings)
    closings.add_argument(
        "--lines",
        type=Path,
        required=True,
        help="A fresh lines CSV (run fetch near kickoff, then point here).",
    )
    closings.add_argument(
        "--out", type=Path, default=Path("runs/closing_props.csv")
    )
    closings.add_argument(
        "--force", action="store_true", help="Overwrite --out if it exists"
    )

    clv = sub.add_parser(
        "clv",
        help="Season CLV summary over graded ledgers: prove, kill, or keep collecting",
        description=(
            "Read one or more graded ledger CSVs and report leg-level closing "
            "line value: n, mean/median/stdev in percentage points, a one-sided "
            "t-stat and p-value for mean > 0, a positive-CLV rate, breakdowns by "
            "platform / stat_type / market, and a verdict. It reads; it does not "
            "submit or place a bet."
        ),
    )
    clv.add_argument(
        "--ledger",
        type=Path,
        action="append",
        required=True,
        dest="ledger",
        help="A graded ledger CSV. Repeatable; every ledger is combined.",
    )
    clv.add_argument(
        "--min-legs",
        type=int,
        default=100,
        help="Independent-leg target for the verdict (default 100).",
    )
    clv.add_argument(
        "--json", action="store_true", help="Print the summary as JSON."
    )
    clv.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Also write the summary JSON to this path.",
    )

    jev = sub.add_parser(
        "jev-gate",
        help="Mark a composed card with Jev before you type",
        description=(
            "Run after compose and before you type. "
            "Writes jev_gate_report.csv. "
            "The gate marks each row. It does not reprice, void, rewrite, or submit. "
            "It fails closed: a block, a do_not_type, or a thesis_unsupported row "
            "exits 2. Pass --allow-flagged to let a contradiction through."
        ),
    )
    jev.add_argument("--card", type=Path, required=True, help="compose card.json")
    jev.add_argument("--lines", type=Path, required=True, help="Lines CSV used as evidence")
    jev.add_argument(
        "--environment",
        type=Path,
        default=None,
        help="Environment CSV. Required for a pass_yds thesis. A missing file blocks.",
    )
    jev.add_argument(
        "--late-active",
        type=Path,
        default=None,
        help="Late-active or inactives CSV. A missing file marks review and does not call Jev.",
    )
    jev.add_argument(
        "--promo-terms",
        default="",
        help="Promo terms text. Blank marks review and does not call Jev.",
    )
    jev.add_argument("--out-dir", type=Path, required=True, help="Folder for jev_gate_report.csv")
    jev.add_argument(
        "--fixture",
        type=Path,
        default=None,
        help="Recorded Jev exchanges. Skips the server. No key and no network.",
    )
    jev.add_argument(
        "--record-fixture",
        type=Path,
        default=None,
        help="Append each live exchange to this JSON file.",
    )
    jev.add_argument(
        "--size",
        action="store_true",
        help=(
            "Also size the slate: run the two-stage epistemic Kelly controller and "
            "write jev_gate_sizing.csv. Needs --environment. Off by default; the "
            "gate stays a marker and never sizes."
        ),
    )
    jev.add_argument(
        "--edges",
        type=Path,
        default=None,
        help=(
            "edges.csv from rank. Supplies kelly_quarter per ticket_id for --size. "
            "A ticket with no row sizes to zero."
        ),
    )
    jev.add_argument(
        "--max-ticket-pct",
        type=float,
        default=DEFAULT_TICKET_CAP_PCT,
        help=f"Bankroll share for one ticket (default {DEFAULT_TICKET_CAP_PCT}).",
    )
    jev.add_argument(
        "--max-slate-pct",
        type=float,
        default=DEFAULT_SLATE_PCT,
        help=f"Bankroll share for the whole slate (default {DEFAULT_SLATE_PCT}).",
    )
    jev.add_argument(
        "--jev-provider",
        default="auto",
        choices=list(PROVIDERS),
        help="Jev transport for --size: auto, typesafe, mcp, or openrouter.",
    )
    jev.add_argument("--jev-cache-dir", type=Path, default=None)
    jev.add_argument(
        "--allow-flagged",
        action="store_true",
        help=(
            "Let a do_not_type or thesis_unsupported row through (exit 0). A "
            "block row still exits 2. Default fails closed on all three."
        ),
    )

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
    fetch.add_argument(
        "--closing-snapshot",
        action="store_true",
        help=(
            "Also freeze the two-way prop lines into runs/<week>/closing_lines.csv "
            "for CLV. Run this inside the last minutes before kickoff. Needs --week."
        ),
    )
    fetch.add_argument(
        "--week",
        default=None,
        help=(
            "Run folder under runs/ for --closing-snapshot, e.g. 2026-w05-sun. "
            "The snapshot is written to runs/<week>/closing_lines.csv."
        ),
    )
    fetch.add_argument("--roster", type=Path, default=None)
    fetch.add_argument("--no-roster", action="store_true")
    fetch.add_argument(
        "--reference-book",
        default=None,
        choices=PLATFORM_CHOICES,
        help=(
            "Stamp this book's de-vigged quotes on every other book's rows as "
            "ref_book_over/ref_book_under (ref_p for TD pools). Default: pick the "
            "sharpest fetched book that is not the bet platform."
        ),
    )
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


def _stake_rule(bankroll: float | None) -> str:
    """Name the stake rule recorded on the card."""

    return "no-bankroll" if bankroll is None else "quarter-kelly 5% cap"


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


def _flag_value(value: object) -> str:
    if value is None:
        return "*"
    text = str(value).strip()
    return text if text else "*"


def _flag_path(value: object) -> str:
    if value is None:
        return "-"
    return str(value)


def _print_command_flags(
    *,
    legs: object,
    markets: object,
    min_odds: object,
    max_odds: object,
    n_tickets: object,
    environment: object,
    handoff: object,
) -> None:
    """One stdout line of applied flags before CSV reads."""

    print(
        "flags "
        f"legs={_flag_value(legs)} "
        f"markets={_flag_value(markets)} "
        f"min_odds={_flag_value(min_odds)} "
        f"max_odds={_flag_value(max_odds)} "
        f"n_tickets={_flag_value(n_tickets)} "
        f"environment={_flag_path(environment)} "
        f"handoff={_flag_path(handoff)}"
    )


def _game_keys(path: Path) -> set[tuple[str, str]]:
    """Unordered team pairs from a games file, for the ``--games`` off-card guard."""

    games = read_games(path)
    return {tuple(sorted({game.away, game.home})) for game in games if game.away and game.home}


def _off_card_filter(
    lines: list,
    games_path: Path | None,
) -> tuple[list, list]:
    """Drop legs whose team/opp pair is absent from ``--games``.

    Returns ``(kept, dropped)``. ``None`` path means no filtering. A leg whose
    team and opponent are absent from the file is warned ``off-card``. The
    filtered read is not used to infer a slate day or widen the fetch window.
    """

    if games_path is None:
        return lines, []
    keys = _game_keys(games_path)
    kept: list = []
    dropped: list = []
    for row in lines:
        pair = tuple(sorted({(row.team or "").upper(), (row.opponent or "").upper()}))
        if pair in keys:
            kept.append(row)
        else:
            dropped.append(row)
    return kept, dropped


def _require_environment_fields(tickets: list, environment: dict) -> None:
    """Fail loud when a written ticket needs a blank implied_total.

    Compose scores on ITT. A blank ``implied_total`` on a ticket game must not
    produce a card or ``compose_itt.json``. Blank ``spread`` alone is common in
    operator env files and is not scored here. Only runs when ``--environment``
    pointed at a present file that yielded rows. A missing file stays a skip.
    Does not invent numbers.
    """

    if not environment or not tickets:
        return
    for ticket in tickets:
        for leg in ticket:
            row = env_for(environment, leg.line.team, leg.line.opponent)
            if row is None:
                continue
            label = row.game_id or f"{leg.line.team}@{leg.line.opponent}"
            if row.implied_total is None:
                raise ValueError(
                    f"environment blank implied_total for {label} "
                    f"({leg.line.team}); fill the field or omit --environment"
                )


def _score_games_for_correlation(args: argparse.Namespace, environment: dict) -> dict:
    """Score each game's four regimes, one bundled Jev call per game.

    Fails closed: with no environment row there is no game state to score, so
    the operator gets an error rather than a silently unperturbed slate.
    """

    if not environment:
        raise ValueError(
            "--jev-correlation needs --environment with one row per game; "
            "there is no game state to score without it"
        )
    client = JevClient(
        provider=getattr(args, "jev_provider", "auto"),
        cache_dir=getattr(args, "jev_cache_dir", None) or DEFAULT_CACHE_DIR,
    )
    scores: dict = {}
    seen: set[str] = set()
    for row in environment.values():
        team = str(getattr(row, "team", "") or "")
        opponent = str(getattr(row, "opponent", "") or "")
        if not team or not opponent:
            continue
        key = game_key_for(team, opponent)
        if key in seen:
            continue
        seen.add(key)
        scores[key] = score_game(client, game_state(row))
    print(f"jev-correlation: scored {len(scores)} game(s) via {client.provider}")
    return scores


def _apply_dfs_pricing(
    live: list,
    handoff: object,
    platform: str,
    jev_regime_conf: float,
) -> int:
    """Price each leg's split-normal against the non-circular reference book.

    The reference book is a different book from the bet platform, so the de-vig
    is never circular. A leg with no handoff distribution, no reference price,
    or no typed line is left blank rather than guessed.
    """

    index = distribution_index(handoff)
    if not index:
        print("dfs-pricing: no handoff distributions; nothing priced")
        return 0
    priced = 0
    for leg in live:
        row = leg.line
        dist = index.get((row.player_key, row.stat_type))
        if dist is None:
            continue
        if _blank_cell(row.ref_book_over) or _blank_cell(row.ref_book_under):
            continue
        if row.line is None or isnan(row.line):
            continue
        consensus = consensus_fair_p_over(
            [BookQuote(REFERENCE_BOOK_SLOT, int(row.ref_book_over), int(row.ref_book_under))],
            target_book=platform,
        )
        if consensus is None:
            continue
        try:
            p_dfs, _family = p_dfs_over(dist, row.line, stat_type=row.stat_type)
        except (ValueError, TypeError):
            continue
        leg.p_dfs_over = p_dfs
        leg.p_market_fair = consensus.fair_p_over
        leg.p_fair_posterior = posterior_fair(
            consensus.fair_p_over, p_dfs, jev_regime_conf
        )
        leg.disagreement_edge_bps = disagreement_edge_bps(p_dfs, consensus.fair_p_over)
        priced += 1
    print(f"dfs-pricing: priced {priced} of {len(live)} live legs")
    return priced


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
    lines, off_card = _off_card_filter(lines, getattr(args, "games", None))
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
    environment = read_environment(getattr(args, "environment", None))
    live, excluded = evaluate_legs(
        lines,
        dists,
        implied_p=per_leg,
        method=args.devig_method,
        allow_integer_lines=args.allow_integer_lines,
        platform=platform,
        roster=roster,
        allow_high_receiving=bool(getattr(args, "allow_rec_line", False)),
        require_model=bool(getattr(args, "require_model", False)),
        environment=environment,
        max_line_age_minutes=getattr(args, "max_line_age", None),
    )
    if environment:
        kept = drop_unavailable_first_td(live, environment)
        for leg in live:
            if leg not in kept:
                print(f"  dropped {leg.line.player_name}: first_td-none")
        live = kept
    dropped = [leg for leg in excluded if leg.warn not in {"scratch"}]
    scratched = [leg for leg in excluded if leg.warn == "scratch"]
    print(
        f"lines={len(lines)} live={len(live)} dropped={len(dropped) + len(off_card)} "
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
    for row in off_card:
        print(f"  dropped {row.player_name}: off-card")
    for leg in scratched:
        print(f"  scratched {leg.line.player_name}")

    if strict and (dropped or off_card):
        print("strict mode: refusing to rank with dropped legs; fix the rows or pass --no-strict")
        return 2

    # Modeled-edge gate, same contract as compose: ``weak-edge`` fails closed
    # (exit 2) only when the operator sets --min-edge; ``no-edge`` (no model P at
    # all) is a loud flag and never a hard fail.
    min_edge = getattr(args, "min_edge", None)
    gate_floor = DEFAULT_MIN_EDGE if min_edge is None else min_edge
    edge_fails = edge_failures(live, gate_floor)
    for leg, token in edge_fails:
        shown = "na" if leg.prop_edge is None else f"{leg.prop_edge:+.4f}"
        print(
            f"EDGE-GATE {token}: {leg.line.player_name} {leg.line.stat_type} "
            f"prop_edge={shown} (floor {gate_floor:+.4f})"
        )
    if min_edge is not None and any(
        token == "weak-edge" for _leg, token in edge_fails
    ):
        print(
            f"edge gate: a leg is below --min-edge {min_edge:+.4f}; fix the rows, "
            "drop the leg, or lower --min-edge"
        )
        return 2

    if getattr(args, "dfs_pricing", False):
        handoff_path = getattr(args, "from_ceminidfs", None)
        if handoff_path is None:
            raise ValueError("--dfs-pricing needs --from-ceminidfs <handoff.csv>")
        handoff = load_ceminidfs_handoff(handoff_path)
        if handoff.missing:
            print(handoff.note)
        _apply_dfs_pricing(
            live,
            handoff,
            platform,
            float(getattr(args, "jev_regime_conf", 0.0) or 0.0),
        )

    scores_by_game: dict = {}
    if getattr(args, "jev_correlation", False):
        scores_by_game = _score_games_for_correlation(args, environment)

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
        allow_unmodeled_correlation=bool(
            getattr(args, "allow_unmodeled_correlation", False)
        ),
        scores_by_game=scores_by_game,
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
    _print_command_flags(
        legs=getattr(args, "legs", None),
        markets=getattr(args, "markets", None),
        min_odds=getattr(args, "min_odds", None),
        max_odds=getattr(args, "max_odds", None),
        n_tickets=getattr(args, "max_slips", None),
        environment=getattr(args, "environment", None),
        handoff="*",
    )
    return _rank_and_write(args, args.out, args.report)


def _cmd_grade(args: argparse.Namespace) -> int:
    dfs_path = getattr(args, "from_ceminidfs", None)
    handoff = load_ceminidfs_handoff(dfs_path) if dfs_path else None
    if handoff is not None and handoff.missing:
        print(handoff.note)
    summary = grade_ledger(
        args.ledger,
        profile_dir=args.profile_dir,
        default_platform=normalize_platform(args.platform),
        games_path=getattr(args, "games", None),
        card_path=getattr(args, "card", None),
        closings_path=getattr(args, "closings", None),
        handoff=handoff,
    )
    write_grade(summary, args.out)
    print(json.dumps(summary.__dict__, indent=2))
    season_ledger = getattr(args, "season_ledger", None)
    if season_ledger:
        legs = collect_legs([args.ledger])
        row = ledger_row(
            week=str(getattr(args, "week", "") or ""),
            legs=legs,
            run_date=datetime.now(timezone.utc).date().isoformat(),
            stake=float(getattr(summary, "stake", 0.0) or 0.0),
            pnl=float(getattr(summary, "net_pnl", 0.0) or 0.0),
            brier_pairs=[
                BrierPair(**pair) for pair in getattr(summary, "brier_pairs", [])
            ],
            ledgers=[args.ledger],
        )
        append_ledger(season_ledger, row)
        print(
            f"appended {season_ledger} n_legs={row['n_legs']} "
            f"mean_clv_bps={row['mean_clv_bps']} t_stat={row['t_stat']}"
        )
    if summary.partial_tickets:
        for item in summary.partial_tickets:
            print(
                f"PARTIAL {item['status']}: captured legs {item['captured_legs']}"
                f" N-Bet {item['visible_n_bet']} clipped={item['clipped']}"
            )
        print("do not submit — type the ticket in-app")
        print(STANDARD_DISCLAIMER)
        return 2
    print("do not submit — type the ticket in-app")
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
    _print_command_flags(
        legs=getattr(args, "legs", None),
        markets=getattr(args, "markets", None),
        min_odds=getattr(args, "min_odds", None),
        max_odds=getattr(args, "max_odds", None),
        n_tickets=getattr(args, "max_slips", None),
        environment="*",
        handoff="*",
    )
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


def _card_leg(leg, min_edge: float) -> dict[str, object]:
    """One leg on the machine-readable card, with its modeled edge."""

    line = leg.line
    return {
        "player_name": line.player_name,
        "player_key": line.player_key,
        "team": line.team,
        "opp": line.opponent,
        "stat_type": line.stat_type,
        "side": line.side,
        "line": None if isnan(line.line) else line.line,
        "bet_over": line.book_over,
        "bet_under": line.book_under,
        "leg_odds": line.leg_odds,
        "slip_odds": line.slip_odds,
        "fair_p": leg.fair_p,
        "model_p": leg.model_p,
        "model_source": leg.edge_source,
        "market_implied_p": leg.market_implied_p,
        "prop_edge": leg.prop_edge,
        "edge_status": edge_status(leg, min_edge),
        "source": leg.source,
        "warn": leg.warn,
        "injury_status": line.injury_status,
        "ticket_id": line.ticket_id,
        "captured_at": line.captured_at,
    }


def _compose_card_payload(
    *,
    captured_at: str,
    platform: str,
    reason: str,
    edge_gate: str,
    min_edge: float,
    tickets: list,
    slips: dict[int, object],
    dropped: list,
    off_card_rows: list,
    stake_by_ticket: dict[int, float | None],
    stake_rule: str,
    bankroll: float | None,
) -> dict[str, object]:
    """Build the machine-readable card. One object per ticket and per leg.

    The card is the bet-time snapshot. It carries the line, both prices, the
    model P, the market implied P, and the edge. Never rewrite it from box
    scores. ``reason`` names why a ticket list is short or empty.
    """

    card_tickets: list[dict[str, object]] = []
    for index, legs in enumerate(tickets, start=1):
        typed_ids = {leg.line.ticket_id for leg in legs if leg.line.ticket_id}
        composed_id = (
            next(iter(typed_ids)) if len(typed_ids) == 1 else f"compose-{index:03d}"
        )
        slip = slips.get(index)
        card_tickets.append(
            {
                "ticket_id": composed_id,
                "n_legs": len(legs),
                "multiplier": getattr(slip, "multiplier", None),
                "multiplier_source": getattr(slip, "multiplier_source", ""),
                "multiplier_unconfirmed": getattr(slip, "multiplier_unconfirmed", None),
                "p_joint": getattr(slip, "p_joint", None),
                "ev": getattr(slip, "ev", None),
                "stake": stake_by_ticket.get(index),
                "legs": [_card_leg(leg, min_edge) for leg in legs],
            }
        )
    return {
        "captured_at": captured_at,
        "platform": platform,
        "reason": reason,
        "edge_gate": edge_gate,
        "min_edge": min_edge,
        "bankroll": bankroll,
        "stake_rule": stake_rule,
        "n_tickets": len(tickets),
        "tickets": card_tickets,
        "dropped": [
            {
                "player_name": leg.line.player_name,
                "stat_type": leg.line.stat_type,
                "warn": leg.warn,
            }
            for leg in dropped
        ],
        "off_card": [row.player_name for row in off_card_rows],
        "do_not_submit": True,
    }


def _write_card_json(out_dir: Path, payload: dict[str, object]) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "card.json"
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def _cmd_compose(args: argparse.Namespace) -> int:
    _print_command_flags(
        legs=getattr(args, "legs", None),
        markets=getattr(args, "markets", None),
        min_odds=getattr(args, "min_odds", None),
        max_odds=getattr(args, "max_odds", None),
        n_tickets=getattr(args, "n_tickets", None),
        environment=getattr(args, "environment", None),
        handoff=getattr(args, "from_ceminidfs", None),
    )
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
    lines, off_card = _off_card_filter(lines, getattr(args, "games", None))
    if late_path is not None:
        for name in apply_inactive_scratch(lines, late_path):
            print(f"scratch (late status): {name}")
        for note in in_game_exit_warnings(lines):
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
    slate_ids = {row.slate_id for row in lines if row.slate_id}
    if len(slate_ids) > 1:
        raise ValueError(f"mixed slate_id values in lines file: {sorted(slate_ids)}")
    out_dir = args.out_dir or Path("runs") / (next(iter(slate_ids), "compose"))
    if not lines:
        # No rows after the filters. Write a null card so the slate still keeps
        # a card artifact, then fail closed.
        reason = f"no rows for platform {platform}; check --lines, --ticket-id, --markets"
        print(f"NULL-CARD: {reason}")
        payload = _compose_card_payload(
            captured_at=captured_at,
            platform=platform,
            reason="no-rows",
            edge_gate="na",
            min_edge=getattr(args, "min_edge", DEFAULT_MIN_EDGE),
            tickets=[],
            slips={},
            dropped=[],
            off_card_rows=off_card,
            stake_by_ticket={},
            stake_rule=_stake_rule(getattr(args, "bankroll", None)),
            bankroll=getattr(args, "bankroll", None),
        )
        json_path = _write_card_json(out_dir, payload)
        (out_dir / "card.txt").write_text(
            f"NULL CARD — {reason}\n{STANDARD_DISCLAIMER}\n", encoding="utf-8"
        )
        print(f"wrote {json_path}")
        return 2

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
    environment = read_environment(args.environment)
    live, excluded = evaluate_legs(
        lines,
        dists,
        implied_p=per_leg,
        method=args.devig_method,
        allow_integer_lines=False,
        platform=platform,
        roster=roster,
        allow_high_receiving=bool(getattr(args, "allow_rec_line", False)),
        require_model=bool(getattr(args, "require_model", False)),
        environment=environment,
        max_line_age_minutes=getattr(args, "max_line_age", None),
    )
    dropped = [leg for leg in excluded if leg.warn not in {"scratch"}]
    print(
        f"lines={len(lines)} live={len(live)} dropped={len(dropped) + len(off_card)} "
        f"scratch={len(excluded) - len(dropped)}"
    )
    for leg in dropped:
        print(f"  dropped {leg.line.player_name}: {leg.warn}")
    for row in off_card:
        print(f"  dropped {row.player_name}: off-card")
    if strict and (dropped or off_card):
        print("strict mode: refusing to compose with dropped legs; fix the rows")
        payload = _compose_card_payload(
            captured_at=captured_at,
            platform=platform,
            reason="dropped-legs",
            edge_gate="na",
            min_edge=getattr(args, "min_edge", DEFAULT_MIN_EDGE),
            tickets=[],
            slips={},
            dropped=dropped,
            off_card_rows=off_card,
            stake_by_ticket={},
            stake_rule=_stake_rule(getattr(args, "bankroll", None)),
            bankroll=getattr(args, "bankroll", None),
        )
        json_path = _write_card_json(out_dir, payload)
        (out_dir / "card.txt").write_text(
            "NULL CARD — strict mode refused to compose with dropped legs\n"
            f"{STANDARD_DISCLAIMER}\n",
            encoding="utf-8",
        )
        print(f"wrote {json_path}")
        return 2

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
    if environment:
        kept = drop_unavailable_first_td(live, environment)
        for leg in live:
            if leg not in kept:
                print(f"  dropped {leg.line.player_name}: first_td-none")
        live = kept

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
        allow_high_receiving=bool(getattr(args, "allow_rec_line", False)),
    )
    # A present --environment file with a blank implied_total on a ticket game
    # fails before any ticket CSV, card, or compose_itt.json write.
    # Blank spread is not scored and does not fail this check.
    if args.environment is not None and Path(args.environment).is_file():
        _require_environment_fields(tickets, environment)
    if args.environment is not None:
        for note in _weather_market_reviews(tickets, environment):
            print(note)
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
    min_edge = getattr(args, "min_edge", DEFAULT_MIN_EDGE)
    bankroll = getattr(args, "bankroll", None)
    priced_slips: dict[int, object] = {}
    for index, ticket_legs in enumerate(tickets, start=1):
        typed_ids = {leg.line.ticket_id for leg in ticket_legs if leg.line.ticket_id}
        # Copy the operator's typed id when it is unambiguous; otherwise keep
        # the generated compose-00N placeholder. Never pad or prefix-match.
        composed_id = next(iter(typed_ids)) if len(typed_ids) == 1 else f"compose-{index:03d}"
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
            allow_unmodeled_correlation=bool(
                getattr(args, "allow_unmodeled_correlation", False)
            ),
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
        priced_slips[index] = slip

    # Stake: quarter-Kelly of the bankroll, capped at 5% per ticket. A missing
    # bankroll records no stake. The operator types the ticket in-app.
    stake_by_ticket: dict[int, float | None] = {}
    for index, slip in priced_slips.items():
        stake_by_ticket[index] = (
            None if bankroll is None else stake_dollars(bankroll, slip.kelly)
        )

    # Modeled-edge gate, over the legs that entered a card. ``weak-edge`` is a
    # leg whose model P is known and loses to the market implied: it fails
    # closed (exit 2). ``no-edge`` is a leg with no model P at all (no typed
    # fair_p, no projection). It is flagged on the card and printed, but does
    # not fail the run: with no projection feed the honest output is a loud
    # flag, not a permanent null card.
    card_legs = [leg for ticket in tickets for leg in ticket]
    edge_fails = edge_failures(card_legs, min_edge)
    weak_fails = [(leg, token) for leg, token in edge_fails if token == "weak-edge"]
    if weak_fails:
        edge_gate = "fail"
    elif edge_fails:
        edge_gate = "no-model"
    elif live:
        edge_gate = "pass"
    else:
        edge_gate = "na"
    for leg, token in edge_fails:
        shown = "na" if leg.prop_edge is None else f"{leg.prop_edge:+.4f}"
        print(
            f"EDGE-GATE {token}: {leg.line.player_name} {leg.line.stat_type} "
            f"prop_edge={shown} (floor {min_edge:+.4f})"
        )

    slips = [priced_slips[index] for index in sorted(priced_slips)]
    bankroll_note = _bankroll_note(bankroll, len(tickets) or 1)
    card = slip_card(slips, bankroll_note=bankroll_note)
    extra: list[str] = []
    if edge_fails:
        extra.append(
            f"EDGE-GATE {edge_gate} — floor {min_edge:+.4f}; "
            "weak-edge fails, no-edge is flagged only:"
        )
        for leg, token in edge_fails:
            shown = "na" if leg.prop_edge is None else f"{leg.prop_edge:+.4f}"
            extra.append(
                f"  {token}: {leg.line.player_name} {leg.line.stat_type} prop_edge={shown}"
            )
    for index, stake in sorted(stake_by_ticket.items()):
        if stake is not None:
            extra.append(f"  stake ticket-{index:03d}: ${stake:.2f} (quarter-Kelly, 5% cap)")
    if extra:
        card = card + "\n" + "\n".join(extra)
    card_path = out_dir / "card.txt"
    card_path.write_text(card + "\n", encoding="utf-8")
    payload = _compose_card_payload(
        captured_at=captured_at,
        platform=platform,
        reason="ok" if len(tickets) == n_tickets else "no-qualifying-legs",
        edge_gate=edge_gate,
        min_edge=min_edge,
        tickets=tickets,
        slips=priced_slips,
        dropped=dropped,
        off_card_rows=off_card,
        stake_by_ticket=stake_by_ticket,
        stake_rule=_stake_rule(bankroll),
        bankroll=bankroll,
    )
    json_path = _write_card_json(out_dir, payload)
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
    print(f"wrote {json_path}")
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
    if weak_fails:
        return 2
    # P0: fewer tickets than --n-tickets is a hard fail. Do not pad the card.
    if len(tickets) != n_tickets:
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
    print("do not submit — type the ticket in-app")
    if args.accept_booked:
        print(ACCEPTED)
        if emit is not None:
            write_booked_ledger(emit, booked)
            print(f"wrote {emit}")
        return 0
    return 2


#: Sharp reference books in preference order, used to auto-pick ``--reference-book``.
SHARP_REFERENCE_PRIORITY = ("draftkings", "fanduel", "betmgm")


def _resolve_reference_book(requested: str | None, platforms: list[str]) -> str | None:
    """The book whose quotes become ``ref_*``. Never the default bet book."""

    if requested:
        return requested
    available = [book for book in SHARP_REFERENCE_PRIORITY if book in platforms]
    return available[0] if available else None


def _blank_cell(value: object) -> bool:
    """A missing cell. Fetch writes an empty string, not None, for a void field."""

    return value is None or (isinstance(value, str) and not value.strip())


def _closing_snapshot_rows(rows: list[dict], captured_at: str) -> list[dict]:
    """One closing row per (platform, player, stat, side) from fetched events.

    A two-way price is stamped on both sides so ``side_implied`` can pick either.
    Alternate lines for the same key would collide on read, so the first wins.
    A row with no line or no two-way price is skipped: a TD market carries no
    line, and a blank cell would break the CLV join at read time.
    """

    out: list[dict] = []
    seen: set[tuple[str, str, str, str]] = set()
    for row in rows:
        platform = str(row.get("platform") or "")
        player_key = str(row.get("player_key") or "")
        stat_type = str(row.get("stat_type") or "")
        line = row.get("line")
        over = row.get("book_over")
        under = row.get("book_under")
        if not platform or not player_key or not stat_type:
            continue
        if _blank_cell(line) or _blank_cell(over) or _blank_cell(under):
            continue
        for side in ("more", "less"):
            key = (platform, player_key, stat_type, side)
            if key in seen:
                continue
            seen.add(key)
            out.append(
                {
                    "platform": platform,
                    "player_key": player_key,
                    "stat_type": stat_type,
                    "side": side,
                    "line": line,
                    "over": over,
                    "under": under,
                    "captured_at": captured_at,
                }
            )
    return out


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

    reference_book = _resolve_reference_book(
        getattr(args, "reference_book", None), platforms
    )
    rows = rows_from_events(
        events,
        platform_filter=set(platforms),
        roster=roster,
        slate_id=slate_id,
        captured_at=captured_at,
        notes=notes,
        reference_book=reference_book,
    )
    if reference_book:
        print(f"reference-book={reference_book}")
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
    if getattr(args, "closing_snapshot", False):
        week = (getattr(args, "week", None) or "").strip()
        if not week:
            raise ValueError("--closing-snapshot needs --week, e.g. --week 2026-w05-sun")
        close_path = Path("runs") / week / "closing_lines.csv"
        if close_path.exists() and not args.force:
            raise ValueError(f"{close_path} exists; pass --force to overwrite")
        closes = _closing_snapshot_rows(rows, captured_at)
        write_prop_closes(close_path, closes)
        print(f"wrote {close_path} rows={len(closes)} captured_at={captured_at}")
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


def _kelly_by_ticket(path: Path | None) -> dict[str, float]:
    """Full-Kelly fraction per ticket, from ``rank``'s edges.csv.

    edges.csv stores quarter Kelly, and the sizing controller applies 0.25 of a
    full Kelly, so the stored value is scaled back up by four.
    """

    if path is None:
        return {}
    out: dict[str, float] = {}
    with Path(path).open(newline="", encoding="utf-8") as handle:
        for raw in csv.DictReader(handle):
            ticket_id = (raw.get("ticket_id") or "").strip()
            if not ticket_id or ticket_id in out:
                continue
            try:
                quarter = float(raw.get("kelly_quarter") or "")
            except ValueError:
                continue
            out[ticket_id] = quarter * 4.0
    return out


def _env_metrics_for_legs(legs: list, environment: dict) -> dict | None:
    """Game metrics for a ticket, from the first leg whose team has an env row."""

    for leg in legs:
        team = str(leg.get("team") or "").strip()
        if not team:
            continue
        for row in environment.values():
            if str(getattr(row, "team", "")).strip() != team:
                continue
            return {
                "implied_total": row.implied_total,
                "spread": row.spread,
                "roof": row.roof,
                "weather_exposed": row.weather_exposed,
                "wind_mph": row.wind_mph,
                "precip_pop": row.precip_pop,
            }
    return None


def _size_slate(args: argparse.Namespace, card: dict, environment: dict) -> list:
    """Build one TicketInput per card ticket and run the sizing controller."""

    if not environment:
        raise ValueError("--size needs --environment with one row per game")
    client = JevClient(
        provider=getattr(args, "jev_provider", "auto"),
        cache_dir=getattr(args, "jev_cache_dir", None) or DEFAULT_CACHE_DIR,
    )
    kelly_by_ticket = _kelly_by_ticket(getattr(args, "edges", None))
    platform = str(card.get("platform") or "")
    tickets = [
        TicketInput(
            ticket_id=str(ticket.get("ticket_id") or ""),
            legs=list(ticket.get("legs") or []),
            platform=platform,
            environment=_env_metrics_for_legs(list(ticket.get("legs") or []), environment),
            kelly_f_star=kelly_by_ticket.get(str(ticket.get("ticket_id") or ""), 0.0),
        )
        for ticket in (card.get("tickets") or [])
    ]
    return size_tickets(
        client,
        tickets,
        ticket_cap_pct=float(getattr(args, "max_ticket_pct", DEFAULT_TICKET_CAP_PCT)),
        max_slate_pct=float(getattr(args, "max_slate_pct", DEFAULT_SLATE_PCT)),
    )


def _cmd_jev_gate(args: argparse.Namespace) -> int:
    card = load_card(args.card)
    lines_text = args.lines.read_text(encoding="utf-8")
    rows = evaluate_gate(
        card,
        lines_text=lines_text,
        environment_path=args.environment,
        late_active_path=args.late_active,
        promo_terms=args.promo_terms,
        fixture_path=args.fixture,
        record_path=args.record_fixture,
    )
    report_path = args.out_dir / "jev_gate_report.csv"
    write_jev_gate_report(report_path, rows)
    line = verdict_line(rows)
    card_md = args.card.parent / "card.md"
    if not append_card_verdict(card_md, line):
        # No card.md (compose ran without --card-md). Never create a card
        # holding only a verdict; keep the verdict beside the report instead.
        args.out_dir.mkdir(parents=True, exist_ok=True)
        (args.out_dir / "card_verdict.txt").write_text(
            f"{line}\ndo not submit — type every ticket in-app\n{STANDARD_DISCLAIMER}\n",
            encoding="utf-8",
        )
        print(f"no card.md at {card_md}; wrote the verdict to the report folder")
    for row in rows:
        if row["action"] == "pass":
            continue
        print(format_mark(row))
    print(line)
    print(f"wrote {report_path}")
    if getattr(args, "size", False):
        environment = read_environment(getattr(args, "environment", None))
        sizes = _size_slate(args, card, environment)
        sizing_path = args.out_dir / "jev_gate_sizing.csv"
        write_sizing_report(sizing_path, sizes)
        for size in sizes:
            detail = size.reason or f"stake={size.final_stake_pct:.4f}"
            print(f"  SIZE {size.ticket_id} {size.gate_status} {detail}")
        total = sum(size.final_stake_pct for size in sizes)
        print(f"slate exposure {total:.4f} of bankroll (cap {args.max_slate_pct})")
        print(f"wrote {sizing_path}")
    print("The gate marks. It does not reprice or submit.")
    print("do not submit — type every ticket in-app")
    return gate_exit_code(rows, allow_flagged=bool(getattr(args, "allow_flagged", False)))


def _cmd_closings(args: argparse.Namespace) -> int:
    out = args.out
    if out.exists() and not args.force:
        print(f"exists: {out} (pass --force to overwrite)")
        return 2
    captured_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    platform = normalize_platform(args.platform)
    lines = read_manual_lines(args.lines, strict=False)
    rows: list[dict[str, object]] = []
    for row in lines:
        if not row.player_key or not row.stat_type:
            continue
        if row.book_over is None or row.book_under is None:
            continue
        if isnan(row.line):
            continue
        if row.platform and normalize_platform(row.platform) != platform:
            continue
        rows.append(
            {
                "platform": platform,
                "player_key": row.player_key,
                "stat_type": row.stat_type,
                "side": row.side,
                "line": row.line,
                "over": row.book_over,
                "under": row.book_under,
                "captured_at": captured_at,
            }
        )
    write_prop_closes(out, rows)
    print(f"wrote {out} rows={len(rows)} captured_at={captured_at}")
    print("closing snapshot only — do not submit")
    return 0


def _cmd_clv(args: argparse.Namespace) -> int:
    report = clv_report(args.ledger, min_legs=args.min_legs)
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(format_clv_report(report))
    if args.out is not None:
        write_clv_json(report, args.out)
        print(f"wrote {args.out}")
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
        "closings": _cmd_closings,
        "clv": _cmd_clv,
        "jev-gate": _cmd_jev_gate,
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
