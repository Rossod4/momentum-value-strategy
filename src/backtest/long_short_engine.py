"""
Long-short momentum backtest engine (Phase 4): the monthly rebalance loop
for a strategy that is simultaneously LONG the highest-momentum names and
SHORT the lowest-momentum names.

Deliberately a SEPARATE module from src/backtest/engine.py, for the same
reason value_engine.py is: engine.py's run_backtest() is the settled,
working Phase 1 long-only loop, and threading "optional short book" logic
through it would complicate code that currently has one clear job. What
genuinely IS shared and factor-agnostic - the momentum signal itself,
compute_holding_period_return (including its vendor-glitch guard),
compute_benchmark_result, turnover, and transaction cost application - is
imported and reused as-is, not duplicated.

How the monthly return is built (the whole strategy in four lines):

    r_long  = equal-weight return of the top-N momentum names
    r_short = equal-weight return of the bottom-N momentum names
    gross   = long_exposure * r_long - short_exposure * r_short
    net     = gross - transaction costs (per book) - borrow fee

The minus sign in front of the short book is the essence of shorting: the
position PROFITS when the underlying stocks FALL. Everything is expressed
per $1 of the portfolio's capital, so `long_exposure=1.3,
short_exposure=0.3` means $1.30 of longs and $0.30 of shorts per $1 of
capital (a "130/30" fund), and 1.0/1.0 is the classic dollar-neutral
winners-minus-losers factor.

Cash-flow simplifications, stated plainly (see notebook 04's Limitations):
consistent with the project-wide 0% risk-free-rate assumption, no interest
is earned on short-sale proceeds and no financing cost is charged on
leverage above 100% long. The one short-specific carrying cost that has no
long-only analogue - the stock borrow fee - IS modeled, as a single
blended annual bps rate charged monthly on the short book.

No-look-ahead invariant: identical to engine.py's. At each rebalance date
`t`, this loop only ever uses prices dated <= t and the point-in-time
constituents list as-of t. Nothing here peeks at future data to decide
either book at `t`.
"""

from dataclasses import dataclass, field

import pandas as pd

from src.backtest.engine import (
    BacktestResult,
    compute_benchmark_result,
    compute_holding_period_return,
    compute_warmup_start,
)
from src.config import LongShortBacktestConfig
from src.costs.transaction_costs import apply_transaction_costs, compute_turnover
from src.data_layer.constituents import get_membership, load_constituents_table
from src.data_layer.prices import get_prices
from src.strategy.momentum import compute_momentum_signal, select_bottom_n, select_top_n

MONTHS_PER_YEAR = 12


@dataclass
class LongShortBacktestResult(BacktestResult):
    """BacktestResult plus per-book diagnostics.

    Subclassing (rather than a new unrelated dataclass) is deliberate: the
    inherited fields mean every existing evaluation tool - summary_table,
    strategy_comparison_table, combine_strategies - accepts this result
    unchanged. Two inherited fields carry long-short-specific conventions:

      * holdings_history: formation_date -> {"long": [...], "short": [...]}
        (a dict per date instead of Phase 1's flat ticker list, since there
        are now two books to record).
      * turnover_history: the fraction of TOTAL GROSS EXPOSURE traded each
        month, i.e. (long_exposure * long_turnover + short_exposure *
        short_turnover) / (long_exposure + short_exposure). Weighting by
        exposure matters for asymmetric books: in a 130/30 fund the long
        book is over 4x the short book's size, so their turnover fractions
        can't just be averaged equally. With short_exposure=0 this reduces
        exactly to Phase 1's definition.

    The per-book missing/extreme counts below exist because the two books'
    data problems mean OPPOSITE things for reported performance (a dropped
    delisting flatters the long book but understates the short book's
    profit; an excluded >300% gain flatters the short book but understates
    the long book's) - so lumping them into one number would hide exactly
    the asymmetry worth scrutinizing. The inherited totals are kept
    populated too, as the sum of the per-book counts.
    """

    long_turnover_history: pd.Series = field(default_factory=pd.Series)
    short_turnover_history: pd.Series = field(default_factory=pd.Series)
    long_missing_forward_price_count: int = 0
    short_missing_forward_price_count: int = 0
    long_extreme_return_count: int = 0
    short_extreme_return_count: int = 0


