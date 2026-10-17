"""Team attribution helpers keep the book team authoritative."""

from ceminiparlays.book_team import canonical_team, offensive_team, teams_disagree


def test_book_team_wins() -> None:
    assert offensive_team("HOU", "ARI") == "HOU"


def test_blank_book_team_falls_back() -> None:
    assert offensive_team("", "ARI") == "ARI"


def test_disagreement_needs_both_sides() -> None:
    assert teams_disagree("HOU", "ARI") is True
    assert teams_disagree("HOU", "HOU") is False
    assert teams_disagree("", "ARI") is False


def test_full_name_and_alias_match_the_nflverse_code() -> None:
    assert canonical_team("Los Angeles Rams") == "LAR"
    assert canonical_team("LA") == "LAR"
    assert canonical_team("JAC") == "JAX"
    assert canonical_team("Rams") == "LAR"
    assert teams_disagree("Los Angeles Rams", "LAR") is False
    assert teams_disagree("LA", "LAR") is False
    assert teams_disagree("JAC", "JAX") is False
    assert teams_disagree("HOU", "ARI") is True
