from ceminiparlays.names import alias_fold_keys, fold_name, resolve_player_key


def test_fold_jamarr() -> None:
    assert fold_name("Ja'Marr Chase") == "jamarr_chase"
    assert fold_name("Patrick Mahomes") == "patrick_mahomes"
    assert fold_name("Odell Beckham Jr.") == "odell_beckham"


def test_override_wins() -> None:
    assert resolve_player_key("Mahomes", {"mahomes": "patrick_mahomes"}) == "patrick_mahomes"
    assert resolve_player_key("X", existing_key="keep_me") == "keep_me"


def test_alias_fold_keys_lists_the_person_and_the_alias() -> None:
    assert alias_fold_keys("Kenny Gainwell") == ["kenny_gainwell", "kenneth_gainwell"]


def test_alias_fold_keys_does_not_repeat_a_canonical_name() -> None:
    assert alias_fold_keys("Kenneth Gainwell") == ["kenneth_gainwell"]
