"""Alias table helpers for ticket-to-box player name matching."""

from ceminiparlays.names import (
    AliasRequiredError,
    canonical_person,
    loose_name,
    names_match,
    unique_box_alias,
)


def test_canonical_person_is_callable() -> None:
    assert callable(canonical_person)


def test_loose_name_period_becomes_space() -> None:
    assert loose_name("K.Gainwell") == "k gainwell"


def test_loose_name_strips_jr_suffix() -> None:
    assert loose_name("Chris Godwin Jr.") == loose_name("Chris Godwin") == "chris godwin"


def test_names_match_alias_groups() -> None:
    groups = [
        ["Kenneth Gainwell", "Kenny Gainwell", "K.Gainwell"],
        ["Marquise Brown", "Hollywood Brown"],
        ["Bam Knight", "Zonovan Knight"],
        ["Josh Palmer", "Joshua Palmer"],
        ["Chigoziem Okonkwo", "Chig Okonkwo"],
    ]
    for group in groups:
        for left in group:
            for right in group:
                assert names_match(left, right)


def test_names_match_godwin_jr() -> None:
    assert names_match("Chris Godwin Jr.", "Chris Godwin") is True


def test_names_match_rejects_unrelated() -> None:
    assert names_match("Kenneth Gainwell", "Tony Pollard") is False


def test_unique_box_alias_already_matched_is_none() -> None:
    assert (
        unique_box_alias(
            "Kenny Gainwell",
            "PHI",
            "RB",
            [{"name": "Kenneth Gainwell", "team": "PHI", "position": "RB"}],
        )
        is None
    )


def test_unique_box_alias_resolves_walker() -> None:
    assert (
        unique_box_alias(
            "K. Walker",
            "SEA",
            "RB",
            [{"name": "Kenneth Walker III", "team": "SEA", "position": "RB"}],
        )
        == "Kenneth Walker III"
    )


def test_unique_box_alias_ambiguous_last_name_is_none() -> None:
    assert (
        unique_box_alias(
            "K. Walker",
            "SEA",
            "RB",
            [
                {"name": "Kenneth Walker III", "team": "SEA", "position": "RB"},
                {"name": "Zach Walker", "team": "SEA", "position": "RB"},
            ],
        )
        is None
    )


def test_unique_box_alias_missing_position_is_none() -> None:
    assert (
        unique_box_alias(
            "K. Walker",
            "SEA",
            "RB",
            [{"name": "Kenneth Walker III", "team": "SEA"}],
        )
        is None
    )


def test_alias_required_error_attributes() -> None:
    assert issubclass(AliasRequiredError, LookupError)
    err = AliasRequiredError("K. Walker", "Kenneth Walker III", "SEA", "RB")
    assert err.ticket_name == "K. Walker"
    assert err.box_name == "Kenneth Walker III"
    assert err.team == "SEA"
    assert err.position == "RB"
    assert "AliasRequiredError" in str(err)
    assert "K. Walker" in str(err)
    assert "Kenneth Walker III" in str(err)
