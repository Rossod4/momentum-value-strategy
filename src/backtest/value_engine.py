"""
Value backtest engine: the quarterly rebalance loop that ties the price and
fundamentals data layers, the value composite signal, and the transaction
cost model together into an equity curve.

Deliberately a SEPARATE module from src/backtest/engine.py rather than a
modification of it. engine.py's run_backtest() is actively owned by the
momentum work on a parallel branch, and value's data needs are different
enough (a fundamentals table joined by filing date, quarterly cadence,
occasionally-missing metrics per ticker) that forcing both strategies
through one generic loop right now would mean guessing at an abstraction
before it's needed. What genuinely IS shared and factor-agnostic -
compute_holding_period_return, compute_benchmark_result, turnover, and
transaction cost application - is imported and reused as-is, not
duplicated.

No-look-ahead invariant: identical in spirit to engine.py's. At each
rebalance date `t`, this loop only ever uses (a) prices dated <= t, (b) the
point-in-time constituents list as-of t, and (c) fundamentals FILED on or
before t (see src/data_layer/fundamentals.py). Nothing here peeks at future
data to decide the portfolio at `t`.
"""

import pandas as pd

from src.backtest.engine import (
    EXTREME_MONTHLY_RETURN_BOUND,
    BacktestResult,
    compute_benchmark_result,
    compute_holding_period_return,
)
from src.config import ValueBacktestConfig
from src.costs.transaction_costs import apply_transaction_costs, compute_turnover
from src.data_layer.constituents import get_membership, load_constituents_table
from src.data_layer.fundamentals import (
    get_fundamentals_facts,
    get_point_in_time_fundamentals,
    load_ticker_cik_map,
)
from src.data_layer.prices import get_prices
from src.strategy.value import compute_composite_score, compute_value_ratios, select_top_n


def run_value_backtest(config: ValueBacktestConfig) -> BacktestResult:
    constituents_table = load_constituents_table(cache_dir=config.cache_dir, url=config.constituents_url)

    # Quarterly rebalance dates the user asked for (candidates - the actual
    # usable set is narrowed down to trading days once we have price data).
    requested_rebalance_dates = pd.date_range(
        config.start_date, config.end_date, freq=config.rebalance_freq
    )

    # Every ticker that was ever a constituent on any requested rebalance
    # date - this is the full universe we need price and fundamentals
    # history for.
    all_tickers: set[str] = set()
    for d in requested_rebalance_dates:
        all_tickers.update(get_membership(d, constituents_table))

    # Unlike momentum, the value signal needs no price history BEFORE the
    # first rebalance date - it's not a lookback-return calculation, just a
    # price snapshot at each formation date - so prices are fetched from
    # config.start_date directly, with no warmup offset.
    daily_prices, price_failed_tickers = get_prices(
        sorted(all_tickers | {config.benchmark_ticker}), config.start_date, config.end_date, cache_dir=config.cache_dir
    )
    quarter_end_prices = daily_prices.resample(config.rebalance_freq).last()

    cik_map = load_ticker_cik_map(config.cache_dir)
    facts_by_ticker, fundamentals_failed_tickers = get_fundamentals_facts(
        sorted(all_tickers), config.cache_dir, cik_map=cik_map
    )

    # Only formation dates that are actually present as trading
    # quarter-ends AND fall within the user's requested window can be used.
    eligible_formation_dates = [
        d for d in quarter_end_prices.index if d >= pd.Timestamp(config.start_date)
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
        formation_idx = quarter_end_prices.index.get_loc(formation_date)
        if formation_idx + 1 >= len(quarter_end_prices.index):
            break  # no next quarter to hold into - stop before the last date
        next_date = quarter_end_prices.index[formation_idx + 1]

        membership_t = get_membership(formation_date, constituents_table)
        universe_size_history[formation_date] = len(membership_t)

        # Point-in-time fundamentals for every constituent we have filing
        # history for - extracted fresh for THIS formation_date, so only
        # facts filed on or before it are visible (see fundamentals.py).
        fundamentals_t = {
            ticker: get_point_in_time_fundamentals(facts_by_ticker[ticker], formation_date)
            for ticker in membership_t
            if ticker in facts_by_ticker
        }

        # get_prices() only returns columns for tickers it actually fetched
        # successfully (failures are dropped, not filled with NaN columns -
        # see prices.py) - membership_t can include tickers that failed to
        # download entirely, which would raise a KeyError if indexed
        # directly, so the membership list is narrowed to the price
        # DataFrame's actual columns first.
        priceable_tickers = [t for t in membership_t if t in quarter_end_prices.columns]
        prices_t = quarter_end_prices.loc[formation_date, priceable_tickers]
        prices_t = {ticker: price for ticker, price in prices_t.items() if pd.notna(price)}

        raw_ratios = compute_value_ratios(fundamentals_t, prices_t)
        composite_scores = compute_composite_score(raw_ratios)
        new_portfolio = select_top_n(composite_scores, config.top_n)

        if not new_portfolio:
            continue

        holdings_history[formation_date] = new_portfolio

        turnover = compute_turnover(old_portfolio, new_portfolio, len(new_portfolio))
        turnover_history[formation_date] = turnover

        formation_prices = quarter_end_prices.loc[formation_date, new_portfolio]
        next_prices = quarter_end_prices.loc[next_date, new_portfolio]

        # Same vendor-glitch guard as the momentum engine, reused via the
        # same bound: whether an implied single-holding-period return is
        # "too large to be real for an S&P 500-type stock" doesn't depend
        # on whether the holding period is a month or a quarter, only on
        # the size of the move - see engine.py's EXTREME_MONTHLY_RETURN_BOUND
        # docstring for the full reasoning (the CBE vendor glitch it was
        # calibrated against).
        gross_return, missing_count, extreme_count = compute_holding_period_return(
            formation_prices, next_prices, extreme_return_bound=EXTREME_MONTHLY_RETURN_BOUND
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

    # A ticker can fail to produce usable data for either reason (no price
    # history, or no SEC filing history) - both are real coverage gaps
    # worth surfacing together, so they're merged into one list rather than
    # tracked separately.
    failed_tickers = sorted(set(price_failed_tickers) | set(fundamentals_failed_tickers))

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


def compute_value_benchmark_result(config: ValueBacktestConfig) -> tuple[pd.Series, pd.Series]:
    """Thin wrapper around engine.compute_benchmark_result() - it only reads
    generic fields (benchmark_ticker, start_date, end_date, rebalance_freq,
    cache_dir) that both BacktestConfig and ValueBacktestConfig share, so no
    value-specific logic is needed here at all.
    """
    return compute_benchmark_result(config)
