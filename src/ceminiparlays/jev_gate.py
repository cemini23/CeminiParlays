"""Jev gate for a composed card.

Jev answers questions. This module does not price a leg, size a stake, or submit a ticket.
A missing server, a bad response, or a fixture miss fails closed.
"""

from __future__ import annotations

import csv
import json
import os
import subprocess
from dataclasses import dataclass
from io import StringIO
from pathlib import Path
from typing import Protocol

from ceminiparlays import __version__

REPORT_COLUMNS = [
    "ticket_id",
    "leg",
    "player",
    "question",
    "primitive",
    "result",
    "confidence",
    "action",
    "evidence_ref",
]
ACTIONS = ("pass", "do_not_type", "thesis_unsupported", "review", "block")
AUTO_ACCEPT = 0.80
EXISTS_FLOOR = 0.50
DEFAULT_BIN = "/Users/claudiobarone/.local/bin/mcp-jev"
CALL_TIMEOUT_S = 60


class JevError(RuntimeError):
    """The Jev server or the fixture could not answer. The gate fails closed."""


class JevClient(Protocol):
    def verify(
        self, claims: list[str], evidence: str, auto_accept: float = AUTO_ACCEPT
    ) -> dict: ...

    def find(self, query: str, candidates: list[dict], top_k: int = 3) -> dict: ...


def verify_arguments(
    claims: list[str], evidence: str, auto_accept: float = AUTO_ACCEPT
) -> dict:
    return {"claims": list(claims), "evidence": evidence, "auto_accept": auto_accept}


def find_arguments(query: str, candidates: list[dict], top_k: int = 3) -> dict:
    return {"query": query, "candidates": candidates, "top_k": top_k}


def ticket_type_candidates() -> list[dict[str, str]]:
    return [
        {
            "id": "promo_hedge",
            "text": "A promo hedge uses a book promotion and is not a priced edge.",
        },
        {
            "id": "real_hedge",
            "text": "A real hedge offsets exposure on the other side of a position.",
        },
        {
            "id": "straight_bet",
            "text": "A straight bet is a normal parlay or single with no hedge.",
        },
    ]


def leg_validity_claim(
    *,
    player: str,
    stat_type: str,
    side: str,
    line: object,
    platform: str,
) -> str:
    return (
        f"The lines file shows line {_fmt_line(line)} for {player} "
        f"{stat_type} on {side} at {platform}."
    )


def status_claim(player: str) -> str:
    return f"{player} is expected to be active for this game."


def thesis_claim(team: str, side: str = "more") -> str:
    """The passing-volume claim for a ``pass_yds`` leg, per its side.

    An Over needs high volume and an Under needs low volume (A-06).
    """

    token = (side or "").strip().lower()
    volume = "low" if token in {"less", "under", "lower", "u"} else "high"
    return (
        f"{team} is projected for {volume} passing volume, given the spread, "
        "the total, and the implied team total."
    )


def promo_claim(terms: str) -> str:
    return f"Player props qualify for this promo: {terms}"


def choice_query(legs: list[dict]) -> str:
    parts = [
        f"{leg['player_name']} {str(leg['side']).strip()} {_fmt_line(leg['line'])} "
        f"{str(leg['stat_type']).strip()}"
        for leg in legs
    ]
    summary = "; ".join(parts)
    return f"Which ticket type is this: {summary}?"


def thesis_evidence(environment_text: str, lines_text: str) -> str:
    return environment_text + lines_text


def _fmt_line(value: object) -> str:
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, (int, float)):
        number = float(value)
        if number.is_integer():
            return str(int(number))
        return str(number)
    return str(value).strip()


def _fmt_confidence(value: float) -> str:
    text = f"{float(value):.6f}".rstrip("0").rstrip(".")
    return text or "0"


