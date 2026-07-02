"""
Unit tests for the transaction cost model.
"""

import pytest

from src.costs.transaction_costs import apply_transaction_costs, compute_turnover


def test_turnover_full_overlap_is_zero():
    assert compute_turnover(["A", "B", "C"], ["A", "B", "C"], top_n=3) == pytest.approx(0.0)


def test_turnover_no_overlap_is_one():
    assert compute_turnover(["A", "B", "C"], ["D", "E", "F"], top_n=3) == pytest.approx(1.0)


def test_turnover_partial_overlap():
    # 2 of 4 names carried over -> turnover = 1 - 2/4 = 0.5
    assert compute_turnover(["A", "B", "C", "D"], ["A", "B", "E", "F"], top_n=4) == pytest.approx(0.5)


def test_turnover_empty_old_portfolio_is_full_turnover():
    assert compute_turnover([], ["A", "B", "C"], top_n=3) == pytest.approx(1.0)


def test_apply_transaction_costs_exact_bps_subtraction():
    # Full replacement (turnover=1.0) means selling 100% AND buying 100% of
    # the portfolio - two one-way trades - so at 10bps one-way the charge is
    # 2 * 1.0 * 10/10000 = 0.002, not 0.001.
    net = apply_transaction_costs(gross_return=0.05, turnover=1.0, one_way_cost_bps=10.0)
    assert net == pytest.approx(0.05 - 0.002)


def test_apply_transaction_costs_half_turnover():
    # Replacing half the names: sell 50% + buy 50% -> 2 * 0.5 * 10bps = 10bps.
    net = apply_transaction_costs(gross_return=0.02, turnover=0.5, one_way_cost_bps=10.0)
    assert net == pytest.approx(0.02 - 0.001)


def test_apply_transaction_costs_zero_turnover_no_cost():
    net = apply_transaction_costs(gross_return=0.05, turnover=0.0, one_way_cost_bps=10.0)
    assert net == pytest.approx(0.05)
