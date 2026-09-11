# Project context for Claude Code

## What this is
A point-in-time, cost-aware factor-strategy backtester on the S&P 500 (momentum, value, blends,
long-short momentum) with a bias audit and walk-forward test. See README.md for results and
REVIEW.md / REVIEW_PHASE5.md for the audit record. The project is complete as a study; its
successor is the `quantlab` repo in the same parent directory.

## Working conventions
- Explain reasoning, not just code, especially for strategy logic and evaluation choices. The
  owner wants to be able to defend every design decision in an interview.
- Flag non-obvious design choices briefly so they can be questioned.
- Check in before big structural changes rather than building ahead.
- Keep code readable to a novice Python programmer, with relevant comments.
- No chart-pattern or technical-pattern analysis, ever.
- Honest numbers over flattering ones. No result gets rescued; awkward findings are reported as
  found and their provenance recorded.

## Invariants (do not weaken)
- Every signal uses only data available at its formation date.
- Fundamentals are gated on filed date (`filed <= as_of_date`), never period end.
- Index membership is reconstructed as of each rebalance date.
- Costs are charged two-sided on turnover. The benchmark window is aligned to the strategy's
  first realised return.
- `python -m pytest tests/` must stay green and offline. Numerical results in REVIEW.md and
  REVIEW_PHASE5.md are frozen; a change that moves them needs a documented reason.

## Running
```
.venv\Scripts\activate
python -m pytest tests/
jupyter notebook notebooks/
```
The data cache under `data/cache/` is gitignored and regenerated on first notebook run.