def _canon(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


class FixtureJevClient:
    """Replay recorded exchanges. A miss fails closed."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise JevError(f"unreadable jev fixture: {self.path.name}") from exc
        exchanges = data.get("exchanges") if isinstance(data, dict) else None
        if not isinstance(exchanges, list):
            raise JevError("jev fixture missing exchanges")
        self._by_key: dict[tuple[str, str], dict] = {}
        for item in exchanges:
            if not isinstance(item, dict):
                raise JevError("jev fixture exchange is not an object")
            tool = item.get("tool")
            arguments = item.get("arguments")
            result = item.get("result")
            if (
                not isinstance(tool, str)
                or not isinstance(arguments, dict)
                or not isinstance(result, dict)
            ):
                raise JevError("jev fixture exchange is malformed")
            self._by_key[(tool, _canon(arguments))] = result

    def verify(
        self, claims: list[str], evidence: str, auto_accept: float = AUTO_ACCEPT
    ) -> dict:
        return self._lookup("jev_verify", verify_arguments(claims, evidence, auto_accept))

    def find(self, query: str, candidates: list[dict], top_k: int = 3) -> dict:
        return self._lookup("jev_find", find_arguments(query, candidates, top_k))

    def _lookup(self, tool: str, arguments: dict) -> dict:
        found = self._by_key.get((tool, _canon(arguments)))
        if found is None:
            raise JevError(f"no fixture exchange for {tool}")
        return found


class McpJevClient:
    """One stdio JSON-RPC call to the mcp-jev launcher."""

    def __init__(self, record_path: Path | None = None, bin_path: str | None = None) -> None:
        self.record_path = Path(record_path) if record_path is not None else None
        self.bin_path = bin_path if bin_path is not None else os.environ.get(
            "JEV_MCP_BIN", DEFAULT_BIN
        )

    def verify(
        self, claims: list[str], evidence: str, auto_accept: float = AUTO_ACCEPT
    ) -> dict:
        arguments = verify_arguments(claims, evidence, auto_accept)
        result = self._call("jev_verify", arguments)
        self._record("jev_verify", arguments, result)
        return result

    def find(self, query: str, candidates: list[dict], top_k: int = 3) -> dict:
        arguments = find_arguments(query, candidates, top_k)
        result = self._call("jev_find", arguments)
        self._record("jev_find", arguments, result)
        return result

    def _call(self, tool: str, arguments: dict) -> dict:
        if not self.bin_path or not Path(self.bin_path).is_file():
            raise JevError("missing jev server binary")
        payload = _rpc_payload(tool, arguments)
        try:
            completed = subprocess.run(
                [self.bin_path],
                input=payload,
                capture_output=True,
                text=True,
                timeout=CALL_TIMEOUT_S,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise JevError("jev server timed out") from exc
        except OSError as exc:
            raise JevError("jev server failed to start") from exc
        if completed.returncode != 0:
            raise JevError(f"jev server exited {completed.returncode}")
        message = _match_id(completed.stdout, call_id=2)
        return _parse_tool_text(message)

    def _record(self, tool: str, arguments: dict, result: dict) -> None:
        if self.record_path is None:
            return
        path = self.record_path
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise JevError(f"unreadable jev record: {path.name}") from exc
            if not isinstance(data, dict) or not isinstance(data.get("exchanges"), list):
                data = {"exchanges": []}
        else:
            data = {"exchanges": []}
        data["exchanges"].append(
            {"tool": tool, "arguments": arguments, "result": result}
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def resolve_client(
    fixture_path: Path | None = None,
    record_path: Path | None = None,
) -> JevClient:
    if fixture_path is not None:
        return FixtureJevClient(fixture_path)
    return McpJevClient(record_path=record_path)


def _rpc_payload(tool: str, arguments: dict) -> str:
    messages = [
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "ceminiparlays", "version": __version__},
            },
        },
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": tool, "arguments": arguments},
        },
    ]
    return "\n".join(json.dumps(message) for message in messages) + "\n"


def _match_id(stdout: str, call_id: int) -> dict:
    found: dict | None = None
    for line in stdout.splitlines():
        text = line.strip()
        if not text:
            continue
        try:
            message = json.loads(text)
        except json.JSONDecodeError:
            continue
        if not isinstance(message, dict):
            continue
        if message.get("id") == call_id or str(message.get("id")) == str(call_id):
            found = message
    if found is None:
        raise JevError("jev response missing tools/call result")
    return found


def _parse_tool_text(message: dict) -> dict:
    if "error" in message:
        raise JevError("jev server returned an error")
    result = message.get("result")
    if not isinstance(result, dict):
        raise JevError("jev response missing result")
    content = result.get("content")
    if not isinstance(content, list) or not content or not isinstance(content[0], dict):
        raise JevError("jev response missing content")
    text = content[0].get("text")
    if not isinstance(text, str):
        raise JevError("jev response missing text")
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise JevError("jev response text is not json") from exc
    if not isinstance(parsed, dict):
        raise JevError("jev response text is not an object")
    return parsed


@dataclass
class RowTemplate:
    ticket_id: str
    leg: str
    player: str
    question: str
    primitive: str
    evidence_ref: str
    contradicted_action: str = "review"
    unsupported_action: str = "review"


@dataclass
class CallRow:
    claim_index: int
    template: RowTemplate


@dataclass
class VerifyBatch:
    claims: list[str]
    evidence: str
    rows: list[CallRow]


@dataclass
class FindBatch:
    query: str
    template: RowTemplate


@dataclass
class ReadyBatch:
    rows: list[dict[str, str]]


Batch = VerifyBatch | FindBatch | ReadyBatch


def _public(
    template: RowTemplate, *, result: str, confidence: str, action: str
) -> dict[str, str]:
    return {
        "ticket_id": template.ticket_id,
        "leg": template.leg,
        "player": template.player,
        "question": template.question,
        "primitive": template.primitive,
        "result": result,
        "confidence": confidence,
        "action": action,
        "evidence_ref": template.evidence_ref,
    }


def _block(template: RowTemplate) -> dict[str, str]:
    return _public(template, result="error", confidence="", action="block")


def mark_noul(
    verdict: str,
    confidence: float,
    contradicted_action: str,
    unsupported_action: str = "review",
) -> str:
    """Map one Noul verdict onto a row action.

    ``contradicted`` and ``verified`` need the ``auto_accept`` floor. Below it
    the row routes to the operator as ``review``. ``unsupported`` means the
    evidence says nothing, so it takes ``unsupported_action`` with no floor: for
    a thesis that is the finding itself, not a probability about one. A thesis
    asserted with no supporting evidence is the Week 5 failure.
    """

    if verdict not in {"verified", "contradicted", "unsupported"}:
        raise JevError(f"unknown verdict: {verdict}")
    high = float(confidence) >= AUTO_ACCEPT
    if verdict == "contradicted":
        return contradicted_action if high else "review"
    if verdict == "verified":
        return "pass" if high else "review"
    return unsupported_action


def mark_choice(exists: float, probability: float) -> str:
    if float(exists) < EXISTS_FLOOR or float(probability) < AUTO_ACCEPT:
        return "review"
    return "pass"


def _ordered_results(payload: dict, count: int) -> list[dict]:
    results = payload.get("results")
    if not isinstance(results, list):
        raise JevError("jev_verify missing results")
    by_id: dict[str, dict] = {}
    for item in results:
        if not isinstance(item, dict) or "id" not in item:
            raise JevError("jev_verify result missing id")
        by_id[str(item["id"])] = item
    if len(by_id) != count:
        raise JevError("jev_verify result count does not match claims")
    ordered: list[dict] = []
    for index in range(count):
        item = by_id.get(f"claim{index}")
        if item is None:
            raise JevError(f"jev_verify missing claim{index}")
        verdict = item.get("verdict")
        confidence = item.get("confidence")
        if not isinstance(verdict, str) or not isinstance(confidence, (int, float)):
            raise JevError("jev_verify result missing verdict or confidence")
        ordered.append(item)
    return ordered


def _apply_verify(payload: dict, batch: VerifyBatch) -> list[dict[str, str]]:
    ordered = _ordered_results(payload, len(batch.claims))
    rows: list[dict[str, str]] = []
    for call_row in batch.rows:
        item = ordered[call_row.claim_index]
        verdict = str(item["verdict"])
        confidence = float(item["confidence"])
        action = mark_noul(
            verdict,
            confidence,
            call_row.template.contradicted_action,
            call_row.template.unsupported_action,
        )
        rows.append(
            _public(
                call_row.template,
                result=verdict,
                confidence=_fmt_confidence(confidence),
                action=action,
            )
        )
    return rows


def _apply_find(payload: dict, template: RowTemplate) -> dict[str, str]:
    exists = payload.get("exists")
    top = payload.get("top")
    if not isinstance(exists, (int, float)) or not isinstance(top, list) or not top:
        raise JevError("jev_find result is malformed")
    best = top[0]
    if not isinstance(best, dict):
        raise JevError("jev_find result is malformed")
    top_id = best.get("id")
    probability = best.get("probability")
    if not isinstance(top_id, str) or not isinstance(probability, (int, float)):
        raise JevError("jev_find result is malformed")
    action = mark_choice(float(exists), float(probability))
    return _public(
        template,
        result=top_id,
        confidence=_fmt_confidence(float(probability)),
        action=action,
    )


def load_card(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path} is not a JSON card") from exc
    if not isinstance(data, dict):
        raise ValueError(f"{path} is not a card object")
    tickets = data.get("tickets", [])
    if not isinstance(tickets, list):
        raise ValueError(f"{path} tickets is not a list")
    return data


def _iter_legs(card: dict) -> list[tuple[str, int, dict]]:
    found: list[tuple[str, int, dict]] = []
    for ticket in card.get("tickets") or []:
        if not isinstance(ticket, dict):
            raise ValueError("card ticket is not an object")
        ticket_id = str(ticket.get("ticket_id") or "")
        legs = ticket.get("legs") or []
        if not isinstance(legs, list):
            raise ValueError(f"{ticket_id} legs is not a list")
        for index, leg in enumerate(legs, start=1):
            if not isinstance(leg, dict):
                raise ValueError(f"{ticket_id} leg {index} is not an object")
            for key in ("player_name", "team", "stat_type", "side", "line"):
                if leg.get(key) in (None, ""):
                    raise ValueError(f"{ticket_id} leg {index} missing {key}")
            found.append((ticket_id, index, leg))
    return found


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def environment_has_rows(path: Path | None) -> bool:
    if path is None or not path.is_file():
        return False
    try:
        text = _read_text(path)
    except OSError:
        return False
    lines = [line for line in text.splitlines() if line.strip()]
    return len(lines) >= 2


def environment_teams(path: Path | None) -> set[str]:
    """Every team code named in the environment file's team / opp columns."""

    if path is None or not path.is_file():
        return set()
    try:
        text = _read_text(path)
    except OSError:
        return set()
    reader = csv.DictReader(StringIO(text))
    teams: set[str] = set()
    for raw in reader:
        for column in ("team", "opp", "opponent"):
            value = (raw.get(column) or "").strip().upper()
            if value:
                teams.add(value)
    return teams


def _ready(
    template: RowTemplate, *, result: str, action: str
) -> dict[str, str]:
    return _public(template, result=result, confidence="", action=action)


def _build_batches(
    card: dict,
    *,
    lines_text: str,
    environment_path: Path | None,
    late_active_path: Path | None,
    promo_terms: str,
) -> list[Batch]:
    platform = str(card.get("platform") or "").strip()
    legs = _iter_legs(card)
    batches: list[Batch] = []

    validity_rows: list[CallRow] = []
    validity_claims: list[str] = []
    for ticket_id, index, leg in legs:
        claim = leg_validity_claim(
            player=str(leg["player_name"]).strip(),
            stat_type=str(leg["stat_type"]).strip(),
            side=str(leg["side"]).strip(),
            line=leg["line"],
            platform=platform,
        )
        validity_claims.append(claim)
        validity_rows.append(
            CallRow(
                claim_index=len(validity_claims) - 1,
                template=RowTemplate(
                    ticket_id=ticket_id,
                    leg=str(index),
                    player=str(leg["player_name"]).strip(),
                    question=claim,
                    primitive="noul",
                    evidence_ref="lines.csv",
                    contradicted_action="do_not_type",
                ),
            )
        )
    if validity_claims:
        batches.append(
            VerifyBatch(claims=validity_claims, evidence=lines_text, rows=validity_rows)
        )

    late_text = None
    if late_active_path is not None and late_active_path.is_file():
        late_text = _read_text(late_active_path)
    if late_text is None:
        ready_rows = [
            _ready(
                RowTemplate(
                    ticket_id=ticket_id,
                    leg=str(index),
                    player=str(leg["player_name"]).strip(),
                    question=status_claim(str(leg["player_name"]).strip()),
                    primitive="noul",
                    evidence_ref="NO_EVIDENCE",
                ),
                result="no_source",
                action="review",
            )
            for ticket_id, index, leg in legs
        ]
        if ready_rows:
            batches.append(ReadyBatch(rows=ready_rows))
    else:
        distinct: list[str] = []
        for _ticket_id, _index, leg in legs:
            name = str(leg["player_name"]).strip()
            if name not in distinct:
                distinct.append(name)
        claims = [status_claim(name) for name in distinct]
        index_by_player = {name: index for index, name in enumerate(distinct)}
        rows = [
            CallRow(
                claim_index=index_by_player[str(leg["player_name"]).strip()],
                template=RowTemplate(
                    ticket_id=ticket_id,
                    leg=str(index),
                    player=str(leg["player_name"]).strip(),
                    question=status_claim(str(leg["player_name"]).strip()),
                    primitive="noul",
                    evidence_ref="late_active.csv",
                    contradicted_action="do_not_type",
                ),
            )
            for ticket_id, index, leg in legs
        ]
        batches.append(VerifyBatch(claims=claims, evidence=late_text, rows=rows))

    pass_legs = [
        (ticket_id, index, leg)
        for ticket_id, index, leg in legs
        if str(leg["stat_type"]).strip() == "pass_yds"
    ]
    if pass_legs:
        teams = environment_teams(environment_path)
        have_env = environment_has_rows(environment_path)
        # A leg whose team is absent from environment.csv (or with no env file at
        # all) cannot be checked against a game total: block it (A-06).
        unmodeled = [
            (ticket_id, index, leg)
            for ticket_id, index, leg in pass_legs
            if not have_env or str(leg["team"]).strip().upper() not in teams
        ]
        passive = [item for item in pass_legs if item not in unmodeled]
        if unmodeled:
            batches.append(
                ReadyBatch(
                    rows=[
                        _ready(
                            RowTemplate(
                                ticket_id=ticket_id,
                                leg=str(index),
                                player=str(leg["player_name"]).strip(),
                                question=thesis_claim(
                                    str(leg["team"]).strip(), str(leg["side"]).strip()
                                ),
                                primitive="noul",
                                evidence_ref=("environment.csv" if have_env else "NO_EVIDENCE"),
                                contradicted_action="thesis_unsupported",
                            ),
                            result=("no_environment_row" if have_env else "NO_EVIDENCE"),
                            action="block",
                        )
                        for ticket_id, index, leg in unmodeled
                    ]
                )
            )
        if passive:
            assert environment_path is not None
            env_text = _read_text(environment_path)
            claims = [
                thesis_claim(str(leg["team"]).strip(), str(leg["side"]).strip())
                for _ticket_id, _index, leg in passive
            ]
            rows = [
                CallRow(
                    claim_index=claim_index,
                    template=RowTemplate(
                        ticket_id=ticket_id,
                        leg=str(index),
                        player=str(leg["player_name"]).strip(),
                        question=claims[claim_index],
                        primitive="noul",
                        evidence_ref="environment.csv",
                        contradicted_action="thesis_unsupported",
                        unsupported_action="thesis_unsupported",
                    ),
                )
                for claim_index, (ticket_id, index, leg) in enumerate(passive)
            ]
            batches.append(
                VerifyBatch(
                    claims=claims,
                    evidence=thesis_evidence(env_text, lines_text),
                    rows=rows,
                )
            )

    terms = (promo_terms or "").strip()
    promo_question = promo_claim(terms)
    if not terms:
        batches.append(
            ReadyBatch(
                rows=[
                    _ready(
                        RowTemplate(
                            ticket_id="",
                            leg="",
                            player="",
                            question=promo_question,
                            primitive="noul",
                            evidence_ref="NO_EVIDENCE",
                        ),
                        result="no_source",
                        action="review",
                    )
                ]
            )
        )
    else:
        batches.append(
            VerifyBatch(
                claims=[promo_question],
                evidence=terms,
                rows=[
                    CallRow(
                        claim_index=0,
                        template=RowTemplate(
                            ticket_id="",
                            leg="",
                            player="",
                            question=promo_question,
                            primitive="noul",
                            evidence_ref="promo_terms",
                            contradicted_action="review",
                        ),
                    )
                ],
            )
        )

    for ticket in card.get("tickets") or []:
        ticket_legs = ticket.get("legs") or []
        if not ticket_legs:
            continue
        query = choice_query(ticket_legs)
        batches.append(
            FindBatch(
                query=query,
                template=RowTemplate(
                    ticket_id=str(ticket.get("ticket_id") or ""),
                    leg="",
                    player="",
                    question=query,
                    primitive="choice",
                    evidence_ref="card.json",
                ),
            )
        )
    return batches


def _block_batch(batch: Batch) -> list[dict[str, str]]:
    if isinstance(batch, ReadyBatch):
        return list(batch.rows)
    if isinstance(batch, VerifyBatch):
        return [_block(row.template) for row in batch.rows]
    return [_block(batch.template)]


def _run_batch(client: JevClient, batch: Batch) -> list[dict[str, str]]:
    if isinstance(batch, ReadyBatch):
        return list(batch.rows)
    if isinstance(batch, VerifyBatch):
        payload = client.verify(batch.claims, batch.evidence, AUTO_ACCEPT)
        return _apply_verify(payload, batch)
    payload = client.find(batch.query, ticket_type_candidates(), top_k=3)
    return [_apply_find(payload, batch.template)]


def evaluate_gate(
    card: dict,
    *,
    lines_text: str,
    environment_path: Path | None = None,
    late_active_path: Path | None = None,
    promo_terms: str = "",
    fixture_path: Path | None = None,
    record_path: Path | None = None,
) -> list[dict[str, str]]:
    """Mark every gate row. A Jev failure blocks pending rows and stops later calls."""

    batches = _build_batches(
        card,
        lines_text=lines_text,
        environment_path=environment_path,
        late_active_path=late_active_path,
        promo_terms=promo_terms,
    )
    rows: list[dict[str, str]] = []
    client: JevClient | None = None
    failed = False
    for batch in batches:
        if isinstance(batch, ReadyBatch):
            rows.extend(batch.rows)
            continue
        if failed:
            rows.extend(_block_batch(batch))
            continue
        try:
            if client is None:
                client = resolve_client(fixture_path, record_path)
            rows.extend(_run_batch(client, batch))
        except JevError:
            failed = True
            rows.extend(_block_batch(batch))
    return rows


def write_jev_gate_report(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=REPORT_COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in REPORT_COLUMNS})


