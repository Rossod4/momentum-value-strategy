"""
Tests for src/evaluation/walk_forward.py - all offline, all against small
synthetic return series whose right answers can be worked out by hand.

The key walk-forward property under test: a quarter's return must only ever
be produced by a weight chosen WITHOUT seeing that quarter. The synthetic
setups make the correct choice unambiguous (one sleeve dominates the other
in every training window), so the test can assert exactly which weight the
walk-forward must pick and exactly what its out-of-sample returns must be.
"""

import numpy as np
import pandas as pd
import pytest

from src.evaluation.walk_forward import rolling_window_metrics, walk_forward_blend


def quarterly_dates(n: int) -> pd.DatetimeIndex:
    return pd.date_range("2012-03-31", periods=n, freq="QE")


def alternating_series(n: int, high: float, low: float) -> pd.Series:
    """n quarters alternating high, low, high, low, ... - non-zero volatility
    so Sharpe ratios are well-defined (a constant series has zero std, which
    makes Sharpe NaN and comparisons meaningless)."""
    values = [high if i % 2 == 0 else low for i in range(n)]
    return pd.Series(values, index=quarterly_dates(n))


# ---------------------------------------------------------------------------
# rolling_window_metrics
# ---------------------------------------------------------------------------


def test_rolling_windows_count_and_index():
    # 24 monthly returns, 1-year windows -> windows end at months 12..24,
    # i.e. 13 rows, each labelled by its window's last date.
    returns = pd.Series(0.01, index=pd.date_range("2020-01-31", periods=24, freq="ME"))
    table = rolling_window_metrics(returns, window_years=1, periods_per_year=12)
    assert len(table) == 13
    assert table.index[0] == returns.index[11]
    assert table.index[-1] == returns.index[-1]


def test_rolling_window_metrics_values():
    # Constant +1%/month: every 12-month window compounds to 1.01^12, never
    # draws down, and has zero volatility (so Sharpe is NaN by design).
    returns = pd.Series(0.01, index=pd.date_range("2020-01-31", periods=24, freq="ME"))
    table = rolling_window_metrics(returns, window_years=1, periods_per_year=12)
    # cagr() measures growth between the first and last EQUITY points, and
    # the first equity point already includes the first return - so a
    # 12-return window measures 11 compounded returns over the 11 months of
    # elapsed calendar time between its first and last dates.
    expected_growth = 1.01**11
    days = (table.index[0] - returns.index[0]).days
    expected_cagr = expected_growth ** (365.25 / days) - 1
    assert np.isclose(table["CAGR"].iloc[0], expected_cagr)
    assert (table["Max Drawdown"] == 0).all()
    # Constant returns have zero volatility, up to floating-point dust from
    # the std computation.
    assert np.allclose(table["Annualized Volatility"], 0, atol=1e-12)


def test_rolling_window_too_short_raises():
    returns = pd.Series(0.01, index=pd.date_range("2020-01-31", periods=10, freq="ME"))
    with pytest.raises(ValueError):
        rolling_window_metrics(returns, window_years=1, periods_per_year=12)


# ---------------------------------------------------------------------------
# walk_forward_blend
# ---------------------------------------------------------------------------


def test_walk_forward_picks_dominant_sleeve():
    # Momentum: alternates +4%/0% (positive mean, Sharpe 2.0 annualized).
    # Value: alternates +1%/-1% (zero mean). Every candidate weight's
    # training Sharpe falls monotonically as momentum weight falls, so the
    # walk-forward must pick 100% momentum at every step - and its
    # out-of-sample returns must therefore BE momentum's returns.
    n = 32  # 8 years of quarters
    momentum = alternating_series(n, 0.04, 0.0)
    value = alternating_series(n, 0.01, -0.01)

    result = walk_forward_blend(momentum, value, train_years=5, test_years=1)

    assert (result.chosen_weights == 1.0).all()
    # 5 training years = 20 quarters, so 12 out-of-sample quarters remain.
    assert len(result.oos_returns) == n - 20
    pd.testing.assert_series_equal(result.oos_returns, momentum.iloc[20:])


def test_walk_forward_picks_other_sleeve_when_dominance_flips():
    # Same setup mirrored: value dominates, so every step must choose 0%.
    n = 32
    momentum = alternating_series(n, 0.01, -0.01)
    value = alternating_series(n, 0.04, 0.0)

    result = walk_forward_blend(momentum, value, train_years=5, test_years=1)

    assert (result.chosen_weights == 0.0).all()
    pd.testing.assert_series_equal(result.oos_returns, value.iloc[20:])


def test_walk_forward_comparison_table_consistency():
    # When every chosen weight is 1.0, the walk-forward column of the
    # comparison table must match the fixed-100%-momentum column exactly -
    # they are the same series over the same window.
    n = 32
    momentum = alternating_series(n, 0.04, 0.0)
    value = alternating_series(n, 0.01, -0.01)

    result = walk_forward_blend(momentum, value, train_years=5, test_years=1)

    pd.testing.assert_series_equal(
        result.comparison["Walk-Forward"],
        result.comparison["Fixed 100% Mom / 0% Val"],
        check_names=False,
    )


def test_walk_forward_keeps_partial_final_test_block():
    # 23 common quarters with 5 training years: test blocks start at
    # quarters 20 (full year) and... there is no quarter 24, so the second
    # block would start beyond the data - the tail after quarter 20 is just
    # one 3-quarter partial block, which must be kept, not dropped.
    n = 23
    momentum = alternating_series(n, 0.04, 0.0)
    value = alternating_series(n, 0.01, -0.01)

    result = walk_forward_blend(momentum, value, train_years=5, test_years=1)

    assert len(result.oos_returns) == 3
    assert result.oos_returns.index[-1] == momentum.index[-1]


def test_walk_forward_too_few_quarters_raises():
    n = 20  # exactly the training window, nothing left to test
    momentum = alternating_series(n, 0.04, 0.0)
    value = alternating_series(n, 0.01, -0.01)
    with pytest.raises(ValueError):
        walk_forward_blend(momentum, value, train_years=5, test_years=1)


def test_walk_forward_uses_only_common_dates():
    # Value missing the first 4 quarters: the common window starts where
    # both exist, so training/test indexing must shift accordingly rather
    # than silently aligning misdated returns.
    n = 32
    momentum = alternating_series(n, 0.04, 0.0)
    value = alternating_series(n, 0.01, -0.01).iloc[4:]

    result = walk_forward_blend(momentum, value, train_years=5, test_years=1)

    # 28 common quarters - 20 training = 8 out-of-sample.
    assert len(result.oos_returns) == 8
    pd.testing.assert_series_equal(result.oos_returns, momentum.iloc[24:])
