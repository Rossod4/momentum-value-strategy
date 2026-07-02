"""
Backtest engine: the monthly rebalance loop that ties the data layer,
momentum signal, and transaction cost model together into an equity curve.

No-look-ahead invariant: at each rebalance date `t`, this loop only ever
uses (a) prices dated <= t, and (b) the point-in-time constituents list
as-of t (see src/data_layer/constituents.py). Nothing here peeks at future
data to decide the portfolio at `t`.
"""

from dataclasses import dataclass, field

import pandas as pd
from dateutil.relativedelta import relativedelta

from src.config import BacktestConfig
from src.costs.transaction_costs import apply_transaction_costs, compute_turnover
from src.data_layer.constituents import get_membership, load_constituents_table
from src.data_layer.prices import get_prices
from src.strategy.momentum import compute_momentum_signal, select_top_n


@dataclass
class BacktestResult:
    gross_returns: pd.Series  # monthly, indexed by the date the return is realized
    gross_equity: pd.Series  # starts at 1.0
    net_returns: pd.Series
    net_equity: pd.Series
    holdings_history: dict  # formation_date -> list[ticker]
    turnover_history: pd.Series
    universe_size_history: pd.Series  # point-in-time constituent count per formation date
    failed_tickers: list = field(default_factory=list)
    missing_forward_price_count: int = 0
    extreme_return_count: int = 0


def compute_warmup_start(start_date: str, lookback_months: int, skip_months: int) -> str:
    """First date we need price history from, to have enough lookback for
    the very first rebalance."""
    start = pd.Timestamp(start_date)
    warmup = start - relativedelta(months=lookback_months + skip_months)
    return warmup.strftime("%Y-%m-%d")


# A single held stock implying a monthly gain beyond this is treated as a
# vendor data glitch, not genuine price action, and excluded from that
# month's equal-weight average.
#
# This is deliberately a much higher bar than the daily-return outlier
# threshold used for the informational quality-check display in the
# notebook (config.price_outlier_threshold, ~50%): a 50%+ move in a single
# DAY is almost always a bad print for a large-cap name, but a 50%+ move
# over an entire HOLDING MONTH is not - momentum strategies specifically
# select recent high-flyers, and genuine monthly gains well above 50%
# (short squeezes, biotech trial results, M&A premia) do happen. Reusing
# the daily threshold here would silently strip out real, sometimes very
# profitable, momentum winners and bias the strategy's reported returns
# downward. 300% was chosen as a bound that's essentially unreachable
# organically in one month for an S&P 500-type name, based on a real
# vendor glitch found during development: ticker CBE (Cooper Industries,
# delisted Nov 2012 after being acquired by Eaton) continued to trade
# under its old symbol afterward with prices swinging between $0.005 and
# $300+ month to month - implying single-month "returns" in the tens of
# thousands of percent. Only the upside is capped: a monthly LOSS is
# naturally bounded at -100% and a genuine collapse (fraud, bankruptcy)
# can legitimately look just as extreme, so excluding large losses here
# would risk hiding real downside risk rather than data errors.
EXTREME_MONTHLY_RETURN_BOUND = 3.0


def compute_holding_period_return(
    formation_prices: pd.Series,
    next_prices: pd.Series,
    extreme_return_bound: float = EXTREME_MONTHLY_RETURN_BOUND,
) -> tuple[float, int, int]:
    """Equal-weight average return for one holding period.

    Compares each held stock's price at `formation_prices` (start of the
    holding month) to its price at `next_prices` (end of the holding month).

    Two categories of individual-stock return are excluded from the
    equal-weight average rather than trusted blindly, and both are counted
    so the exclusions are visible rather than hidden:
      - missing: the stock has no valid price at one end of the period
        (e.g. a mid-holding delisting or data gap).
      - extreme: the implied single-stock gain exceeds `extreme_return_bound`
        (see EXTREME_MONTHLY_RETURN_BOUND above for why 300% and why only
        the upside is guarded).

    Returns (gross_return, missing_price_count, extreme_return_count).
    """
    valid = next_prices.notna() & formation_prices.notna()
    missing_count = int((~valid).sum())

    holding_returns = (next_prices[valid] / formation_prices[valid]) - 1

    is_extreme = holding_returns > extreme_return_bound
    extreme_count = int(is_extreme.sum())
    holding_returns = holding_returns[~is_extreme]

    gross_return = holding_returns.mean() if len(holding_returns) > 0 else 0.0
    return gross_return, missing_count, extreme_count


