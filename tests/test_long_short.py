"""
Unit tests for the long-short momentum pieces (Phase 4):
select_bottom_n (src/strategy/momentum.py) and the per-period return
arithmetic in src/backtest/long_short_engine.py.

Like the rest of the suite, everything here is offline and hand-computable:
every expected value below is worked out step by step in comments, so the
arithmetic can be checked with a calculator, not just trusted.
"""

import pandas as pd
import pytest

from src.backtest.engine import compute_holding_period_return
from src.backtest.long_short_engine import (
    compute_long_short_period_return,
    monthly_borrow_fee,
)
from src.strategy.momentum import select_bottom_n, select_top_n


# ---------------------------------------------------------------------------
# Bottom-N selection (the short book's stock picker)
# ---------------------------------------------------------------------------


def test_select_bottom_n_picks_lowest_scores():
    scores = pd.Series({"A": 0.50, "B": -0.30, "C": 0.10, "D": -0.05})
    # Lowest two momentum scores are B (-0.30) then D (-0.05).
    assert select_bottom_n(scores, 2) == ["B", "D"]


def test_select_bottom_n_handles_fewer_than_n_available():
    scores = pd.Series({"A": 0.2, "B": -0.1})
    assert set(select_bottom_n(scores, 5)) == {"A", "B"}


def test_top_and_bottom_books_are_disjoint_on_a_large_universe():
    # 10 tickers, pick 3 from each end: the books must never share a name
    # as long as the universe has at least top_n + bottom_n members.
    scores = pd.Series({f"T{i}": i * 0.01 for i in range(10)})
    long_book = select_top_n(scores, 3)
    short_book = select_bottom_n(scores, 3)
    assert set(long_book) == {"T9", "T8", "T7"}
    assert set(short_book) == {"T0", "T1", "T2"}
    assert set(long_book) & set(short_book) == set()


# ---------------------------------------------------------------------------
# Borrow fee
# ---------------------------------------------------------------------------


def test_monthly_borrow_fee_dollar_neutral():
    # 30bps/year on a full-size short book: 30 / 12 / 10000 = 2.5bps/month.
    assert monthly_borrow_fee(1.0, 30.0) == pytest.approx(0.00025)


def test_monthly_borrow_fee_scales_with_short_exposure():
    # A 130/30 fund's short book is only 0.3x capital, so at 100bps/year:
    # 0.3 * 100 / 12 / 10000 = 2.5bps/month.
    assert monthly_borrow_fee(0.3, 100.0) == pytest.approx(0.00025)


def test_monthly_borrow_fee_zero_when_no_short_book():
    assert monthly_borrow_fee(0.0, 30.0) == 0.0


def test_borrow_fee_charged_even_with_no_trading_and_flat_prices():
    # Nothing moved and nothing traded - the ONLY drag left is the borrow
    # fee, because borrowed stock costs money to hold, not just to trade.
    gross, net = compute_long_short_period_return(
        long_return=0.0,
        short_underlying_return=0.0,
        long_turnover=0.0,
        short_turnover=0.0,
        long_exposure=1.0,
        short_exposure=1.0,
        one_way_cost_bps=10.0,
        borrow_fee_annual_bps=30.0,
    )
    assert gross == 0.0
    assert net == pytest.approx(-0.00025)


# ---------------------------------------------------------------------------
# The long-short return arithmetic, hand-worked
# ---------------------------------------------------------------------------


