"""Rank, run, and compose share the slip and market caps."""

from ceminiparlays.cli import build_parser, shortfall_exit
from ceminiparlays.slips import combo_over_market_cap


class _Line:
    def __init__(self, stat: str) -> None:
        self.stat_type = stat


class _Leg:
    def __init__(self, stat: str) -> None:
        self.line = _Line(stat)


def test_market_cap_matches_compose() -> None:
    combo = (_Leg("receptions_q4"), _Leg("receptions_q4"), _Leg("rush_yds"))
    assert combo_over_market_cap(combo, None) is False
    assert combo_over_market_cap(combo, 0) is False
    assert combo_over_market_cap(combo, 2) is False
    assert combo_over_market_cap(combo, 1) is True


def test_shortfall_exit_codes(capsys) -> None:
    assert shortfall_exit(5, 5, False) is None
    assert shortfall_exit(4, 5, False) == 2
    assert "COMPOSED_SHORTFALL composed=4 requested=5" in capsys.readouterr().out
    assert shortfall_exit(4, 5, True) == 0


def test_rank_run_and_compose_accept_the_same_flags() -> None:
    parser = build_parser()
    rank = parser.parse_args(
        [
            "rank",
            "--lines",
            "lines.csv",
            "--distributions",
            "dist.csv",
            "--n-tickets",
            "4",
            "--max-legs-per-market",
            "2",
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
            "--n-tickets",
            "4",
            "--max-legs-per-market",
            "2",
        ]
    )
    compose = parser.parse_args(
        ["compose", "--lines", "lines.csv", "--n-tickets", "4", "--max-legs-per-market", "2", "--allow-fewer"]
    )
    assert rank.n_tickets == run.n_tickets == compose.n_tickets == 4
    assert rank.max_legs_per_market == run.max_legs_per_market == compose.max_legs_per_market == 2
    assert rank.allow_fewer is True
    assert compose.allow_fewer is True
    assert rank.max_slips == 25
