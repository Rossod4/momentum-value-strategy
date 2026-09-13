# CLAUDE.md

Guidance for Claude Code when working in this repository.

## Project

A backtester for momentum and value strategies on the S&P 500, 2012 to 2026, built as a
learning project and interview portfolio piece by Alex Gard (Mathematics, University of
Bristol). All five planned phases are complete. Read `README.md` for the results and
`REVIEW.md` / `REVIEW_PHASE5.md` for the reasoning behind every design choice. The
successor platform is `Rossod4/quantlab`; new platform work goes there, not here.

## Commands

```bash
python -m pytest tests/                   # offline, deterministic, ~1s, must stay green
jupyter nbconvert --to notebook --execute --inplace notebooks/0N_*.ipynb   # re-run one notebook
python scripts/coverage_gap_analysis.py   # reproduces REVIEW_PHASE5 section 4 from the cache
python scripts/cost_realism_analysis.py   # reproduces REVIEW_PHASE5 section 5 from the cache
```

Notebooks are committed **with outputs**. If you change anything a notebook depends on,
re-run it and commit the executed version. Notebook 02 takes about 20 minutes with a warm
cache; a cold cache adds an hour of SEC EDGAR downloads.

## Invariants

- **No look-ahead.** Signals at a rebalance date may use only prices dated on or before
  it and only fundamentals whose `filed` date is on or before it. Tests in
  `tests/test_fundamentals.py` and `tests/test_momentum.py` guard this; extend them if
  you add a data path.
- **Point-in-time universe.** Membership comes from `data_layer/constituents.py` as-of
  the rebalance date. Never use current membership.
- **Costs are charged on both sides** of every replacement (`2 x turnover x cost_bps`).
  See REVIEW.md fix 1 before touching `costs/transaction_costs.py`.
- **Benchmark windows match strategy windows.** `get_prices()` trims to the requested
  range; REVIEW.md fix 2 explains why.
- **Reproducibility.** Cache entries record the date range they were fetched for, so
  delisted tickers are not re-downloaded. Do not change cache semantics casually.
- **Parameters live in `src/config.py`** with the reasoning in comments. Do not hardcode
  lookbacks, portfolio sizes or dates elsewhere.

## Conventions

- Code must be readable by a novice: plain names, comments that say why, no cleverness.
- Non-obvious design choices get flagged in the commit message and, if they change a
  result, in the relevant review document.
- Results are reported as honest numbers. No pass/fail verdicts, no tuning until a
  result looks better, no quietly dropping an unflattering finding.
- Dependencies are pinned in `requirements.txt`. Bump deliberately and re-run the tests
  and one notebook.
