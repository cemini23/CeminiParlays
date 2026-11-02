"""Local slip screen.

The screen describes a slip. It returns facts and, only beside a measured
accuracy, a risk band. The operator decides. Nothing in this system acts.
No output path connects to a bet-submission surface.

The evaluator is injected. LiquidAI/d1-2B is loaded only by the measure and
describe commands after a 200-slip accuracy file exists. Slip text is not
sent to a remote model. This module does not size a stake and it does not
mark a row pass or block.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ceminiparlays.numbered_span import (
    VerbatimSpan,
    choice_index,
    numbered_state,
    span_from_indices,
    tokenize,
)
from ceminiparlays.odds import american_to_decimal, american_to_implied

MODEL_ID = "LiquidAI/d1-2B"
REQUIRED_N = 200
SAMPLE_DATE = "2026-11-01"
MAX_LEGS = 6
MARKET_LABELS = (
    "pass_yds",
    "rush_yds",
    "rec_yds",
    "receptions",
    "anytime_td",
    "spread",
    "total",
    "moneyline",
    "absent",
)
NO_LINE_MARKETS = frozenset({"anytime_td", "moneyline"})
RISK_LEVELS = ("plain", "short_stack", "same_game", "same_player", "long")
CORRELATION_LABELS = ("independent", "same_game", "same_player")
LEG_COUNT_LABELS = ("2", "3", "4", "5", "6")
FIELD_NAMES = (
    "leg_count",
    "markets",
    "correlation",
    "risk_band",
    "implied_probability",
    "quoted_odds",
    "quoted_lines",
)
BOUNDARY = (
    "The screen describes a slip. It returns facts and a risk band. "
    "The operator decides. Nothing in this system acts. "
    "No output path connects to a bet-submission surface."
)
_AMERICAN = re.compile(r"[+-]\d+")


@dataclass(frozen=True)
class FieldScore:
    field: str
    exact: int
    total: int

    @property
    def rate(self) -> float:
        if self.total == 0:
            return 0.0
        return self.exact / self.total


@dataclass(frozen=True)
class AccuracyReport:
    model_id: str
    n: int
    sample_date: str
    fields: dict[str, FieldScore]

    def allows_risk_band(self) -> bool:
        row = self.fields.get("risk_band")
        return (
            self.model_id == MODEL_ID
            and self.n == REQUIRED_N
            and self.sample_date == SAMPLE_DATE
            and row is not None
            and row.total == REQUIRED_N
            and 0 <= row.exact <= row.total
        )


@dataclass(frozen=True)
class SlipFacts:
    leg_count: str
    markets: tuple[str, ...]
    correlation: str
    parlay_odds: VerbatimSpan
    implied_text: str
    quoted: tuple[VerbatimSpan, ...]
    risk_band_raw: str
    risk_band: str | None
    risk_exact_match: str | None


def parse_american(token: str) -> int:
    """Parse one displayed American token. Reject any other string."""

    cleaned = token.strip().replace("\u2212", "-").replace("\u2013", "-")
    if _AMERICAN.fullmatch(cleaned) is None:
        raise ValueError("not an American price token")
    odds = int(cleaned)
    american_to_decimal(odds)
    return odds


def format_implied(token: str) -> str:
    """Implied probability of one verbatim American token, 10 decimal places."""

    return format(american_to_implied(parse_american(token)), ".10f")


def questions_for(text: str) -> tuple[str, dict[str, dict[str, Any]]]:
    """One choice/score payload over the numbered slip. No image question."""

    tokens = tokenize(text)
    if not tokens:
        raise ValueError("slip text is empty")
    criteria = {str(token.index): token.text for token in tokens}
    questions: dict[str, dict[str, Any]] = {
        "leg_count": {
            "type": "choice",
            "instructions": "How many legs are on this slip?",
            "criteria": {label: f"{label} legs" for label in LEG_COUNT_LABELS},
        },
        "correlation": {
            "type": "choice",
            "instructions": "Do the legs share a game or a player?",
            "criteria": {
                "independent": "No shared game and no shared player",
                "same_game": "At least two legs share a game and no player repeats",
                "same_player": "One player is on two or more legs",
            },
        },
        "risk_band": {
            "type": "score",
            "instructions": (
                "Ordered structural band, lowest first. "
                "A description of the slip. The operator decides."
            ),
            "criteria": list(RISK_LEVELS),
        },
    }
    for index in range(1, MAX_LEGS + 1):
        questions[f"market_{index}"] = {
            "type": "choice",
            "instructions": (
                f"Market type of leg {index}. "
                "Choose absent when that leg is not on the slip."
            ),
            "criteria": {label: label for label in MARKET_LABELS},
        }
        questions[f"leg{index}_odds_start"] = _index_question(
            f"Index of the American odds token on leg {index}.",
            criteria,
        )
        questions[f"leg{index}_odds_end"] = _index_question(
            f"End index of the American odds token on leg {index}.",
            criteria,
        )
        questions[f"leg{index}_line_start"] = _index_question(
            f"Index of the line token on leg {index}.",
            criteria,
        )
        questions[f"leg{index}_line_end"] = _index_question(
            f"End index of the line token on leg {index}.",
            criteria,
        )
    questions["parlay_odds_start"] = _index_question(
        "Index of the American parlay price token.",
        criteria,
    )
    questions["parlay_odds_end"] = _index_question(
        "End index of the American parlay price token.",
        criteria,
    )
    return numbered_state(text), questions


def describe_slip(
    text: str,
    evaluate: Any,
    accuracy: AccuracyReport | None = None,
) -> SlipFacts:
    """Describe one pasted slip. Withhold the risk band until accuracy exists."""

    if not text.strip():
        raise ValueError("slip text is empty")
    state, questions = questions_for(text)
    answers = _answers(evaluate(state, questions))
    leg_count = _label(answers["leg_count"], set(LEG_COUNT_LABELS))
    markets = tuple(
        _label(answers[f"market_{index}"], set(MARKET_LABELS))
        for index in range(1, int(leg_count) + 1)
    )
    if "absent" in markets:
        raise ValueError("a listed leg has no market")
    correlation = _label(answers["correlation"], set(CORRELATION_LABELS))
    tokens = tokenize(text)
    quoted: list[VerbatimSpan] = [_span(text, tokens, answers, "parlay_odds")]
    for index, market in enumerate(markets, start=1):
        quoted.append(_span(text, tokens, answers, f"leg{index}_odds"))
        if market not in NO_LINE_MARKETS:
            quoted.append(_span(text, tokens, answers, f"leg{index}_line"))
    for span in quoted:
        span.assert_invariant(text)
    raw_band = _risk_name(answers["risk_band"])
    shown, rate = _shown_band(raw_band, accuracy)
    return SlipFacts(
        leg_count=leg_count,
        markets=markets,
        correlation=correlation,
        parlay_odds=quoted[0],
        implied_text=format_implied(quoted[0].value),
        quoted=tuple(quoted),
        risk_band_raw=raw_band,
        risk_band=shown,
        risk_exact_match=rate,
    )


def answers_from_annotation(slip: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Answer payload for a hand annotation. This is not a model call."""

    _state, questions = questions_for(slip["text"])
    answers: dict[str, dict[str, Any]] = {
        "leg_count": {"choice": slip["leg_count"]},
        "correlation": {"choice": slip["correlation"]},
        "risk_band": {
            "score": RISK_LEVELS.index(slip["risk_band"]),
            "legend": {str(i): name for i, name in enumerate(RISK_LEVELS)},
        },
    }
    markets = list(slip["markets"])
    for index in range(1, MAX_LEGS + 1):
        label = markets[index - 1] if index <= len(markets) else "absent"
        answers[f"market_{index}"] = {"choice": label}
    for name, span in slip["spans"].items():
        answers[f"{name}_start"] = {"choice": str(span["start_index"])}
        answers[f"{name}_end"] = {"choice": str(span["end_index"])}
    for key in questions:
        if key not in answers:
            answers[key] = {"choice": "0"}
    extra = set(answers) - set(questions)
    if extra:
        raise ValueError(f"annotation answers have unknown keys: {sorted(extra)}")
    return answers