def monthly_borrow_fee(short_exposure: float, borrow_fee_annual_bps: float) -> float:
    """The month's stock-borrow fee, as a fraction of portfolio capital.

    The lender's annualized fee (in basis points) applies to the value of
    stock actually borrowed - the short book - so it's scaled by
    short_exposure and divided by 12 to get one month's charge:

        fee = short_exposure * borrow_fee_annual_bps / 12 / 10000

    e.g. a dollar-neutral book (short_exposure=1.0) at 30bps/year pays
    2.5bps of capital per month; a 130/30 book (short_exposure=0.3) pays
    0.75bps per month.
    """
    return short_exposure * borrow_fee_annual_bps / MONTHS_PER_YEAR / 10_000


def compute_long_short_period_return(
    long_return: float,
    short_underlying_return: float,
    long_turnover: float,
    short_turnover: float,
    long_exposure: float,
    short_exposure: float,
    one_way_cost_bps: float,
    borrow_fee_annual_bps: float,
) -> tuple[float, float]:
    """One month's (gross, net) portfolio return, per $1 of capital.

    This is the strategy's entire return arithmetic, kept as a pure
    function of plain numbers so the tests can verify it against
    hand-worked examples (see tests/test_long_short.py).

    `short_underlying_return` is the return of the shorted STOCKS
    themselves (the bottom-N basket's equal-weight move). The short
    position's contribution is its negative: shorts profit when the
    underlying falls.

        gross = long_exposure * r_long - short_exposure * r_short

    Costs: each book pays the round-trip transaction cost
    (2 * turnover * one_way_cost_bps - see transaction_costs.py for why
    the 2x) on ITS OWN turnover. A book's turnover is a fraction of that
    book's value, and the book's value is exposure * capital, so as a
    fraction of capital the charge scales by the book's exposure. That's
    implemented by reusing apply_transaction_costs() unchanged on each
    book's per-$-of-book return, then scaling the whole book by its
    exposure:

        net = long_exposure  * (r_long  - book cost)
            + short_exposure * (-r_short - book cost)
            - borrow fee

    Finally the borrow fee (see monthly_borrow_fee) is a carrying cost of
    the short book, charged whether or not anything traded.
    """
    gross = long_exposure * long_return - short_exposure * short_underlying_return
    net = (
        long_exposure * apply_transaction_costs(long_return, long_turnover, one_way_cost_bps)
        + short_exposure
        * apply_transaction_costs(-short_underlying_return, short_turnover, one_way_cost_bps)
        - monthly_borrow_fee(short_exposure, borrow_fee_annual_bps)
    )
    return gross, net


