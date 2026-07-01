"""
Point-in-time S&P 500 constituents.

Using TODAY'S S&P 500 list for the whole backtest would introduce survivorship
bias: any company that was in the index and later got removed (bankruptcy,
acquisition, demotion) would be invisible to the strategy, silently inflating
returns. Instead this module tracks index MEMBERSHIP AS IT ACTUALLY WAS on
each historical date, using a free, community-maintained dataset:

    https://github.com/fja05680/sp500

This is NOT an official index vendor feed - it's compiled from Wikipedia and
the book "Trading Evolved" (Andreas Clenow), updated by the maintainer
roughly every couple of months. That means:
  - Some historical add/remove dates may be slightly imprecise.
  - Membership for the very latest weeks/months may lag true real-time
    changes until the maintainer's next update.
This is a real, documented limitation - "point-in-time" here means
"best-effort point-in-time from a free community source", not "guaranteed
survivorship-bias-free". It's still a meaningful improvement over using
today's constituent list retroactively, which has zero protection against
survivorship bias.

The CSV itself has one row per date-of-change, with a single quoted,
comma-separated `tickers` column (not JSON), e.g.:

    date,tickers
    1996-01-02,"AAL,AAMRQ,AAPL,ABI,..."
"""

import io
from pathlib import Path

import pandas as pd
import requests

from src.config import CONSTITUENTS_URL, DEFAULT_CONFIG
from src.data_layer.cache_utils import read_cache, write_cache

CACHE_FILENAME = "sp500_constituents.parquet"


def _download_constituents_csv(url: str = CONSTITUENTS_URL) -> pd.DataFrame:
    """Download and parse the raw point-in-time constituents CSV.

    Returns a DataFrame with a DatetimeIndex named `date` (sorted ascending)
    and a single column `tickers`, where each value is a list[str].

    Uses `requests` rather than `pandas.read_csv(url)` directly - the latter
    goes through urllib, which was found to truncate this ~5MB file when
    fetched through this environment's proxy (IncompleteRead), while
    `requests` handles it correctly.
    """
    response = requests.get(url, timeout=60)
    response.raise_for_status()
    raw = pd.read_csv(io.StringIO(response.text))
    raw["date"] = pd.to_datetime(raw["date"])
    # The `tickers` column is a single quoted comma-separated string, e.g.
    # "AAL,AAMRQ,AAPL" - split it into an actual list of ticker strings.
    raw["tickers"] = raw["tickers"].str.split(",")
    raw = raw.set_index("date").sort_index()
    return raw[["tickers"]]


def load_constituents_table(
    cache_dir: Path = DEFAULT_CONFIG.cache_dir,
    url: str = CONSTITUENTS_URL,
    force_refresh: bool = False,
) -> pd.DataFrame:
    """Load the point-in-time constituents table, using the local cache if present.

    The parquet cache stores `tickers` as a native list column, so no
    re-parsing of the comma-separated string is needed on cache hits.
    """
    cache_path = cache_dir / CACHE_FILENAME
    if not force_refresh:
        cached = read_cache(cache_path)
        if cached is not None:
            return cached

    table = _download_constituents_csv(url)
    write_cache(table, cache_path)
    return table


def normalize_ticker(ticker: str) -> str:
    """Convert a dataset ticker to the symbol yfinance/Yahoo Finance expects.

    Share classes are written with a dot in this dataset (e.g. "BF.B",
    "BRK.B") but yfinance/Yahoo Finance use a hyphen ("BF-B", "BRK-B").
    """
    return ticker.replace(".", "-")


def get_membership(date, table: pd.DataFrame | None = None) -> list[str]:
    """Return the S&P 500 tickers that were constituents as of `date`.

    This is an "as-of" lookup: it finds the most recent row in the
    constituents table with a date <= the requested date, and returns that
    row's ticker list. This is what enforces the no-look-ahead invariant for
    the universe: a backtest rebalancing on date `t` can never see index
    changes that happened after `t`, because `table` only ever contains
    changes recorded up to whenever it was downloaded, and this function
    only ever looks at rows dated <= `date`.

    Raises ValueError if `date` precedes the earliest date in the table,
    since there's no valid point-in-time membership to return.
    """
    if table is None:
        table = load_constituents_table()

    date = pd.Timestamp(date)
    if date < table.index.min():
        raise ValueError(
            f"No point-in-time S&P 500 membership data available before "
            f"{table.index.min().date()}; requested date {date.date()} is "
            f"earlier than that."
        )

    # `asof` finds the last index label <= date, which is exactly the
    # "most recent known membership as of this date" lookup we need.
    as_of_date = table.index.asof(date)
    tickers = table.loc[as_of_date, "tickers"]
    return [normalize_ticker(t) for t in tickers]
