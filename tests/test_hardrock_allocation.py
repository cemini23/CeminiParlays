"""$25.00 Hard Rock allocator. Stakes are integer cents."""

import pytest

from ceminiparlays.jev_sizing import HARDROCK_BANKROLL_CENTS, DollarPlay, allocate_hardrock_dollars


def _play(
    index: int,
    *,
    pool: str = "checkdown",
    game: str | None = None,
    player: str | None = None,
    players: tuple[str, ...] | None = None,
    ev: float = 0.20,
) -> DollarPlay:
    keys = players if players is not None else (player or f"player{index}",)
    return DollarPlay(
        play_id=f"p{index}",
        pool=pool,
        game_ids=(game or f"g{index}",),
        player_keys=keys,
        ev=ev,
        model_p=0.60,
        decimal_odds=2.0,
    )


def _broad() -> list[DollarPlay]:
    plays: list[DollarPlay] = []
    index = 1
    for pool, count in (("checkdown", 6), ("core", 5), ("sgp", 6)):
        for _step in range(count):
            keys = (f"p{index}a", f"p{index}b") if pool == "sgp" else (f"player{index}",)
            plays.append(_play(index, pool=pool, players=keys))
            index += 1
    return plays


def test_mode_a_uses_the_fixed_bands() -> None:
    mode, stakes = allocate_hardrock_dollars(_broad())
    assert mode == "A"
    assert len(stakes) == 17
    assert sum(row.stake_cents for row in stakes) == HARDROCK_BANKROLL_CENTS
    assert [row.stake_cents for row in stakes].count(175) == 6
    assert [row.stake_cents for row in stakes].count(170) == 5
    assert [row.stake_cents for row in stakes].count(100) == 6


def test_mode_b_splits_seven_to_nine_tickets() -> None:
    mode, stakes = allocate_hardrock_dollars([_play(index) for index in range(1, 9)])
    assert mode == "B"
    assert len(stakes) == 8
    assert sum(row.stake_cents for row in stakes) == HARDROCK_BANKROLL_CENTS
    assert all(200 <= row.stake_cents <= 400 for row in stakes)


def test_mode_b_keeps_one_ticket_per_player() -> None:
    plays = [_play(index, ev=0.30 if index == 1 else 0.20) for index in range(1, 8)]
    plays.append(_play(8, player="player1", ev=0.10, game="g8"))
    _mode, stakes = allocate_hardrock_dollars(plays)
    ids = {row.play_id for row in stakes}
    assert "p1" in ids
    assert "p8" not in ids
    assert len(stakes) == 7
    assert sum(row.stake_cents for row in stakes) == HARDROCK_BANKROLL_CENTS


def test_six_plays_cannot_fill_the_bankroll() -> None:
    with pytest.raises(ValueError):
        allocate_hardrock_dollars([_play(index) for index in range(1, 7)])


def test_one_game_cannot_hold_the_bankroll() -> None:
    plays = [_play(index, game="only") for index in range(1, 9)]
    with pytest.raises(ValueError):
        allocate_hardrock_dollars(plays)