def verdict_line(rows: list[dict[str, str]]) -> str:
    counts = {name: 0 for name in ACTIONS}
    for row in rows:
        action = row.get("action", "")
        if action in counts:
            counts[action] += 1
    parts = [f"{counts[name]} {name}" for name in ACTIONS]
    return "Jev gate: " + ", ".join(parts)


def append_card_verdict(path: Path, line: str) -> bool:
    """Keep exactly one gate verdict on the card.

    A re-run replaces the old verdict line instead of stacking a second copy.
    The line is stake-free: counts only. Returns ``False`` and writes nothing
    when the card does not exist, so an absent card is never created holding
    only a verdict (A-06).
    """

    if not path.is_file():
        return False
    kept = [
        text
        for text in path.read_text(encoding="utf-8").splitlines()
        if not text.startswith("Jev gate:")
    ]
    body = "\n".join(kept)
    if body and not body.endswith("\n"):
        body += "\n"
    path.write_text(body + line + "\n", encoding="utf-8")
    return True


def format_mark(row: dict[str, str]) -> str:
    loc = (
        f"ticket={row['ticket_id']} leg={row['leg']} player={row['player']} "
        f"result={row['result']} confidence={row['confidence']}"
    )
    if row["action"] == "review":
        return f"JEV-REVIEW {loc}"
    return f"JEV {row['action']} {loc}"


#: Actions that fail the gate closed. ``review`` is advisory and never fails.
FAILING_ACTIONS = ("block", "do_not_type", "thesis_unsupported")


def gate_exit_code(rows: list[dict[str, str]], *, allow_flagged: bool = False) -> int:
    """Non-zero when any row is a block, a do-not-type, or an unsupported thesis.

    ``--allow-flagged`` downgrades a contradiction to an advisory pass so the
    operator can override on purpose (A-06).
    """

    if allow_flagged:
        return 2 if any(row.get("action") == "block" for row in rows) else 0
    if any(row.get("action") in FAILING_ACTIONS for row in rows):
        return 2
    return 0
