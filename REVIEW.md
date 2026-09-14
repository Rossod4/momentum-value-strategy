# Project Review — Momentum & Value Strategy Backtester

*Full-project review carried out 2 July 2026, after the Phase 2 (value) work merged.
Scope: verify both strategies against the project's goals — reliable, verifiable,
no-look-ahead, cost-aware, reproducible — fix what needed fixing, and add the
Phase 3 comparison/blending layer. Everything below is written to be readable
without a software background; every change is explained with its reasoning.*

---

## 1. Verdict in one paragraph

The project is in good shape. Both strategies are correctly built point-in-time
(no look-ahead bias found anywhere — checked line by line and confirmed by the
test suite), they share config/costs/evaluation code cleanly, and the value
strategy's honest labelling and documented limitations carry the project's
standards through. The review found **three genuine correctness issues** — all
now fixed and tested: transaction costs were charged on only one side of each
trade (understating them by roughly half), the SPY benchmark quietly covered
13 more months than the strategies it was compared against, and repeated runs
weren't bit-for-bit identical because delisted tickers were re-downloaded every
run. After the fixes: **all 82 tests pass, and running each backtest twice
produces exactly identical results.**

---

## 2. What was audited, and what passed

| Check | Result |
|---|---|
| No look-ahead bias (both strategies) | **Pass.** Momentum only uses prices dated ≤ each rebalance date. Value gates every SEC figure on its *filed* date (not the fiscal period it describes) — verified in `fundamentals.py` and its tests. |
| Survivorship bias | **Pass, with a known caveat.** Both strategies use point-in-time S&P 500 membership. The value strategy has a *data-coverage echo* of survivorship bias: SEC's ticker mapping only covers currently-registered filers, so ~24% of the historical universe (mostly long-gone acquired companies) has no fundamentals. This was already documented honestly in notebook 02 — nothing hidden. |
| Design matches what was agreed | **Pass.** Composite value factor (P/B + P/E + EV/EBITDA + growth-adjusted value), percentile ranks not z-scores, quarterly rebalance, top-50, SEC EDGAR source, loss-makers ranked least-attractive rather than excluded, factor honestly *not* called PEG. VIX overlay deferred as agreed, not silently dropped. |
| Code consistency between strategies | **Pass.** Value reuses momentum's genuinely shared pieces (holding-period return with the vendor-glitch guard, benchmark, turnover/costs, metrics) rather than duplicating them. The separate quarterly engine is justified in its docstring and I agree with the call. |
| Test coverage | **Pass.** Value arrived with its own offline, hand-computable test suites (signal + fundamentals extraction), mirroring Phase 1's. This review added three more test files (details below). Suite: **82 tests, all green, runs in ~1 second offline.** |
| Evaluation depth | **Pass.** Both report CAGR, volatility, Sharpe, max drawdown, gross vs net, benchmark comparison, via the same `src/evaluation/metrics.py` code, with the annualization factor handled correctly for quarterly data. |
| Reproducibility | **Failed initially — now fixed.** See issue 3 below. Both backtests now produce bit-for-bit identical results run to run (verified by running each twice and comparing every number). |

---

## 3. Issues found and fixed

### Fix 1 — Transaction costs only charged one side of each trade
**File:** `src/costs/transaction_costs.py` (+ its tests)

Replacing a holding is two trades: you **sell** the outgoing stock *and* **buy**
the incoming one, and each trade pays its own commission/spread/impact. The old
formula charged `turnover × 10bps`; since `turnover` counts the *fraction of
names replaced*, that priced only one of the two trades — understating costs by
roughly half. The formula is now `2 × turnover × 10bps`. One knock-on effect,
accepted deliberately: the very first rebalance (all buys, nothing to sell) is
now overcharged by at most 10bps, once — a conservative error in the safe
direction, preferred over special-casing the first period in both engines.

*Effect on results: momentum's cost drag roughly doubled to ~0.8%/year (it
trades monthly); value's to ~0.2%/year (it trades quarterly). Direction of all
conclusions unchanged.*

### Fix 2 — The SPY benchmark covered a different window than the strategies
**File:** `src/data_layer/prices.py` (+ new `tests/test_prices.py`)

