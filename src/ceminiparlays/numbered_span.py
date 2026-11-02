"""Numbered-token extraction.

Every word gets an index. The evaluator may only pick indices. The value is
always ``text[start:end]``. A picked index cannot invent a price, a line, or
a market name.

The evaluator is injected. This module does not call a remote model and it
does not submit a bet.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

_WORD = re.compile(r"\S+")


class SliceInvariantError(ValueError):
    """Raised when a returned value is not the source slice."""


@dataclass(frozen=True)
class Token:
    index: int
    text: str
    start: int
    end: int


@dataclass(frozen=True)
class VerbatimSpan:
    name: str
    value: str
    start: int
    end: int
    start_index: int
    end_index: int

    def assert_invariant(self, text: str) -> None:
        if text[self.start : self.end] != self.value:
            raise SliceInvariantError(
                f"{self.name}: text[{self.start}:{self.end}] != value"
            )


def tokenize(text: str) -> list[Token]:
    return [
        Token(index, match.group(), match.start(), match.end())
        for index, match in enumerate(_WORD.finditer(text))
    ]


def numbered_state(text: str) -> str:
    """Show the source, then one numbered word per line."""

    lines = [f"[{token.index}] {token.text}" for token in tokenize(text)]
    return f"SLIP_TEXT\n{text}\nEND_SLIP_TEXT\nINDEXED\n" + "\n".join(lines)


def slip_text_from_state(state: str) -> str:
    prefix = "SLIP_TEXT\n"
    marker = "\nEND_SLIP_TEXT\n"
    if not state.startswith(prefix) or marker not in state:
        raise ValueError("state is not a numbered slip")
    return state[len(prefix) : state.index(marker)]


def choice_index(answer: dict[str, Any], allowed: set[str]) -> int:
    """Read a choice only when it is one of the token indices."""

    raw = answer.get("choice")
    if isinstance(raw, bool) or not isinstance(raw, (str, int)):
        raise ValueError("choice is not a token index")
    label = str(raw)
    if label not in allowed:
        raise ValueError("choice is not a token index")
    return int(label)


def span_from_indices(
    text: str,
    tokens: list[Token],
    name: str,
    start_index: int,
    end_index: int,
) -> VerbatimSpan:
    if start_index < 0 or end_index >= len(tokens) or end_index < start_index:
        raise ValueError("index out of range")
    start = tokens[start_index].start
    end = tokens[end_index].end
    span = VerbatimSpan(
        name=name,
        value=text[start:end],
        start=start,
        end=end,
        start_index=start_index,
        end_index=end_index,
    )
    span.assert_invariant(text)
    return span


def extract_span(
    text: str,
    name: str,
    instruction: str,
    evaluate: Any,
) -> VerbatimSpan:
    """Ask two choice questions and slice the source with the chosen indices."""

    tokens = tokenize(text)
    if not tokens:
        raise ValueError("slip text is empty")
    criteria = {str(token.index): token.text for token in tokens}
    questions = {
        "start": {
            "type": "choice",
            "instructions": f"Index of the first word of {instruction}.",
            "criteria": criteria,
        },
        "end": {
            "type": "choice",
            "instructions": f"Index of the last word of {instruction}.",
            "criteria": criteria,
        },
    }
    payload = evaluate(numbered_state(text), questions)
    answers = _answers(payload)
    allowed = set(criteria)
    return span_from_indices(
        text,
        tokens,
        name,
        choice_index(answers["start"], allowed),
        choice_index(answers["end"], allowed),
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
