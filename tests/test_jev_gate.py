"""Jev gate. Fixture replay only. No key and no network."""

from __future__ import annotations

import csv
import json
import stat
from pathlib import Path

import pytest

from ceminiparlays.cli import main
from ceminiparlays.jev_gate import (
    find_arguments,
    leg_validity_claim,
    mark_choice,
    mark_noul,
    promo_claim,
    status_claim,
    thesis_claim,
    thesis_evidence,
    ticket_type_candidates,
    verify_arguments,
    FixtureJevClient,
    JevError,
    McpJevClient,
    choice_query,
)

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "jev_gate_fixture.json"
WEEK5_CARD = Path(__file__).resolve().parent / "fixtures" / "jev_gate_week5_card.json"
WEEK5_LINES = Path(__file__).resolve().parent / "fixtures" / "jev_gate_week5_lines.csv"
WEEK5_ENV = Path(__file__).resolve().parents[1] / "examples" / "environment.csv"
ENV = (
    "slate_id,game_id,team,opp,implied_total,spread,roof,weather_exposed,wind_mph,precip_pop\n"
    "demo,SEA@NYG,NYG,SEA,17.5,3.5,open,true,12,20\n"
)
LATE = "player_name,status\nAda Lovelace,ACTIVE\nGrace Hopper,ACTIVE\n"
PROMO_OK = "Up to $10 back as a Bonus Bet if your 2+ leg NFL bets lose"
PROMO_NO = "Site credit for a single moneyline only"
COLUMNS = [
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


def _lines(line_ada: float, line_grace: float) -> str:
    return (
        "slate_id,platform,player_name,player_key,team,opp,stat_type,line,side,"
        "book_over,book_under\n"
        f"demo,hardrock,Ada Lovelace,ada_lovelace,NYG,SEA,pass_yds,{line_ada},less,-115,-115\n"
        f"demo,hardrock,Grace Hopper,grace_hopper,NYJ,MIA,rush_yds,{line_grace},more,-115,-115\n"
    )


def _card(line_ada: float, line_grace: float) -> dict:
    return {
        "platform": "hardrock",
        "tickets": [
            {
                "ticket_id": "compose-001",
                "legs": [
                    {
                        "player_name": "Ada Lovelace",
                        "team": "NYG",
                        "stat_type": "pass_yds",
                        "side": "less",
                        "line": line_ada,
                    },
                    {
                        "player_name": "Grace Hopper",
                        "team": "NYJ",
                        "stat_type": "rush_yds",
                        "side": "more",
                        "line": line_grace,
                    },
                ],
            }
        ],
    }


def _loaded_card(line_ada: float, line_grace: float) -> dict:
    return json.loads(json.dumps(_card(line_ada, line_grace)))


def _verify_exchange(claims: list[str], evidence: str, verdicts: list[tuple[str, float]]) -> dict:
    results = []
    for index, (claim, (verdict, confidence)) in enumerate(zip(claims, verdicts, strict=True)):
        results.append(
            {
                "id": f"claim{index}",
                "claim": claim,
                "verdict": verdict,
                "confidence": confidence,
                "action": "auto" if confidence >= 0.80 else "review",
            }
        )
    return {
        "tool": "jev_verify",
        "arguments": verify_arguments(claims, evidence),
        "result": {"tool": "jev_verify", "model": "jev-latest", "results": results},
    }


def _find_exchange(query: str, top_id: str, probability: float, exists: float) -> dict:
    return {
        "tool": "jev_find",
        "arguments": find_arguments(query, ticket_type_candidates(), 3),
        "result": {
            "tool": "jev_find",
            "model": "jev-latest",
            "query": query,
            "exists": exists,
            "exists_verdict": "partial",
            "top": [{"id": top_id, "probability": probability, "text": top_id}],
        },
    }


def _scenario_exchanges(
    line_ada: float,
    line_grace: float,
    *,
    promo: str,
    leg_verdicts: list[tuple[str, float]],
    thesis_verdict: tuple[str, float],
    promo_verdict: tuple[str, float],
    choice: tuple[str, float, float],
) -> list[dict]:
    card = _loaded_card(line_ada, line_grace)
    lines = _lines(line_ada, line_grace)
    legs = card["tickets"][0]["legs"]
    leg_claims = [
        leg_validity_claim(
            player=leg["player_name"],
            stat_type=leg["stat_type"],
            side=leg["side"],
            line=leg["line"],
            platform=card["platform"],
        )
        for leg in legs
    ]
    thesis_claims = [thesis_claim(leg["team"]) for leg in legs if leg["stat_type"] == "pass_yds"]
    top_id, probability, exists = choice
    return [
        _verify_exchange(leg_claims, lines, leg_verdicts),
        _verify_exchange(thesis_claims, thesis_evidence(ENV, lines), [thesis_verdict]),
        _verify_exchange([promo_claim(promo)], promo, [promo_verdict]),
        _find_exchange(choice_query(legs), top_id, probability, exists),
    ]


def build_fixture_document() -> dict:
    status = _verify_exchange(
        [status_claim("Ada Lovelace"), status_claim("Grace Hopper")],
        LATE,
        [("verified", 0.96), ("verified", 0.96)],
    )
    high = _scenario_exchanges(
        200.5,
        71.5,
        promo=PROMO_OK,
        leg_verdicts=[("contradicted", 0.95), ("verified", 0.95)],
        thesis_verdict=("verified", 0.95),
        promo_verdict=("verified", 0.95),
        choice=("straight_bet", 0.91, 0.90),
    )
    low = _scenario_exchanges(
        199.5,
        70.5,
        promo=PROMO_OK,
        leg_verdicts=[("contradicted", 0.42), ("verified", 0.95)],
        thesis_verdict=("verified", 0.95),
        promo_verdict=("verified", 0.95),
        choice=("straight_bet", 0.63, 0.40),
    )
    thesis = _scenario_exchanges(
        180.5,
        60.5,
        promo=PROMO_NO,
        leg_verdicts=[("verified", 0.95), ("verified", 0.95)],
        thesis_verdict=("contradicted", 0.93),
        promo_verdict=("contradicted", 0.88),
        choice=("straight_bet", 0.60, 0.70),
    )
    return {"exchanges": [status, *high, *low, *thesis]}


def _run(
    tmp_path: Path,
    line_ada: float,
    line_grace: float,
    *,
    promo: str,
    environment: bool = True,
    late: bool = True,
    fixture: Path | None = FIXTURE,
    player_override: str | None = None,
) -> tuple[int, list[dict[str, str]], str]:
    card = _card(line_ada, line_grace)
    if player_override:
        card["tickets"][0]["legs"][0]["player_name"] = player_override
    card_path = tmp_path / "card.json"
    lines_path = tmp_path / "lines.csv"
    card_path.write_text(json.dumps(card), encoding="utf-8")
    lines_path.write_text(_lines(line_ada, line_grace), encoding="utf-8")
    (tmp_path / "card.md").write_text("# CeminiParlays card\n\ndo not submit\n", encoding="utf-8")
    args = [
        "jev-gate",
        "--card",
        str(card_path),
        "--lines",
        str(lines_path),
        "--promo-terms",
        promo,
        "--out-dir",
        str(tmp_path / "out"),
    ]
    if environment:
        env_path = tmp_path / "environment.csv"
        env_path.write_text(ENV, encoding="utf-8")
        args.extend(["--environment", str(env_path)])
    if late:
        late_path = tmp_path / "late.csv"
        late_path.write_text(LATE, encoding="utf-8")
        args.extend(["--late-active", str(late_path)])
    if fixture is not None:
        args.extend(["--fixture", str(fixture)])
    code = main(args)
    report_path = tmp_path / "out" / "jev_gate_report.csv"
    with report_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        assert reader.fieldnames == COLUMNS
        rows = list(reader)
    card_md = (tmp_path / "card.md").read_text(encoding="utf-8")
    return code, rows, card_md


def _row(rows: list[dict[str, str]], predicate) -> dict[str, str]:
    matches = [row for row in rows if predicate(row)]
    assert len(matches) == 1, matches
    return matches[0]


def test_mark_noul_and_choice_routing() -> None:
    assert mark_noul("contradicted", 0.95, "do_not_type") == "do_not_type"
    assert mark_noul("contradicted", 0.80, "do_not_type") == "do_not_type"
    assert mark_noul("contradicted", 0.79, "do_not_type") == "review"
    assert mark_noul("verified", 0.79, "do_not_type") == "review"
    assert mark_noul("verified", 0.80, "do_not_type") == "pass"
    assert mark_noul("unsupported", 0.99, "do_not_type") == "review"
    assert mark_noul("contradicted", 0.93, "thesis_unsupported") == "thesis_unsupported"
    assert mark_noul("contradicted", 0.93, "review") == "review"
    assert mark_choice(0.49, 0.99) == "review"
    assert mark_choice(0.80, 0.70) == "review"
    assert mark_choice(0.80, 0.80) == "pass"


def test_fixture_miss_raises() -> None:
    client = FixtureJevClient(FIXTURE)
    with pytest.raises(JevError, match="no fixture exchange"):
        client.verify(["this claim is not in the fixture"], "no evidence", 0.80)


def test_high_confidence_contradiction_is_do_not_type(tmp_path: Path, capsys) -> None:
    code, rows, card_md = _run(tmp_path, 200.5, 71.5, promo=PROMO_OK)
    capsys.readouterr()
    assert code == 0
    ada = _row(rows, lambda row: row["player"] == "Ada Lovelace" and row["question"].startswith("The lines"))
    grace = _row(rows, lambda row: row["player"] == "Grace Hopper" and row["question"].startswith("The lines"))
    assert ada["action"] == "do_not_type"
    assert ada["result"] == "contradicted"
    assert ada["evidence_ref"] == "lines.csv"
    assert ada["primitive"] == "noul"
    assert ada["leg"] == "1"
    assert grace["action"] == "pass"
    assert grace["leg"] == "2"
    choice = _row(rows, lambda row: row["primitive"] == "choice")
    assert choice["action"] == "pass"
    assert choice["result"] == "straight_bet"
    assert choice["evidence_ref"] == "card.json"
    assert choice["leg"] == ""
    line = [item for item in card_md.splitlines() if item.startswith("Jev gate:")][-1]
    assert "do not submit" in card_md
    assert "$" not in line
    assert "stake" not in line.lower()
    assert "1 do_not_type" in line


def test_low_confidence_contradiction_is_review(tmp_path: Path, capsys) -> None:
    code, rows, _card_md = _run(tmp_path, 199.5, 70.5, promo=PROMO_OK)
    stdout = capsys.readouterr().out
    assert code == 0
    ada = _row(rows, lambda row: row["player"] == "Ada Lovelace" and row["question"].startswith("The lines"))
    assert ada["action"] == "review"
    assert ada["result"] == "contradicted"
    assert "JEV-REVIEW" in stdout
    choice = _row(rows, lambda row: row["primitive"] == "choice")
    assert choice["action"] == "review"
    assert choice["result"] == "straight_bet"


def test_thesis_contradiction_is_thesis_unsupported(tmp_path: Path, capsys) -> None:
    code, rows, _card_md = _run(tmp_path, 180.5, 60.5, promo=PROMO_NO)
    stdout = capsys.readouterr().out
    assert code == 0
    thesis = _row(rows, lambda row: "low passing volume" in row["question"])
    assert thesis["action"] == "thesis_unsupported"
    assert thesis["result"] == "contradicted"
    assert thesis["evidence_ref"] == "environment.csv"
    assert "JEV thesis_unsupported" in stdout
    promo = _row(rows, lambda row: row["question"].startswith("Player props qualify"))
    assert promo["action"] == "review"
    assert promo["result"] == "contradicted"
    assert promo["evidence_ref"] == "promo_terms"
    assert promo["leg"] == ""
    assert PROMO_NO in promo["question"]


def test_missing_environment_blocks_and_exits_2(tmp_path: Path, capsys) -> None:
    code, rows, card_md = _run(tmp_path, 200.5, 71.5, promo=PROMO_OK, environment=False)
    capsys.readouterr()
    assert code == 2
    thesis = _row(rows, lambda row: "low passing volume" in row["question"])
    assert thesis["result"] == "NO_EVIDENCE"
    assert thesis["action"] == "block"
    assert thesis["evidence_ref"] == "NO_EVIDENCE"
    assert "block" in card_md
    ada = _row(rows, lambda row: row["player"] == "Ada Lovelace" and row["question"].startswith("The lines"))
    assert ada["action"] == "do_not_type"


def test_fixture_miss_blocks_and_exits_2(tmp_path: Path, capsys) -> None:
    code, rows, _card_md = _run(
        tmp_path,
        200.5,
        71.5,
        promo=PROMO_OK,
        late=False,
        player_override="Missing Key",
    )
    capsys.readouterr()
    assert code == 2
    blocked = [row for row in rows if row["action"] == "block"]
    assert blocked
    assert all(row["result"] == "error" for row in blocked)
    status_rows = [row for row in rows if row["question"].endswith("active for this game.")]
    assert status_rows
    assert {row["result"] for row in status_rows} == {"no_source"}
    assert {row["action"] for row in status_rows} == {"review"}
    assert {row["evidence_ref"] for row in status_rows} == {"NO_EVIDENCE"}


def test_missing_binary_blocks_and_exits_2(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("JEV_MCP_BIN", str(tmp_path / "missing-mcp-jev"))
    code, rows, _card_md = _run(tmp_path, 200.5, 71.5, promo=PROMO_OK, fixture=None)
    capsys.readouterr()
    assert code == 2
    assert any(row["action"] == "block" and row["result"] == "error" for row in rows)


def test_blank_promo_and_missing_late_active_do_not_call(tmp_path: Path, capsys) -> None:
    code, rows, _card_md = _run(tmp_path, 200.5, 71.5, promo="  ", late=False)
    capsys.readouterr()
    assert code == 0
    promo = _row(rows, lambda row: row["question"].startswith("Player props qualify"))
    assert promo["result"] == "no_source"
    assert promo["action"] == "review"
    assert promo["evidence_ref"] == "NO_EVIDENCE"
    status_rows = [row for row in rows if row["question"].endswith("active for this game.")]
    assert len(status_rows) == 2
    assert {row["result"] for row in status_rows} == {"no_source"}
    assert {row["action"] for row in status_rows} == {"review"}


def test_help_says_the_gate_does_not_reprice(capsys) -> None:
    with pytest.raises(SystemExit) as caught:
        main(["jev-gate", "--help"])
    assert caught.value.code == 0
    text = capsys.readouterr().out
    assert "does not reprice" in text


def test_mcp_client_parses_records_and_rejects_a_bad_response(tmp_path: Path, monkeypatch) -> None:
    inner = {"tool": "jev_verify", "results": [{"id": "claim0", "verdict": "verified", "confidence": 0.91}]}
    message = {
        "jsonrpc": "2.0",
        "id": 2,
        "result": {"content": [{"type": "text", "text": json.dumps(inner)}]},
    }
    script = tmp_path / "jev"
    script.write_text(
        "#!/usr/bin/env python3\n"
        "import json, sys\n"
        "sys.stdin.read()\n"
        f"init = {json.dumps({'jsonrpc': '2.0', 'id': 1, 'result': {}})!r}\n"
        f"call = {message!r}\n"
        "sys.stdout.write(json.dumps(init) + '\\n')\n"
        "sys.stdout.write(json.dumps(call) + '\\n')\n",
        encoding="utf-8",
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("JEV_MCP_BIN", str(script))
    recorded = tmp_path / "recorded.json"
    client = McpJevClient(record_path=recorded)
    result = client.verify(["one claim"], "evidence text", 0.80)
    assert result["results"][0]["verdict"] == "verified"
    replay = FixtureJevClient(recorded)
    assert replay.verify(["one claim"], "evidence text", 0.80) == result

    bad = tmp_path / "bad-jev"
    bad.write_text(
        "#!/usr/bin/env python3\n"
        "import json, sys\n"
        "sys.stdin.read()\n"
        "sys.stdout.write(json.dumps({'jsonrpc': '2.0', 'id': 2, 'result': "
        "{'content': [{'type': 'text', 'text': 'not-json'}]}}) + '\\n')\n",
        encoding="utf-8",
    )
    bad.chmod(bad.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("JEV_MCP_BIN", str(bad))
    with pytest.raises(JevError, match="not json"):
        McpJevClient().verify(["one claim"], "evidence text", 0.80)


def test_launcher_exit_1_is_a_jev_error(tmp_path: Path, monkeypatch) -> None:
    script = tmp_path / "exit-jev"
    script.write_text("#!/bin/sh\necho 'mcp-jev: key absent' >&2\nexit 1\n", encoding="utf-8")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("JEV_MCP_BIN", str(script))
    with pytest.raises(JevError, match="exited 1"):
        McpJevClient().verify(["one claim"], "evidence text", 0.80)


def test_unsupported_thesis_has_no_confidence_floor() -> None:
    # An unsupported thesis is the finding itself: the evidence says nothing.
    # The confidence floor still routes every other gate, and it still routes a
    # contradicted thesis below the floor.
    assert (
        mark_noul("unsupported", 0.56, "thesis_unsupported", "thesis_unsupported")
        == "thesis_unsupported"
    )
    assert mark_noul("unsupported", 0.99, "do_not_type") == "review"
    assert mark_noul("contradicted", 0.56, "thesis_unsupported", "thesis_unsupported") == "review"


def test_week5_winston_thesis_is_marked(tmp_path: Path, capsys) -> None:
    """The Week 5 card replayed offline. The Winston under is the thesis failure.

    The recorded exchanges are the real ones from the live server, so this test
    needs no key and no network. The card is copied into tmp_path because the
    gate appends its verdict to card.md next to the card.
    """

    card = tmp_path / "card.json"
    card.write_bytes(WEEK5_CARD.read_bytes())
    out_dir = tmp_path / "jev"
    code = main(
        [
            "jev-gate",
            "--card",
            str(card),
            "--lines",
            str(WEEK5_LINES),
            "--environment",
            str(WEEK5_ENV),
            "--promo-terms",
            PROMO_OK,
            "--out-dir",
            str(out_dir),
            "--fixture",
            str(FIXTURE),
        ]
    )
    capsys.readouterr()
    assert code == 0
    rows = list(
        csv.DictReader((out_dir / "jev_gate_report.csv").open(encoding="utf-8"))
    )
    assert [row["action"] for row in rows].count("block") == 0
    thesis = _row(rows, lambda row: "low passing volume" in row["question"])
    assert thesis["player"] == "Jameis Winston"
    assert thesis["result"] == "unsupported"
    assert thesis["action"] == "thesis_unsupported"
    assert thesis["evidence_ref"] == "environment.csv"
    validity = _row(
        rows,
        lambda row: row["player"] == "Jameis Winston" and row["question"].startswith("The lines"),
    )
    assert validity["action"] == "pass"
    assert validity["result"] == "verified"


if __name__ == "__main__":
    FIXTURE.write_text(json.dumps(build_fixture_document(), indent=2) + "\n", encoding="utf-8")
