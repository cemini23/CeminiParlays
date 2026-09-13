import json
from pathlib import Path

from ceminiparlays import resources
from ceminiparlays.correlation import load_priors
from ceminiparlays.payouts import load_profile
from ceminiparlays.roster import load_roster


def test_config_resolves_from_a_non_repo_cwd(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    assert "pairs" in load_priors()
    assert load_profile("underdog")["platform"] == "underdog"
    assert load_profile("prizepicks")["platform"] == "prizepicks"
    assert load_profile("hardrock")["platform"] == "hardrock"
    assert load_profile("fanduel")["platform"] == "fanduel"
    assert load_profile("draftkings")["platform"] == "draftkings"
    assert load_roster().players["dj_moore"].team == "BUF"


def test_config_falls_back_to_package_data(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(resources, "REPO_CONFIG", tmp_path / "no-such-config")
    priors = json.loads(resources.read_config_text("correlation_priors.json"))
    assert "pairs" in priors
    profile = json.loads(
        resources.read_config_text("payout_profiles", "underdog.json")
    )
    assert profile["platform"] == "underdog"
    roster = json.loads(resources.read_config_text("rosters", "nfl.json"))
    assert roster["players"]["dj_moore"]["team"] == "BUF"


def test_missing_config_raises_file_not_found(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(resources, "REPO_CONFIG", tmp_path / "no-such-config")
    try:
        resources.read_config_text("nope.json")
    except FileNotFoundError as exc:
        assert "not found" in str(exc)
    else:
        raise AssertionError("expected FileNotFoundError")
