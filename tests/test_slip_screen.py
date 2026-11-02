"""The local slip screen describes. It does not act."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ceminiparlays.cli import main
from ceminiparlays.numbered_span import (
    SliceInvariantError,
    VerbatimSpan,
    extract_span,
    span_from_indices,
    tokenize,
)
from ceminiparlays.slip_annotations import (
    build_annotated_slips,
    gold_risk_band,
    load_annotated,
)
from ceminiparlays.slip_screen import (
    CORRELATION_LABELS,
    FIELD_NAMES,
    MARKET_LABELS,
    MODEL_ID,
    RISK_LEVELS,
    AccuracyReport,
    FieldScore,
    answers_from_annotation,
    describe_slip,
    format_screen,
    measure_slips,
    questions_for,
)

ROOT = Path(__file__).resolve().parents[1]
ANNOTATED = Path(__file__).resolve().parent / "fixtures" / "slip_screen" / "annotated.json"
SRC = ROOT / "src" / "ceminiparlays"


class AnnotationEvaluator:
    def __init__(self, slips: list[dict]) -> None:
        self.by_text = {slip["text"]: slip for slip in slips}

    def __call__(self, state: str, questions: dict) -> dict:
        from ceminiparlays.numbered_span import slip_text_from_state

        slip = self.by_text[slip_text_from_state(state)]
        answers = answers_from_annotation(slip)
        missing = set(questions) - set(answers)
        if missing:
            raise KeyError(sorted(missing))
        return {
            "answers": {key: answers[key] for key in questions},
            "usage": {"output_tokens": 0},
        }


def test_annotated_set_has_200_hand_labels() -> None:
    slips = load_annotated(ANNOTATED)
    assert slips == build_annotated_slips()
    assert [slip["id"] for slip in slips] == [f"s{i:03d}" for i in range(1, 201)]
    assert {slip["sample_date"] for slip in slips} == {"2026-11-01"}
    assert {slip["risk_band"] for slip in slips} == set(RISK_LEVELS)
    assert {slip["correlation"] for slip in slips} == set(CORRELATION_LABELS)
    markets = {market for slip in slips for market in slip["markets"]}
    assert markets == set(MARKET_LABELS) - {"absent"}
    blob = ANNOTATED.read_text(encoding="utf-8").lower()
    for banned in ("api_key", "password", "bearer", "typesafe"):
        assert banned not in blob
    for slip in slips:
        assert gold_risk_band(int(slip["leg_count"]), slip["correlation"]) == slip["risk_band"]
        for span in slip["spans"].values():
            assert slip["text"][span["start"] : span["end"]] == span["value"]


def test_multiword_slice_equals_the_source() -> None:
    text = "Patrick Mahomes pass yds Over 274.5"
    tokens = tokenize(text)
    span = span_from_indices(text, tokens, "market", 2, 3)
    assert span.value == "pass yds"
    assert text[span.start : span.end] == span.value


def test_a_non_index_choice_raises_and_returns_nothing() -> None:
    def evaluate(state: str, questions: dict) -> dict:
        return {"answers": {"start": {"choice": "+265"}, "end": {"choice": "0"}}}

    with pytest.raises(ValueError, match="token index"):
        extract_span("Parlay +265\n", "price", "the parlay price", evaluate)


def test_extract_span_keeps_the_invariant() -> None:
    text = "price -115 board -110"

    def evaluate(state: str, questions: dict) -> dict:
        return {
            "answers": {"start": {"choice": "1"}, "end": {"choice": "1"}},
            "usage": {"output_tokens": 0},
        }

    span = extract_span(text, "odds", "the price", evaluate)
    assert span.value == "-115"
    assert text[span.start : span.end] == span.value


def test_a_lied_span_fails_the_invariant() -> None:
    span = VerbatimSpan("odds", "-115", 0, 4, 0, 0)
    with pytest.raises(SliceInvariantError):
        span.assert_invariant("xxxx")


def test_unicode_minus_parses_as_the_source_token() -> None:
    from ceminiparlays.slip_screen import format_implied

    assert format_implied("\u2212115") == format_implied("-115")


def test_scripted_evaluator_matches_every_annotated_field() -> None:
    slips = build_annotated_slips()
    report = measure_slips(
        slips,
        AnnotationEvaluator(slips),
        model_id="gold-script",
        sample_date="2026-11-01",
    )
    for name in FIELD_NAMES:
        row = report.fields[name]
        assert row.total > 0
        assert row.exact == row.total, name
    assert report.allows_risk_band() is False


def test_decoy_index_returns_the_board_price() -> None:
    slips = build_annotated_slips()
    slip = slips[0]
    text = slip["text"]
    decoy = next(token for token in tokenize(text) if token.text == "-110")
    base = answers_from_annotation(slip)

    def evaluate(state: str, questions: dict) -> dict:
        answers = dict(base)
        answers["parlay_odds_start"] = {"choice": str(decoy.index)}
        answers["parlay_odds_end"] = {"choice": str(decoy.index)}
        return {"answers": answers, "usage": {"output_tokens": 0}}

    facts = describe_slip(text, evaluate, accuracy=None)
    assert facts.parlay_odds.value == "-110"
    assert text[facts.parlay_odds.start : facts.parlay_odds.end] == "-110"
    assert facts.parlay_odds.value != slip["spans"]["parlay_odds"]["value"]
    assert facts.risk_band is None
    assert "risk_band withheld" in format_screen(facts)


def test_generated_tokens_are_refused() -> None:
    slips = build_annotated_slips()
    slip = slips[0]

    def evaluate(state: str, questions: dict) -> dict:
        return {
            "answers": answers_from_annotation(slip),
            "usage": {"output_tokens": 4},
        }

    with pytest.raises(ValueError, match="generated tokens"):
        describe_slip(slip["text"], evaluate)


def test_questions_are_choice_or_score_only() -> None:
    _state, questions = questions_for(build_annotated_slips()[0]["text"])
    assert questions
    assert {item["type"] for item in questions.values()} <= {"choice", "score"}


def test_risk_band_prints_only_beside_measured_accuracy() -> None:
    slips = build_annotated_slips()
    slip = slips[0]
    report = AccuracyReport(
        model_id=MODEL_ID,
        n=200,
        sample_date="2026-11-01",
        fields={"risk_band": FieldScore("risk_band", 140, 200)},
    )
    facts = describe_slip(slip["text"], AnnotationEvaluator(slips), report)
    rendered = format_screen(facts)
    assert f"risk_band {slip['risk_band']} exact_match=140/200" in rendered
    assert "The operator decides." in rendered
    bare = describe_slip(slip["text"], AnnotationEvaluator(slips), accuracy=None)
    assert bare.risk_band is None
    assert "exact_match=" not in format_screen(bare)


def test_slip_screen_stays_unwired_without_accuracy(tmp_path: Path, capsys) -> None:
    text = tmp_path / "slip.txt"
    text.write_text("SLIP s001\n", encoding="utf-8")
    code = main(["slip-screen", "--text", str(text)])
    out = capsys.readouterr().out
    assert code == 2
    assert "The operator decides." in out
    assert "Nothing in this system acts." in out
    assert "risk_band withheld" in out
    assert "unwired" in out


def test_a_script_accuracy_file_does_not_wire_the_model(tmp_path: Path, capsys) -> None:
    text = tmp_path / "slip.txt"
    text.write_text("hello\n", encoding="utf-8")
    accuracy = tmp_path / "accuracy.json"
    accuracy.write_text(
        json.dumps(
            {
                "model_id": "gold-script",
                "n": 200,
                "sample_date": "2026-11-01",
                "fields": {"risk_band": {"exact": 200, "total": 200}},
            }
        ),
        encoding="utf-8",
    )
    code = main(["slip-screen", "--text", str(text), "--accuracy", str(accuracy)])
    out = capsys.readouterr().out
    assert code == 2
    assert "risk_band withheld" in out
    assert "unwired" in out


def test_help_states_the_boundary(capsys) -> None:
    with pytest.raises(SystemExit) as caught:
        main(["slip-screen", "--help"])
    assert caught.value.code == 0
    text = capsys.readouterr().out
    assert "The operator decides." in text
    assert "bet-submission" in text


def test_screen_modules_stay_offline() -> None:
    for name in ("slip_screen.py", "slip_annotations.py", "numbered_span.py", "d1_local.py"):
        source = (SRC / name).read_text(encoding="utf-8")
        for banned in ("urllib", "TYPESAFE", "openrouter", "playwright", "selenium", "jeveryword"):
            assert banned not in source
    gate = (SRC / "jev_gate.py").read_text(encoding="utf-8")
    assert "slip_screen" not in gate
    assert "d1_local" not in gate
    loader = (SRC / "d1_local.py").read_text(encoding="utf-8")
    assert "system_one(" in loader
    assert "trust_remote_code=True" in loader