def measure_slips(
    slips: list[dict[str, Any]],
    evaluate: Any,
    *,
    model_id: str,
    sample_date: str,
) -> AccuracyReport:
    """Per-field exact match. The caller names the model. A script is not d1."""

    if len(slips) != REQUIRED_N:
        raise ValueError("the annotated set must contain 200 slips")
    exact = {name: 0 for name in FIELD_NAMES}
    total = {name: 0 for name in FIELD_NAMES}
    for slip in slips:
        odds_names = [name for name in slip["spans"] if name.endswith("_odds")]
        line_names = [name for name in slip["spans"] if name.endswith("_line")]
        total["leg_count"] += 1
        total["markets"] += 1
        total["correlation"] += 1
        total["risk_band"] += 1
        total["implied_probability"] += 1
        total["quoted_odds"] += len(odds_names)
        total["quoted_lines"] += len(line_names)
        try:
            facts = describe_slip(slip["text"], evaluate, accuracy=None)
        except (ValueError, KeyError):
            continue
        if facts.leg_count == slip["leg_count"]:
            exact["leg_count"] += 1
        if list(facts.markets) == list(slip["markets"]):
            exact["markets"] += 1
        if facts.correlation == slip["correlation"]:
            exact["correlation"] += 1
        if facts.risk_band_raw == slip["risk_band"]:
            exact["risk_band"] += 1
        if facts.implied_text == slip["implied_probability"]:
            exact["implied_probability"] += 1
        found = {span.name: span for span in facts.quoted}
        for name in odds_names:
            exact["quoted_odds"] += _span_ok(slip, found.get(name), name)
        for name in line_names:
            exact["quoted_lines"] += _span_ok(slip, found.get(name), name)
    fields = {name: FieldScore(name, exact[name], total[name]) for name in FIELD_NAMES}
    return AccuracyReport(
        model_id=model_id,
        n=REQUIRED_N,
        sample_date=sample_date,
        fields=fields,
    )


