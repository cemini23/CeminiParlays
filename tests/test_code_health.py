from __future__ import annotations

import json
from pathlib import Path

import pytest

from code_health import REPO_ROOT, SRC_DIR
from code_health.loop import guard_check
from code_health.queue import Finding, Queue, severity
from code_health.review import FORBIDDEN_KEYS, build_packet, blind_score
from code_health.scan import (
    check_complexity,
    check_dead_code,
    check_duplication,
    check_test_gaps,
    collect_occurrences,
    load_modules,
    load_test_modules,
)
from code_health.scope import EVALUATION, FREE, PROTECTED, tier


def _tree(root: Path, path: str, text: str) -> Path:
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    return target


def _modules(root: Path):
    src = root / "src" / "ceminiparlays"
    return load_modules(root, src), load_test_modules(root, root / "tests")


def test_protected_module_is_never_scannable() -> None:
    assert tier("slip_screen.py") == PROTECTED
    assert tier("cli.py") == PROTECTED
    assert tier("jev_gate.py") == PROTECTED


def test_no_finding_targets_a_protected_module() -> None:
    from code_health.scan import scan

    findings = scan(REPO_ROOT)
    offenders = [f.path for f in findings if tier(Path(f.path).name) == PROTECTED]
    assert offenders == []


def test_evaluation_module_is_guarded_and_free_module_is_not() -> None:
    from code_health.scope import finding_guard

    assert tier("compose.py") == EVALUATION
    assert tier("diff.py") == FREE
    assert finding_guard("compose.py", "complexity") == "rebaseline"
    assert finding_guard("diff.py", "complexity") == "none"


def test_a_test_cannot_move_a_metric_so_it_is_not_guarded() -> None:
    from code_health.scope import finding_guard

    assert finding_guard("compose.py", "test_gap") == "none"
    assert finding_guard("compose.py", "unused_import") == "none"
    assert finding_guard("compose.py", "dead_code") == "rebaseline"


def test_dead_code_finds_an_unreferenced_function(tmp_path: Path) -> None:
    _tree(
        tmp_path,
        "src/ceminiparlays/sample.py",
        "def used() -> int:\n    return 1\n\n\ndef orphan() -> int:\n    return 2\n\n\ndef caller() -> int:\n    return used()\n",
    )
    modules, tests = _modules(tmp_path)
    occurrences = collect_occurrences(modules + tests)
    symbols = [f.symbol for f in check_dead_code(modules, occurrences)]
    assert "orphan" in symbols
    assert "used" not in symbols


def test_a_use_in_a_test_counts_as_a_use(tmp_path: Path) -> None:
    _tree(
        tmp_path,
        "src/ceminiparlays/sample.py",
        "def helper() -> int:\n    return 1\n",
    )
    _tree(tmp_path, "tests/test_sample.py", "from ceminiparlays.sample import helper\n\n\ndef test_x() -> None:\n    assert helper() == 1\n")
    modules, tests = _modules(tmp_path)
    occurrences = collect_occurrences(modules + tests)
    assert check_dead_code(modules, occurrences) == []


def test_a_quoted_annotation_counts_as_a_use(tmp_path: Path) -> None:
    _tree(
        tmp_path,
        "src/ceminiparlays/sample.py",
        (
            "from __future__ import annotations\n\n"
            "class Widget:\n    pass\n\n\n"
            'def build(widget: "Widget | None" = None) -> int:\n    return 0\n'
        ),
    )
    modules, tests = _modules(tmp_path)
    occurrences = collect_occurrences(modules + tests)
    symbols = [f.symbol for f in check_dead_code(modules, occurrences)]
    assert "Widget" not in symbols


def test_complexity_flags_a_branchy_function(tmp_path: Path) -> None:
    body = "".join(f"    if value == {index}:\n        return {index}\n" for index in range(15))
    _tree(
        tmp_path,
        "src/ceminiparlays/sample.py",
        f"def branchy(value: int) -> int:\n{body}    return -1\n",
    )
    modules, _ = _modules(tmp_path)
    kinds = [f.kind for f in check_complexity(modules)]
    assert "complexity" in kinds


def test_duplication_flags_two_equal_bodies(tmp_path: Path) -> None:
    body = "".join(f"    total += step_{index}\n" for index in range(12))
    text = (
        "def first(steps: list[int]) -> int:\n    total = 0\n"
        + body
        + "    return total\n\n\ndef second(steps: list[int]) -> int:\n    total = 0\n"
        + body
        + "    return total\n"
    )
    _tree(tmp_path, "src/ceminiparlays/sample.py", text)
    modules, _ = _modules(tmp_path)
    assert any(f.kind == "duplication" for f in check_duplication(modules))


def test_test_gap_flags_an_unnamed_public_function(tmp_path: Path) -> None:
    _tree(
        tmp_path,
        "src/ceminiparlays/sample.py",
        "def untested(value: int) -> int:\n    return value + 1\n",
    )
    _tree(tmp_path, "tests/test_sample.py", "def test_other() -> None:\n    assert True\n")
    modules, _ = _modules(tmp_path)
    gaps = check_test_gaps(modules, tmp_path / "tests")
    assert any(g.symbol == "untested" for g in gaps)


def test_severity_weights_mechanical_at_a_quarter() -> None:
    assert severity(100, None) == 100
    assert severity(100, 0) == 25
    assert severity(0, 100) == 75


