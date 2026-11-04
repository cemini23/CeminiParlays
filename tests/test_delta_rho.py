"""Regime questions, the game state, and the auditable rho perturbation."""

import numpy as np

from ceminiparlays.delta_rho import (
    REGIME_SCALE,
    REGIMES,
    LegRef,
    RHO_CLIP,
    game_state,
    perturb_matrix,
    regime_questions,
    score_game,
)


def _legs() -> list[LegRef]:
    return [
        LegRef(player_key="a", team="KC", opponent="BUF", stat_type="pass_yds", side="more"),
        LegRef(player_key="b", team="KC", opponent="BUF", stat_type="rec_yds", side="more"),
    ]


def test_regime_questions_offers_every_regime_on_the_same_scale() -> None:
    questions = regime_questions()
    assert len(questions) == len(REGIMES)
    assert [question for question, _ in questions] == [regime.question for regime in REGIMES]
    assert all(scale == list(REGIME_SCALE) for _, scale in questions)


def test_game_state_reads_the_named_fields() -> None:
    class Row:
        implied_total = 24.5
        spread = -2.5
        roof = "open"
        weather_exposed = True
        wind_mph = 17.0
        precip_pop = 20

    state = game_state(Row(), notes=["cold"])
    assert state["implied_total"] == 24.5
    assert state["spread"] == -2.5
    assert state["roof"] == "open"
    assert state["weather_exposed"] is True
    assert state["wind_mph"] == 17.0
    assert state["notes"] == ["cold"]


def test_game_state_defaults_a_row_without_the_attributes() -> None:
    state = game_state(object())
    assert state["implied_total"] is None
    assert state["spread"] is None
    assert state["roof"] == ""
    assert state["weather_exposed"] is False
    assert state["notes"] == []


def test_score_game_maps_each_regime_onto_its_key() -> None:
    class Client:
        def score_bundle(self, state: dict, questions: list) -> list[int]:
            assert state == {"x": 1}
            assert len(questions) == len(REGIMES)
            return list(range(len(REGIMES)))

    scored = score_game(Client(), {"x": 1})
    assert set(scored) == {regime.key for regime in REGIMES}
    assert scored[REGIMES[0].key] == 0


def test_perturb_matrix_with_no_scores_leaves_the_base_alone() -> None:
    base = np.array([[1.0, 0.3], [0.3, 1.0]])
    out, records = perturb_matrix(base, _legs(), {})
    assert np.allclose(out, base)
    assert len(records) == 1
    assert records[0].rho_base == 0.3
    assert records[0].rho_adj == 0.3
    assert records[0].delta_rho == 0.0
    assert records[0].regimes == ()


def test_perturb_matrix_clips_a_base_above_the_limit() -> None:
    base = np.array([[1.0, 0.99], [0.99, 1.0]])
    out, records = perturb_matrix(base, _legs(), {})
    assert records[0].rho_adj == RHO_CLIP
    assert out[0, 1] == RHO_CLIP
    assert out[1, 0] == RHO_CLIP


def test_perturb_matrix_keeps_the_matrix_symmetric() -> None:
    base = np.array([[1.0, 0.2], [0.2, 1.0]])
    out, _ = perturb_matrix(base, _legs(), {})
    assert np.allclose(out, out.T)
    assert np.allclose(np.diag(out), 1.0)
