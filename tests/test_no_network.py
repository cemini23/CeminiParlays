from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "src" / "ceminiparlays"
BANNED = {
    "requests",
    "httpx",
    "aiohttp",
    "urllib.request",
    "selenium",
    "playwright",
    "websocket",
}


def test_source_has_no_network_clients() -> None:
    offenders: list[str] = []
    for path in ROOT.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            for name in names:
                if name in BANNED or name.split(".")[0] in {item.split(".")[0] for item in BANNED}:
                    if name.startswith("urllib") and name != "urllib.request":
                        continue
                    if name in BANNED or name.split(".")[0] in {
                        "requests",
                        "httpx",
                        "aiohttp",
                        "selenium",
                        "playwright",
                    }:
                        offenders.append(f"{path.name}:{name}")
    assert offenders == []
