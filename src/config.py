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
    #
    # "One-way" means EACH side of a trade pays this: replacing a holding
    # involves both a sell and a buy, so the per-period charge is
    # 2 * turnover * this figure - see src/costs/transaction_costs.py.
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


@dataclass
class ValueBacktestConfig:
    """Configuration for the value strategy (src/strategy/value.py,
    src/backtest/value_engine.py) - kept as its own dataclass rather than
    added to BacktestConfig, since several fields (rebalance_freq, the
    metric composite) don't apply to momentum at all. Fields that ARE
    shared between the two strategies (date window, benchmark, cost
    assumption, cache location) deliberately use the same values/defaults
    as BacktestConfig above, so the two strategies' results are directly
    comparable in the notebook rather than differing for incidental reasons.
    """

    # --- Backtest window --- same as BacktestConfig, for comparability.
    start_date: str = "2012-01-01"
    end_date: str = "2026-06-30"

    # --- Portfolio construction ---
    # Quarterly, not monthly like momentum: fundamentals only change when a
    # company files a new 10-Q/10-K, so rebalancing monthly would mostly
    # just churn turnover/costs against stale, unchanged ratios.
    rebalance_freq: str = "QE"  # pandas offset alias: quarter-end
    top_n: int = 50  # same concentration as momentum's top_n, for comparability

    # --- Benchmark ---
    benchmark_ticker: str = "SPY"

    # --- Evaluation ---
    risk_free_rate: float = 0.0

    # --- Transaction costs --- same blended assumption as BacktestConfig;
    # see that class's comment for the reasoning.
    one_way_cost_bps: float = 10.0

    # --- Data quality --- reused from BacktestConfig for the same reason.
    price_outlier_threshold: float = 0.5

    # --- Data caching --- shared cache directory and data sources with the
    # momentum strategy (prices, point-in-time constituents); fundamentals
    # get their own subdirectory inside the same cache_dir (see
    # src/data_layer/fundamentals.py).
    cache_dir: Path = REPO_ROOT / "data" / "cache"
    constituents_url: str = CONSTITUENTS_URL


DEFAULT_VALUE_CONFIG = ValueBacktestConfig()


@dataclass
class LongShortBacktestConfig:
    """Configuration for the LONG-SHORT momentum strategy (Phase 4,
    src/backtest/long_short_engine.py) - its own dataclass, like
    ValueBacktestConfig, rather than extra fields bolted onto
    BacktestConfig: the exposure/borrow-fee fields mean nothing to the
    long-only strategies, and keeping them separate means Phase 1's config
    (and results) cannot be disturbed by Phase 4 work.

    Everything the long book shares with Phase 1 momentum (universe,
    window, signal parameters, rebalance cadence, benchmark, cost
    assumption) deliberately uses the SAME values/defaults as
    BacktestConfig, so the long-short results are directly comparable to
    the long-only ones rather than differing for incidental reasons.
    """

    # --- Backtest window --- same as BacktestConfig, for comparability.
    # (As there, start_date is the first REBALANCE date; the engine fetches
    # 13 extra months of history before it for the momentum lookback.)
    start_date: str = "2012-01-01"
    end_date: str = "2026-06-30"

    # --- Momentum signal --- identical 12-1 spec to Phase 1; the short
    # book uses the same signal, just read from the other end of the
    # ranking (lowest momentum instead of highest).
    lookback_months: int = 12
    skip_months: int = 1

    # --- Portfolio construction ---
    rebalance_freq: str = "ME"  # pandas offset alias: month-end
    top_n: int = 50  # long book: the 50 HIGHEST-momentum names, equal-weighted
    bottom_n: int = 50  # short book: the 50 LOWEST-momentum names, equal-weighted

    # --- Exposures ---
    # How large each book is, as a fraction of the portfolio's capital
    # (its net asset value). The two headline variants in notebook 04:
    #   * 1.0 / 1.0  - "dollar-neutral": $1 long and $1 short per $1 of
    #     capital. This is the classic academic winners-minus-losers
    #     momentum factor (the market's overall direction largely cancels
    #     out, leaving the pure momentum bet).
    #   * 1.3 / 0.3  - "130/30": $1.30 long and $0.30 short per $1 of
    #     capital. Net exposure stays 1.0 (like a normal long-only fund)
    #     but the short book adds a way to profit from the weakest names.
    # Known simplification, stated plainly: consistent with the project's
    # 0% risk-free-rate assumption, NO interest is earned on the cash
    # raised by short sales, and NO financing cost is charged on borrowing
    # to run the 130% long book. Both are real-world cash flows a fund
    # would face; with rates near zero they roughly cancel, with rates
    # high they don't. See notebook 04's Limitations section.
    long_exposure: float = 1.0
    short_exposure: float = 1.0

    # --- Benchmark ---
    benchmark_ticker: str = "SPY"

    # --- Evaluation ---
    risk_free_rate: float = 0.0

    # --- Transaction costs --- same blended one-way assumption as
    # BacktestConfig (see that class's comment); each book pays it on its
    # own turnover, scaled by that book's exposure.
    one_way_cost_bps: float = 10.0

    # --- Borrow fee ---
    # Shorting a stock means BORROWING it (from a broker's lending pool)
    # before selling it, and the lender charges an annualized fee for
    # that. 30bps/year is a typical "general collateral" rate for liquid
    # large-caps; genuinely hard-to-borrow names can cost hundreds of bps,
    # so - matching the project's transaction-cost philosophy - this is
    # one honest blended number, sensitivity-tested in notebook 04's
    # robustness appendix (0 / 30 / 100 bps) rather than trusted as a
    # point estimate. Charged monthly on the short book's exposure:
    # short_exposure * borrow_fee_annual_bps / 12 / 10000.
    borrow_fee_annual_bps: float = 30.0

    # --- Data quality --- reused from BacktestConfig for the same reason.
    price_outlier_threshold: float = 0.5

    # --- Data caching --- shared cache with the other strategies.
    cache_dir: Path = REPO_ROOT / "data" / "cache"
    constituents_url: str = CONSTITUENTS_URL


DEFAULT_LONG_SHORT_CONFIG = LongShortBacktestConfig()
