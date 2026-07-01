"""
Unit tests for performance evaluation metrics, using synthetic series with
hand-computable expected answers.
"""

import numpy as np
import pandas as pd
import pytest

from src.evaluation.metrics import annualized_vol, cagr, max_drawdown, sharpe_ratio


def test_cagr_constant_monthly_return():
    r = 0.01
    dates = pd.date_range("2020-01-31", periods=25, freq="ME")
    equity = pd.Series((1 + r) ** np.arange(25), index=dates)
    # Small tolerance: CAGR uses actual calendar days (365.25/yr), and 24
    # months isn't exactly 2 x 365.25 days, so there's a tiny, expected
    # discrepancy from the pure (1+r)**12 - 1 formula.
    assert cagr(equity) == pytest.approx((1 + r) ** 12 - 1, abs=1e-3)


def test_max_drawdown_exact_fifty_percent():
    equity = pd.Series(
        [1.0, 1.5, 2.0, 1.5, 1.0, 1.0, 1.0],
        index=pd.date_range("2020-01-31", periods=7, freq="ME"),
    )
    assert max_drawdown(equity) == pytest.approx(-0.5)


def test_max_drawdown_no_decline_is_zero():
    equity = pd.Series([1.0, 1.1, 1.2, 1.3], index=pd.date_range("2020-01-31", periods=4, freq="ME"))
    assert max_drawdown(equity) == pytest.approx(0.0)


def test_annualized_vol_zero_for_constant_returns():
    returns = pd.Series([0.01] * 12, index=pd.date_range("2020-01-31", periods=12, freq="ME"))
    assert annualized_vol(returns) == pytest.approx(0.0)


def test_sharpe_ratio_zero_risk_free_matches_return_over_vol():
    returns = pd.Series([0.01, 0.02, -0.01, 0.03], index=pd.date_range("2020-01-31", periods=4, freq="ME"))
    expected = (returns.mean() * 12) / (returns.std() * np.sqrt(12))
    assert sharpe_ratio(returns, risk_free_rate=0.0) == pytest.approx(expected)
