"""
Basic data quality checks for downloaded price series.

yfinance data isn't guaranteed to be clean - bad prints, unadjusted splits,
and other vendor glitches happen. We can't fix bad data without a paid
vendor, but we CAN flag it instead of trusting it silently. That turns
"trust yfinance blindly" into "trust yfinance, but flag what looks wrong",
so anyone reading the notebook can see exactly what was flagged and decide
whether it matters for their conclusions.
"""

import pandas as pd


def find_price_outliers(
    prices: pd.DataFrame, threshold: float = 0.5
) -> pd.DataFrame:
    """Flag single-day |return| moves beyond `threshold` (e.g. 0.5 = 50%).

    A single-day move this large is far more often a bad print or an
    unadjusted corporate action slipping through than genuine price action,
    especially for large, liquid S&P 500-type names.

    `prices` is a wide DataFrame (index=date, columns=tickers) of adjusted
    close prices. Returns a long-format DataFrame with columns
    [date, ticker, daily_return] for every flagged move, sorted by the size
    of the move (largest first) so the worst offenders are easy to spot.
    """
    daily_returns = prices.pct_change()
    flagged = daily_returns[daily_returns.abs() > threshold]

    # NOTE: pandas' DataFrame.stack() no longer drops NaN by default (its
    # `dropna` argument is ignored under the modern stacking implementation),
    # so it must be dropped explicitly - otherwise every non-flagged cell
    # would show up as a spurious NaN "flagged" row.
    flagged_long = flagged.stack().dropna().reset_index()
    flagged_long.columns = ["date", "ticker", "daily_return"]
    flagged_long = flagged_long.sort_values(
        "daily_return", key=lambda s: s.abs(), ascending=False
    ).reset_index(drop=True)
    return flagged_long
