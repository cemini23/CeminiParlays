"""Rank, run, and compose share max-slips, market-cap, and allow-fewer flags."""

import pytest

from ceminiparlays.cli import build_parser


def test_rank_run_compose_flag_parity() -> None:
    parser = build_parser()
    rank = parser.parse_args(
        [
            "rank",
            "--lines",
            "lines.csv",
            "--distributions",
            "dist.csv",
            "--max-slips",
            "7",
            "--max-legs-per-market",
            "2",
            "--n-tickets",
            "4",
            "--allow-fewer",
        ]
    )
    run = parser.parse_args(
        [
            "run",
            "--lines",
            "lines.csv",
            "--distributions",
            "dist.csv",
            "--max-slips",
            "7",
            "--max-legs-per-market",
            "2",
            "--n-tickets",
            "4",
            "--allow-fewer",
        ]
    )
    compose = parser.parse_args(
        [
            "compose",
            "--lines",
            "lines.csv",
            "--max-slips",
            "7",
            "--max-legs-per-market",
            "2",
            "--n-tickets",
            "4",
            "--allow-fewer",
        ]
    )
    assert rank.max_slips == run.max_slips == compose.max_slips == 7
    assert (
        rank.max_legs_per_market
        == run.max_legs_per_market
        == compose.max_legs_per_market
        == 2
    )
    assert rank.n_tickets == run.n_tickets == compose.n_tickets == 4
    assert rank.allow_fewer is True
    assert compose.allow_fewer is True
    assert run.allow_fewer is True


def test_strict_ticket_count_and_leg_reuse_parity() -> None:
    parser = build_parser()
    commands = (
        ["rank", "--lines", "lines.csv", "--distributions", "dist.csv"],
        ["run", "--lines", "lines.csv", "--distributions", "dist.csv"],
        ["compose", "--lines", "lines.csv"],
        ["sunday-card", "--lines", "lines.csv"],
    )
    for prefix in commands:
        args = parser.parse_args(
            [
                *prefix,
                "--strict-ticket-count",
                "--max-leg-reuse",
                "1",
                "--n-tickets",
                "3",
            ]
        )
        assert args.strict_ticket_count is True
        assert args.max_leg_reuse == 1
        assert args.n_tickets == 3
    compose = parser.parse_args(
        [
            "compose",
            "--lines",
            "lines.csv",
            "--env-csv",
            "environment.csv",
            "--env-odds-csv",
            "environment_odds_2026-11-08.csv",
            "--sync-dirs",
            "parlays-slate",
            "parlays-recap",
        ]
    )
    sunday = parser.parse_args(
        [
            "sunday-card",
            "--lines",
            "lines.csv",
            "--env-csv",
            "environment.csv",
            "--env-odds-csv",
            "environment_odds_2026-11-08.csv",
            "--require-env-odds",
        ]
    )
    assert compose.env_odds_csv.name == "environment_odds_2026-11-08.csv"
    assert sunday.env_odds_csv.name == "environment_odds_2026-11-08.csv"
    assert compose.require_env_odds is None
    assert sunday.require_env_odds is True
    assert len(compose.sync_dirs) == 2


def test_engine_flag_is_on_rank_and_run_but_not_compose() -> None:
    """``--engine`` reaches ``rank_slips`` from rank and run only.

    ``compose`` prices one explicit ticket and keeps its own flags; it still
    follows ``CEMINIPARLAYS_ENGINE`` through the default ``None``.
    """

    parser = build_parser()
    rank = parser.parse_args(
        ["rank", "--lines", "lines.csv", "--distributions", "dist.csv"]
    )
    run = parser.parse_args(
        ["run", "--lines", "lines.csv", "--distributions", "dist.csv"]
    )
    assert rank.engine is None
    assert run.engine is None
    for command in ("rank", "run"):
        args = parser.parse_args(
            [
                command,
                "--lines",
                "lines.csv",
                "--distributions",
                "dist.csv",
                "--engine",
                "rust",
            ]
        )
        assert args.engine == "rust"
    with pytest.raises(SystemExit):
        parser.parse_args(
            ["compose", "--lines", "lines.csv", "--engine", "rust"]
        )
