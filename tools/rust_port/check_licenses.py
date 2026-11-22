#!/usr/bin/env python3
"""Licence gate for the Rust copula crate.

Reads the dependency graph from ``cargo metadata`` and splits it in two:

* **linked** — reachable from the crate root through normal (non-build,
  non-dev) edges, ignoring proc-macro crates, whose code runs on the host at
  build time and is never shipped in the ``cdylib``;
* **host-only** — everything else (build scripts, build-dependencies and
  proc-macro crates with their own trees).

Linked packages must be inside the permissive allowlist (MIT, Apache-2.0,
BSD-2-Clause, BSD-3-Clause, ISC, and ``OR``/``AND`` combinations of them).
Host-only packages outside the allowlist are still printed, with their SPDX
expression and the note ``host-only, not shipped``, and do not fail the gate.

The script exits 1 when any package anywhere carries a GPL/AGPL/LGPL/SSPL or
non-commercial licence, or when a **linked** package falls outside the
allowlist. It exits 0 otherwise.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = "rust/copula_engine/Cargo.toml"

#: Permissive licences a shipped binary may carry.
ALLOWLIST = frozenset(
    {"MIT", "Apache-2.0", "BSD-2-Clause", "BSD-3-Clause", "ISC"}
)

#: Copyleft or non-commercial terms that fail the gate outright.
_FORBIDDEN_ID = re.compile(r"GPL|SSPL", re.IGNORECASE)
_NON_COMMERCIAL = re.compile(
    r"(?:^|[-_.])NC(?:$|[-_.])|NONCOMMERCIAL|NON-COMMERCIAL", re.IGNORECASE
)

_TOKEN = re.compile(r"\(|\)|\bAND\b|\bOR\b|\bWITH\b|[A-Za-z0-9.+:-]+")


@dataclass(frozen=True)
class Package:
    name: str
    version: str
    spdx: str
    linked: bool
    allowed: bool
    forbidden: bool


class _SpdxParser:
    """Minimal SPDX expression parser (parentheses, AND, OR, WITH)."""

    def __init__(self, expression: str) -> None:
        self.tokens = _TOKEN.findall(expression)
        self.position = 0
        self.leaves: list[str] = []

    def parse(self) -> bool:
        value = self._or()
        if self.position != len(self.tokens):
            raise ValueError(f"trailing tokens in SPDX expression: {self.tokens!r}")
        return value

    def _peek(self) -> str | None:
        return self.tokens[self.position] if self.position < len(self.tokens) else None

    def _take(self, expected: str | None = None) -> str:
        token = self._peek()
        if token is None or (expected is not None and token.upper() != expected):
            raise ValueError(f"expected {expected!r}, found {token!r}")
        self.position += 1
        return token

    def _or(self) -> bool:
        value = self._and()
        while (self._peek() or "").upper() == "OR":
            self._take("OR")
            value = self._and() or value
        return value

    def _and(self) -> bool:
        value = self._factor()
        while (self._peek() or "").upper() == "AND":
            self._take("AND")
            value = self._factor() and value
        return value

    def _factor(self) -> bool:
        if self._peek() == "(":
            self._take("(")
            value = self._or()
            self._take(")")
            return value
        identifier = self._take()
        self.leaves.append(identifier)
        if (self._peek() or "").upper() == "WITH":
            # A licence exception (e.g. LLVM-exception) modifies the grant; the
            # base licence still decides allowlist membership.
            self._take("WITH")
            self._take()
        return identifier in ALLOWLIST


def _split_expression(expression: str) -> tuple[bool, bool]:
    """Return ``(allowed, forbidden)`` for one SPDX expression."""

    parser = _SpdxParser(expression)
    allowed = parser.parse()
    forbidden = any(
        _FORBIDDEN_ID.search(leaf) or _NON_COMMERCIAL.search(leaf)
        for leaf in parser.leaves
    )
    return allowed, forbidden


def _cargo_metadata() -> dict:
    process = subprocess.run(
        [
            "cargo",
            "metadata",
            "--format-version",
            "1",
            "--manifest-path",
            MANIFEST,
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    if process.returncode != 0:
        raise SystemExit(
            "check_licenses: cargo metadata failed\n"
            + (process.stderr or process.stdout)[-2000:]
        )
    return json.loads(process.stdout)


def _is_proc_macro(package: dict) -> bool:
    return any("proc-macro" in target.get("kind", []) for target in package["targets"])


def _classify(meta: dict) -> list[Package]:
    packages = {package["id"]: package for package in meta["packages"]}
    nodes = {node["id"]: node for node in meta["resolve"]["nodes"]}
    root = meta["resolve"]["root"]
    if root is None:
        raise SystemExit("check_licenses: cargo metadata has no resolve root")

    # Linked = reachable over normal edges only, never entering a proc-macro
    # crate. Everything else in the resolve graph is host-only.
    linked: set[str] = set()
    queue = [root]
    while queue:
        current = queue.pop()
        for dependency in nodes[current]["deps"]:
            kinds = {kind["kind"] for kind in dependency["dep_kinds"]}
            if None not in kinds:
                continue
            target = dependency["pkg"]
            if _is_proc_macro(packages[target]):
                continue
            if target not in linked:
                linked.add(target)
                queue.append(target)

    result: list[Package] = []
    for identifier, package in packages.items():
        if identifier == root or identifier not in nodes:
            continue
        expression = package.get("license")
        if not expression:
            expression = "UNKNOWN"
        allowed, forbidden = _split_expression(expression)
        result.append(
            Package(
                name=package["name"],
                version=package["version"],
                spdx=expression,
                linked=identifier in linked,
                allowed=allowed,
                forbidden=forbidden,
            )
        )
    result.sort(key=lambda package: (package.name, package.version))
    return result


def _table(rows: list[Package], host_only: bool) -> list[str]:
    lines = [
        "| Package | Version | SPDX | Status |",
        "| --- | --- | --- | --- |",
    ]
    for package in rows:
        if package.forbidden:
            status = "FORBIDDEN"
        elif package.allowed:
            status = "ok"
        elif host_only:
            status = "host-only, not shipped"
        else:
            status = "VIOLATION: not in allowlist"
        lines.append(
            f"| {package.name} | {package.version} | {package.spdx} | {status} |"
        )
    return lines


def main() -> int:
    meta = _cargo_metadata()
    packages = _classify(meta)
    linked = [package for package in packages if package.linked]
    host_only = [package for package in packages if not package.linked]

    violations: list[str] = []
    for package in packages:
        if package.forbidden:
            violations.append(
                f"{package.name} {package.version}: forbidden licence {package.spdx}"
            )
        elif package.linked and not package.allowed:
            violations.append(
                f"{package.name} {package.version}: linked licence {package.spdx} "
                "is outside the allowlist"
            )

    print("LINKED PACKAGES (shipped in the extension)")
    print()
    print("\n".join(_table(linked, host_only=False)))
    print()
    print("HOST-ONLY PACKAGES (build time / proc-macro, not shipped)")
    print()
    print("\n".join(_table(host_only, host_only=True)))
    print()

    if violations:
        print(f"LICENSES_FAILED linked={len(linked)} host_only={len(host_only)} "
              f"violations={len(violations)}")
        for violation in violations:
            sys.stderr.write(f"check_licenses: {violation}\n")
        return 1

    print(
        f"LICENSES_OK linked={len(linked)} host_only={len(host_only)} violations=0"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
