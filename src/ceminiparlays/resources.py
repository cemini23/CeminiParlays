from __future__ import annotations

from importlib import resources
from pathlib import Path

PACKAGE = "ceminiparlays"
PACKAGE_DATA = "data"
REPO_ROOT = Path(__file__).resolve().parents[2]
REPO_CONFIG = REPO_ROOT / "config"


def _repo_path(*parts: str) -> Path:
    return REPO_CONFIG.joinpath(*parts)


def read_config_text(*parts: str) -> str:
    """Read a config file, preferring the repo ``config/`` tree then package data.

    Order matters: an editable checkout keeps using the working ``config/`` files
    so operators can tweak priors, while a non-editable wheel falls back to the
    JSON copied into ``ceminiparlays/data/`` (I-18).
    """

    repo = _repo_path(*parts)
    if repo.is_file():
        return repo.read_text(encoding="utf-8")
    resource = resources.files(PACKAGE).joinpath(PACKAGE_DATA, *parts)
    try:
        return resource.read_text(encoding="utf-8")
    except (FileNotFoundError, ModuleNotFoundError, NotADirectoryError) as exc:
        raise FileNotFoundError(f"config not found: {'/'.join(parts)}") from exc
