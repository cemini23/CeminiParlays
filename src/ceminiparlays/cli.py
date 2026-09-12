from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ceminiparlays import STANDARD_DISCLAIMER, __version__
from ceminiparlays.fair import p_over_line, side_probability
from ceminiparlays.grade import grade_ledger, write_grade
from ceminiparlays.io import read_distributions, read_manual_lines, write_csv
from ceminiparlays.odds import american_to_decimal, devig_spread, devig_two_way
from ceminiparlays.payouts import (
    SPORTSBOOK_PLATFORMS,
    breakeven_per_leg,
    display_name,
    implied_slip_win,
    normalize_platform,
    resolve_payout,
)
from ceminiparlays.report import fair_card, slip_card
from ceminiparlays.slips import EDGE_FIELDS, evaluate_legs, rank_slips, slip_as_row

UNCONFIRMED_BANNER = "UNCONFIRMED TABLE MULTIPLIER — confirm in-app"


def _add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--platform",
        default="hardrock",
        choices=["hardrock", "fanduel", "draftkings", "underdog", "prizepicks"],
    )
    parser.add_argument("--profile-dir", type=Path, default=None)


def _add_rank_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--mode", default="standard", choices=["standard", "power", "flex"])
    parser.add_argument("--slip-size", type=int, default=2)
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
        description="Local sportsbook parlay / pick'em research CLI. Operator submits. No scrapers.",
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

    run = sub.add_parser("run", help="Write edges.csv + report under runs/{slate}")
    _add_common(run)
    _add_rank_options(run)
    run.add_argument("--lines", type=Path, required=True)
    run.add_argument("--distributions", type=Path, required=True)
    run.add_argument("--slate-id", default="demo")
    run.add_argument("--out-dir", type=Path, default=None)
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


def _rank_and_write(args: argparse.Namespace, out_csv: Path, report_path: Path | None) -> int:
    strict = getattr(args, "strict", True)
    platform = normalize_platform(args.platform)
    if platform in SPORTSBOOK_PLATFORMS and args.mode.lower() == "flex":
        raise ValueError(
            f"{display_name(platform)} Flex Parlay is not modeled. Use --mode standard "
            "and pass --displayed-odds from the app."
        )
    lines = read_manual_lines(args.lines, strict=strict)
    lines = [
        row
        for row in lines
        if (not row.platform or normalize_platform(row.platform) == platform)
    ]
    if not lines:
        raise ValueError(
            f"no rows for platform {platform}; set the CSV platform column "
            "or leave it blank"
        )
    slate_ids = {row.slate_id for row in lines if row.slate_id}
    if len(slate_ids) > 1:
        raise ValueError(f"mixed slate_id values in lines file: {sorted(slate_ids)}")

    displayed_m = _cli_displayed_multiplier(args)
    effective_m, unconfirmed_slate = _effective_multiplier(lines, displayed_m)
    if unconfirmed_slate and platform not in SPORTSBOOK_PLATFORMS:
        print(UNCONFIRMED_BANNER)
    if unconfirmed_slate and platform in SPORTSBOOK_PLATFORMS:
        print(
            f"{display_name(platform).upper()}: no slate-wide displayed price — ranking "
            "uses per-row slip_odds / product of leg_odds. Confirm the SGP ticket "
            "in-app."
        )

    dists = read_distributions(args.distributions)
    if platform in SPORTSBOOK_PLATFORMS and effective_m is None:
        implied = 0.0
        per_leg = 0.0
    else:
        table = resolve_payout(
            platform,
            args.mode,
            args.slip_size,
            displayed_multiplier=effective_m,
            profile_dir=args.profile_dir,
        )
        implied = implied_slip_win(table.all_hit)
        per_leg = breakeven_per_leg(table.all_hit, args.slip_size)
    live, excluded = evaluate_legs(
        lines,
        dists,
        implied_p=per_leg,
        method=args.devig_method,
        allow_integer_lines=args.allow_integer_lines,
        platform=platform,
    )
    dropped = [leg for leg in excluded if leg.warn not in {"scratch"}]
    scratched = [leg for leg in excluded if leg.warn == "scratch"]
    print(
        f"lines={len(lines)} live={len(live)} dropped={len(dropped)} "
        f"scratched={len(scratched)}"
    )
    for leg in dropped:
        print(f"  dropped {leg.line.player_name}: {leg.warn}")
    for leg in scratched:
        print(f"  scratched {leg.line.player_name}")

    if strict and dropped:
        print("strict mode: refusing to rank with dropped legs; fix the rows or pass --no-strict")
        return 2

    notes: list[str] = []
    slips = rank_slips(
        live,
        platform=platform,
        mode=args.mode,
        slip_size=args.slip_size,
        n_sims=args.n_sims,
        seed=args.seed,
        displayed_multiplier=displayed_m,
        profile_dir=args.profile_dir,
        max_slips=args.max_slips,
        allow_large_enum=args.allow_large_enum,
        shade_pp=args.shade_pp,
        notes=notes,
    )
    for note in notes:
        print(f"  {note}")
    write_csv(out_csv, [slip_as_row(slip, i) for i, slip in enumerate(slips, start=1)], EDGE_FIELDS)
    card = slip_card(slips)
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


def _cmd_run(args: argparse.Namespace) -> int:
    out_dir = args.out_dir or Path("runs") / args.slate_id
    out_dir.mkdir(parents=True, exist_ok=True)
    return _rank_and_write(args, out_dir / "edges.csv", out_dir / "report.txt")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    handlers = {
        "fair": _cmd_fair,
        "rank": _cmd_rank,
        "grade": _cmd_grade,
        "devig": _cmd_devig,
        "run": _cmd_run,
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
