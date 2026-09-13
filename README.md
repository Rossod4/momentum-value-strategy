# Momentum and Value Strategy Backtester

[![tests](https://github.com/Rossod4/momentum-value-strategy/actions/workflows/tests.yml/badge.svg)](https://github.com/Rossod4/momentum-value-strategy/actions/workflows/tests.yml)

A Python backtester for two classic equity factor strategies, momentum and value, on the
S&P 500 from 2012 to 2026. The point of the project is not the headline returns but the
discipline around them: point-in-time index membership, fundamentals gated on the date
they were actually filed, a transaction cost and capacity model, long-short variants, and
a walk-forward test that overturned the project's own best-looking result.

Built by [Alex Gard](mailto:arwgard@icloud.com), a Mathematics student at the University
of Bristol, to understand how these strategies behave and to have a project where every
design decision can be defended in an interview.

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

Figures are from the committed notebook runs (August and September 2026) and move by a
few tenths of a percent between data refreshes; SPY is measured at each strategy's own
rebalancing frequency, hence the range. Three findings matter more than the numbers:

- **The long-only strategies beat the index on return but not on risk-adjusted return.**
  SPY has the highest Sharpe ratio in the table. Neither strategy is a free lunch.
- **The classic dollar-neutral momentum factor was flat over this window**, and stays
  flat in both halves, under a 6-1 construction, and in over half of rolling 3-year
  windows. This matches the published post-2009 momentum-crash literature. The 130/30
  structure, which keeps most of the long book, is the practically interesting variant.
- **"The 50/50 blend is best" did not survive out-of-sample.** Choosing the blend weight
  from trailing data would have underperformed every fixed weight, and the chosen weight
  jumped around from year to year. The defensible claim is weaker: any fixed blend did
  fine, none was reliably best, and timing the blend made things worse.

The full reasoning, including three bugs found and fixed during review, is in
[`REVIEW.md`](REVIEW.md) and [`REVIEW_PHASE5.md`](REVIEW_PHASE5.md). If you read one
file, read the second.

## What was built, in order

| Phase | Notebook | What it adds |
|---|---|---|
| 1 | [`01_momentum_backtest`](notebooks/01_momentum_backtest.ipynb) | Long-only 12-1 momentum on point-in-time S&P 500 membership, turnover-based costs, monthly rebalancing |
| 2 | [`02_value_backtest`](notebooks/02_value_backtest.ipynb) | Value composite (P/B, P/E, EV/EBITDA, growth-adjusted) on a from-scratch SEC EDGAR data layer where every figure is gated on its filing date |
| 3 | [`03_strategy_comparison`](notebooks/03_strategy_comparison.ipynb) | Head-to-head comparison and fixed-weight blends |
| 4 | [`04_long_short_momentum`](notebooks/04_long_short_momentum.ipynb) | Dollar-neutral and 130/30 long-short momentum with per-book costs and a borrow fee |
| 5 | [`05_walk_forward_and_robustness`](notebooks/05_walk_forward_and_robustness.ipynb) | Rolling-window consistency, walk-forward test of the blend weight, robustness of the flat long-short result |

The notebooks are committed with their outputs, so the results can be read on GitHub
without running anything.

## How bias is handled

- **Look-ahead.** Momentum scores use only month-end prices at and before the formation
  date. Fundamentals use only filings whose `filed` date is on or before the rebalance
  date, not the fiscal period they describe. Restated figures keep only the version that
  was public at the time.
- **Survivorship.** The universe at each rebalance is the S&P 500 as it was on that
  date. The one known gap, historical members with no SEC ticker mapping, is measured
  rather than footnoted: about 2% of the average quarter's names, with a return tilt
  that is statistically indistinguishable from zero. See
  [`scripts/coverage_gap_analysis.py`](scripts/coverage_gap_analysis.py).
- **Costs.** A flat 10 bps one-way cost, charged on both sides of every replacement, is
  stress-tested against estimated spreads and a computed capacity ceiling of roughly
  $100 to 350 million. See [`scripts/cost_realism_analysis.py`](scripts/cost_realism_analysis.py).
- **Data snooping.** Every strategy parameter is a fixed textbook choice. The one
  conclusion that was read off the data, the best blend weight, is the one that got a
  walk-forward test.
- **Reproducibility.** Runs are bit-for-bit identical run to run. The test suite is
  offline and deterministic.

## Project structure

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
without touching signal or backtest logic.

## Run it

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows; source .venv/bin/activate elsewhere
pip install -r requirements.txt
python -m pytest tests/         # offline, about a second
jupyter notebook notebooks/     # run 01 to 05 in order
```

Requires Python 3.12 or later. The first run of each notebook downloads and caches its
data under `data/cache/`, which takes an hour or so for the SEC fundamentals; every run
after that is minutes. The cache is gitignored. Both audit scripts run offline against it.

## Limitations

- Yahoo Finance is an unofficial source and roughly 150 delisted tickers have no price
  history at all. This affects every strategy equally, but SPY implicitly contains those
  names' real returns, which slightly flatters every strategy-versus-index comparison.
- Delistings mid-holding are dropped rather than booked at a loss. This is optimistic
  and is disclosed in the engines.
- The cost model is flat. It is realistic at small size for S&P 500 names and thinnest
  for the short book of the long-short strategy, where spreads are widest.
- Planned extensions, not started: per-stock slippage, a quality factor, universes
  beyond the S&P 500. The successor project, [quantlab](https://github.com/Rossod4/quantlab),
  rebuilds this as a platform with these gaps designed in from the start.

## How this was built

Built with [Claude Code](https://claude.com/claude-code), an AI coding assistant. I set the
research questions, chose every strategy parameter and evaluation criterion, and reviewed
each design decision; the assistant wrote most of the code. Every phase was committed
separately with a message saying what changed and why, and the two review documents
record what was checked and what was found. I can explain any part of it.

## License

MIT. See [`LICENSE`](LICENSE).
