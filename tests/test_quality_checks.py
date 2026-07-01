"""
Unit tests for price data quality checks.
"""

import numpy as np
import pandas as pd

from src.data_layer.quality_checks import find_price_outliers


def test_no_false_positives_on_normal_returns():
    """Regression test: pandas' DataFrame.stack() stopped dropping NaN by
    default, which previously caused every non-flagged (NaN-masked) cell to
    show up as a spurious "flagged" row."""
    dates = pd.date_range("2020-01-01", periods=10, freq="B")
    prices = pd.DataFrame(
        {
            "A": [100, 101, 99, 100, 102, 101, 103, 104, 102, 105],
            "B": [50, 51, 52, 53, 54, 55, 56, 57, 58, 59],
        },
        index=dates,
    )
    result = find_price_outliers(prices, threshold=0.5)
    assert len(result) == 0


def test_detects_injected_price_spike():
    dates = pd.date_range("2020-01-01", periods=10, freq="B")
    prices = pd.DataFrame(
        {
            "A": [100.0] * 10,
            "B": [50.0] * 10,
        },
        index=dates,
    )
    # A single bad print at index 5 shows up as two large moves: the spike
    # itself, and the apparent crash back down the next day.
    prices.iloc[5, 0] = prices.iloc[4, 0] * 3
    result = find_price_outliers(prices, threshold=0.5)
    assert len(result) == 2
    assert set(result["ticker"]) == {"A"}
