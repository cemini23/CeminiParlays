import json
from pathlib import Path

from ceminiparlays.cli import main

ROOT = Path(__file__).resolve().parents[1]


def test_devig_cli(capsys) -> None:
    assert main(["devig", "--over", "-155", "--under", "120"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["p_over"] > 0.57


def test_fair_cli(capsys) -> None:
    assert (
        main(
            [
                "fair",
                "--player",
                "Patrick Mahomes",
                "--stat",
                "pass_yds",
                "--line",
                "275.5",
                "--median",
                "268",
                "--sd",
                "55",
            ]
        )
        == 0
    )
    out = capsys.readouterr().out
    assert "fair_p" in out
    assert "do not submit" in out.lower() or "Research only" in out


def test_run_cli(tmp_path: Path) -> None:
    out_dir = tmp_path / "slate"
    assert (
        main(
            [
                "run",
                "--lines",
                str(ROOT / "examples" / "manual_lines.csv"),
                "--distributions",
                str(ROOT / "examples" / "distributions.csv"),
                "--platform",
                "underdog",
                "--slip-size",
                "2",
                "--n-sims",
                "3000",
                "--out-dir",
                str(out_dir),
            ]
        )
        == 0
    )
    assert (out_dir / "edges.csv").is_file()
    report = (out_dir / "report.txt").read_text(encoding="utf-8")
    assert "do not submit" in report.lower()
    assert "Pacheco" not in report
