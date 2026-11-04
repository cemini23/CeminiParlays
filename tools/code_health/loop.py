"""Pick one item, hand out a work order, and refuse a bad change.

The loop does not rewrite code on its own. It selects, it prints the order,
and it gates the result. A person or an agent does the edit.
"""

from __future__ import annotations

import ast
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .queue import Finding, Queue
from .scope import BANNED_IMPORT_ROOTS, PROTECTED_MODULES

_FILE_HEADER = re.compile(r"^\+\+\+ b/(.+)$")


@dataclass
class Violation:
    path: str
    reason: str

    def __str__(self) -> str:
        return f"{self.path}: {self.reason}"


def added_lines(diff_text: str) -> dict[str, list[str]]:
    """Map each changed file to its added lines, from a unified diff."""

    changed: dict[str, list[str]] = {}
    current: str | None = None
    for line in diff_text.splitlines():
        header = _FILE_HEADER.match(line)
        if header:
            current = header.group(1)
            changed.setdefault(current, [])
            continue
        if current is None or line.startswith("+++"):
            continue
        if line.startswith("+") and not line.startswith("+++"):
            changed[current].append(line[1:])
    return changed


def guard_check(diff_text: str) -> list[Violation]:
    """Refuse a diff that reaches the action boundary or adds a network client."""

    violations: list[Violation] = []
    for path, lines in added_lines(diff_text).items():
        name = Path(path).name
        if path.startswith("src/") and name in PROTECTED_MODULES:
            violations.append(Violation(path, "protected: action boundary or frozen file"))
            continue
        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue
            roots = _import_roots(stripped)
            for root in roots:
                if root in BANNED_IMPORT_ROOTS:
                    violations.append(
                        Violation(path, f"adds a network client import: {root}")
                    )
    return violations


def _import_roots(line: str) -> list[str]:
    try:
        tree = ast.parse(line)
    except SyntaxError:
        return []
    roots: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.append(node.module)
    return roots


def working_diff(root: Path) -> str:
    """The diff of the worktree against HEAD. Empty when git is absent."""

    try:
        result = subprocess.run(
            ["git", "diff", "HEAD", "--"],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return result.stdout


def work_order(finding: Finding) -> str:
    """The block an operator or an agent reads before the edit."""

    guard = (
        "GUARDED: this module feeds a price, a stake, or a grade.\n"
        "A change needs a baseline rerun before the next comparison.\n"
        "Run the loop with --allow-rebaseline to pick it.\n"
        if finding.guard == "rebaseline"
        else "free: no extra gate beyond the tests.\n"
    )
    return (
        f"{finding.id}  score {finding.score}  {finding.kind}\n"
        f"{finding.path}:{finding.line}  {finding.symbol}\n"
        f"{finding.detail}\n\n"
        f"{guard}\n"
        "After the edit:\n"
        "  1. .venv/bin/ruff check src tests\n"
        "  2. .venv/bin/python -m pytest -q\n"
        "  3. PYTHONPATH=tools .venv/bin/python -m code_health guard\n"
        f"  4. PYTHONPATH=tools .venv/bin/python -m code_health mark {finding.id} done\n"
    )


def pick(queue: Queue, allow_rebaseline: bool = False) -> Finding | None:
    eligible = queue.eligible(allow_rebaseline)
    return eligible[0] if eligible else None