def test_dollar_neutral_hand_worked_example():
    """1.0/1.0 dollar-neutral month, every number checkable by hand.

    Longs gained 4%; shorted stocks FELL 2% (so the short book PROFITS 2%).
      gross = 1.0*0.04 - 1.0*(-0.02)                    = 0.06
      long book cost  = 2 * 0.20 * 10bps = 4bps  -> long net  = 0.0396
      short book cost = 2 * 0.50 * 10bps = 10bps -> short net = 0.02 - 0.001 = 0.019
      borrow fee = 1.0 * 30/12/10000               = 0.00025
      net = 0.0396 + 0.019 - 0.00025                = 0.05835
    """
    gross, net = compute_long_short_period_return(
        long_return=0.04,
        short_underlying_return=-0.02,
        long_turnover=0.20,
        short_turnover=0.50,
        long_exposure=1.0,
        short_exposure=1.0,
        one_way_cost_bps=10.0,
        borrow_fee_annual_bps=30.0,
    )
    assert gross == pytest.approx(0.06)
    assert net == pytest.approx(0.05835)


def test_130_30_hand_worked_example():
    """1.3/0.3 month where the short book LOSES (shorted stocks rose 5%).

      gross = 1.3*0.02 - 0.3*0.05 = 0.026 - 0.015     = 0.011
      long book:  0.02 - 2*0.25*10bps = 0.0195; * 1.3 = 0.02535
      short book: -0.05 - 2*1.00*10bps = -0.052; * 0.3 = -0.0156
      borrow fee = 0.3 * 30/12/10000                  = 0.000075
      net = 0.02535 - 0.0156 - 0.000075               = 0.009675
    """
    gross, net = compute_long_short_period_return(
        long_return=0.02,
        short_underlying_return=0.05,
        long_turnover=0.25,
        short_turnover=1.00,
        long_exposure=1.3,
        short_exposure=0.3,
        one_way_cost_bps=10.0,
        borrow_fee_annual_bps=30.0,
    )
    assert gross == pytest.approx(0.011)
    assert net == pytest.approx(0.009675)


def test_dollar_neutral_gross_is_zero_when_both_baskets_move_together():
    # The whole point of dollar-neutral: a market-wide move that lifts both
    # baskets equally cancels out, leaving no gross return.
    gross, _ = compute_long_short_period_return(
        long_return=0.03,
        short_underlying_return=0.03,
        long_turnover=0.0,
        short_turnover=0.0,
        long_exposure=1.0,
        short_exposure=1.0,
        one_way_cost_bps=0.0,
        borrow_fee_annual_bps=0.0,
    )
    assert gross == pytest.approx(0.0)


def test_gross_return_excludes_all_costs():
    # Gross must be pure price action: cranking costs and borrow fees way
    # up changes net but must leave gross untouched.
    gross_cheap, net_cheap = compute_long_short_period_return(
        0.04, -0.02, 0.5, 0.5, 1.0, 1.0, one_way_cost_bps=0.0, borrow_fee_annual_bps=0.0
    )
    gross_pricey, net_pricey = compute_long_short_period_return(
        0.04, -0.02, 0.5, 0.5, 1.0, 1.0, one_way_cost_bps=50.0, borrow_fee_annual_bps=200.0
    )
    assert gross_cheap == gross_pricey
    assert net_pricey < net_cheap


# ---------------------------------------------------------------------------
# Per-book turnover costing
# ---------------------------------------------------------------------------


def test_each_book_pays_costs_on_its_own_turnover():
    """Adding turnover to ONE book must cost exactly that book's round-trip
    charge, scaled by that book's exposure - the other book's cost is
    unaffected.
    """
    base_kwargs = dict(
        long_return=0.0,
        short_underlying_return=0.0,
        long_exposure=1.3,
        short_exposure=0.3,
        one_way_cost_bps=10.0,
        borrow_fee_annual_bps=0.0,
    )
    _, net_no_trading = compute_long_short_period_return(
        long_turnover=0.0, short_turnover=0.0, **base_kwargs
    )
    _, net_long_trades = compute_long_short_period_return(
        long_turnover=0.5, short_turnover=0.0, **base_kwargs
    )
    _, net_short_trades = compute_long_short_period_return(
        long_turnover=0.0, short_turnover=0.5, **base_kwargs
    )
    # Long book: 1.3 * (2 * 0.5 * 10bps) = 1.3 * 0.001 = 0.0013 of capital.
    assert net_no_trading - net_long_trades == pytest.approx(0.0013)
    # Short book: 0.3 * (2 * 0.5 * 10bps) = 0.3 * 0.001 = 0.0003 of capital.
    assert net_no_trading - net_short_trades == pytest.approx(0.0003)


