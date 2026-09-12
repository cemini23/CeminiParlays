from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ceminiparlays import STANDARD_DISCLAIMER, __version__
from ceminiparlays.fair import p_over_line, side_probability
from ceminiparlays.grade import grade_ledger, write_grade
from ceminiparlays.io import read_distributions, read_manual_lines, write_csv
from ceminiparlays.odds import DevigMethod, devig_two_way
from ceminiparlays.payouts import breakeven_per_leg, implied_slip_win, resolve_payout
from ceminiparlays.report import fair_card, slip_card
from ceminiparlays.slips import EDGE_FIELDS, evaluate_legs, rank_slips, slip_as_row


def _add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--platform", default="underdog", choices=["underdog", "prizepicks"])
    parser.add_argument("--profile-dir", type=Path, default=None)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ceminiparlays",
        description="Local pick'em / parlay research CLI. Operator submits. No scrapers.",
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
    rank.add_argument("--lines", type=Path, required=True)
    rank.add_argument("--distributions", type=Path, required=True)
    rank.add_argument("--mode", default="standard", choices=["standard", "power", "flex"])
    rank.add_argument("--slip-size", type=int, default=2)
    rank.add_argument("--out", type=Path, default=Path("runs/edges.csv"))
    rank.add_argument("--report", type=Path, default=None)
    rank.add_argument("--n-sims", type=int, default=20_000)
    rank.add_argument("--seed", type=int, default=42)
    rank.add_argument("--displayed-multiplier", type=float, default=None)
    rank.add_argument("--devig-method", default="power", choices=["power", "multiplicative", "additive"])

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
    run.add_argument("--lines", type=Path, required=True)
    run.add_argument("--distributions", type=Path, required=True)
    run.add_argument("--slate-id", default="demo")
    run.add_argument("--mode", default="standard", choices=["standard", "power", "flex"])
    run.add_argument("--slip-size", type=int, default=2)
    run.add_argument("--out-dir", type=Path, default=None)
    run.add_argument("--n-sims", type=int, default=20_000)
    run.add_argument("--seed", type=int, default=42)
    run.add_argument("--displayed-multiplier", type=float, default=None)
    run.add_argument("--devig-method", default="power", choices=["power", "multiplicative", "additive"])
    return parser


def _cmd_fair(args: argparse.Namespace) -> int:
    result = p_over_line(args.line, args.median, args.sd, family=args.family, stat_type=args.stat)
    fair_p = side_probability(result, args.side)
    print(fair_card(args.player, args.stat, args.line, result, args.side, fair_p))
    if args.show_dist:
        print(json.dumps(result.__dict__, indent=2))
    return 0


def _rank_and_write(
    lines_path: Path,
    dist_path: Path,
    platform: str,
    mode: str,
    slip_size: int,
    out_csv: Path,
    report_path: Path | None,
    n_sims: int,
    seed: int,
    displayed_multiplier: float | None,
    method: DevigMethod,
    profile_dir: Path | None,
) -> int:
    lines = read_manual_lines(lines_path)
    lines = [row for row in lines if (not row.platform or row.platform == platform)]
    slate_ids = {row.slate_id for row in lines if row.slate_id}
    if len(slate_ids) > 1:
        raise ValueError(f"mixed slate_id values in lines file: {sorted(slate_ids)}")
    dists = read_distributions(dist_path)
    table = resolve_payout(platform, mode, slip_size, displayed_multiplier, profile_dir)
    implied = implied_slip_win(table.all_hit)
    per_leg = breakeven_per_leg(table.all_hit, slip_size)
    evaluated = evaluate_legs(lines, dists, implied_p=per_leg, method=method)
    slips = rank_slips(
        evaluated,
        platform=platform,
        mode=mode,
        slip_size=slip_size,
        n_sims=n_sims,
        seed=seed,
        displayed_multiplier=displayed_multiplier,
        profile_dir=profile_dir,
    )
    write_csv(out_csv, [slip_as_row(slip, i) for i, slip in enumerate(slips, start=1)], EDGE_FIELDS)
    card = slip_card(slips)
    target = report_path or out_csv.with_suffix(".report.txt")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(card + "\n", encoding="utf-8")
    print(card)
    print(f"wrote {out_csv}")
    print(f"implied slip win {implied:.4f}; per-leg breakeven {per_leg:.4f}")
    return 0


def _cmd_rank(args: argparse.Namespace) -> int:
    return _rank_and_write(
        args.lines,
        args.distributions,
        args.platform,
        args.mode,
        args.slip_size,
        args.out,
        args.report,
        args.n_sims,
        args.seed,
        args.displayed_multiplier,
        args.devig_method,
        args.profile_dir,
    )


def _cmd_grade(args: argparse.Namespace) -> int:
    summary = grade_ledger(args.ledger, profile_dir=args.profile_dir)
    write_grade(summary, args.out)
    print(json.dumps(summary.__dict__, indent=2))
    print(STANDARD_DISCLAIMER)
    return 0


def _cmd_devig(args: argparse.Namespace) -> int:
    result = devig_two_way(args.over, args.under, method=args.method)
    print(
        json.dumps(
            {
                "p_over": round(result.p_over, 6),
                "p_under": round(result.p_under, 6),
                "method": result.method,
                "k_exponent": round(result.k_exponent, 6),
                "market_width_cents": result.market_width_cents,
                "raw_overround": round(result.raw_overround, 6),
            },
            indent=2,
        )
    )
    return 0


def _cmd_run(args: argparse.Namespace) -> int:
    out_dir = args.out_dir or Path("runs") / args.slate_id
    out_dir.mkdir(parents=True, exist_ok=True)
    return _rank_and_write(
        args.lines,
        args.distributions,
        args.platform,
        args.mode,
        args.slip_size,
        out_dir / "edges.csv",
        out_dir / "report.txt",
        args.n_sims,
        args.seed,
        args.displayed_multiplier,
        args.devig_method,
        args.profile_dir,
    )


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
    return handlers[args.command](args)


def main_fair() -> int:
    return main(["fair", *sys.argv[1:]])


def main_rank() -> int:
    return main(["rank", *sys.argv[1:]])


def main_grade() -> int:
    return main(["grade", *sys.argv[1:]])


if __name__ == "__main__":
    raise SystemExit(main())
