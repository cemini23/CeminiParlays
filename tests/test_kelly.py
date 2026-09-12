from ceminiparlays.kelly import slip_kelly, stake_dollars


def test_quarter_kelly_on_plus_ev_slip() -> None:
    sized = slip_kelly(0.3671, 3.0, fraction=0.25)
    full = (0.3671 * 3.0 - 1.0) / 2.0
    assert abs(sized - min(full * 0.25, 0.05)) < 1e-9
    assert sized > 0


def test_negative_edge_is_zero() -> None:
    assert slip_kelly(0.30, 3.0) == 0.0


def test_stake_dollars() -> None:
    assert stake_dollars(1000, 0.01) == 10.0
