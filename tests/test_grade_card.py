"""Grade a saved card from synthetic play-by-play. Hard Rock history is not read."""

from ceminiparlays.grade_card import LEDGER_COLUMNS, grade_rows, main
from ceminiparlays.odds import american_to_decimal


def _row(**kwargs: str) -> dict[str, str]:
    base = {column: "" for column in LEDGER_COLUMNS}
    base.update(
        {
            "ticket_id": "1",
            "tier": "1",
            "leg_num": "1",
            "game_id": "2026_07_GB_DET",
            "kick_et": "4:25 PM ET",
            "player_name": "Jahmyr Gibbs",
            "gsis_id": "00-0030001",
            "team": "DET",
            "opp": "GB",
            "market": "receptions_q4",
            "side": "over",
            "line": "0.5",
            "book_american_odds": "-110",
            "model_prob": "0.60",
            "tax_adj_ev": "0.10",
            "ticket_stake_usd": "1.75",
            "t90_flag": "none",
        }
    )
    base.update(kwargs)
    return base


def _catch(quarter: int, catches: float = 1, yards: float = 8) -> dict:
    return {
        "game_id": "2026_07_GB_DET",
        "qtr": quarter,
        "posteam": "DET",
        "defteam": "GB",
        "receiver_player_id": "00-0030001",
        "receiver_player_name": "Jahmyr Gibbs",
        "complete_pass": catches,
        "receiving_yards": yards,
    }


def test_single_win_loss_and_push() -> None:
    win = grade_rows([_row()], [_catch(4, 1)])
    assert win.settled_tickets == 1
    assert win.legs[0].result == "win"
    assert win.profit == 1.75 * (american_to_decimal(-110) - 1)
    loss = grade_rows([_row()], [_catch(4, 0)])
    assert loss.legs[0].result == "loss"
    assert loss.profit == -1.75
    push = grade_rows([_row(line="1.0")], [_catch(4, 1)])
    assert push.legs[0].result == "push"
    assert push.profit == 0
    assert push.stake == 1.75
    assert push.brier is None


def test_quarter_does_not_use_another_quarter() -> None:
    grade = grade_rows([_row(market="receptions_q3")], [_catch(4, 1)])
    assert grade.legs[0].result == "ungraded"
    assert grade.settled_tickets == 0
    assert grade.stake == 0


def test_sgp_loss_and_push_reprice() -> None:
    loss_rows = [
        _row(ticket_id="2", leg_num="1", ticket_stake_usd="2.00"),
        _row(
            ticket_id="2",
            leg_num="2",
            player_name="Josh Jacobs",
            gsis_id="00-0030002",
            team="GB",
            opp="DET",
            market="rush_yds_q4",
            line="10.5",
            book_american_odds="100",
            ticket_stake_usd="2.00",
        ),
    ]
    plays = [
        _catch(4, 0),
        {
            "game_id": "2026_07_GB_DET",
            "qtr": 4,
            "rusher_player_id": "00-0030002",
            "rusher_player_name": "Josh Jacobs",
            "rushing_yards": 20,
        },
    ]
    lost = grade_rows(loss_rows, plays)
    assert lost.profit == -2.0
    assert lost.stake == 2.0
    push_rows = [
        _row(ticket_id="3", line="1.0", ticket_stake_usd="1.00", book_american_odds="-110"),
        _row(
            ticket_id="3",
            leg_num="2",
            player_name="Josh Jacobs",
            gsis_id="00-0030002",
            team="GB",
            opp="DET",
            market="rush_yds_q4",
            line="10.5",
            book_american_odds="100",
            model_prob="0.55",
            ticket_stake_usd="1.00",
        ),
    ]
    pushed = grade_rows(push_rows, [_catch(4, 1), plays[1]])
    assert pushed.legs[0].result == "push"
    assert pushed.legs[1].result == "win"
    assert pushed.profit == 1.0
    assert pushed.brier == (0.55 - 1.0) ** 2


def test_full_game_without_quarter_and_q3_total() -> None:
    full = grade_rows(
        [_row(market="rush_yds", line="60.5", book_american_odds="100", model_prob="0.70")],
        [
            {
                "game_id": "2026_07_GB_DET",
                "rusher_player_id": "00-0030001",
                "rusher_player_name": "Jahmyr Gibbs",
                "rushing_yards": 80,
            }
        ],
    )
    assert full.legs[0].result == "win"
    total = grade_rows(
        [
            _row(
                market="total_q3",
                player_name="",
                gsis_id="",
                line="6.5",
                side="over",
                book_american_odds="-110",
                model_prob="0.40",
            )
        ],
        [
            {"game_id": "2026_07_GB_DET", "qtr": 3, "points": 10},
            {"game_id": "2026_07_GB_DET", "qtr": 4, "points": 14},
        ],
    )
    assert total.legs[0].result == "win"
    assert total.legs[0].actual == 10
    assert total.brier == (0.40 - 1.0) ** 2


def test_missing_quarter_on_a_player_row_stays_ungraded() -> None:
    grade = grade_rows([_row()], [{"game_id": "2026_07_GB_DET", "complete_pass": 2}])
    assert grade.legs[0].result == "ungraded"


def test_cli_requires_one_source() -> None:
    assert main(["ledger.csv"]) == 2
    assert main(["ledger.csv", "--pbp", "a.parquet", "--summary", "b.json"]) == 2
