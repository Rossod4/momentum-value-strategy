"""
Plots for the backtest notebook.

Kept separate from metrics.py so the pure numeric evaluation functions have
no dependency on matplotlib and stay trivially unit-testable.
"""

import matplotlib.pyplot as plt
import pandas as pd


def plot_equity_curves(
    strategy_gross_equity: pd.Series,
    strategy_net_equity: pd.Series,
    benchmark_equity: pd.Series,
    log_scale: bool = True,
):
    """Overlay strategy (gross & net of costs) vs. benchmark equity curves.

    Log scale is used by default: over a ~15-year window both series likely
    grow several-fold, and a linear scale would compress the early years
    into an unreadable flat line near zero.
    """
    fig, ax = plt.subplots(figsize=(10, 5))
    ax.plot(strategy_gross_equity.index, strategy_gross_equity, label="Strategy (Gross)", linestyle="--")
    ax.plot(strategy_net_equity.index, strategy_net_equity, label="Strategy (Net of costs)")
    ax.plot(benchmark_equity.index, benchmark_equity, label="Benchmark (SPY)")
    if log_scale:
        ax.set_yscale("log")
    ax.set_xlabel("Date")
    ax.set_ylabel("Growth of $1")
    ax.set_title("Equity Curve: Strategy vs. Benchmark")
    ax.legend()
    fig.tight_layout()
    return fig


def plot_drawdown(equity_curve: pd.Series, title: str = "Drawdown"):
    """Underwater plot: drawdown from the running peak over time."""
    running_max = equity_curve.cummax()
    drawdown = equity_curve / running_max - 1

    fig, ax = plt.subplots(figsize=(10, 3))
    ax.fill_between(drawdown.index, drawdown, 0, color="firebrick", alpha=0.5)
    ax.set_xlabel("Date")
    ax.set_ylabel("Drawdown")
    ax.set_title(title)
    fig.tight_layout()
    return fig


def plot_universe_size(universe_size_history: pd.Series):
    """Point-in-time S&P 500 universe size over the backtest window.

    A direct visual sanity check that the universe isn't static (which
    would indicate the point-in-time constituents logic isn't actually
    varying over time) and stays in a plausible ~500-name neighborhood.
    """
    fig, ax = plt.subplots(figsize=(10, 3))
    ax.plot(universe_size_history.index, universe_size_history)
    ax.set_xlabel("Date")
    ax.set_ylabel("Number of constituents")
    ax.set_title("Point-in-Time S&P 500 Universe Size")
    fig.tight_layout()
    return fig
