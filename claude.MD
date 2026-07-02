# Project context

## Who I am
I'm Alex Gard, a second-year Mathematics student at the University of Bristol (1:1 track, 88.8% second-year average, 1:1 first and second year), looking to break into a quantitative/analytical finance career — currently exploring quant trading, actuarial, and traditional finance/investment banking through work experience. I'm comfortable with Python, R/MATLAB, and Excel-based financial modelling, but I'm not a professional software engineer.

## What I'm building
A Python-based stock screener and strategy backtesting tool. I want to:
- Screen stocks/ETFs against configurable criteria (value, momentum, quality, or similar factors)
- Backtest one or more screening strategies against historical data
- Evaluate strategies properly (e.g. Sharpe ratio, max drawdown, CAGR, benchmark comparison) rather than just eyeballing returns
- Produce verifiable results
- Account for real world variables such as slippage and fees
- Stratergies should be able to function well in the real world

## Why I'm building it
Two goals, in this order:
1. **Genuine personal interest** — I want to actually understand how these strategies perform and why, not just have a working script.
2. **A CV/interview talking point** — I want to be able to open this code cold in an interview and explain every design decision: why this metric, why this universe of stocks, why this lookback window, what the code does line by line if asked.

## How I want to work with you
I'm using Claude Code deliberately and openly — I'm not trying to hide that. But the bar for me is: I need to be able to defend and explain every part of this project, not just that it runs. So please:
- Explain your reasoning as you go, not just the code — especially for strategy logic and evaluation choices, which I want to make/understand myself rather than just accept
- Boilerplate (data pulling, plotting setup, backtest loop scaffolding) can move fast
- Where you make a non-obvious design choice, flag it and briefly say why, so I can push back or ask questions
- Check in with me before big structural decisions rather than assuming and building ahead
- As you write code, make sure the code is all readable to a novice coder, including relavent comments

## What I want you to do right now
Before writing any code, ask me clarification questions about the project's goals and objectives — things like: what data source to use, what universe of stocks/assets, which strategies/factors I actually want to test first, what timeframe and rebalancing frequency, what "success" looks like for a strategy, how deep I want the evaluation to go, and what the eventual deliverable should look like (script, notebook, simple dashboard, etc.). Ask me one focused round of questions before we start building.