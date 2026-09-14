# Momentum and Value Strategy Backtester

[![tests](https://github.com/Rossod4/momentum-value-strategy/actions/workflows/tests.yml/badge.svg)](https://github.com/Rossod4/momentum-value-strategy/actions/workflows/tests.yml)

I built this to find out whether the classic momentum and value strategies actually work
once you strip out the usual backtest cheats. Short answer: on the S&P 500 from 2012 to
2026 they beat the index on return, not on risk-adjusted return, and the pure long-short
momentum version doesn't work at all in this period.

The strategies themselves are textbook. The work is in everything around them: index
membership as it was on each rebalance date, company fundamentals only visible from the
day they were filed, transaction costs charged properly, a capacity estimate, and a
walk-forward test that ended up overturning my own best-looking result.

![Momentum strategy vs SPY, growth of $1, log scale](docs/img/momentum_vs_spy.png)

## Results

Net of transaction costs, 2012 to mid-2026, equal-weight top-50 portfolios.

| Strategy | Net CAGR | Sharpe | Max drawdown |
|---|---:|---:|---:|
| Long-only 12-1 momentum, monthly | 15.7% | 0.96 | -20% |
| Value composite, quarterly | 15.9% | 0.93 | -34% |
| 130/30 long-short momentum | 16.4% | 0.93 | -19% |
| Dollar-neutral long-short momentum | 1.0% | 0.14 | -56% |
| S&P 500 (SPY) | 14.5% to 14.8% | 1.02 to 1.05 | -24% |

These come from the committed notebook runs (August and September 2026) and shift by a
few tenths of a percent whenever the data is refreshed. SPY is measured at each
strategy's own rebalancing frequency, which is why it shows a range.

Three things I took from this:

- **Beating the index on return isn't the same as beating it.** SPY has the highest
  Sharpe ratio in the table. 2012 to 2026 was a strong, low-volatility bull market,
  which is the easiest possible environment for buy-and-hold.
- **The academic long-short momentum factor was flat.** It stays flat in both halves of
  the window, under a 6-1 construction instead of 12-1, and in more than half of all
  rolling 3-year windows. The worst months are all sharp market rebounds where the short
  book snaps back, which is exactly the momentum-crash pattern in the published
  research. The 130/30 version, which keeps most of the long book, is the one that's
  actually usable.
- **My "50/50 blend is best" result didn't survive out-of-sample.** If you'd picked the
  blend weight from trailing data each year, you'd have underperformed every fixed
  weight, and the weight you'd have picked jumps around from year to year. What
  survives is weaker: any fixed blend did fine, none was reliably best, and trying to
  time it made things worse.

The full reasoning, including three bugs I found and fixed along the way, is in
[`REVIEW.md`](REVIEW.md) and [`REVIEW_PHASE5.md`](REVIEW_PHASE5.md).

## What's here

| Phase | Notebook | What it does |
|---|---|---|
| 1 | [`01_momentum_backtest`](notebooks/01_momentum_backtest.ipynb) | Long-only 12-1 momentum on point-in-time S&P 500 membership, monthly rebalancing, turnover-based costs |
| 2 | [`02_value_backtest`](notebooks/02_value_backtest.ipynb) | Value composite (P/B, P/E, EV/EBITDA, growth-adjusted) on SEC EDGAR fundamentals, gated on filing date, quarterly rebalancing |
| 3 | [`03_strategy_comparison`](notebooks/03_strategy_comparison.ipynb) | Head-to-head comparison and fixed-weight blends |
| 4 | [`04_long_short_momentum`](notebooks/04_long_short_momentum.ipynb) | Dollar-neutral and 130/30 long-short momentum with per-book costs and a borrow fee |
| 5 | [`05_walk_forward_and_robustness`](notebooks/05_walk_forward_and_robustness.ipynb) | Rolling-window consistency, walk-forward test of the blend weight, robustness of the flat long-short result |

The notebooks are committed with their outputs, so you can read the results on GitHub
without running anything.

## Where the bias hides, and what I did about it

- **Look-ahead.** Momentum scores only use month-end prices on or before the formation
  date. Fundamentals only use filings whose `filed` date is on or before the rebalance
  date, not the fiscal period they cover. If a figure was later restated, the backtest
  sees the version that was public at the time.
- **Survivorship.** The universe at each rebalance is the S&P 500 as it was on that
  date, not today's list. The one gap I couldn't close is historical members with no
  SEC ticker mapping, so I measured it instead of footnoting it: about 2% of the average
  quarter's names, with a return tilt that's statistically indistinguishable from zero.
  See [`scripts/coverage_gap_analysis.py`](scripts/coverage_gap_analysis.py).
- **Costs.** A flat 10 bps one-way cost, charged on both the sell and the buy of every
  replacement. I checked it against estimated spreads and worked out a capacity ceiling
  of roughly $100 to 350 million, above which market impact would swamp it. See
  [`scripts/cost_realism_analysis.py`](scripts/cost_realism_analysis.py).
- **Data snooping.** Every strategy parameter is a fixed textbook choice, nothing was
  tuned on this data. The one conclusion that *was* read off the data, the best blend
  weight, is the one I walk-forward tested.
- **Reproducibility.** Running a backtest twice gives identical numbers. The test suite
  is offline and deterministic.

## Layout

```
src/
  config.py          every tunable parameter in one place, with the reasoning
  data_layer/        prices (Yahoo Finance), point-in-time constituents, SEC EDGAR
                     fundamentals, on-disk cache, data quality guards
  strategy/          momentum and value signals and selection
  costs/             turnover-based transaction cost model
  backtest/          monthly, quarterly and long-short engines
  evaluation/        metrics, comparison and blending, walk-forward, plots
tests/               106 offline tests with hand-computable expected values
scripts/             the two Phase 5 audit scripts
notebooks/           the five phases, executed and committed with outputs
```

Strategy code never talks to a data vendor directly, so the data source can be swapped
without touching the signal or backtest code.

## Running it

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows; source .venv/bin/activate elsewhere
pip install -r requirements.txt
python -m pytest tests/         # offline, about a second
jupyter notebook notebooks/     # run 01 to 05 in order
```

Needs Python 3.12 or later. The first run of each notebook downloads and caches its data
under `data/cache/`. The SEC fundamentals take about an hour the first time; after that
everything runs in minutes. The cache is gitignored. Both audit scripts run offline
against it.

## Limitations

- Yahoo Finance is an unofficial source and about 150 delisted tickers have no price
  history at all. That hits every strategy equally, but SPY implicitly contains those
  names' real returns, so every strategy-versus-index comparison is slightly flattered.
- Stocks delisted mid-holding are dropped rather than booked at a loss. That's optimistic
  and the engines say so.
- The cost model is flat. It's realistic at small size for S&P 500 names and thinnest for
  the short book of the long-short strategy, where spreads are widest.
- Not done: per-stock slippage, a quality factor, anything outside the S&P 500. I'm
  rebuilding this as a proper platform in [quantlab](https://github.com/Rossod4/quantlab)
  with those gaps designed in from the start.

## How I built it

I used [Claude Code](https://claude.com/claude-code) for most of the actual code. The
research questions, the strategy parameters, the evaluation choices and the decisions
about what counts as a fair test are mine, and I reviewed every design decision as it
went in. Each phase is a separate commit saying what changed and why, and the two review
documents record what I checked and what I found.

Written by Alex Gard. MIT licence, see [`LICENSE`](LICENSE).
