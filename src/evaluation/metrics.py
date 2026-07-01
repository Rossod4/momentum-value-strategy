"""
Performance evaluation metrics.

Every function here takes a plain return/equity series and has no knowledge
of the backtest engine internals - that keeps them independently testable
(with simple synthetic series that have hand-computable answers) and
reusable for evaluating the SPY benchmark the exact same way as the
strategy itself.
"""

import numpy as np
import pandas as pd

MONTHS_PER_YEAR = 12


def cagr(equity_curve: pd.Series) -> float:
    """Compound annual growth rate implied by an equity curve.

    `equity_curve` is indexed by date, starting at some baseline value
    (e.g. 1.0) and compounding over time.
    """
    total_return = equity_curve.iloc[-1] / equity_curve.iloc[0]
    years = (equity_curve.index[-1] - equity_curve.index[0]).days / 365.25
    if years <= 0:
        return np.nan
    return total_return ** (1 / years) - 1


def annualized_vol(monthly_returns: pd.Series) -> float:
    """Annualized volatility from a series of monthly returns."""
    return monthly_returns.std() * np.sqrt(MONTHS_PER_YEAR)


def sharpe_ratio(monthly_returns: pd.Series, risk_free_rate: float = 0.0) -> float:
    """Annualized Sharpe ratio from a series of monthly returns.

    `risk_free_rate` is an ANNUAL rate (e.g. 0.0 for the Phase 1 default
    assumption of a 0% risk-free rate - see config.py for why).
    """
    annualized_return = monthly_returns.mean() * MONTHS_PER_YEAR
    vol = annualized_vol(monthly_returns)
    if vol == 0:
        return np.nan
    return (annualized_return - risk_free_rate) / vol


def max_drawdown(equity_curve: pd.Series) -> float:
    """Largest peak-to-trough decline in an equity curve, as a negative fraction."""
    running_max = equity_curve.cummax()
    drawdown = equity_curve / running_max - 1
    return drawdown.min()


def summary_table(
    strategy_gross_returns: pd.Series,
    strategy_gross_equity: pd.Series,
    strategy_net_returns: pd.Series,
    strategy_net_equity: pd.Series,
    benchmark_returns: pd.Series,
    benchmark_equity: pd.Series,
    risk_free_rate: float = 0.0,
) -> pd.DataFrame:
    """Side-by-side comparison table: Strategy (Gross) / Strategy (Net) / Benchmark."""
    columns = {
        "Strategy (Gross)": (strategy_gross_returns, strategy_gross_equity),
        "Strategy (Net of costs)": (strategy_net_returns, strategy_net_equity),
        "Benchmark": (benchmark_returns, benchmark_equity),
    }
    rows = {}
    for label, (returns, equity) in columns.items():
        rows[label] = {
            "CAGR": cagr(equity),
            "Annualized Volatility": annualized_vol(returns),
            "Sharpe Ratio": sharpe_ratio(returns, risk_free_rate),
            "Max Drawdown": max_drawdown(equity),
        }
    return pd.DataFrame(rows)
