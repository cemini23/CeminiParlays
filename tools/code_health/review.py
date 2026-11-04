"""The blind reviewer.

Blind means the reviewer sees the artefact and nothing else: no author, no
commit, no branch, no blame, no date. The packet builder reads the worktree
only. It never calls git.

The reviewer scores three things a mechanical check cannot see: naming,
abstraction, and module boundaries. Each subscore is a *concern* score.
0 means no concern. 100 means stop and rewrite.
"""

from __future__ import annotations

import ast
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import PACKET_DIR, REPO_ROOT
from .queue import Finding
from .scan import iter_functions

DIMENSIONS = ("naming", "abstraction", "boundaries")

#: Keys a packet must never carry. A test asserts this.
FORBIDDEN_KEYS = frozenset(
    {"author", "commit", "committer", "branch", "blame", "sha", "date", "email"}
)

INSTRUCTIONS = {
    "role": "You review one function of a Python package. You do not know who wrote it.",
    "ignore": "Do not use git history, an author, or a commit. None is given.",
    "scores": (
        "Return a concern score 0-100 for each dimension. 0 means no concern. "
        "100 means stop and rewrite."
    ),
    "dimensions": {
        "naming": "Do the names state what the values are?",
        "abstraction": "Is each step at one level? Is a detail hidden or leaked?",
        "boundaries": "Does this belong in this module, or does it reach across one?",
    },
    "reply": (
        'Return JSON: {"finding_id": "...", "scores": {"naming": 0, '
        '"abstraction": 0, "boundaries": 0}, "note": "one or two sentences"}'
    ),
}


@dataclass
class Packet:
    finding_id: str
    payload: dict[str, Any]

    def to_json(self) -> str:
        return json.dumps(self.payload, indent=2)


def _module_source(rel_path: str) -> tuple[str, ast.Module]:
    path = REPO_ROOT / rel_path
    text = path.read_text(encoding="utf-8")
    return text, ast.parse(text, filename=str(path))


def _function_span(rel_path: str, symbol: str) -> tuple[int, int] | None:
    """1-based start and end lines for a dotted symbol, or None."""

    _, tree = _module_source(rel_path)
    wanted = tuple(symbol.split("."))
    for path, node in iter_functions(tree):
        if path == wanted:
            return node.lineno, node.end_lineno or node.lineno
    return None


def _module_surface(rel_path: str) -> list[str]:
    _, tree = _module_source(rel_path)
    return [
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    ]


def build_packet(finding: Finding) -> Packet | None:
    """The smallest artefact that lets a reviewer judge this finding.

    Returns None when the target no longer exists in the worktree.
    """

    source, tree = _module_source(finding.path)
    lines = source.splitlines()
    span = _function_span(finding.path, finding.symbol)
    if span is None:
        if "." in finding.symbol:
            return None
        start = max(1, finding.line - 3)
        end = min(len(lines), finding.line + 12)
        code = "\n".join(lines[start - 1:end])
    else:
        start, end = span
        code = "\n".join(lines[start - 1:end])

    payload: dict[str, Any] = {
        "finding_id": finding.id,
        "kind": finding.kind,
        "path": finding.path,
        "symbol": finding.symbol,
        "line": start,
        "code": code,
        "module_docstring": ast.get_docstring(tree) or "",
        "module_public_names": _module_surface(finding.path),
        "mechanical_note": finding.detail,
        "instructions": INSTRUCTIONS,
    }
    return Packet(finding_id=finding.id, payload=payload)


def emit_packets(findings: list[Finding], out_dir: Path = PACKET_DIR) -> list[Path]:
    """Write one packet per finding. A missing target is skipped."""

    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for finding in findings:
        packet = build_packet(finding)
        if packet is None:
            continue
        path = out_dir / f"{finding.id}.json"
        path.write_text(packet.to_json() + "\n", encoding="utf-8")
        written.append(path)
    return written


def _mean(values: list[int]) -> int:
    return int(round(sum(values) / len(values))) if values else 0


def blind_score(scores: dict[str, Any]) -> int:
    """One number for the finding. The mean of the three concern scores."""

    values = [int(scores[name]) for name in DIMENSIONS if name in scores]
    return max(0, min(100, _mean(values)))


def load_verdicts(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        if "verdicts" in payload:
            return list(payload["verdicts"])
        return [payload]
    return list(payload)


def apply_verdicts(findings: list[Finding], verdicts: list[dict[str, Any]]) -> int:
    """Merge reviewer scores onto findings. Returns the number that matched."""

    by_id = {finding.id: finding for finding in findings}
    applied = 0
    for verdict in verdicts:
        finding = by_id.get(str(verdict.get("finding_id", "")))
        if finding is None:
            continue
        finding.blind_score = blind_score(verdict.get("scores") or {})
        note = str(verdict.get("note") or "").strip()
        if note:
            finding.notes.append(f"blind: {note}")
        applied += 1
    return applied
