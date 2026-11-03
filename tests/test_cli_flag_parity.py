"""Rank, run, and compose share max-slips, market-cap, and allow-fewer flags."""

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
