from __future__ import annotations

import os
from pathlib import Path

from ceminiparlays.envfile import load_env_file, parse_env_text


def test_parse_env_text_handles_comment_export_and_quotes() -> None:
    text = "# a comment\n\nexport A=1\nB = 'two'\nC=\"three\"\nMALFORMED\n"
    assert parse_env_text(text) == {"A": "1", "B": "two", "C": "three"}


def test_parse_env_text_keeps_value_containing_equals() -> None:
    assert parse_env_text("K=abc=def") == {"K": "abc=def"}


def test_load_env_file_sets_defaults_without_override(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("CEP_A", raising=False)
    monkeypatch.setenv("CEP_B", "keep")
    path = tmp_path / ".env"
    path.write_text("CEP_A=fresh\nCEP_B=override\n", encoding="utf-8")

    assert load_env_file(path) == 1
    assert os.environ["CEP_A"] == "fresh"
    assert os.environ["CEP_B"] == "keep"


def test_load_env_file_missing_returns_zero(tmp_path: Path) -> None:
    assert load_env_file(tmp_path / "absent") == 0
