"""Mechanical checks: dead code, duplication, complexity, test gaps.

Every check reads the code only. No check reads git history.
Standard library only, so this tool adds no dependency to the package.
"""

from __future__ import annotations

import ast
import re
from collections import defaultdict
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path

from . import SRC_DIR, TESTS_DIR
from .queue import Finding
from .scope import finding_guard, tier

#: Thresholds. One place, so a change is visible.
COMPLEXITY_LIMIT = 12
NESTING_LIMIT = 5
FUNCTION_LINES_LIMIT = 80
DUPLICATION_RATIO = 0.85
DUPLICATION_MIN_STATEMENTS = 12

#: The checks report every finding. A quiet cap here once made a queue of 41
#: look like the whole list, when the real count was 121. Display is capped by
#: ``list -n`` and ``top -n`` instead.
_IDENTIFIER = re.compile(r"^[A-Za-z_]\w*$")
_TOKEN = re.compile(r"[A-Za-z_]\w*|\d+\.?\d*|[^\s\w]")
_BRANCHING = (ast.If, ast.For, ast.AsyncFor, ast.While, ast.ExceptHandler, ast.match_case)
_NESTING = (ast.If, ast.For, ast.AsyncFor, ast.While, ast.Try, ast.With, ast.AsyncWith, ast.match_case)


@dataclass
class ModuleInfo:
    path: str
    name: str
    tree: ast.Module
    text: str

    @property
    def lines(self) -> list[str]:
        return self.text.splitlines()


