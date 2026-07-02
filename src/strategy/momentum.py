"""
12-1 month momentum signal.

Classic academic momentum specification (Jegadeesh & Titman-style): rank
stocks by their return from `lookback_months` ago to `skip_months` ago,
deliberately skipping the most recent month. The skip exists because stock
returns show short-term (1-month) REVERSAL - last month's winners tend to
partially reverse over the next month - which is the opposite effect from
momentum and would contaminate the signal if included.

These are the textbook parameter values, not fitted to this project's
dataset - see the "Overfitting guard" section of the project plan for why
that distinction matters.
"""

import pandas as pd


def compute_momentum_signal(
    month_end_prices: pd.DataFrame,
    formation_date: pd.Timestamp,
    lookback_months: int = 12,
    skip_months: int = 1,
) -> pd.Series:
    """Compute the 12-1 momentum score for every ticker at `formation_date`.

    `month_end_prices` is a wide DataFrame (index=month-end dates,
    columns=tickers) of prices. `formation_date` must be one of its index
    values.

    momentum = Price[formation_date - skip_months] / Price[formation_date - lookback_months] - 1

    Only tickers with a valid (non-NaN) price at BOTH the lookback date and
    the skip date get a score - a ticker missing either point (e.g. it
    didn't exist yet, or has a data gap) is excluded rather than silently
    given a misleading score.

    Returns a Series indexed by ticker, containing only tickers with a
    valid score.
    """
    dates = month_end_prices.index
    formation_idx = dates.get_loc(formation_date)

    skip_idx = formation_idx - skip_months
    lookback_idx = formation_idx - lookback_months

    if skip_idx < 0 or lookback_idx < 0:
        raise ValueError(
            f"Not enough price history before {formation_date.date()} to "
            f"compute a {lookback_months}-{skip_months} momentum signal "
            f"(need {lookback_months} months of prior month-end data)."
        )

    skip_prices = month_end_prices.iloc[skip_idx]
    lookback_prices = month_end_prices.iloc[lookback_idx]

    valid = skip_prices.notna() & lookback_prices.notna() & (lookback_prices != 0)
    momentum = (skip_prices[valid] / lookback_prices[valid]) - 1
    return momentum.dropna()


def select_top_n(scores: pd.Series, n: int) -> list[str]:
    """Rank momentum scores descending and return the top `n` tickers.

    If fewer than `n` tickers have valid scores, returns all of them
    (rather than erroring), since the eligible universe can occasionally
    be a little thin, especially in the earliest years of the backtest.
    """
    return scores.sort_values(ascending=False).head(n).index.tolist()


def select_bottom_n(scores: pd.Series, n: int) -> list[str]:
    """Rank momentum scores ascending and return the bottom `n` tickers -
    the LOWEST-momentum names, i.e. the short book of the long-short
    strategy (src/backtest/long_short_engine.py).

    Exact mirror of select_top_n, including the same lenient behavior when
    fewer than `n` tickers have valid scores. Note that if the scored
    universe ever held fewer than (top-n + bottom-n) names, the two
    selections could overlap - the long-short engine checks for that and
    fails loudly rather than silently holding a stock long and short at
    the same time.
    """
    return scores.sort_values(ascending=True).head(n).index.tolist()
