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

#: The only modules allowed to open an HTTP connection. The Odds API client and
#: the tiered Jev client are both licensed paths; every other module stays offline.
LICENSED_HTTP = {"odds_api.py", "jev_client.py"}


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
                root = name.split(".")[0]
                if name == "urllib.request":
                    if path.name not in LICENSED_HTTP:
                        offenders.append(f"{path.name}:{name}")
                    continue
                if name.startswith("urllib"):
                    continue
                if name in BANNED or root in {
                    "requests",
                    "httpx",
                    "aiohttp",
                    "selenium",
                    "playwright",
                }:
                    offenders.append(f"{path.name}:{name}")
    assert offenders == []
