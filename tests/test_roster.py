from ceminiparlays.io import LineRow
from ceminiparlays.roster import load_roster, lookup_player, normalize_team, roster_mismatch
from ceminiparlays.slips import evaluate_legs, resolve_slip_sizes


def _line(name: str, team: str, key: str = "") -> LineRow:
    return LineRow(
        slate_id="s",
        platform="hardrock",
        player_name=name,
        player_key=key,
        team=team,
        opponent="HOU",
        stat_type="rec_yds",
        line=62.5,
        side="more",
        line_type="standard",
        captured_at="",
        displayed_multiplier=None,
        injury_status="",
        book_over=-110,
        book_under=-110,
    )


def test_dj_moore_is_a_bill() -> None:
    roster = load_roster()
    assert roster_mismatch(_line("DJ Moore", "CHI"), roster) == "wrong-team"
    assert roster_mismatch(_line("D.J. Moore", "CHI"), roster) == "wrong-team"
    assert roster_mismatch(_line("DJ Moore", "BUF"), roster) is None
    found = lookup_player(_line("DJ Moore", "CHI"), roster)
    assert found is not None
    assert found.team == "BUF"


def test_unknown_player_passes() -> None:
    roster = load_roster()
    assert roster_mismatch(_line("Brand New Callup", "KC"), roster) is None


def test_jac_alias_matches_jax() -> None:
    assert normalize_team("JAC") == "JAX"
    assert normalize_team("WSH") == "WAS"


def test_evaluate_drops_wrong_team() -> None:
    roster = load_roster()
    live, excluded = evaluate_legs(
        [_line("DJ Moore", "CHI")],
        {},
        implied_p=0.5,
        platform="hardrock",
        roster=roster,
    )
    assert live == []
    assert excluded[0].warn == "wrong-team"


def test_resolve_slip_sizes() -> None:
    assert resolve_slip_sizes(2) == [2]
    assert resolve_slip_sizes(2, "4") == [4]
    assert resolve_slip_sizes(2, "2,3,4") == [2, 3, 4]
    assert resolve_slip_sizes(2, "2-4") == [2, 3, 4]
