"""The persisted queue.

A finding has a stable fingerprint. A re-scan updates the finding in place and
keeps its status, its notes, and its first sighting. That is what makes the
file a queue: an item you finished stays finished.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

STATUSES = ("open", "in_progress", "done", "deferred", "wontfix")
CLOSED = frozenset({"done", "wontfix"})

#: Weights for the blended severity. The split mirrors the review budget:
#: a quarter mechanical, three quarters blind review.
MECHANICAL_WEIGHT = 0.25
BLIND_WEIGHT = 0.75


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def fingerprint(kind: str, path: str, symbol: str) -> str:
    """A stable identity for a finding, independent of line numbers."""

    raw = f"{kind}|{path}|{symbol}".encode()
    return hashlib.sha1(raw).hexdigest()


def severity(mechanical: int, blind: int | None) -> int:
    """Blend the two scores. A finding with no blind score keeps the mechanical one."""

    if blind is None:
        return int(round(mechanical))
    blended = MECHANICAL_WEIGHT * mechanical + BLIND_WEIGHT * blind
    return int(round(max(0, min(100, blended))))


@dataclass
class Finding:
    kind: str
    path: str
    symbol: str
    detail: str
    line: int = 0
    mechanical_score: int = 0
    blind_score: int | None = None
    guard: str = "none"
    source: str = "mechanical"
    status: str = "open"
    present: bool = True
    first_seen: str = ""
    last_seen: str = ""
    notes: list[str] = field(default_factory=list)

    @property
    def id(self) -> str:
        return "ch-" + fingerprint(self.kind, self.path, self.symbol)[:8]

    @property
    def fingerprint(self) -> str:
        return fingerprint(self.kind, self.path, self.symbol)

    @property
    def score(self) -> int:
        return severity(self.mechanical_score, self.blind_score)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "fingerprint": self.fingerprint,
            "kind": self.kind,
            "path": self.path,
            "line": self.line,
            "symbol": self.symbol,
            "detail": self.detail,
            "source": self.source,
            "mechanical_score": self.mechanical_score,
            "blind_score": self.blind_score,
            "severity": self.score,
            "guard": self.guard,
            "status": self.status,
            "present": self.present,
            "first_seen": self.first_seen,
            "last_seen": self.last_seen,
            "notes": list(self.notes),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> Finding:
        return cls(
            kind=str(payload.get("kind", "")),
            path=str(payload.get("path", "")),
            symbol=str(payload.get("symbol", "")),
            detail=str(payload.get("detail", "")),
            line=int(payload.get("line") or 0),
            mechanical_score=int(payload.get("mechanical_score") or 0),
            blind_score=payload.get("blind_score"),
            guard=str(payload.get("guard", "none")),
            source=str(payload.get("source", "mechanical")),
            status=str(payload.get("status", "open")),
            present=bool(payload.get("present", True)),
            first_seen=str(payload.get("first_seen", "")),
            last_seen=str(payload.get("last_seen", "")),
            notes=[str(note) for note in payload.get("notes") or []],
        )


@dataclass
class Queue:
    findings: list[Finding] = field(default_factory=list)
    root: Path = Path(".")

    @classmethod
    def load(cls, path: Path) -> Queue:
        if not path.exists():
            return cls()
        payload = json.loads(path.read_text(encoding="utf-8"))
        findings = [Finding.from_dict(raw) for raw in payload.get("findings") or []]
        return cls(findings=findings)

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": 1,
            "updated_at": now(),
            "findings": [finding.to_dict() for finding in self.sorted()],
        }
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    def by_fingerprint(self) -> dict[str, Finding]:
        return {finding.fingerprint: finding for finding in self.findings}

    def get(self, finding_id: str) -> Finding | None:
        for finding in self.findings:
            if finding.id == finding_id:
                return finding
        return None

    def merge_scan(self, fresh: list[Finding]) -> tuple[int, int, int]:
        """Merge a scan result into the queue.

        Returns (added, updated, absent). A finding from an earlier scan that
        this scan did not observe keeps its status and is marked absent. That
        reveals a fix that landed without a status change.
        """

        existing = self.by_fingerprint()
        stamp = now()
        seen: set[str] = set()
        added = updated = 0
        for finding in fresh:
            key = finding.fingerprint
            seen.add(key)
            current = existing.get(key)
            if current is None:
                finding.first_seen = stamp
                finding.last_seen = stamp
                finding.present = True
                self.findings.append(finding)
                added += 1
                continue
            current.detail = finding.detail
            current.line = finding.line
            current.kind = finding.kind
            current.guard = finding.guard
            current.mechanical_score = max(current.mechanical_score, finding.mechanical_score)
            current.last_seen = stamp
            current.present = True
            updated += 1
        absent = 0
        for finding in self.findings:
            if finding.fingerprint not in seen and finding.present:
                finding.present = False
                absent += 1
        return added, updated, absent

    def sorted(self) -> list[Finding]:
        order = {status: index for index, status in enumerate(STATUSES)}
        return sorted(
            self.findings,
            key=lambda f: (order.get(f.status, 99), -f.score, f.path, f.line, f.symbol),
        )

    def eligible(self, allow_rebaseline: bool = False) -> list[Finding]:
        """Open findings the loop may pick, highest severity first."""

        picks = [
            finding
            for finding in self.findings
            if finding.status == "open"
            and finding.present
            and (allow_rebaseline or finding.guard == "none")
        ]
        return sorted(picks, key=lambda f: (-f.score, f.path, f.line))

    def stats(self) -> dict[str, int]:
        counts = {status: 0 for status in STATUSES}
        for finding in self.findings:
            counts[finding.status] = counts.get(finding.status, 0) + 1
        counts["absent"] = sum(1 for f in self.findings if not f.present)
        counts["total"] = len(self.findings)
        counts["eligible"] = len(self.eligible())
        counts["guarded"] = sum(
            1 for f in self.findings if f.status == "open" and f.guard != "none"
        )
        return counts