def _rel(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def load_modules(root: Path, src_dir: Path) -> list[ModuleInfo]:
    """Parse every module under ``src_dir``. A parse error is raised, not skipped."""

    modules: list[ModuleInfo] = []
    for path in sorted(src_dir.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        modules.append(
            ModuleInfo(
                path=_rel(path, root),
                name=path.name,
                tree=ast.parse(text, filename=str(path)),
                text=text,
            )
        )
    return modules


def load_test_modules(root: Path, tests_dir: Path) -> list[ModuleInfo]:
    """Parse the tests, so a test-only use counts as a use."""

    modules: list[ModuleInfo] = []
    if not tests_dir.exists():
        return modules
    for path in sorted(tests_dir.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        try:
            tree = ast.parse(text, filename=str(path))
        except SyntaxError:
            continue
        modules.append(
            ModuleInfo(path=_rel(path, root), name=path.name, tree=tree, text=text)
        )
    return modules


def collect_occurrences(modules: list[ModuleInfo]) -> dict[str, list[tuple[str, int]]]:
    """Map every identifier to the file and top-level block that mentions it."""

    occurrences: dict[str, list[tuple[str, int]]] = defaultdict(list)
    for info in modules:
        for index, node in enumerate(info.tree.body):
            owner = index if isinstance(
                node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
            ) else -1
            for sub in ast.walk(node):
                name = None
                if isinstance(sub, ast.Name):
                    name = sub.id
                elif isinstance(sub, ast.Attribute):
                    name = sub.attr
                elif isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                    _record_string(sub.value, info.path, owner, occurrences)
                    continue
                if name is not None:
                    occurrences[name].append((info.path, owner))
    return occurrences


def _string_names(value: str) -> list[str]:
    """Identifiers inside a string that is a type expression.

    ``"Environment | None"`` names ``Environment``. A quoted annotation is a
    real use, so it must count as a reference.
    """

    if _IDENTIFIER.match(value):
        return [value]
    try:
        tree = ast.parse(value, mode="eval")
    except SyntaxError:
        return []
    return [node.id for node in ast.walk(tree) if isinstance(node, ast.Name)]


def _record_string(
    value: str,
    path: str,
    owner: int,
    occurrences: dict[str, list[tuple[str, int]]],
) -> None:
    for name in _string_names(value):
        occurrences[name].append((path, owner))


def _external_refs(
    occurrences: dict[str, list[tuple[str, int]]], name: str, path: str, owner: int
) -> int:
    return sum(
        1
        for ref_path, ref_owner in occurrences.get(name, [])
        if not (ref_path == path and ref_owner == owner)
    )


def _is_public(name: str) -> bool:
    return not name.startswith("_")


def _body_statements(node: ast.FunctionDef | ast.AsyncFunctionDef) -> list[ast.stmt]:
    body = list(node.body)
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
        body = body[1:]
    return body


def _all_exports(tree: ast.Module) -> set[str]:
    exports: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "__all__":
                    try:
                        values = ast.literal_eval(node.value)
                    except (ValueError, SyntaxError):
                        continue
                    exports.update(str(value) for value in values)
    return exports


def check_dead_code(
    modules: list[ModuleInfo], occurrences: dict[str, list[tuple[str, int]]]
) -> list[Finding]:
    """Top-level functions, classes, and constants that nothing else mentions."""

    findings: list[Finding] = []
    for info in modules:
        if tier(info.name) not in {"free", "evaluation"}:
            continue
        exports = _all_exports(info.tree)
        for index, node in enumerate(info.tree.body):
            name: str | None = None
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                name = node.name
            elif isinstance(node, ast.Assign):
                targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
                name = targets[0] if len(targets) == 1 else None
            if not name or name in exports or name == "__all__":
                continue
            if name.startswith("__") or name == "main":
                continue
            if _external_refs(occurrences, name, info.path, index):
                continue
            score = 60
            if not _is_public(name):
                score += 10
            span = getattr(node, "end_lineno", node.lineno) - node.lineno
            if span >= 10:
                score += 15
            findings.append(
                Finding(
                    kind="dead_code",
                    path=info.path,
                    symbol=name,
                    line=node.lineno,
                    detail=f"`{name}` is defined and never referenced outside its own block",
                    mechanical_score=min(95, score),
                    guard=finding_guard(info.name, "dead_code"),
                )
            )
    findings.sort(key=lambda f: -f.mechanical_score)
    return findings


def check_unused_imports(modules: list[ModuleInfo]) -> list[Finding]:
    """An imported name that the module never uses. Mirrors ruff F401."""

    findings: list[Finding] = []
    for info in modules:
        if tier(info.name) not in {"free", "evaluation"}:
            continue
        used: set[str] = set()
        for node in ast.walk(info.tree):
            if isinstance(node, ast.Name):
                used.add(node.id)
            elif isinstance(node, ast.Attribute):
                used.add(node.attr)
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                used.update(_string_names(node.value))
        used.update(_all_exports(info.tree))
        for node in ast.walk(info.tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                for alias in node.names:
                    local = alias.asname or alias.name.split(".")[0]
                    if local in {"annotations", "*"} or local in used:
                        continue
                    findings.append(
                        Finding(
                            kind="unused_import",
                            path=info.path,
                            symbol=local,
                            line=node.lineno,
                            detail=f"`{local}` is imported and never used",
                            mechanical_score=35,
                            guard=finding_guard(info.name, "unused_import"),
                        )
                    )
    return findings


def _cyclomatic(node: ast.FunctionDef | ast.AsyncFunctionDef) -> int:
    complexity = 1
    for sub in ast.walk(node):
        if isinstance(sub, _BRANCHING):
            complexity += 1
        elif isinstance(sub, ast.IfExp):
            complexity += 1
        elif isinstance(sub, ast.BoolOp):
            complexity += max(0, len(sub.values) - 1)
        elif isinstance(sub, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
            complexity += sum(len(generator.ifs) for generator in sub.generators)
    return complexity


def _nesting_depth(node: ast.AST, depth: int = 0) -> int:
    deepest = depth
    for child in ast.iter_child_nodes(node):
        step = depth + 1 if isinstance(child, _NESTING) else depth
        deepest = max(deepest, _nesting_depth(child, step))
    return deepest


def iter_functions(
    tree: ast.Module,
) -> list[tuple[tuple[str, ...], ast.FunctionDef | ast.AsyncFunctionDef]]:
    """Every function or method, with its dotted path inside the module."""

    found: list[tuple[tuple[str, ...], ast.FunctionDef | ast.AsyncFunctionDef]] = []

    def walk(node: ast.AST, prefix: tuple[str, ...]) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                path = prefix + (child.name,)
                found.append((path, child))
                walk(child, path)
            elif isinstance(child, ast.ClassDef):
                walk(child, prefix + (child.name,))

    walk(tree, ())
    return found


def check_complexity(modules: list[ModuleInfo]) -> list[Finding]:
    """High branching, deep nesting, or long bodies."""

    findings: list[Finding] = []
    for info in modules:
        if tier(info.name) not in {"free", "evaluation"}:
            continue
        for path, node in iter_functions(info.tree):
            symbol = ".".join(path)
            complexity = _cyclomatic(node)
            if complexity >= COMPLEXITY_LIMIT:
                findings.append(
                    Finding(
                        kind="complexity",
                        path=info.path,
                        symbol=symbol,
                        line=node.lineno,
                        detail=f"cyclomatic complexity {complexity} (limit {COMPLEXITY_LIMIT})",
                        mechanical_score=min(95, 40 + (complexity - COMPLEXITY_LIMIT) * 4),
                        guard=finding_guard(info.name, "complexity"),
                    )
                )
            depth = _nesting_depth(node)
            if depth >= NESTING_LIMIT:
                findings.append(
                    Finding(
                        kind="nesting",
                        path=info.path,
                        symbol=symbol,
                        line=node.lineno,
                        detail=f"nesting depth {depth} (limit {NESTING_LIMIT})",
                        mechanical_score=min(90, 45 + (depth - NESTING_LIMIT) * 8),
                        guard=finding_guard(info.name, "nesting"),
                    )
                )
            length = (node.end_lineno or node.lineno) - node.lineno
            if length >= FUNCTION_LINES_LIMIT:
                findings.append(
                    Finding(
                        kind="long_function",
                        path=info.path,
                        symbol=symbol,
                        line=node.lineno,
                        detail=f"{length} lines (limit {FUNCTION_LINES_LIMIT})",
                        mechanical_score=min(80, 35 + (length - FUNCTION_LINES_LIMIT) // 10 * 5),
                        guard=finding_guard(info.name, "long_function"),
                    )
                )
    findings.sort(key=lambda f: -f.mechanical_score)
    return findings


def _normalised_tokens(node: ast.FunctionDef | ast.AsyncFunctionDef) -> list[str]:
    body = _body_statements(node)
    if not body:
        return []
    text = "\n".join(ast.unparse(statement) for statement in body)
    return _TOKEN.findall(text)


def check_duplication(modules: list[ModuleInfo]) -> list[Finding]:
    """Function bodies that carry the same logic under a different signature."""

    candidates: list[tuple[str, str, int, list[str]]] = []
    for info in modules:
        if tier(info.name) not in {"free", "evaluation"}:
            continue
        for path, node in iter_functions(info.tree):
            if len(_body_statements(node)) < DUPLICATION_MIN_STATEMENTS:
                continue
            tokens = _normalised_tokens(node)
            if tokens:
                candidates.append((info.path, ".".join(path), node.lineno, tokens))

    findings: list[Finding] = []
    for index, (path_a, symbol_a, line_a, tokens_a) in enumerate(candidates):
        for path_b, symbol_b, line_b, tokens_b in candidates[index + 1:]:
            shorter = min(len(tokens_a), len(tokens_b))
            longer = max(len(tokens_a), len(tokens_b))
            if not longer or shorter / longer < DUPLICATION_RATIO:
                continue
            ratio = SequenceMatcher(None, tokens_a, tokens_b).ratio()
            if ratio < DUPLICATION_RATIO:
                continue
            findings.append(
                Finding(
                    kind="duplication",
                    path=path_a,
                    symbol=symbol_a,
                    line=line_a,
                    detail=(
                        f"`{symbol_a}` and `{symbol_b}` ({path_b}:{line_b}) "
                        f"share {ratio:.0%} of their tokens"
                    ),
                    mechanical_score=min(90, 50 + int((ratio - DUPLICATION_RATIO) / 0.12 * 40)),
                    guard=finding_guard(Path(path_a).name, "duplication")
                    if finding_guard(Path(path_a).name, "duplication") != "none"
                    else finding_guard(Path(path_b).name, "duplication"),
                )
            )
    findings.sort(key=lambda f: -f.mechanical_score)
    return findings


def _test_text(tests_dir: Path) -> str:
    if not tests_dir.exists():
        return ""
    return "\n".join(
        path.read_text(encoding="utf-8") for path in sorted(tests_dir.rglob("*.py"))
    )


def _test_stems(tests_dir: Path) -> set[str]:
    if not tests_dir.exists():
        return set()
    return {path.stem for path in tests_dir.rglob("*.py")}


def _module_is_covered(module_stem: str, stems: set[str], text: str) -> bool:
    """True when a test file is named for the module, or the text names it."""

    if any(module_stem in stem for stem in stems):
        return True
    return bool(re.search(rf"\b{re.escape(module_stem)}\b", text))


def _is_testable(path: tuple[str, ...], classes: set[str]) -> bool:
    """A test can name a module function or a public class method.

    A closure lives inside another function. Only its parent can reach it, so
    the parent is the unit of coverage. A method on a private class is internal
    too: the class is what the module exposes.
    """

    if len(path) == 1:
        return True
    if len(path) != 2 or path[0] not in classes:
        return False
    return not path[0].startswith("_")


def check_test_gaps(modules: list[ModuleInfo], tests_dir: Path) -> list[Finding]:
    """A public function or a whole module that no test names."""

    text = _test_text(tests_dir)
    stems = _test_stems(tests_dir)
    findings: list[Finding] = []
    for info in modules:
        if tier(info.name) not in {"free", "evaluation"}:
            continue
        classes = {node.name for node in info.tree.body if isinstance(node, ast.ClassDef)}
        public: list[tuple[tuple[str, ...], ast.FunctionDef | ast.AsyncFunctionDef]] = [
            (path, node)
            for path, node in iter_functions(info.tree)
            if _is_public(path[-1])
            and not path[-1].startswith("__")
            and _is_testable(path, classes)
        ]
        if not public:
            continue
        if not _module_is_covered(info.name[:-3], stems, text):
            findings.append(
                Finding(
                    kind="test_gap",
                    path=info.path,
                    symbol=info.name,
                    line=1,
                    detail=f"no test file mentions `{info.name[:-3]}` or any of its names",
                    mechanical_score=55,
                    guard=finding_guard(info.name, "test_gap"),
                )
            )
            continue
        for path, node in public:
            name = path[-1]
            if re.search(rf"\b{re.escape(name)}\b", text):
                continue
            span = (node.end_lineno or node.lineno) - node.lineno
            findings.append(
                Finding(
                    kind="test_gap",
                    path=info.path,
                    symbol=".".join(path),
                    line=node.lineno,
                    detail=f"`{'.'.join(path)}` is public and no test names it",
                    mechanical_score=min(70, 30 + span // 5 * 5),
                    guard=finding_guard(info.name, "test_gap"),
                )
            )
    findings.sort(key=lambda f: -f.mechanical_score)
    return findings


def scan(root: Path) -> list[Finding]:
    """Run every mechanical check and return the findings, highest score first."""

    modules = load_modules(root, SRC_DIR)
    occurrences = collect_occurrences(modules + load_test_modules(root, TESTS_DIR))
    findings: list[Finding] = []
    findings.extend(check_dead_code(modules, occurrences))
    findings.extend(check_unused_imports(modules))
    findings.extend(check_complexity(modules))
    findings.extend(check_duplication(modules))
    findings.extend(check_test_gaps(modules, TESTS_DIR))
    findings.sort(key=lambda f: (-f.mechanical_score, f.path, f.line))
    return findings
