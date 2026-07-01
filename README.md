# Momentum & Value Strategy Backtester

A Python stock screener and strategy backtesting tool for evaluating factor-based strategies (momentum first, value/quality to follow) against historical market data — with proper performance evaluation (Sharpe ratio, max drawdown, CAGR, benchmark comparison) rather than just eyeballing returns.

## Why this project exists

Built by [Alex Gard](mailto:arwgard@icloud.com), a Mathematics student at the University of Bristol, for two reasons:

1. Genuine interest in understanding how these strategies actually perform and why.
2. A portfolio piece for quant/analytical finance work — every design decision here should be explainable, not just functional.

## Status

**Phase 1 (in progress):** a long-only, equal-weight, S&P 500 momentum strategy (classic 12-1 month formation), backtested over ~10-15 years, evaluated against core metrics (CAGR, volatility, Sharpe, max drawdown, benchmark comparison). No transaction costs modelled yet.

Planned next phases: transaction cost/slippage modelling, value and quality factors, deeper robustness testing, and universe expansion beyond the S&P 500.

## Design principles

- **Swappable data layer** — strategy logic never talks to a data vendor directly, so the data source (currently `yfinance`) can be replaced without touching signal or backtest code.
- **Config-driven parameters** — lookback windows, portfolio size, and dates live in one place, not hardcoded across modules.
- **Built to extend** — each new phase (costs, additional factors, new universes) is designed to slot in rather than require a rebuild.

## Development history

This project is built iteratively and transparently with Claude Code assistance — each step is committed individually with a message describing what changed and why, so the project's evolution (and any past state) is always recoverable.