def load_accuracy(path: Path) -> AccuracyReport:
    payload = json.loads(path.read_text(encoding="utf-8"))
    fields = {
        str(name): FieldScore(str(name), int(row["exact"]), int(row["total"]))
        for name, row in payload["fields"].items()
    }
    return AccuracyReport(
        model_id=str(payload["model_id"]),
        n=int(payload["n"]),
        sample_date=str(payload["sample_date"]),
        fields=fields,
    )


def write_accuracy(path: Path, report: AccuracyReport) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = {
        "model_id": report.model_id,
        "n": report.n,
        "sample_date": report.sample_date,
        "fields": {
            name: {"exact": report.fields[name].exact, "total": report.fields[name].total}
            for name in FIELD_NAMES
            if name in report.fields
        },
    }
    path.write_text(json.dumps(body, indent=2) + "\n", encoding="utf-8")


def format_screen(facts: SlipFacts) -> str:
    lines = [
        BOUNDARY,
        f"leg_count {facts.leg_count}",
        f"markets {','.join(facts.markets)}",
        f"correlation {facts.correlation}",
        (
            f"parlay_odds {facts.parlay_odds.value} "
            f"slice={facts.parlay_odds.start}:{facts.parlay_odds.end}"
        ),
        f"implied_probability {facts.implied_text}",
    ]
    for span in facts.quoted:
        if span.name == "parlay_odds":
            continue
        lines.append(f"quoted {span.name} {span.value} slice={span.start}:{span.end}")
    if facts.risk_band is None or facts.risk_exact_match is None:
        lines.append("risk_band withheld")
    else:
        lines.append(f"risk_band {facts.risk_band} exact_match={facts.risk_exact_match}")
    return "\n".join(lines) + "\n"


def format_withheld(reason: str) -> str:
    return f"{BOUNDARY}\nrisk_band withheld\n{reason}\n"


def format_accuracy(report: AccuracyReport) -> str:
    lines = [
        f"model {report.model_id}",
        f"n {report.n}",
        f"sample_date {report.sample_date}",
    ]
    for name in FIELD_NAMES:
        row = report.fields[name]
        lines.append(f"{name} {row.exact}/{row.total}")
    lines.append("This report describes field accuracy. It does not place a bet.")
    return "\n".join(lines) + "\n"


def _index_question(instruction: str, criteria: dict[str, str]) -> dict[str, Any]:
    return {"type": "choice", "instructions": instruction, "criteria": criteria}


def _label(answer: dict[str, Any], allowed: set[str]) -> str:
    raw = answer.get("choice")
    if isinstance(raw, bool) or not isinstance(raw, (str, int)):
        raise ValueError("choice is outside the label set")
    label = str(raw)
    if label not in allowed:
        raise ValueError("choice is outside the label set")
    return label


def _risk_name(answer: dict[str, Any]) -> str:
    raw = answer.get("score")
    if isinstance(raw, bool):
        raise ValueError("score is not a level")
    if isinstance(raw, int):
        level = raw
    elif isinstance(raw, float) and raw.is_integer():
        level = int(raw)
    else:
        raise ValueError("score is not a level")
    if not 0 <= level < len(RISK_LEVELS):
        raise ValueError("score is outside the levels")
    expected = RISK_LEVELS[level]
    legend = answer.get("legend")
    if isinstance(legend, dict) and str(level) in legend:
        named = str(legend[str(level)])
        if named != expected:
            raise ValueError("risk legend does not match the ordered levels")
    return expected


def _span(
    text: str,
    tokens: list[Any],
    answers: dict[str, Any],
    name: str,
) -> VerbatimSpan:
    allowed = {str(token.index) for token in tokens}
    return span_from_indices(
        text,
        tokens,
        name,
        choice_index(answers[f"{name}_start"], allowed),
        choice_index(answers[f"{name}_end"], allowed),
    )


def _answers(payload: dict[str, Any]) -> dict[str, Any]:
    if "answers" not in payload:
        raise ValueError("evaluator returned no answers")
    usage = payload.get("usage")
    if isinstance(usage, dict) and int(usage.get("output_tokens") or 0) != 0:
        raise ValueError("evaluator generated tokens")
    answers = payload["answers"]
    if not isinstance(answers, dict):
        raise ValueError("evaluator returned no answers")
    return answers


def _shown_band(
    raw: str,
    accuracy: AccuracyReport | None,
) -> tuple[str | None, str | None]:
    if accuracy is None or not accuracy.allows_risk_band():
        return None, None
    row = accuracy.fields["risk_band"]
    return raw, f"{row.exact}/{row.total}"


def _span_ok(slip: dict[str, Any], span: VerbatimSpan | None, name: str) -> int:
    if span is None:
        return 0
    gold = slip["spans"][name]
    text = slip["text"]
    if span.value != gold["value"]:
        return 0
    if text[span.start : span.end] != span.value:
        return 0
    if text[gold["start"] : gold["end"]] != gold["value"]:
        return 0
    return 1
