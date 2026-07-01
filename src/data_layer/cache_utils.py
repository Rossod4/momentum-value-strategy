"""
Small shared helpers for reading/writing the local parquet cache.

All downloaded data (point-in-time constituents, per-ticker prices) is cached
to disk as parquet so repeated runs don't re-hit the network or yfinance's
rate limits. The cache directory is gitignored and fully regenerable -
deleting it just means the next run re-downloads everything.
"""

from pathlib import Path

import pandas as pd


def read_cache(path: Path) -> pd.DataFrame | None:
    """Return the cached DataFrame at `path`, or None if it doesn't exist."""
    if not path.exists():
        return None
    return pd.read_parquet(path)


def write_cache(df: pd.DataFrame, path: Path) -> None:
    """Write `df` to `path` as parquet, creating parent directories if needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path)
