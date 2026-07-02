"""
Unit tests for the price data layer's cache/windowing logic
(src/data_layer/prices.py).

Actual yfinance downloads are deliberately NOT exercised - like the rest of
the suite, these tests run offline. The helper below writes a synthetic
per-ticker parquet in the exact shape prices.py caches (a date-indexed frame
with an "Adj Close" column), so get_prices() is satisfied entirely from the
cache and never touches the network.
"""

import json

import pandas as pd
import pytest

import src.data_layer.prices as prices_module
from src.data_layer.prices import get_prices


def _write_fake_cache(cache_dir, ticker: str, start: str, end: str) -> pd.DataFrame:
    """Create a cached price file covering [start, end] for `ticker`, in the
    same layout prices.py writes (data/cache/prices/<ticker>.parquet with an
    "Adj Close" column indexed by date)."""
    dates = pd.date_range(start, end, freq="B")  # business days
    df = pd.DataFrame(
        {"Adj Close": [float(i) for i in range(1, len(dates) + 1)]}, index=dates
    )
    path = cache_dir / "prices" / f"{ticker}.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path)
    return df


def _write_fake_meta(cache_dir, ticker: str, requested_start: str, requested_end: str) -> None:
    """Sidecar metadata in the same format prices.py writes after a download."""
    meta_path = cache_dir / "prices" / f"{ticker}.meta.json"
    meta_path.write_text(
        json.dumps({"requested_start": requested_start, "requested_end": requested_end})
    )


@pytest.fixture
def no_network(monkeypatch):
    """Make any attempted yfinance download fail the test loudly - used to
    prove a code path is served entirely from cache."""

    def _fail(*args, **kwargs):
        raise AssertionError("network download attempted - cache should have been used")

    monkeypatch.setattr(prices_module, "_download_batch", _fail)


def test_get_prices_trims_wider_cache_to_requested_window(tmp_path):
    """Regression test: a cached file can cover a much wider range than a
    call asks for (e.g. SPY cached from the momentum warmup start). The
    returned frame must be trimmed to the requested window - before this
    trim existed, the SPY benchmark quietly included ~13 months the
    strategies weren't running for, misaligning every benchmark comparison."""
    _write_fake_cache(tmp_path, "TEST", "2010-12-01", "2013-06-30")

    prices, failed = get_prices(["TEST"], "2012-01-01", "2012-12-31", cache_dir=tmp_path)

    assert failed == []
    assert prices.index.min() >= pd.Timestamp("2012-01-01")
    assert prices.index.max() <= pd.Timestamp("2012-12-31")


def test_get_prices_values_unchanged_inside_window(tmp_path):
    """Trimming must only cut rows outside the window, never alter the
    values inside it."""
    full = _write_fake_cache(tmp_path, "TEST", "2010-12-01", "2013-06-30")

    prices, _ = get_prices(["TEST"], "2012-01-01", "2012-12-31", cache_dir=tmp_path)

    expected = full.loc["2012-01-01":"2012-12-31", "Adj Close"]
    # check_freq=False: the parquet round-trip drops the index's business-day
    # `freq` attribute (metadata only) - the dates and values still match.
    pd.testing.assert_series_equal(prices["TEST"], expected, check_names=False, check_freq=False)


def test_delisted_ticker_served_from_cache_via_metadata(tmp_path, no_network):
    """Regression test: a ticker delisted mid-window has data that stops
    years before the requested end date. With sidecar metadata recording
    that the cache was FETCHED for the full window, it must be served from
    cache - not re-downloaded on every run (which was both slow and broke
    bit-for-bit reproducibility, since Yahoo's adjusted prices drift
    slightly between downloads)."""
    # Data stops in 2015 (delisting), but the cache was fetched for 2012-2026.
    _write_fake_cache(tmp_path, "GONE", "2012-01-03", "2015-06-30")
    _write_fake_meta(tmp_path, "GONE", "2012-01-01", "2026-06-30")

    prices, failed = get_prices(["GONE"], "2012-01-01", "2026-06-30", cache_dir=tmp_path)

    assert failed == []  # no_network fixture proves no download was attempted
    assert "GONE" in prices.columns
    assert prices.index.max() == pd.Timestamp("2015-06-30")


def test_stale_cache_without_metadata_triggers_refetch(tmp_path, monkeypatch):
    """The data-based fallback: an old cache file with NO metadata whose data
    stops early must still be treated as insufficient (it might be stale
    rather than delisted), so a re-download is attempted once - after which
    the metadata written by that download prevents any further re-fetching."""
    _write_fake_cache(tmp_path, "GONE", "2012-01-03", "2015-06-30")  # no meta file

    attempted = []

    def _record_and_fail(batch, start, end):
        attempted.extend(batch)
        raise ConnectionError("simulated network failure")

    monkeypatch.setattr(prices_module, "_download_batch", _record_and_fail)
    prices, failed = get_prices(["GONE"], "2012-01-01", "2026-06-30", cache_dir=tmp_path)

    assert attempted == ["GONE"]  # the fallback correctly tried to refresh
    assert failed == ["GONE"]
