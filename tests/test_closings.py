import csv
from pathlib import Path

import numpy as np
import pytest

from ceminiparlays.closings import ClosingLine, closing_correlation, read_closing_lines
from ceminiparlays.copula import exact_joint


def test_read_closing_lines_key_lookup(tmp_path: Path) -> None:
    csv_path = tmp_path / "closings.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["season", "week", "game", "closing_spread", "closing_total"])
        writer.writerow([2024, 1, "AAA@BBB", -3.5, 45.5])
        writer.writerow([2024, 1, "CCC@DDD", 2.5, 48.0])

    rows = read_closing_lines(csv_path)
    assert (2024, 1, "AAA@BBB") in rows
    assert rows[(2024, 1, "AAA@BBB")].closing_spread == -3.5
    assert rows[(2024, 1, "AAA@BBB")].closing_total == 45.5
    assert (2024, 1, "CCC@DDD") in rows
    assert len(rows) == 2


def test_read_closing_lines_duplicate_key_fails(tmp_path: Path) -> None:
    csv_path = tmp_path / "closings.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["season", "week", "game", "closing_spread", "closing_total"])
        writer.writerow([2024, 1, "AAA@BBB", -3.5, 45.5])
        writer.writerow([2024, 1, "AAA@BBB", 2.5, 48.0])

    with pytest.raises(ValueError, match="Duplicate key"):
        read_closing_lines(csv_path)


def test_read_closing_lines_blank_number_fails(tmp_path: Path) -> None:
    csv_path = tmp_path / "closings.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["season", "week", "game", "closing_spread", "closing_total"])
        writer.writerow([2024, 1, "AAA@BBB", "", 45.5])

    with pytest.raises(ValueError, match="blank closing_spread"):
        read_closing_lines(csv_path)


def test_read_closing_lines_missing_file_raises() -> None:
    with pytest.raises(FileNotFoundError):
        read_closing_lines(Path("nonexistent.csv"))


def test_closing_correlation_matches_numpy(tmp_path: Path) -> None:
    csv_path = tmp_path / "closings.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["season", "week", "game", "closing_spread", "closing_total"])
        writer.writerow([2024, 1, "AAA@BBB", -3.5, 45.5])
        writer.writerow([2024, 1, "CCC@DDD", 2.5, 48.0])
        writer.writerow([2024, 2, "EEE@FFF", -7.0, 42.5])
        writer.writerow([2024, 2, "GGG@HHH", 1.5, 51.0])

    rows = read_closing_lines(csv_path)
    corr = closing_correlation(rows)

    # Check shape and diagonal
    assert corr.shape == (2, 2)
    assert abs(corr[0, 0] - 1.0) < 1e-9
    assert abs(corr[1, 1] - 1.0) < 1e-9
    assert abs(corr[0, 1] - corr[1, 0]) < 1e-9

    # Compare rho to numpy.corrcoef
    spreads = np.array([-3.5, 2.5, -7.0, 1.5])
    totals = np.array([45.5, 48.0, 42.5, 51.0])
    expected_rho = float(np.corrcoef(spreads, totals)[0, 1])
    assert abs(corr[0, 1] - expected_rho) < 1e-9


def test_closing_correlation_exact_joint_runs() -> None:
    # Build a small valid correlation matrix manually
    rows = {
        (2024, 1, "AAA@BBB"): ClosingLine(2024, 1, "AAA@BBB", -3.5, 45.5),
        (2024, 1, "CCC@DDD"): ClosingLine(2024, 1, "CCC@DDD", 2.5, 48.0),
        (2024, 2, "EEE@FFF"): ClosingLine(2024, 2, "EEE@FFF", -7.0, 42.5),
    }
    corr = closing_correlation(rows)

    # exact_joint should accept this matrix
    joint = exact_joint([0.5, 0.5], corr)
    assert 0.0 < joint < 1.0


def test_example_file_loads_and_calibrates() -> None:
    example_path = Path("examples/closing_lines.csv")
    if not example_path.is_file():
        pytest.skip("examples/closing_lines.csv not present")

    rows = read_closing_lines(example_path)
    assert len(rows) == 4
    corr = closing_correlation(rows)
    assert corr.shape == (2, 2)
    assert abs(corr[0, 0] - 1.0) < 1e-9
    assert abs(corr[1, 1] - 1.0) < 1e-9

    # Should be usable by exact_joint
    joint = exact_joint([0.5, 0.5], corr)
    assert 0.0 < joint < 1.0


def test_closing_correlation_requires_at_least_three_rows() -> None:
    rows = {
        (2024, 1, "AAA@BBB"): ClosingLine(2024, 1, "AAA@BBB", -3.5, 45.5),
        (2024, 1, "CCC@DDD"): ClosingLine(2024, 1, "CCC@DDD", 2.5, 48.0),
    }
    with pytest.raises(ValueError, match="at least 3 rows"):
        closing_correlation(rows)


def test_closing_correlation_zero_variance_fails() -> None:
    rows = {
        (2024, 1, "AAA@BBB"): ClosingLine(2024, 1, "AAA@BBB", -3.5, 45.5),
        (2024, 1, "CCC@DDD"): ClosingLine(2024, 1, "CCC@DDD", -3.5, 48.0),
        (2024, 2, "EEE@FFF"): ClosingLine(2024, 2, "EEE@FFF", -3.5, 42.5),
    }
    with pytest.raises(ValueError, match="zero variance"):
        closing_correlation(rows)