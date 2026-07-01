"""
Unit tests for the 12-1 momentum signal calculation.
"""

import numpy as np
import pandas as pd
import pytest

from src.strategy.momentum import compute_momentum_signal, select_top_n


def make_month_end_prices(n_months=20):
    dates = pd.date_range("2020-01-31", periods=n_months, freq="ME")
    prices = pd.DataFrame(
        {
            "A": [100 * 1.01**i for i in range(n_months)],  # steady 1%/mo grower
            "B": [100 * 1.05**i for i in range(n_months)],  # steady 5%/mo grower
            "C": [np.nan] * 5 + [100 * 1.02**i for i in range(n_months - 5)],  # late listing
        },
        index=dates,
    )
    return prices


def test_momentum_formula_exact_value():
    prices = make_month_end_prices()
    formation_date = prices.index[13]
    scores = compute_momentum_signal(prices, formation_date, lookback_months=12, skip_months=1)

    # momentum = Price[t-1] / Price[t-12] - 1 = growth^(12-1) - 1
    expected_a = 1.01**11 - 1
    expected_b = 1.05**11 - 1
    assert scores["A"] == pytest.approx(expected_a)
    assert scores["B"] == pytest.approx(expected_b)


def test_excludes_ticker_missing_lookback_price():
    prices = make_month_end_prices()
    # At formation_date index 13, lookback index = 13-12 = 1, where C is NaN
    # (C only has data from index 5 onward).
    formation_date = prices.index[13]
    scores = compute_momentum_signal(prices, formation_date, lookback_months=12, skip_months=1)
    assert "C" not in scores.index


def test_includes_ticker_once_lookback_available():
    prices = make_month_end_prices()
    # At formation_date index 18, lookback index = 18-12 = 6, where C has data.
    formation_date = prices.index[18]
    scores = compute_momentum_signal(prices, formation_date, lookback_months=12, skip_months=1)
    assert "C" in scores.index


def test_raises_when_insufficient_warmup_history():
    prices = make_month_end_prices()
    formation_date = prices.index[6]  # lookback index would be 6-12 = -6
    with pytest.raises(ValueError):
        compute_momentum_signal(prices, formation_date, lookback_months=12, skip_months=1)


def test_select_top_n_ranks_descending():
    scores = pd.Series({"A": 0.1, "B": 0.5, "C": 0.3})
    assert select_top_n(scores, 2) == ["B", "C"]


def test_select_top_n_handles_fewer_than_n_available():
    scores = pd.Series({"A": 0.1, "B": 0.2})
    result = select_top_n(scores, 5)
    assert set(result) == {"A", "B"}
    assert len(result) == 2
