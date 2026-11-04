from ceminiparlays.proppricing import DFS_WEIGHT_CAP, dfs_weight


def test_dfs_weight_is_zero_without_confidence() -> None:
    assert dfs_weight(0.0) == 0.0
    assert dfs_weight(-1.0) == 0.0


def test_dfs_weight_scales_with_confidence() -> None:
    assert dfs_weight(0.5) == DFS_WEIGHT_CAP * 0.5


def test_dfs_weight_stops_at_the_cap() -> None:
    assert dfs_weight(1.0) == DFS_WEIGHT_CAP
    assert dfs_weight(2.0) == DFS_WEIGHT_CAP
