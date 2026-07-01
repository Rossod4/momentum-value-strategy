"""
Price data ingestion and caching - the swappable data layer boundary.

Per the README's design principle, strategy and backtest code should never
talk to a data vendor directly. Everything upstream of this module only ever
calls `get_prices()`. Swapping yfinance for a different vendor later means
rewriting the internals of this file only - nothing else changes.

Prices are cached to disk (one parquet per ticker) so repeated backtest runs
don't re-hit yfinance, which is rate-limited and can be slow for hundreds of
tickers.
"""

import time
from pathlib import Path

import pandas as pd
import yfinance as yf

from src.config import DEFAULT_CONFIG

BATCH_SIZE = 75
BATCH_PAUSE_SECONDS = 2

# Requested start/end dates are calendar dates, but price data only exists
# for trading days. A requested `end` that falls on a weekend/holiday can
# never be matched exactly by the last cached trading day, so an exact
# equality check would make the cache "insufficient" forever. This
# tolerance treats the cache as covering a boundary if it comes within a
# week of it - comfortably more than any run of holidays/weekends.
CACHE_DATE_TOLERANCE_DAYS = 7


def _cache_path(ticker: str, cache_dir: Path) -> Path:
    return cache_dir / "prices" / f"{ticker}.parquet"


def _has_sufficient_cache(ticker: str, start: str, end: str, cache_dir: Path) -> pd.Series | None:
    """Return the cached Adj Close series for `ticker` if it already covers
    [start, end] (within CACHE_DATE_TOLERANCE_DAYS), else None."""
    path = _cache_path(ticker, cache_dir)
    if not path.exists():
        return None
    cached = pd.read_parquet(path)
    if cached.empty:
        return None
    tolerance = pd.Timedelta(days=CACHE_DATE_TOLERANCE_DAYS)
    covers_start = cached.index.min() <= pd.Timestamp(start) + tolerance
    covers_end = cached.index.max() >= pd.Timestamp(end) - tolerance
    if covers_start and covers_end:
        return cached["Adj Close"]
    return None


def _download_batch(tickers: list[str], start: str, end: str) -> pd.DataFrame:
    """Download OHLCV for a batch of tickers via yfinance.

    Returns a DataFrame with a MultiIndex (ticker, field) column structure,
    matching yfinance's `group_by="ticker"` output.
    """
    return yf.download(
        tickers,
        start=start,
        end=end,
        auto_adjust=False,  # keep raw + Adj Close separately, for transparency
        group_by="ticker",
        threads=True,
        progress=False,
    )


def get_prices(
    tickers: list[str],
    start: str,
    end: str,
    cache_dir: Path = DEFAULT_CONFIG.cache_dir,
    force_refresh: bool = False,
) -> tuple[pd.DataFrame, list[str]]:
    """Fetch adjusted close prices for `tickers` over [start, end].

    Returns (prices, failed_tickers):
      - prices: wide DataFrame (index=date, columns=tickers that succeeded)
        of Adjusted Close values. Columns are only the tickers we actually
        got usable data for - failures are dropped, not filled with NaN
        columns, so downstream code doesn't need to special-case them.
      - failed_tickers: tickers that had no usable data (delisted, renamed,
        typo'd, or simply not present on Yahoo Finance). This is returned
        explicitly rather than silently swallowed, so data coverage can be
        reported transparently (e.g. in the notebook).

    Caching: each ticker's full OHLCV history is cached separately. If the
    existing cache for a ticker already covers [start, end], it's reused;
    otherwise the ticker is re-downloaded for the full requested range and
    the cache is overwritten. This is simpler than incrementally patching
    cache gaps, at the cost of occasionally re-downloading data we already
    had - a deliberate simplicity/efficiency trade-off for this project's
    scale (hundreds of tickers, not thousands).
    """
    to_fetch = []
    cached_series = {}

    if not force_refresh:
        for ticker in tickers:
            series = _has_sufficient_cache(ticker, start, end, cache_dir)
            if series is not None:
                cached_series[ticker] = series
            else:
                to_fetch.append(ticker)
    else:
        to_fetch = list(tickers)

    downloaded_series = {}
    failed_tickers = []

    for i in range(0, len(to_fetch), BATCH_SIZE):
        batch = to_fetch[i : i + BATCH_SIZE]
        try:
            raw = _download_batch(batch, start, end)
        except Exception:
            # A whole-batch failure (e.g. transient network error) shouldn't
            # abort the entire fetch - record every ticker in this batch as
            # failed and move on to the next batch.
            failed_tickers.extend(batch)
            continue

        for ticker in batch:
            try:
                if len(batch) == 1:
                    ticker_df = raw
                else:
                    ticker_df = raw[ticker]
                ticker_df = ticker_df.dropna(how="all")
                if ticker_df.empty or "Adj Close" not in ticker_df:
                    failed_tickers.append(ticker)
                    continue
                write_path = _cache_path(ticker, cache_dir)
                write_path.parent.mkdir(parents=True, exist_ok=True)
                ticker_df.to_parquet(write_path)
                downloaded_series[ticker] = ticker_df["Adj Close"]
            except (KeyError, ValueError):
                failed_tickers.append(ticker)

        if i + BATCH_SIZE < len(to_fetch):
            time.sleep(BATCH_PAUSE_SECONDS)

    all_series = {**cached_series, **downloaded_series}
    if not all_series:
        return pd.DataFrame(), failed_tickers

    prices = pd.DataFrame(all_series)
    prices = prices.sort_index()
    return prices, failed_tickers