def test_queue_keeps_status_across_a_rescan(tmp_path: Path) -> None:
    path = tmp_path / "queue.json"
    queue = Queue()
    finding = Finding(kind="dead_code", path="a.py", symbol="gone", detail="x", mechanical_score=60)
    queue.merge_scan([finding])
    queue.findings[0].status = "done"
    queue.save(path)

    reloaded = Queue.load(path)
    reloaded.merge_scan([Finding(kind="dead_code", path="a.py", symbol="gone", detail="x", mechanical_score=60)])
    assert reloaded.findings[0].status == "done"


def test_a_finding_that_disappears_is_marked_absent(tmp_path: Path) -> None:
    queue = Queue()
    finding = Finding(kind="dead_code", path="a.py", symbol="gone", detail="x", mechanical_score=60)
    queue.merge_scan([finding])
    added, updated, absent = queue.merge_scan([])
    assert (added, updated, absent) == (0, 0, 1)
    assert queue.findings[0].present is False


def test_guarded_finding_is_not_eligible_by_default() -> None:
    queue = Queue()
    queue.merge_scan(
        [Finding(kind="complexity", path="a.py", symbol="f", detail="x", mechanical_score=70, guard="rebaseline")]
    )
    assert queue.eligible() == []
    assert len(queue.eligible(allow_rebaseline=True)) == 1


def test_blind_score_is_the_mean_of_the_three_concerns() -> None:
    assert blind_score({"naming": 60, "abstraction": 30, "boundaries": 30}) == 40


def test_a_packet_carries_no_author_or_commit() -> None:
    finding = Finding(
        kind="complexity",
        path="src/ceminiparlays/diff.py",
        symbol="diff_ticket_lines",
        detail="x",
        line=70,
        mechanical_score=50,
    )
    packet = build_packet(finding)
    assert packet is not None
    keys = {key.lower() for key in packet.payload}
    assert keys & FORBIDDEN_KEYS == set()
    assert "def diff_ticket_lines" in packet.payload["code"]


def test_guard_refuses_a_protected_file() -> None:
    diff = (
        "diff --git a/src/ceminiparlays/slip_screen.py b/src/ceminiparlays/slip_screen.py\n"
        "--- a/src/ceminiparlays/slip_screen.py\n"
        "+++ b/src/ceminiparlays/slip_screen.py\n"
        "@@ -1,1 +1,2 @@\n"
        "+# touched\n"
    )
    violations = guard_check(diff)
    assert len(violations) == 1
    assert "protected" in str(violations[0])


def test_guard_refuses_a_new_network_client() -> None:
    diff = (
        "diff --git a/src/ceminiparlays/sample.py b/src/ceminiparlays/sample.py\n"
        "--- a/src/ceminiparlays/sample.py\n"
        "+++ b/src/ceminiparlays/sample.py\n"
        "@@ -1,1 +1,2 @@\n"
        "+import httpx\n"
    )
    violations = guard_check(diff)
    assert len(violations) == 1
    assert "httpx" in str(violations[0])


def test_guard_refuses_the_licensed_module_too() -> None:
    # A licensed HTTP module is still on the action boundary. This tool never
    # proposes a change there, whatever the import would be.
    diff = (
        "diff --git a/src/ceminiparlays/odds_api.py b/src/ceminiparlays/odds_api.py\n"
        "--- a/src/ceminiparlays/odds_api.py\n"
        "+++ b/src/ceminiparlays/odds_api.py\n"
        "@@ -1,1 +1,2 @@\n"
        "+import httpx\n"
    )
    violations = guard_check(diff)
    assert len(violations) == 1
    assert "protected" in str(violations[0])


def test_a_clean_diff_passes_the_guard() -> None:
    diff = (
        "diff --git a/src/ceminiparlays/diff.py b/src/ceminiparlays/diff.py\n"
        "--- a/src/ceminiparlays/diff.py\n"
        "+++ b/src/ceminiparlays/diff.py\n"
        "@@ -1,1 +1,2 @@\n"
        "+import csv\n"
    )
    assert guard_check(diff) == []


def test_record_applies_a_verdict_file(tmp_path: Path) -> None:
    from code_health.review import apply_verdicts, load_verdicts

    finding = Finding(kind="complexity", path="a.py", symbol="f", detail="x", mechanical_score=50)
    verdicts_path = tmp_path / "v.json"
    verdicts_path.write_text(
        json.dumps(
            {
                "finding_id": finding.id,
                "scores": {"naming": 80, "abstraction": 20, "boundaries": 20},
                "note": "the name hides the unit",
            }
        ),
        encoding="utf-8",
    )
    applied = apply_verdicts([finding], load_verdicts(verdicts_path))
    assert applied == 1
    assert finding.blind_score == 40
    assert finding.notes == ["blind: the name hides the unit"]


@pytest.mark.parametrize("name", ["slip_screen.py", "jev_client.py", "hardrock_book.py"])
def test_the_action_boundary_is_protected(name: str) -> None:
    assert tier(name) == PROTECTED


def test_the_scanner_reads_the_real_source_tree() -> None:
    modules = load_modules(REPO_ROOT, SRC_DIR)
    names = {info.name for info in modules}
    assert "compose.py" in names
    assert "cli.py" in names
