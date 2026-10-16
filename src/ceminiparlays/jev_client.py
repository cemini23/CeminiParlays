"""Tiered typed Jev client: System One API, then Jev MCP, then OpenRouter.

Jev is a discrete epistemic router. It answers a typed question about a
structured state and returns calibrated probabilities, a score, and a
confidence. This module never de-vigs, projects a correlation matrix, draws a
copula, or sizes a stake: ``numpy`` and ``scipy`` do that elsewhere.

HTTP uses stdlib ``urllib`` only, the same rule as ``odds_api``. Every answer
is cached on disk as ``data/cache/jev/<sha256>.json``, so a repeated question
costs no network call and a rerun is deterministic.

Routing (``--jev-provider``):

* ``auto`` tries System One (Primary A), then Jev MCP (Primary B), then
  OpenRouter (backup). It moves on only for a missing configuration or a
  transient failure (timeout, HTTP 429, HTTP 5xx).
* ``typesafe`` / ``mcp`` / ``openrouter`` force one provider with no failover,
  so an operator can pin and test a single path.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ceminiparlays.jev_gate import _match_id, _parse_tool_text, _rpc_payload

PROVIDERS = ("auto", "typesafe", "mcp", "openrouter")
DEFAULT_PROVIDER = "auto"
DEFAULT_TYPESAFE_BASE = "https://api.typesafe.ai"
SYSTEMONE_PATH = "/v1/systemone"
DEFAULT_MODEL = "jev-1.13"
BACKUP_MODEL = "typesafe/jev-1.13"
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
TYPESAFE_KEY_ENVS = ("TYPESAFE_API_KEY", "TYPESAFE_AI_API_KEY")
DEFAULT_KEY_FILE = "~/.cemini/typesafe-api-key"
DEFAULT_CACHE_DIR = "data/cache/jev"
DEFAULT_TIMEOUT = 30
CALL_TIMEOUT_S = 60
DEFAULT_SCALE = (-2, -1, 0, 1, 2)

#: HTTP statuses that mean "this provider is down, try the next one". Anything
#: else (400, 401, 404) is the caller's mistake and must not be retried down
#: the chain, or a bad key would silently bill the backup provider.
TRANSIENT_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504})


class JevProviderError(ValueError):
    """One provider could not answer.

    A ``ValueError`` so the CLI reports it as ``error: ...`` and exits 2, the
    same way ``odds_api`` reports an HTTP failure. ``auto`` fails over to the
    next provider only when this provider is ``unconfigured`` (no key, no
    binary) or the failure is ``transient`` (timeout, HTTP 429, HTTP 5xx). A
    permanent failure such as HTTP 401 stops the chain, so a bad key can never
    silently bill the backup provider.
    """

    def __init__(self, message: str, *, transient: bool, unconfigured: bool = False) -> None:
        super().__init__(message)
        self.transient = transient
        self.unconfigured = unconfigured


@dataclass(frozen=True)
class ScoreResult:
    probabilities: dict[int, float]
    expected_score: float
    confidence: float
    provider_used: str


@dataclass(frozen=True)
class ChoiceResult:
    probabilities: dict[str, float]
    top_choice: str
    confidence: float
    provider_used: str


@dataclass(frozen=True)
class NoulResult:
    noul: float
    provider_used: str


def typesafe_api_key() -> str:
    """Resolve the System One key from the environment, then the key file."""

    for name in TYPESAFE_KEY_ENVS:
        value = os.environ.get(name, "").strip()
        if value:
            return value
    path = Path(os.environ.get("TYPESAFE_KEY_FILE", DEFAULT_KEY_FILE)).expanduser()
    if path.is_file():
        try:
            return path.read_text(encoding="utf-8").strip()
        except OSError:
            return ""
    return ""


def _redact(message: str) -> str:
    """Never let a key reach a log or an exception message."""

    for name in TYPESAFE_KEY_ENVS:
        value = os.environ.get(name, "").strip()
        if value:
            message = message.replace(value, "***")
    return message


def _canon(payload: object) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def cache_digest(questions: list[dict], state: dict) -> str:
    """Deterministic hash of the logical request, independent of the provider."""

    body = {"state": state, "questions": questions, "v": 1}
    return hashlib.sha256(_canon(body).encode("utf-8")).hexdigest()


def cache_file(cache_dir: Path, digest: str) -> Path:
    return Path(cache_dir) / f"{digest}.json"


def _read_cache(cache_dir: Path, digest: str) -> dict | None:
    path = cache_file(cache_dir, digest)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _write_cache(cache_dir: Path, digest: str, record: dict) -> None:
    path = cache_file(cache_dir, digest)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_canon(record) + "\n", encoding="utf-8")
    except OSError:
        # A cache that cannot be written must not fail a good answer.
        return


def _score_probabilities(raw: object, scale: tuple[int, ...]) -> dict[int, float]:
    if not isinstance(raw, dict) or not raw:
        raise JevProviderError("score response missing probabilities", transient=False)
    out: dict[int, float] = {}
    for key, value in raw.items():
        try:
            point = int(key)
        except (TypeError, ValueError) as exc:
            raise JevProviderError("score probability key is not an integer", transient=False) from exc
        if point not in scale:
            raise JevProviderError(f"score probability key {point} is off scale", transient=False)
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise JevProviderError("score probability is not a number", transient=False)
        if float(value) < 0.0:
            raise JevProviderError("score probability is negative", transient=False)
        out[point] = float(value)
    total = sum(out.values())
    if total <= 0.0:
        raise JevProviderError("score probabilities sum to zero", transient=False)
    return {point: value / total for point, value in out.items()}


def expected_score(probabilities: dict[int, float]) -> float:
    """Probability-weighted mean over the scale points."""

    return float(sum(point * value for point, value in probabilities.items()))


def _choice_probabilities(raw: object, choices: list[str]) -> dict[str, float]:
    if not isinstance(raw, dict) or not raw:
        raise JevProviderError("choice response missing probabilities", transient=False)
    out: dict[str, float] = {}
    for key, value in raw.items():
        name = str(key)
        if name not in choices:
            raise JevProviderError(f"choice {name!r} is not a candidate", transient=False)
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise JevProviderError("choice probability is not a number", transient=False)
        if float(value) < 0.0:
            raise JevProviderError("choice probability is negative", transient=False)
        out[name] = float(value)
    total = sum(out.values())
    if total <= 0.0:
        raise JevProviderError("choice probabilities sum to zero", transient=False)
    for name in choices:
        out.setdefault(name, 0.0)
    return {name: value / total for name, value in out.items()}


def _confidence(raw: object) -> float:
    if not isinstance(raw, (int, float)) or isinstance(raw, bool):
        raise JevProviderError("response missing confidence", transient=False)
    return min(max(float(raw), 0.0), 1.0)


def _noul_value(raw: object) -> float:
    if not isinstance(raw, (int, float)) or isinstance(raw, bool):
        raise JevProviderError("noul response missing noul", transient=False)
    return min(max(float(raw), 0.0), 1.0)


def build_questions(
    *,
    scores: list[tuple[str, tuple[int, ...]]],
    choices: list[tuple[str, list[str]]],
    nouls: list[str],
) -> list[dict]:
    """Flatten every typed question for one state into one System One payload."""

    questions: list[dict] = []
    for question, scale in scores:
        questions.append(
            {
                "id": f"q{len(questions)}",
                "kind": "score",
                "question": question,
                "scale": list(scale),
            }
        )
    for question, options in choices:
        questions.append(
            {
                "id": f"q{len(questions)}",
                "kind": "choice",
                "question": question,
                "choices": list(options),
            }
        )
    for question in nouls:
        questions.append({"id": f"q{len(questions)}", "kind": "noul", "question": question})
    return questions


def parse_systemone(payload: object, questions: list[dict]) -> list[dict]:
    """Order results by question id. A missing or malformed result fails closed."""

    if not isinstance(payload, dict):
        raise JevProviderError("systemone payload is not an object", transient=False)
    results = payload.get("results")
    if not isinstance(results, list):
        raise JevProviderError("systemone payload missing results", transient=False)
    by_id: dict[str, dict] = {}
    for item in results:
        if not isinstance(item, dict) or "id" not in item:
            raise JevProviderError("systemone result missing id", transient=False)
        by_id[str(item["id"])] = item
    ordered: list[dict] = []
    for question in questions:
        item = by_id.get(str(question["id"]))
        if item is None:
            raise JevProviderError(f"systemone missing {question['id']}", transient=False)
        ordered.append(item)
    return ordered


def _post_json(
    url: str,
    body: dict,
    *,
    headers: dict[str, str],
    opener: Any | None = None,
    timeout: int = DEFAULT_TIMEOUT,
) -> object:
    """POST JSON via stdlib urllib. Raises ``JevProviderError`` with a transient flag."""

    handle = opener or urllib.request.build_opener()
    data = json.dumps(body).encode("utf-8")
    request = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with handle.open(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        exc.close()
        raise JevProviderError(
            _redact(f"jev http {exc.code}"),
            transient=exc.code in TRANSIENT_STATUS,
        ) from exc
    except urllib.error.URLError as exc:
        raise JevProviderError(_redact(f"jev request failed: {exc.reason}"), transient=True) from exc
    except (TimeoutError, OSError) as exc:
        raise JevProviderError(_redact(f"jev request failed: {exc}"), transient=True) from exc
    except json.JSONDecodeError as exc:
        raise JevProviderError("jev response is not json", transient=True) from exc


def _mcp_questions(state: dict, questions: list[dict], bin_path: str | None) -> list[dict]:
    """One stdio JSON-RPC call per typed question through the mcp-jev launcher."""

    resolved = bin_path if bin_path is not None else os.environ.get("JEV_MCP_BIN", "")
    if not resolved or not Path(resolved).is_file():
        raise JevProviderError("missing jev mcp binary", transient=False, unconfigured=True)
    out: list[dict] = []
    for question in questions:
        arguments = {
            "state": state,
            "question": question["question"],
            "kind": question["kind"],
        }
        if question["kind"] == "score":
            arguments["scale"] = question["scale"]
        elif question["kind"] == "choice":
            arguments["choices"] = question["choices"]
        try:
            completed = subprocess.run(
                [resolved],
                input=_rpc_payload(f"jev_{question['kind']}", arguments),
                capture_output=True,
                text=True,
                timeout=CALL_TIMEOUT_S,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise JevProviderError("jev mcp timed out", transient=True) from exc
        except OSError as exc:
            raise JevProviderError("jev mcp failed to start", transient=True) from exc
        if completed.returncode != 0:
            raise JevProviderError(
                f"jev mcp exited {completed.returncode}", transient=True
            )
        try:
            out.append(_parse_tool_text(_match_id(completed.stdout, call_id=2)))
        except Exception as exc:  # JevError and parse failures both fail over
            raise JevProviderError("jev mcp response is malformed", transient=False) from exc
    return out


def _systemone_body(state: dict, questions: list[dict], model: str) -> dict:
    return {"model": model, "mode": "typed", "state": state, "questions": questions}


def _openrouter_prompt(state: dict, question: dict) -> str:
    instruction = (
        "You are a discrete epistemic router. Answer the question about the "
        "state with calibrated probabilities. Reply with one JSON object only, "
        "no prose and no code fence."
    )
    schema = {
        "score": '{"probabilities": {"-2": 0.0, "-1": 0.0, "0": 0.0, "1": 0.0, "2": 0.0},'
        ' "confidence": 0.0}',
        "choice": '{"probabilities": {"<choice>": 0.0}, "confidence": 0.0}',
        "noul": '{"noul": 0.0}',
    }[question["kind"]]
    extra = ""
    if question["kind"] == "score":
        extra = f" Use exactly these scale points: {question['scale']}."
    elif question["kind"] == "choice":
        extra = f" Candidates: {question['choices']}."
    return (
        f"{instruction}\nState: {_canon(state)}\n"
        f"Question: {question['question']}{extra}\nReturn exactly: {schema}"
    )


def _openrouter_question(
    state: dict,
    question: dict,
    *,
    api_key: str,
    model: str,
    opener: Any | None,
    timeout: int,
) -> dict:
    body = {
        "model": model,
        "messages": [{"role": "user", "content": _openrouter_prompt(state, question)}],
        "response_format": {"type": "json_object"},
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = _post_json(OPENROUTER_URL, body, headers=headers, opener=opener, timeout=timeout)
    if not isinstance(payload, dict):
        raise JevProviderError("openrouter payload is not an object", transient=False)
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        raise JevProviderError("openrouter payload missing choices", transient=False)
    content = (choices[0].get("message") or {}).get("content")
    if not isinstance(content, str):
        raise JevProviderError("openrouter message missing content", transient=False)
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as exc:
        raise JevProviderError("openrouter content is not json", transient=False) from exc
    if not isinstance(parsed, dict):
        raise JevProviderError("openrouter content is not an object", transient=False)
    return parsed


def _as_result(question: dict, item: dict) -> dict:
    """Normalize one provider answer into the shared ``Result`` shape."""

    kind = str(question["kind"])
    if kind == "score":
        probabilities = _score_probabilities(
            item.get("probabilities"), tuple(int(point) for point in question["scale"])
        )
        return {
            "kind": "score",
            "probabilities": probabilities,
            "expected_score": expected_score(probabilities),
            "confidence": _confidence(item.get("confidence")),
        }
    if kind == "choice":
        probabilities = _choice_probabilities(
            item.get("probabilities"), [str(name) for name in question["choices"]]
        )
        top = max(probabilities, key=lambda name: probabilities[name])
        return {
            "kind": "choice",
            "probabilities": probabilities,
            "top_choice": top,
            "confidence": _confidence(item.get("confidence")),
        }
    return {"kind": "noul", "noul": _noul_value(item.get("noul"))}


class JevClient:
    """Typed Jev calls with disk cache and provider failover."""

    def __init__(
        self,
        *,
        provider: str = DEFAULT_PROVIDER,
        cache_dir: Path | str = DEFAULT_CACHE_DIR,
        model: str = DEFAULT_MODEL,
        typesafe_base: str | None = None,
        opener: Any | None = None,
        mcp_bin: str | None = None,
        timeout: int = DEFAULT_TIMEOUT,
        use_cache: bool = True,
    ) -> None:
        if provider not in PROVIDERS:
            raise ValueError(f"unknown jev provider: {provider}")
        self.provider = provider
        self.cache_dir = Path(cache_dir)
        self.model = model
        self.typesafe_base = (
            typesafe_base or os.environ.get("TYPESAFE_API_BASE", "").strip() or DEFAULT_TYPESAFE_BASE
        ).rstrip("/")
        self.opener = opener
        self.mcp_bin = mcp_bin
        self.timeout = timeout
        self.use_cache = use_cache

    # -- public typed calls ------------------------------------------------

    def jev_score(
        self,
        state: dict,
        question: str,
        scale: list[int | str] | tuple[int, ...] | None = None,
    ) -> ScoreResult:
        points = self._scale_points(scale)
        answer = self._answer(state, [{"kind": "score", "question": question, "scale": points}])[0]
        return ScoreResult(
            probabilities=answer["probabilities"],
            expected_score=answer["expected_score"],
            confidence=answer["confidence"],
            provider_used=answer["provider_used"],
        )

    def jev_choice(self, state: dict, question: str, choices: list[str]) -> ChoiceResult:
        if not choices:
            raise ValueError("choices must not be empty")
        answer = self._answer(
            state, [{"kind": "choice", "question": question, "choices": list(choices)}]
        )[0]
        return ChoiceResult(
            probabilities=answer["probabilities"],
            top_choice=answer["top_choice"],
            confidence=answer["confidence"],
            provider_used=answer["provider_used"],
        )

    def jev_noul(self, state: dict, question: str) -> NoulResult:
        answer = self._answer(state, [{"kind": "noul", "question": question}])[0]
        return NoulResult(noul=answer["noul"], provider_used=answer["provider_used"])

    def score_bundle(
        self, state: dict, questions: list[tuple[str, list[int | str] | None]]
    ) -> list[ScoreResult]:
        """Score several questions for one state in a single System One call."""

        typed = [
            {"kind": "score", "question": question, "scale": self._scale_points(scale)}
            for question, scale in questions
        ]
        answers = self._answer(state, typed)
        return [
            ScoreResult(
                probabilities=answer["probabilities"],
                expected_score=answer["expected_score"],
                confidence=answer["confidence"],
                provider_used=answer["provider_used"],
            )
            for answer in answers
        ]

    # -- internals ---------------------------------------------------------

    @staticmethod
    def _scale_points(scale: list[int | str] | tuple[int, ...] | None) -> tuple[int, ...]:
        if scale is None:
            return tuple(int(point) for point in DEFAULT_SCALE)
        points: list[int] = []
        for point in scale:
            try:
                points.append(int(point))
            except (TypeError, ValueError) as exc:
                raise ValueError(f"score scale point {point!r} is not an integer") from exc
        if not points:
            raise ValueError("score scale must not be empty")
        return tuple(points)

    def _answer(self, state: dict, typed: list[dict]) -> list[dict]:
        questions = build_questions(
            scores=[
                (item["question"], tuple(item["scale"])) for item in typed if item["kind"] == "score"
            ],
            choices=[
                (item["question"], list(item["choices"])) for item in typed if item["kind"] == "choice"
            ],
            nouls=[item["question"] for item in typed if item["kind"] == "noul"],
        )
        digest = cache_digest(questions, state)
        if self.use_cache:
            cached = _read_cache(self.cache_dir, digest)
            if cached is not None:
                return self._from_record(cached, questions)
        last: JevProviderError | None = None
        for provider in self._routing():
            try:
                items = self._ask(provider, state, questions)
            except JevProviderError as exc:
                last = exc
                if self.provider != "auto" or not (exc.transient or exc.unconfigured):
                    raise
                continue
            label = "openrouter_backup" if provider == "openrouter" else provider
            answers = [_as_result(question, item) for question, item in zip(questions, items)]
            for answer in answers:
                answer["provider_used"] = label
            if self.use_cache:
                _write_cache(self.cache_dir, digest, {"provider": label, "answers": answers})
            return answers
        raise JevProviderError(
            f"no jev provider could answer (last: {last})",
            transient=False,
            unconfigured=bool(last is not None and last.unconfigured),
        )

    def _routing(self) -> list[str]:
        if self.provider != "auto":
            return [self.provider]
        return ["typesafe", "mcp", "openrouter"]

    def _ask(self, provider: str, state: dict, questions: list[dict]) -> list[dict]:
        if provider == "typesafe":
            return self._ask_typesafe(state, questions)
        if provider == "mcp":
            return _mcp_questions(state, questions, self.mcp_bin)
        return self._ask_openrouter(state, questions)

    def _ask_typesafe(self, state: dict, questions: list[dict]) -> list[dict]:
        key = typesafe_api_key()
        if not key:
            raise JevProviderError("typesafe api key is unset", transient=False, unconfigured=True)
        url = f"{self.typesafe_base}{SYSTEMONE_PATH}"
        headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
        payload = _post_json(
            url,
            _systemone_body(state, questions, self.model),
            headers=headers,
            opener=self.opener,
            timeout=self.timeout,
        )
        return parse_systemone(payload, questions)

    def _ask_openrouter(self, state: dict, questions: list[dict]) -> list[dict]:
        key = os.environ.get("OPENROUTER_API_KEY", "").strip()
        if not key:
            raise JevProviderError("openrouter api key is unset", transient=False, unconfigured=True)
        return [
            _openrouter_question(
                state,
                question,
                api_key=key,
                model=BACKUP_MODEL,
                opener=self.opener,
                timeout=self.timeout,
            )
            for question in questions
        ]

    @staticmethod
    def _from_record(record: dict, questions: list[dict]) -> list[dict]:
        answers = record.get("answers")
        if not isinstance(answers, list) or len(answers) != len(questions):
            raise JevProviderError("jev cache record is malformed", transient=False)
        return answers
