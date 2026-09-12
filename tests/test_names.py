from ceminiparlays.names import fold_name, resolve_player_key


def test_fold_jamarr() -> None:
    assert fold_name("Ja'Marr Chase") == "jamarr_chase"
    assert fold_name("Patrick Mahomes") == "patrick_mahomes"
    assert fold_name("Odell Beckham Jr.") == "odell_beckham"


def test_override_wins() -> None:
    assert resolve_player_key("Mahomes", {"mahomes": "patrick_mahomes"}) == "patrick_mahomes"
    assert resolve_player_key("X", existing_key="keep_me") == "keep_me"