The price cache stores each ticker's *full downloaded history*. When the
benchmark asked for SPY from 2012, it silently received data back to December
2010 — the extra 13 months momentum's signal warm-up had downloaded. So SPY's
CAGR and max drawdown were being measured over a *longer, different* market
period than the strategies (including the ~19% drawdown of late 2011, which the
strategies never faced — flattering their relative drawdown). `get_prices()` now
trims its output to exactly the requested window; a regression test locks this in.

### Fix 3 — Results weren't reproducible run-to-run (and why that mattered)
**File:** `src/data_layer/prices.py` (+ tests)

Running the same backtest twice gave results differing in the 8th decimal
place. Diagnosis: 72 tickers that were **delisted mid-window** (their prices
legitimately stop in, say, 2015) looked "stale" to the cache — which judged
completeness by the data's last date — so they were re-downloaded on *every*
run, and Yahoo's adjusted prices drift microscopically between downloads. The
portfolios chosen were identical; only the prices wobbled. Each ticker's cache
now records **what date range was requested** when it was written, so a
delisted ticker fetched once for 2012–2026 is trusted permanently. This also
makes every run after the first faster. Verified: two full runs of each
strategy now match exactly, number for number.

### Housekeeping (small, zero-risk)
- Removed two lines of dead code in `value_engine.py` (a condition that could never be true).
- Removed `tqdm` from `requirements.txt` (declared but never used).
- Rewrote the stale `README.md` status section (it still said "Phase 1 in
  progress, no transaction costs modelled") and added a how-to-run section.

---

## 4. New in this review: head-to-head comparison and blends (Phase 3)

**New files:** `src/evaluation/comparison.py`, `tests/test_comparison.py`,
`notebooks/03_strategy_comparison.ipynb`.

### Side by side, net of costs (2012–2026, each at its native frequency)

| | Momentum (monthly) | Value (quarterly) | SPY Buy & Hold |
|---|---|---|---|
| CAGR (net) | 15.7% | 16.1% | 14.5% |
| Annualized volatility | 16.9% | 17.1% | 14.1% |
| Sharpe ratio (net) | 0.96 | 0.94 | 1.05 |
| Max drawdown (net) | −19.7% | −33.8% | −23.9% |
| CAGR vs SPY | +1.2% | +1.6% | — |
| Cost drag (CAGR) | 0.78%/yr | 0.22%/yr | — |
| Avg turnover per rebalance | 28.8% | 25.2% | — |

**The honest reading:** both strategies beat SPY on raw return, but **neither
beats it risk-adjusted** in this window — SPY's Sharpe of 1.05 tops both. That
is a fair and unsurprising result: 2012–2026 was a strong, low-volatility bull
market, the easiest possible environment for buy-and-hold. It is worth
stating plainly — a backtester that never delivers an awkward result would be
suspicious.

### The blend sweep (common quarterly window, rebalanced to target weights quarterly)

| | 100% Mom | 75/25 | 50/50 | 25/75 | 100% Val |
|---|---|---|---|---|---|
| CAGR | 16.1% | 16.2% | **16.3%** | 16.2% | 16.1% |
| Annualized volatility | 17.3% | 16.4% | **16.1%** | 16.3% | 17.1% |
| Sharpe ratio | 0.93 | 0.98 | **1.00** | 0.98 | 0.94 |
| Max drawdown | −19.1% | −22.7% | −26.4% | −30.1% | −33.8% |

**This is the review's most interesting result.** The 50/50 blend has a *higher
return, lower volatility, and higher Sharpe than either pure strategy* — the
classic diversification pattern, showing up in real data even though the two
strategies' quarterly returns are fairly correlated (0.75). Momentum and
value's bad periods don't fully overlap, and the blend smooths both. (Max
drawdown, unlike Sharpe, just slides from momentum's to value's — blending
diluted value's deep 2022-style drawdowns rather than eliminating them.)

### Try any split yourself

In `notebooks/03_strategy_comparison.ipynb` (section 6), edit one number:

```python
blend = combine_strategies(momentum_result.net_returns, value_result.net_returns, 0.6)
blend.metrics   # CAGR, vol, Sharpe, max drawdown for 60% momentum / 40% value
blend.equity    # growth-of-$1 curve, plottable directly
```

**One convention to know (and challenge if you disagree):** blends are
evaluated *quarterly*, because value's returns only exist quarterly — a monthly
blend would require inventing value's intra-quarter path. The blend is pulled
back to its target split every quarter (otherwise "50/50" would drift toward
whichever sleeve was winning). The small trades that re-balancing between the
two sleeves requires are *not* separately costed — roughly a basis point per
quarter of missing drag on mixed blends; the pure 100/0 and 0/100 columns are
unaffected. All of this is documented in `comparison.py`'s module docstring.

---

## 5. Flagged for you — not changed, your call

1. **~20% of the historical universe has no price data at all** (159 tickers).
   Most are long-delisted names Yahoo no longer serves (expected, and disclosed
   in notebook 01), but a handful look like *live or recently-renamed* large
   caps (e.g. K, WBA, MMC, HES, DFS) that yfinance failed with throttling-style
   errors. Both strategies simply never see these names. Worth a one-off retry
   some evening, or a manual ticker-mapping pass — could nudge results either way.
2. **The data cache is gitignored**, so a fresh clone re-downloads everything.
   SEC fundamentals re-fetch *reproducibly* (the filed-date gating means
   historical answers can't change), but **yfinance prices can drift** (Yahoo
   restates adjusted prices when dividends occur, and serves slightly different
   precision over time). If long-term result stability matters to you, consider
   committing `data/cache/` (~a few hundred MB) or a dated snapshot of it.
   Reproducibility *on this machine, with this cache* is now exact.
3. **The value strategy's fundamentals cache was rebuilt from SEC during this
   review** (the Phase 2 session's cache wasn't committed). ~610 companies
   fetched; results matched the design expectations. Same recommendation as
   above if you want it durable.
4. **Missing-forward-price handling remains slightly optimistic** (a stock
   delisted mid-holding-period is dropped from that period's average rather
   than booked as a loss). Already disclosed in notebook 01's limitations; both
   engines report the count (it was 0 across both full runs, so currently moot).

---

## 6. Verification evidence

- `python -m pytest tests/` → **82 passed** (~1s, fully offline).
- Each backtest run twice, results compared element-by-element → **exactly
  identical** (`momentum_run1_equals_run2: true`, `value_run1_equals_run2: true`).
- Benchmark and strategy first-return dates now align exactly (monthly:
  2012-02-29; quarterly: 2012-06-30) — the Fix 2 misalignment is gone.
- `notebooks/03_strategy_comparison.ipynb` executed end-to-end from a cold
  kernel against the real cache; all tables and plots render. (Notebooks are
  kept unexecuted on disk, matching the project's convention.)
- Blend endpoint sanity: a 100%-momentum "blend" exactly reproduces the pure
  momentum series, and 0% exactly reproduces value (locked in as unit tests).

## 7. What changed, file by file

| File | Change |
|---|---|
| `src/costs/transaction_costs.py` | Cost formula now charges both sides of each trade (Fix 1) |
| `src/data_layer/prices.py` | Output trimmed to requested window (Fix 2); cache metadata sidecars for delisted tickers (Fix 3) |
| `src/backtest/value_engine.py` | Two lines of dead code removed |
| `src/evaluation/comparison.py` | **New** — side-by-side table, `combine_strategies`, blend sweep |
| `notebooks/03_strategy_comparison.ipynb` | **New** — comparison & blending notebook |
| `tests/test_prices.py` | **New** — regression tests for Fixes 2 & 3 |
| `tests/test_comparison.py` | **New** — blend math, endpoints, weight validation |
| `tests/test_costs.py` | Updated for the corrected cost formula |
| `src/config.py` | Comment clarifying the one-way-cost convention |
| `README.md` | Status brought up to date; how-to-run section added |
| `requirements.txt` | Unused `tqdm` removed |

Nothing has been committed — everything is in the working tree so you can
review the full diff (`git diff`) alongside this document and commit it
yourself when you're happy.
