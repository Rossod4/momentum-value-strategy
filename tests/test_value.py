"""
Unit tests for the value composite signal (src/strategy/value.py).

Uses synthetic PointInTimeFundamentals objects rather than real SEC data, so
these tests run offline and stay fast and deterministic.
"""

import math

import pandas as pd
import pytest

from src.data_layer.fundamentals import PointInTimeFundamentals
from src.strategy.value import (
    MIN_AVAILABLE_METRICS,
    _rank_lower_is_better,
    compute_composite_score,
    compute_value_ratios,
    select_top_n,
)


def make_fundamentals(
    shares_outstanding=1000.0,
    stockholders_equity=5000.0,
    ttm_eps=2.0,
    ttm_ebitda=1000.0,
    total_debt=500.0,
    cash=200.0,
    annual_eps_growth=0.10,
):
    return PointInTimeFundamentals(
        shares_outstanding=shares_outstanding,
        stockholders_equity=stockholders_equity,
        ttm_eps=ttm_eps,
        ttm_ebitda=ttm_ebitda,
        total_debt=total_debt,
        cash=cash,
        annual_eps_growth=annual_eps_growth,
    )


def test_compute_value_ratios_basic_arithmetic():
    fundamentals = {"A": make_fundamentals(shares_outstanding=100.0, stockholders_equity=1000.0, ttm_eps=5.0)}
    ratios = compute_value_ratios(fundamentals, {"A": 20.0})

    # market cap = 100 * 20 = 2000
    assert ratios.loc["A", "pb"] == pytest.approx(2000.0 / 1000.0)
    assert ratios.loc["A", "pe"] == pytest.approx(20.0 / 5.0)


def test_ticker_excluded_when_price_missing():
    fundamentals = {"A": make_fundamentals()}
    ratios = compute_value_ratios(fundamentals, {})
    assert "A" not in ratios.index


def test_ticker_excluded_when_shares_outstanding_missing():
    fundamentals = {"A": make_fundamentals(shares_outstanding=None)}
    ratios = compute_value_ratios(fundamentals, {"A": 20.0})
    assert "A" not in ratios.index


def test_ev_ebitda_nan_when_ebitda_missing():
    """A bank-like company with no EBITDA data (see fundamentals.py's note
    that EV/EBITDA is structurally unavailable for financials) should get
    NaN for that one ratio, not be excluded entirely."""
    fundamentals = {"A": make_fundamentals(ttm_ebitda=None)}
    ratios = compute_value_ratios(fundamentals, {"A": 20.0})
    assert "A" in ratios.index
    assert math.isnan(ratios.loc["A", "ev_ebitda"])
    assert not math.isnan(ratios.loc["A", "pb"])


def test_growth_adjusted_value_computed_when_both_positive():
    fundamentals = {"A": make_fundamentals(ttm_eps=5.0, annual_eps_growth=0.20)}
    ratios = compute_value_ratios(fundamentals, {"A": 20.0})
    pe = 20.0 / 5.0
    assert ratios.loc["A", "growth_adjusted_value"] == pytest.approx(pe / 0.20)


def test_growth_adjusted_value_least_attractive_when_growth_negative():
    """Shrinking earnings shouldn't score well on 'cheap relative to
    growth', even though a naive division of two negatives could produce a
    misleadingly attractive-looking positive ratio."""
    fundamentals = {"A": make_fundamentals(ttm_eps=5.0, annual_eps_growth=-0.10)}
    ratios = compute_value_ratios(fundamentals, {"A": 20.0})
    assert ratios.loc["A", "growth_adjusted_value"] == float("inf")


def test_growth_adjusted_value_least_attractive_when_pe_negative():
    fundamentals = {"A": make_fundamentals(ttm_eps=-5.0, annual_eps_growth=0.10)}
    ratios = compute_value_ratios(fundamentals, {"A": 20.0})
    assert ratios.loc["A", "growth_adjusted_value"] == float("inf")


def test_growth_adjusted_value_nan_when_growth_data_missing():
    fundamentals = {"A": make_fundamentals(annual_eps_growth=None)}
    ratios = compute_value_ratios(fundamentals, {"A": 20.0})
    assert math.isnan(ratios.loc["A", "growth_adjusted_value"])


def test_rank_lower_is_better_orders_positive_values_ascending():
    values = pd.Series({"cheap": 5.0, "mid": 10.0, "expensive": 20.0})
    ranks = _rank_lower_is_better(values)
    assert ranks["cheap"] < ranks["mid"] < ranks["expensive"]


def test_rank_lower_is_better_treats_negative_as_worst():
    """A negative ratio (e.g. a loss-making company's P/E) must rank worse
    than every positive ratio, not sort in based on its raw magnitude."""
    values = pd.Series({"very_negative": -100.0, "slightly_negative": -1.0, "cheap": 5.0, "expensive": 50.0})
    ranks = _rank_lower_is_better(values)
    assert ranks["cheap"] < ranks["expensive"] < ranks["very_negative"]
    assert ranks["cheap"] < ranks["expensive"] < ranks["slightly_negative"]
    # Both negative values are tied for worst, regardless of magnitude.
    assert ranks["very_negative"] == ranks["slightly_negative"]


def test_rank_lower_is_better_preserves_nan_as_missing():
    values = pd.Series({"a": 5.0, "b": float("nan"), "c": 10.0})
    ranks = _rank_lower_is_better(values)
    assert math.isnan(ranks["b"])


def test_composite_score_is_mean_of_available_ranks():
    ratios = pd.DataFrame(
        {
            "pb": {"A": 1.0, "B": 1.0},
            "pe": {"A": 1.0, "B": 2.0},
            "ev_ebitda": {"A": 1.0, "B": 3.0},
            "growth_adjusted_value": {"A": 1.0, "B": 4.0},
        }
    )
    scores = compute_composite_score(ratios)
    # A is cheapest on every metric, so should have the lowest (best) score.
    assert scores["A"] < scores["B"]


def test_composite_score_nan_below_min_available_metrics():
    assert MIN_AVAILABLE_METRICS == 2
    ratios = pd.DataFrame(
        {
            "pb": {"A": 1.0},
            "pe": {"A": float("nan")},
            "ev_ebitda": {"A": float("nan")},
            "growth_adjusted_value": {"A": float("nan")},
        }
    )
    scores = compute_composite_score(ratios)
    assert math.isnan(scores["A"])


def test_composite_score_valid_at_min_available_metrics():
    ratios = pd.DataFrame(
        {
            "pb": {"A": 1.0},
            "pe": {"A": 2.0},
            "ev_ebitda": {"A": float("nan")},
            "growth_adjusted_value": {"A": float("nan")},
        }
    )
    scores = compute_composite_score(ratios)
    assert not math.isnan(scores["A"])


def test_select_top_n_picks_lowest_scores():
    scores = pd.Series({"A": 0.9, "B": 0.1, "C": 0.5})
    assert select_top_n(scores, 2) == ["B", "C"]


def test_select_top_n_drops_nan_scores():
    scores = pd.Series({"A": 0.9, "B": float("nan"), "C": 0.1})
    result = select_top_n(scores, 5)
    assert "B" not in result
    assert set(result) == {"A", "C"}


def test_select_top_n_handles_fewer_than_n_available():
    scores = pd.Series({"A": 0.1, "B": 0.2})
    result = select_top_n(scores, 5)
    assert set(result) == {"A", "B"}