def run_backtest(config: BacktestConfig) -> BacktestResult:
    constituents_table = load_constituents_table(cache_dir=config.cache_dir, url=config.constituents_url)

    # Monthly rebalance dates the user asked for (candidates - the actual
    # usable set is narrowed down to trading days once we have price data).
    requested_rebalance_dates = pd.date_range(
        config.start_date, config.end_date, freq=config.rebalance_freq
    )

    # Every ticker that was ever a constituent on any requested rebalance
    # date - this is the full universe we need price history for.
    all_tickers: set[str] = set()
    for d in requested_rebalance_dates:
        all_tickers.update(get_membership(d, constituents_table))
    all_tickers.add(config.benchmark_ticker)

    warmup_start = compute_warmup_start(config.start_date, config.lookback_months, config.skip_months)
    daily_prices, failed_tickers = get_prices(
        sorted(all_tickers), warmup_start, config.end_date, cache_dir=config.cache_dir
    )

    month_end_prices = daily_prices.resample(config.rebalance_freq).last()

    # Only formation dates that are actually present as trading month-ends
    # AND fall within the user's requested window can be used.
    eligible_formation_dates = [
        d for d in month_end_prices.index if d >= pd.Timestamp(config.start_date)
    ]

    gross_returns = {}
    net_returns = {}
    holdings_history = {}
    turnover_history = {}
    universe_size_history = {}
    missing_forward_price_count = 0
    extreme_return_count = 0
    old_portfolio: list[str] = []

    for formation_date in eligible_formation_dates:
        formation_idx = month_end_prices.index.get_loc(formation_date)
        if formation_idx + 1 >= len(month_end_prices.index):
            break  # no next month to hold into - stop before the last date
        next_date = month_end_prices.index[formation_idx + 1]

        membership_t = get_membership(formation_date, constituents_table)
        universe_size_history[formation_date] = len(membership_t)

        try:
            scores = compute_momentum_signal(
                month_end_prices, formation_date, config.lookback_months, config.skip_months
            )
        except ValueError:
            continue  # not enough warmup history yet for this date

        eligible_scores = scores[scores.index.isin(membership_t)]
        new_portfolio = select_top_n(eligible_scores, config.top_n)

        if not new_portfolio:
            continue

        holdings_history[formation_date] = new_portfolio

        turnover = compute_turnover(old_portfolio, new_portfolio, len(new_portfolio))
        turnover_history[formation_date] = turnover

        formation_prices = month_end_prices.loc[formation_date, new_portfolio]
        next_prices = month_end_prices.loc[next_date, new_portfolio]

        # A held stock can occasionally be missing its next-month price
        # (delisting mid-holding-period, or a data gap), or imply an
        # implausible gain (a vendor data glitch - see
        # EXTREME_MONTHLY_RETURN_BOUND above). Both are excluded from this
        # month's equal-weight average rather than trusted blindly - note
        # the missing-price case is a slightly optimistic simplification:
        # a true delisting is usually a loss, not a "doesn't count" event.
        # Both counts are tracked and reported so the exclusions are
        # visible, not hidden.
        gross_return, missing_count, extreme_count = compute_holding_period_return(
            formation_prices, next_prices
        )
        missing_forward_price_count += missing_count
        extreme_return_count += extreme_count

        net_return = apply_transaction_costs(gross_return, turnover, config.one_way_cost_bps)

        gross_returns[next_date] = gross_return
        net_returns[next_date] = net_return

        old_portfolio = new_portfolio

    gross_returns = pd.Series(gross_returns).sort_index()
    net_returns = pd.Series(net_returns).sort_index()

    gross_equity = (1 + gross_returns).cumprod()
    net_equity = (1 + net_returns).cumprod()

    return BacktestResult(
        gross_returns=gross_returns,
        gross_equity=gross_equity,
        net_returns=net_returns,
        net_equity=net_equity,
        holdings_history=holdings_history,
        turnover_history=pd.Series(turnover_history).sort_index(),
        universe_size_history=pd.Series(universe_size_history).sort_index(),
        failed_tickers=failed_tickers,
        missing_forward_price_count=missing_forward_price_count,
        extreme_return_count=extreme_return_count,
    )


def compute_benchmark_result(config: BacktestConfig) -> tuple[pd.Series, pd.Series]:
    """Buy-and-hold return/equity series for the benchmark ticker, over the
    same realized-return dates a run_backtest() call would produce.

    Fetched independently of run_backtest() so the benchmark is a pure
    price-ratio calculation with no ranking/selection logic of its own.
    """
    daily_prices, failed = get_prices(
        [config.benchmark_ticker], config.start_date, config.end_date, cache_dir=config.cache_dir
    )
    if config.benchmark_ticker in failed or daily_prices.empty:
        raise RuntimeError(f"Could not fetch benchmark data for {config.benchmark_ticker}")

    month_end = daily_prices[config.benchmark_ticker].resample(config.rebalance_freq).last()
    returns = month_end.pct_change().dropna()
    equity = (1 + returns).cumprod()
    return returns, equity
