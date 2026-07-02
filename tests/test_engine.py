"""
Unit tests for the backtest engine's per-period return calculation.

run_backtest() itself is an integration point (real data fetching, real
constituents lookup) that isn't easily unit-tested with synthetic inputs.
compute_holding_period_return() is the pure piece of engine logic that
decides which held-stock returns get averaged into a month's portfolio
return, so it's tested in isolation here.
"""

import pandas as pd
import pytest

from src.backtest.engine import compute_holding_period_return


def test_normal_returns_averaged_equally():
    formation = pd.Series({"A": 100.0, "B": 50.0})
    next_ = pd.Series({"A": 110.0, "B": 55.0})  # both +10%
    gross_return, missing, extreme = compute_holding_period_return(formation, next_)
    assert gross_return == pytest.approx(0.10)
    assert missing == 0
    assert extreme == 0


def test_missing_forward_price_excluded_and_counted():
    formation = pd.Series({"A": 100.0, "B": 50.0})
    next_ = pd.Series({"A": 110.0, "B": float("nan")})  # B delisted mid-holding
    gross_return, missing, extreme = compute_holding_period_return(formation, next_)
    assert gross_return == pytest.approx(0.10)  # only A counts
    assert missing == 1
    assert extreme == 0


def test_extreme_gain_excluded_and_counted():
    """Regression test: a real vendor data glitch (ticker CBE, recycled after
    a 2012 delisting) implied single-month gains in the tens of thousands of
    percent. A single stock like this must not be allowed to dominate the
    equal-weight monthly average."""
    formation = pd.Series({"A": 100.0, "B": 0.01})
    next_ = pd.Series({"A": 105.0, "B": 100.0})  # B implies +9,999% - a glitch, not a return
    gross_return, missing, extreme = compute_holding_period_return(formation, next_)
    assert gross_return == pytest.approx(0.05)  # only A counts
    assert missing == 0
    assert extreme == 1


def test_large_genuine_gain_within_bound_is_not_excluded():
    """A monthly gain below the extreme-return bound is real momentum
    behaviour, not a data error, and must still be averaged in - otherwise
    the strategy's genuine big winners get silently stripped out."""
    formation = pd.Series({"A": 100.0, "B": 100.0})
    next_ = pd.Series({"A": 105.0, "B": 250.0})  # B is +150%, well below the 300% bound
    gross_return, missing, extreme = compute_holding_period_return(formation, next_)
    assert gross_return == pytest.approx((0.05 + 1.50) / 2)
    assert extreme == 0


def test_large_loss_is_not_excluded():
    """Only the upside is guarded - a near-total loss can be a genuine
    collapse (fraud, bankruptcy) and must not be silently smoothed away."""
    formation = pd.Series({"A": 100.0, "B": 100.0})
    next_ = pd.Series({"A": 105.0, "B": 1.0})  # B is -99%
    gross_return, missing, extreme = compute_holding_period_return(formation, next_)
    assert gross_return == pytest.approx((0.05 + (-0.99)) / 2)
    assert extreme == 0


def test_all_returns_extreme_yields_zero_return():
    formation = pd.Series({"A": 0.01})
    next_ = pd.Series({"A": 100.0})
    gross_return, missing, extreme = compute_holding_period_return(formation, next_)
    assert gross_return == 0.0
    assert extreme == 1
