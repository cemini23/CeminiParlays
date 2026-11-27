"""Load ``.env`` key=value pairs into ``os.environ`` without overriding real env.

The CLI reads secrets from ``os.environ`` (see ``odds_api.resolve_api_key``). This
helper lets a repo ``.env`` supply defaults so an operator does not export the key
by hand every run. Existing environment values always win.
"""

from __future__ import annotations

import os
from pathlib import Path

from ceminiparlays.resources import REPO_ROOT


def parse_env_text(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        key, sep, value = line.partition("=")
        key = key.strip()
        if not sep or not key:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        out[key] = value
    return out


def load_env_file(path: Path) -> int:
    try:
        text = Path(path).read_text(encoding="utf-8")
    except FileNotFoundError:
        return 0
    loaded = 0
    for key, value in parse_env_text(text).items():
        if key not in os.environ:
            os.environ[key] = value
            loaded += 1
    return loaded


def load_dotenv_defaults(repo_root: Path | None = None) -> int:
    root = repo_root if repo_root is not None else REPO_ROOT
    return load_env_file(Path(root) / ".env")