# ---------------------------------------------------------------------------
# Extreme-return (vendor glitch) handling on the short book
# ---------------------------------------------------------------------------


def test_extreme_underlying_gain_excluded_from_short_basket_and_counted():
    """A shorted stock whose price 'quintuples' in a month trips the same
    >300% vendor-glitch guard as the long book (the engine reuses
    compute_holding_period_return for both books). The suspect stock is
    excluded from the basket average and COUNTED - the count is what lets
    notebook 04's Limitations discuss that, were such a move ever real, it
    would be a catastrophic short loss this guard would be hiding.
    """
    formation = pd.Series({"A": 10.0, "B": 20.0, "C": 50.0})
    # A: +400% (beyond the 300% bound -> excluded), B: +10%, C: -10%.
    following = pd.Series({"A": 50.0, "B": 22.0, "C": 45.0})

    short_underlying, missing_count, extreme_count = compute_holding_period_return(
        formation, following
    )

    assert extreme_count == 1
    assert missing_count == 0
    # Basket average over the two remaining names: (0.10 + -0.10) / 2 = 0.
    assert short_underlying == pytest.approx(0.0)

    # Fed into the short book at full exposure, zero costs: net is simply
    # -1.0 * 0.0 = 0. Had the +400% been kept, the short book would have
    # shown roughly a -133% month ((4.0 + 0.1 - 0.1)/3 underlying, negated).
    gross, net = compute_long_short_period_return(
        long_return=0.0,
        short_underlying_return=short_underlying,
        long_turnover=0.0,
        short_turnover=0.0,
        long_exposure=1.0,
        short_exposure=1.0,
        one_way_cost_bps=0.0,
        borrow_fee_annual_bps=0.0,
    )
    assert gross == pytest.approx(0.0)
    assert net == pytest.approx(0.0)


def test_underlying_collapse_stays_in_short_basket_as_profit():
    """The glitch guard caps only implausible GAINS in the underlying. A
    near-total collapse (-90%) is left in - for the short book that's a
    genuine, large PROFIT, and it must show up, not be smoothed away.
    """
    formation = pd.Series({"A": 100.0, "B": 50.0})
    following = pd.Series({"A": 10.0, "B": 50.0})  # A: -90%, B: flat

    short_underlying, _, extreme_count = compute_holding_period_return(formation, following)

    assert extreme_count == 0
    # Basket: (-0.90 + 0.0) / 2 = -0.45; short profits +0.45 gross.
    assert short_underlying == pytest.approx(-0.45)

    gross, _ = compute_long_short_period_return(
        long_return=0.0,
        short_underlying_return=short_underlying,
        long_turnover=0.0,
        short_turnover=0.0,
        long_exposure=1.0,
        short_exposure=1.0,
        one_way_cost_bps=0.0,
        borrow_fee_annual_bps=0.0,
    )
    assert gross == pytest.approx(0.45)


def test_missing_forward_price_counted_separately_per_basket():
    """A shorted stock with no forward price (e.g. a mid-month delisting)
    is dropped from the basket average and counted, exactly like the long
    book - the engine keeps the two books' counts separate because the
    bias runs OPPOSITE ways (optimistic for longs, pessimistic for shorts;
    see notebook 04's Limitations).
    """
    formation = pd.Series({"A": 10.0, "B": 20.0})
    following = pd.Series({"A": float("nan"), "B": 19.0})  # A delists, B: -5%

    short_underlying, missing_count, _ = compute_holding_period_return(formation, following)

    assert missing_count == 1
    assert short_underlying == pytest.approx(-0.05)
