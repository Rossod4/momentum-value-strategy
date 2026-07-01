"""
Unit tests for point-in-time S&P 500 constituents logic.

Uses small synthetic in-memory tables rather than the real downloaded
dataset, so these tests run offline and stay fast and deterministic.
"""

import pandas as pd
import pytest

from src.data_layer.constituents import get_membership, normalize_ticker


def make_table(rows: dict) -> pd.DataFrame:
    """rows: {date_str: [tickers]}"""
    dates = pd.to_datetime(list(rows.keys()))
    table = pd.DataFrame({"tickers": list(rows.values())}, index=dates).sort_index()
    return table


def test_membership_differs_across_dates():
    table = make_table(
        {
            "2012-01-01": ["A", "B", "C"],
            "2022-01-01": ["A", "D", "E"],
        }
    )
    members_2012 = get_membership("2012-06-15", table)
    members_2022 = get_membership("2022-06-15", table)
    assert set(members_2012) == {"A", "B", "C"}
    assert set(members_2022) == {"A", "D", "E"}
    assert members_2012 != members_2022


def test_as_of_lookup_uses_most_recent_prior_row():
    table = make_table(
        {
            "2020-01-01": ["A", "B"],
            "2020-06-01": ["A", "C"],
            "2021-01-01": ["A", "D"],
        }
    )
    # A date between two change rows should use the most recent row <= it.
    assert set(get_membership("2020-08-15", table)) == {"A", "C"}


def test_no_lookahead_future_row_not_used_for_earlier_date():
    """The core no-look-ahead invariant: a rebalance on date t must never
    see a membership change recorded after t."""
    table = make_table(
        {
            "2020-01-01": ["A", "B"],
            "2025-01-01": ["A", "ZZZZ_FUTURE_ONLY"],  # a change far in the future
        }
    )
    members = get_membership("2020-06-01", table)
    assert "ZZZZ_FUTURE_ONLY" not in members
    assert set(members) == {"A", "B"}


def test_date_before_earliest_raises():
    table = make_table({"2000-01-01": ["A", "B"]})
    with pytest.raises(ValueError):
        get_membership("1999-01-01", table)


def test_normalize_ticker_converts_dot_to_hyphen():
    assert normalize_ticker("BF.B") == "BF-B"
    assert normalize_ticker("BRK.B") == "BRK-B"
    assert normalize_ticker("AAPL") == "AAPL"


def test_get_membership_applies_normalization():
    table = make_table({"2020-01-01": ["BF.B", "AAPL"]})
    members = get_membership("2020-06-01", table)
    assert "BF-B" in members
    assert "BF.B" not in members
