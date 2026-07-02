# Momentum & Value Strategy Backtester

A Python stock screener and strategy backtesting tool for evaluating factor-based strategies (momentum first, value/quality to follow) against historical market data — with proper performance evaluation (Sharpe ratio, max drawdown, CAGR, benchmark comparison) rather than just eyeballing returns.

## Why this project exists

Built by [Alex Gard](mailto:arwgard@icloud.com), a Mathematics student at the University of Bristol, for two reasons:

1. Genuine interest in understanding how these strategies actually perform and why.
2. A portfolio piece for quant/analytical finance work — every design decision here should be explainable, not just functional.

## Status

**Phase 1 (complete):** a long-only, equal-weight, S&P 500 momentum strategy (classic 12-1 month
formation), monthly-rebalanced, backtested 2012–2026 on point-in-time index membership, net of a
turnover-based transaction cost model. See `notebooks/01_momentum_backtest.ipynb`.

**Phase 2 (complete):** a long-only, equal-weight, quarterly-rebalanced value composite
(P/B + P/E + EV/EBITDA + growth-adjusted value) built on a from-scratch, point-in-time SEC EDGAR
fundamentals data layer — every figure gated on the date it was actually *filed*, to enforce the
same no-look-ahead discipline as Phase 1. See `notebooks/02_value_backtest.ipynb`.

**Phase 3 (complete):** head-to-head comparison of the two strategies plus fixed-weight
momentum/value blends at any split, with the full metric set for each. See
`notebooks/03_strategy_comparison.ipynb` and `src/evaluation/comparison.py`.

**Phase 4 (complete):** a LONG-SHORT momentum strategy — long the 50 highest-momentum names,
short the 50 lowest, using the exact Phase 1 signal/universe/window — at configurable exposures
(the classic dollar-neutral 1.0/1.0 academic factor and the practical 130/30 fund structure),
with per-book turnover costing and a sensitivity-tested stock-borrow fee. See
`notebooks/04_long_short_momentum.ipynb`.

Planned extensions: deeper slippage modelling, a quality factor, and universe expansion beyond
the S&P 500.

## How to run it

```
python -m venv .venv
.venv\Scripts\activate          # Windows (source .venv/bin/activate on Mac/Linux)
pip install -r requirements.txt
python -m pytest tests/         # fast, offline - should be all green
jupyter notebook notebooks/     # then run 01, 02, 03, 04 in order
```

The first run of each notebook downloads and caches its data (prices from yfinance, fundamentals
from SEC EDGAR) under `data/cache/` — slow once, fast forever after. The cache is gitignored;
see the reproducibility notes in `REVIEW.md`.

## Design principles

- **Swappable data layer** — strategy logic never talks to a data vendor directly, so the data source (currently `yfinance`) can be replaced without touching signal or backtest code.
- **Config-driven parameters** — lookback windows, portfolio size, and dates live in one place, not hardcoded across modules.
- **Built to extend** — each new phase (costs, additional factors, new universes) is designed to slot in rather than require a rebuild.

## Development history

This project is built iteratively and transparently with Claude Code assistance — each step is committed individually with a message describing what changed and why, so the project's evolution (and any past state) is always recoverable.
