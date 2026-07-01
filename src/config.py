"""
Central configuration for the momentum backtester.

Every tunable parameter for the strategy lives here, in one place, instead of
being hardcoded across modules. This makes the backtest's assumptions easy to
see at a glance and easy to change for the robustness/sensitivity checks in
the notebook (e.g. rerunning with a different `top_n` or `one_way_cost_bps`).
"""

from dataclasses import dataclass
from pathlib import Path

# Repo root, so cache paths work the same whether the code is run from a
# script, a notebook, or a test, regardless of the current working directory.
REPO_ROOT = Path(__file__).resolve().parent.parent

CONSTITUENTS_URL = (
    "https://raw.githubusercontent.com/fja05680/sp500/master/"
    "S%26P%20500%20Historical%20Components%20%26%20Changes%20(Updated).csv"
)


@dataclass
class BacktestConfig:
    # --- Backtest window ---
    # start_date is the date of the FIRST REBALANCE, not the first date of
    # downloaded price history. Computing 12-1 momentum at start_date needs
    # 13 months of price history before it, so the price layer internally
    # fetches from (start_date - lookback_months - skip_months) onward.
    # See src/backtest/engine.py for where this warmup offset is applied.
    start_date: str = "2012-01-01"
    end_date: str = "2026-06-30"

    # --- Momentum signal ---
    # Classic 12-1 momentum (Jegadeesh & Titman-style): rank stocks by their
    # return from 12 months ago to 1 month ago, skipping the most recent
    # month to avoid short-term reversal effects. These are the standard
    # textbook values, not fitted to this dataset.
    lookback_months: int = 12
    skip_months: int = 1

    # --- Portfolio construction ---
    rebalance_freq: str = "ME"  # pandas offset alias: month-end
    top_n: int = 50  # number of stocks held each period, equal-weighted

    # --- Benchmark ---
    benchmark_ticker: str = "SPY"

    # --- Evaluation ---
    # Assumed annual risk-free rate used in the Sharpe ratio calculation.
    # Defaulting to 0% is the simplest defensible starting assumption for
    # Phase 1; swap in a real T-bill series later without touching the
    # Sharpe ratio formula itself (see src/evaluation/metrics.py).
    risk_free_rate: float = 0.0

    # --- Transaction costs ---
    # A single blended one-way cost (commission + bid-ask spread + market
    # impact) applied per unit of monthly portfolio turnover. 10 bps is a
    # moderate assumption for liquid, large-cap US equities, in line with
    # published transaction-cost estimates for this kind of universe (e.g.
    # Novy-Marx & Velikov's anomaly trading-cost research puts large-cap
    # costs well below the small-cap end of their range). This is
    # deliberately a single number rather than separate commission/spread/
    # impact terms, since we don't have reliable volume/spread data to
    # justify a more granular model. It's exposed here so it can be
    # stress-tested (see the robustness appendix in the notebook) rather
    # than trusted as a single point estimate.
    one_way_cost_bps: float = 10.0

    # --- Data quality ---
    # Flag any single-day |return| beyond this threshold as a likely data
    # error (bad print, unadjusted split, vendor glitch) rather than
    # genuine price action, so it can be surfaced instead of silently
    # trusted. See src/data_layer/quality_checks.py.
    price_outlier_threshold: float = 0.5

    # --- Data caching ---
    cache_dir: Path = REPO_ROOT / "data" / "cache"
    constituents_url: str = CONSTITUENTS_URL


DEFAULT_CONFIG = BacktestConfig()