def run_long_short_backtest(config: LongShortBacktestConfig) -> LongShortBacktestResult:
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

    # Same 13-month signal warmup as Phase 1 (the short book uses the same
    # 12-1 signal, so it needs no extra history of its own).
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
    long_turnover_history = {}
    short_turnover_history = {}
    universe_size_history = {}
    long_missing = 0
    short_missing = 0
    long_extreme = 0
    short_extreme = 0
    old_long_book: list[str] = []
    old_short_book: list[str] = []

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

        # ONE ranking, read from both ends: the long book takes the top of
        # it and the short book the bottom, so the two books can never
        # disagree about what "momentum" means on a given date.
        long_book = select_top_n(eligible_scores, config.top_n)
        short_book = select_bottom_n(eligible_scores, config.bottom_n)

        if not long_book or not short_book:
            continue

        # With ~450+ scored S&P 500 names and 50+50 selections the books
        # are disjoint by construction; they could only overlap if the
        # scored universe shrank below top_n + bottom_n. Holding the same
        # stock long AND short simultaneously is nonsense, so that
        # degenerate case fails loudly instead of producing quiet garbage.
        overlap = set(long_book) & set(short_book)
        if overlap:
            raise ValueError(
                f"Long and short books overlap at {formation_date.date()} "
                f"({sorted(overlap)[:5]}...): only {len(eligible_scores)} scored "
                f"tickers for top_n={config.top_n} + bottom_n={config.bottom_n}."
            )

        holdings_history[formation_date] = {"long": long_book, "short": short_book}

        # Each book's turnover is computed against ITS OWN previous
        # holdings - a stock migrating from the short book to the long
        # book (a big momentum reversal) correctly counts as trading in
        # BOTH books, because it really is: the short is bought back AND
        # a new long is bought.
        long_turnover = compute_turnover(old_long_book, long_book, len(long_book))
        short_turnover = compute_turnover(old_short_book, short_book, len(short_book))
        long_turnover_history[formation_date] = long_turnover
        short_turnover_history[formation_date] = short_turnover

        # Combined turnover = fraction of total gross exposure traded (see
        # LongShortBacktestResult's docstring for why exposure-weighted).
        gross_exposure = config.long_exposure + config.short_exposure
        turnover_history[formation_date] = (
            config.long_exposure * long_turnover + config.short_exposure * short_turnover
        ) / gross_exposure

        # Underlying basket returns for each book, via the SAME shared
        # helper Phase 1 and 2 use - including its two data guards:
        #   * missing forward prices are dropped and counted;
        #   * implied single-stock gains >300% are excluded as vendor data
        #     glitches and counted.
        # Applying the >300% exclusion to the SHORT book too is a
        # deliberate judgment call: the test is about whether the DATA is
        # trustworthy, and a price series doesn't become more believable
        # because we happen to be short it. The uncomfortable flip side -
        # a >300% underlying gain, if REAL, would be a catastrophic loss
        # to a short seller, and this guard would hide it - is exactly why
        # the exclusions are counted per book and discussed in notebook
        # 04's Limitations rather than buried.
        long_return, miss_l, ext_l = compute_holding_period_return(
            month_end_prices.loc[formation_date, long_book],
            month_end_prices.loc[next_date, long_book],
        )
        short_underlying_return, miss_s, ext_s = compute_holding_period_return(
            month_end_prices.loc[formation_date, short_book],
            month_end_prices.loc[next_date, short_book],
        )
        long_missing += miss_l
        short_missing += miss_s
        long_extreme += ext_l
        short_extreme += ext_s

        gross_return, net_return = compute_long_short_period_return(
            long_return=long_return,
            short_underlying_return=short_underlying_return,
            long_turnover=long_turnover,
            short_turnover=short_turnover,
            long_exposure=config.long_exposure,
            short_exposure=config.short_exposure,
            one_way_cost_bps=config.one_way_cost_bps,
            borrow_fee_annual_bps=config.borrow_fee_annual_bps,
        )

        gross_returns[next_date] = gross_return
        net_returns[next_date] = net_return

        old_long_book = long_book
        old_short_book = short_book

    gross_returns = pd.Series(gross_returns).sort_index()
    net_returns = pd.Series(net_returns).sort_index()

    gross_equity = (1 + gross_returns).cumprod()
    net_equity = (1 + net_returns).cumprod()

    return LongShortBacktestResult(
        gross_returns=gross_returns,
        gross_equity=gross_equity,
        net_returns=net_returns,
        net_equity=net_equity,
        holdings_history=holdings_history,
        turnover_history=pd.Series(turnover_history).sort_index(),
        universe_size_history=pd.Series(universe_size_history).sort_index(),
        failed_tickers=failed_tickers,
        missing_forward_price_count=long_missing + short_missing,
        extreme_return_count=long_extreme + short_extreme,
        long_turnover_history=pd.Series(long_turnover_history).sort_index(),
        short_turnover_history=pd.Series(short_turnover_history).sort_index(),
        long_missing_forward_price_count=long_missing,
        short_missing_forward_price_count=short_missing,
        long_extreme_return_count=long_extreme,
        short_extreme_return_count=short_extreme,
    )


def compute_long_short_benchmark_result(config: LongShortBacktestConfig) -> tuple[pd.Series, pd.Series]:
    """Thin wrapper around engine.compute_benchmark_result(), exactly like
    value_engine's - it only reads generic fields (benchmark_ticker,
    start_date, end_date, rebalance_freq, cache_dir) that all three config
    dataclasses share.
    """
    return compute_benchmark_result(config)
