"""
Unit tests for the strategy comparison / blended portfolio module
(src/evaluation/comparison.py).

Uses small synthetic return series with hand-computable answers, like the
rest of the suite - fast, offline, deterministic.
"""

import math

import pandas as pd
import pytest

from src.evaluation.comparison import (
    blend_returns,
    blend_sweep,
    combine_strategies,
    compound_to_quarterly,
)


def make_monthly_returns() -> pd.Series:
    """Six months (two full quarters) of simple monthly returns."""
    dates = pd.date_range("2020-01-31", periods=6, freq="ME")
    return pd.Series([0.01, 0.02, 0.03, -0.01, 0.00, 0.02], index=dates)


def make_quarterly_returns() -> pd.Series:
    """Two quarterly returns on the same quarter-end dates the monthly
    series above compounds to (2020-03-31 and 2020-06-30)."""
    dates = pd.date_range("2020-03-31", periods=2, freq="QE")
    return pd.Series([0.05, -0.02], index=dates)


# --- compound_to_quarterly ---------------------------------------------------


def test_compound_to_quarterly_hand_computed():
    quarterly = compound_to_quarterly(make_monthly_returns())
    # Q1 2020: (1.01)(1.02)(1.03) - 1
    assert quarterly.loc["2020-03-31"] == pytest.approx(1.01 * 1.02 * 1.03 - 1)
    # Q2 2020: (0.99)(1.00)(1.02) - 1
    assert quarterly.loc["2020-06-30"] == pytest.approx(0.99 * 1.00 * 1.02 - 1)


def test_compound_to_quarterly_dates_are_quarter_ends():
    quarterly = compound_to_quarterly(make_monthly_returns())
    assert list(quarterly.index) == [pd.Timestamp("2020-03-31"), pd.Timestamp("2020-06-30")]


# --- blend_returns -----------------------------------------------------------


def test_blend_returns_hand_computed_5050():
    momentum_q = pd.Series([0.10, 0.00], index=pd.date_range("2020-03-31", periods=2, freq="QE"))
    value_q = pd.Series([0.02, 0.04], index=pd.date_range("2020-03-31", periods=2, freq="QE"))
    blended = blend_returns(momentum_q, value_q, momentum_weight=0.5)
    assert blended.iloc[0] == pytest.approx(0.5 * 0.10 + 0.5 * 0.02)
    assert blended.iloc[1] == pytest.approx(0.5 * 0.00 + 0.5 * 0.04)


def test_blend_returns_only_uses_common_dates():
    """A quarter where only one strategy has a return can't have a blend
    return - it must be dropped, not filled or assumed zero."""
    momentum_q = pd.Series(
        [0.10, 0.00, 0.05], index=pd.date_range("2020-03-31", periods=3, freq="QE")
    )
    value_q = pd.Series([0.02, 0.04], index=pd.date_range("2020-03-31", periods=2, freq="QE"))
    blended = blend_returns(momentum_q, value_q, momentum_weight=0.5)
    assert len(blended) == 2
    assert pd.Timestamp("2020-09-30") not in blended.index


def test_blend_returns_rejects_weight_outside_zero_to_one():
    momentum_q = make_quarterly_returns()
    value_q = make_quarterly_returns()
    with pytest.raises(ValueError):
        blend_returns(momentum_q, value_q, momentum_weight=1.5)
    with pytest.raises(ValueError):
        blend_returns(momentum_q, value_q, momentum_weight=-0.1)


# --- combine_strategies endpoints (the key sanity bound) ---------------------


def test_weight_one_reproduces_momentum_only():
    """A '100% momentum' blend must exactly equal the compounded momentum
    series on the common window - if it doesn't, the blending math is
    quietly wrong somewhere."""
    monthly = make_monthly_returns()
    value_q = make_quarterly_returns()
    blend = combine_strategies(monthly, value_q, momentum_weight=1.0)
    expected = compound_to_quarterly(monthly)
    pd.testing.assert_series_equal(blend.returns, expected, check_freq=False)


def test_weight_zero_reproduces_value_only():
    monthly = make_monthly_returns()
    value_q = make_quarterly_returns()
    blend = combine_strategies(monthly, value_q, momentum_weight=0.0)
    pd.testing.assert_series_equal(blend.returns, value_q, check_freq=False)


def test_combine_strategies_equity_compounds_from_one():
    monthly = make_monthly_returns()
    value_q = make_quarterly_returns()
    blend = combine_strategies(monthly, value_q, momentum_weight=0.5)
    expected_final = ((1 + blend.returns).cumprod()).iloc[-1]
    assert blend.equity.iloc[-1] == pytest.approx(expected_final)


def test_combine_strategies_metrics_present_and_finite():
    blend = combine_strategies(make_monthly_returns(), make_quarterly_returns(), 0.6)
    for name in ["CAGR", "Annualized Volatility", "Sharpe Ratio", "Max Drawdown"]:
        assert name in blend.metrics.index
        assert not math.isnan(blend.metrics[name])


# --- blend_sweep -------------------------------------------------------------


def test_blend_sweep_default_columns_run_momentum_to_value():
    sweep = blend_sweep(make_monthly_returns(), make_quarterly_returns())
    assert list(sweep.columns) == [
        "100% Mom / 0% Val",
        "75% Mom / 25% Val",
        "50% Mom / 50% Val",
        "25% Mom / 75% Val",
        "0% Mom / 100% Val",
    ]


def test_blend_sweep_endpoints_match_pure_strategies():
    monthly = make_monthly_returns()
    value_q = make_quarterly_returns()
    sweep = blend_sweep(monthly, value_q)
    pure_momentum = combine_strategies(monthly, value_q, 1.0).metrics
    pure_value = combine_strategies(monthly, value_q, 0.0).metrics
    pd.testing.assert_series_equal(sweep["100% Mom / 0% Val"], pure_momentum, check_names=False)
    pd.testing.assert_series_equal(sweep["0% Mom / 100% Val"], pure_value, check_names=False)
