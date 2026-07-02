# Phase 5 Review — Consolidation, Bias Audit, and Out-of-Sample Honesty

*Carried out 2 July 2026, after all four phases were built. Scope, agreed
up front: merge the three git branches into one coherent history, then
re-audit the whole project against its own stated bar — "strategies should
actually be profitable in the real world and we should be able to verify
that without any bias" — including the Phase 4 long-short code the previous
review (REVIEW.md) never saw. Three ground rules were fixed before any work
started: results are reported as honest numbers with no pass/fail verdicts;
the data-snooping question gets a real walk-forward test, not a footnote;
and the flat dollar-neutral result gets a robustness check, not a rescue.*

---

## 1. Verdict in one paragraph

The project consolidates cleanly and its core discipline holds up: the
look-ahead re-audit passed everywhere, including Phase 4, and this
review's two headline additions both produced honest, slightly
uncomfortable findings that make the project *more* defensible, not less.
First: the full-sample claim that "the 50/50 momentum/value blend is best"
does **not** survive a walk-forward test — an investor picking the
best-looking blend weight from trailing data would have *underperformed*
every fixed weight, and fixed 50/50 out-of-sample is roughly tied with
pure momentum rather than clearly superior. Second: the dollar-neutral
long-short's flatness is **robust** — it is flat in both halves of the
window, flat under a 6-1 construction, and negative in 59% of rolling
3-year windows, which is exactly what the post-2009 momentum-crash
literature predicts. The survivorship coverage gap, measured rather than
footnoted, shows a small upward tilt (~2%/yr on the measurable slice) that
is statistically indistinguishable from noise; the cost model is realistic
at small scale with a measured capacity ceiling of roughly $100–350M. All
106 tests pass.

---

## 2. Branch consolidation

The three branches turned out to be a fully **linear** history, not a real
divergence: `long-short-momentum` was `master` plus exactly one commit
(Phase 4), and the stale `value-strategy` branch's single commit was
already contained in `master`. So "merging" was a fast-forward, with
nothing to resolve and nothing lost:

- `master` fast-forwarded to include Phase 4 (plus the CLAUDE.md edit
  adding the real-world-viability goal), and pushed.
- Local `long-short-momentum` deleted (fully merged).
- `value-strategy` is fully merged too, but its local branch can't be
  deleted until the old `MomentumValueStrategy-value` worktree folder is
  removed — that folder was verified to contain **no** uncommitted,
  stashed, or unpushed work (its data cache duplicates the main repo's),
  so it's safe to delete manually, after which
  `git branch -d value-strategy` completes the cleanup.

## 3. Look-ahead bias — re-verified from scratch, including Phase 4

Per the mandate, the prior audit's "pass" was not trusted; every signal
computation was re-checked against its rebalance date:

| Component | Check | Result |
|---|---|---|
| Momentum signal (`momentum.py`) | Scores at formation date use only month-end prices at formation−1 and formation−12; names lacking either price are excluded before selection | **Pass** |
| Long-short engine (`long_short_engine.py`) — *new since REVIEW.md* | Both books read from ONE ranking built at formation; membership as-of formation; returns booked at the next month-end; per-book turnover against each book's own prior holdings | **Pass** |
| Bottom-book NaN risk | A subtle failure mode checked specifically: could the short book fill with insufficient-history names ranked "low" because their score was NaN? No — `compute_momentum_signal` drops invalid names before `select_bottom_n` ever sees them | **Pass** |
| Value fundamentals (`fundamentals.py`) | Every extraction path (`_most_recent_instant_with_end`, `_duration_facts`, and everything built on them) filters `filed <= as_of_date` before touching values; restated quarters keep only versions filed by the as-of date | **Pass** |
| Constituents (`constituents.py`) | `asof` lookup returns the last membership change dated ≤ the rebalance date | **Pass** |
| Benchmark | First return date aligns with each strategy's first realized return (the Fix 2 regression test still guards this) | **Pass** |

## 4. Survivorship — the coverage gap, measured instead of footnoted

The known issue: SEC's ticker→CIK mapping only covers currently-registered
filers, so part of the historical universe has no fundamentals and is
invisible to the value strategy. The "~24%" headline figure needed
decomposing, because it mixes two very different problems
(`scripts/coverage_gap_analysis.py` reproduces all of this offline):

- **85.5%** of the average quarter's members are covered (fundamentals +
  prices) — the value strategy's actual ranking pool.
- **1.9%** (avg ~10 names/quarter, 26 early falling to 2 late) have
  prices but no fundamentals — the *measurable* gap.
- **12.6%** (avg ~63, 112 early falling to 1 late) have no price data at
  all — unmeasurable, but crucially invisible to **every** strategy in
  this project, momentum included, so it's a project-wide data limitation
  rather than a value-specific bias.

For the measurable slice: covered names returned ~14.7%/yr vs ~12.7%/yr
for uncovered — a **+2%/yr tilt in the strategy's favor, but with a
t-statistic of 0.47**, i.e. statistically indistinguishable from noise
(the uncovered group is tiny, so its per-year returns swing ±30%). One
honesty caveat cuts the other way: ~40% of uncovered ticker-quarters end
in a mid-quarter delisting, which the return calculation drops rather than
books (the same optimistic simplification the engines disclose) — and
delistings skew bad — so +2%/yr is best read as a **lower bound** on the
tilt. The fair summary: *a small upward bias in the value strategy's favor
probably exists, it cannot be distinguished from zero with this data, and
the truly unmeasurable part of the universe affects every strategy here
equally — while SPY, which implicitly contains those names' real returns,
does not suffer it at all.* That last asymmetry slightly flatters every
strategy-vs-SPY comparison in this project and is now stated wherever
those comparisons appear.

## 5. Real-world frictions — the 10bps assumption, stress-tested

`scripts/cost_realism_analysis.py` checks the flat 10bps one-way cost
against the cached market data two ways:

- **Spreads**: a Corwin-Schultz high-low estimate puts the median
  member's full spread at ~21bps (half-spread ~10bps) — but CS is a known
  *over*-estimator for liquid large-caps (overnight gaps leak in), and
  true quoted half-spreads for S&P 500 names are typically 1–5bps. Read
  together: 10bps one-way comfortably covers half-spread + commission for
  this universe, with headroom for impact at small size.
- **Capacity**: an equal-weight 50-name portfolio trades 2%-of-capital
  slices; bounding each trade at 5–10% of the least-liquid likely
  holding's daily dollar volume gives a ceiling of roughly **$95M–$335M
  AUM**. Below that, the flat cost is realistic-to-conservative; near or
  above it, market impact would grow past anything 10bps covers.

**Decision: keep the flat model, label it honestly.** The alternative — a
per-stock spread/impact model — would need reliable historical quote and
volume-profile data this project doesn't have; modelling it "precisely"
anyway would be false precision. Where the assumption is thinnest is the
long-short strategy's **short book**: bottom-momentum names have the
widest spreads (p90 half-spread ~18bps by CS) and the 30bps blended borrow
fee understates genuinely hard-to-borrow names — both were already
sensitivity-tested in notebook 04, and are now flagged as the cost model's
weakest corner.

## 6. Data-snooping — the walk-forward test (the review's headline)

Everything in this project had been measured on the same 2012–2026 window,
with four strategies and a blend sweep tried on it. The strategies
themselves carry real protection — every parameter (12-1 momentum, the
value composite, top-50, quarterly cadence) is a fixed textbook choice,
never fitted to this data — so classic "refit the strategy" walk-forward
has nothing to refit. But one conclusion **was** effectively fitted: Phase
3's "the 50/50 blend has the best Sharpe," read off a full-sample table.
That claim got the two standard honesty checks
(`src/evaluation/walk_forward.py`, tested in `tests/test_walk_forward.py`,
run end-to-end in `notebooks/05_walk_forward_and_robustness.ipynb`):

**Rolling 3-year windows** (no fitting — just consistency): momentum's
3-year CAGR ranges +1.8% to +30.2% (median +11.3%) with *zero* negative
windows; value ranges −4.1% to +24.5% (median +15.0%, 2% of windows
negative); SPY ranges +4.8% to +24.9% (median +12.8%). Nobody's headline
number is one lucky stretch — but note SPY's *floor* is the highest of the
three.

**Walk-forward on the blend weight**: at each step, the weight with the
best Sharpe over the trailing 5 training years is chosen from the same
coarse grid as Phase 3's table (0/25/50/75/100% momentum), then applied to
the next unseen year, rolling 2017→2026 (37 out-of-sample quarters). Two
findings:

1. **The chosen weight is wildly unstable** — 50%, 50%, 25%, 75%, 50%,
   100%, 75%, 75%, 0%, 25% — the training windows keep "discovering"
   different answers, which is what fitting noise looks like.
2. **Adapting underperforms every fixed weight**: walk-forward Sharpe
   +0.78 vs +0.76–0.86 for the five fixed weights over the same quarters
   (and its max drawdown, −30%, is worse than fixed 50/50's −26%). This
   is robust to the training length — with 3, 5, or 7 training years the
   walk-forward Sharpe (0.75/0.78/0.76) lands below every fixed weight
   tested. Chasing the recently-best blend systematically buys whichever
   sleeve just had its good run.

**The honest restatement of Phase 3's conclusion**: out-of-sample, fixed
50/50 (Sharpe +0.85) is roughly *tied* with pure momentum (+0.85) and
modestly ahead of pure value (+0.76) — the diversification benefit is
real but small, well within noise, and "50/50 is *best*" was partly a
full-sample artifact. What survives is the weaker, more defensible claim:
*any* fixed blend did fine, no fixed blend was reliably best, and trying
to time the blend made things worse. Notebook 03's conclusion now carries
a pointer to this result.

## 7. The dollar-neutral result — robustness-checked, not rescued

The Phase 4 finding (dollar-neutral 12-1 WML: net CAGR +0.5%, Sharpe
+0.12, max drawdown −56%) was deliberately stress-tested to see whether
the flatness was a window artifact. It is not:

| Check | Result |
|---|---|
| Rolling 3-year windows | Median CAGR −1.1%; **58.7% of windows negative**; range −20% to +21% |
| First half (2012–2019Q1) | CAGR +1.4%, Sharpe +0.14 |
| Second half (2019Q2–2026) | CAGR +0.3%, Sharpe +0.11, maxDD −52% |
| 6-1 construction (same everything else) | CAGR +0.6%, Sharpe +0.10 — flat in both halves too |
| Worst months | Nov 2020 (−23.5%), Jan 2023 (−16.7%), Apr 2020 (−14.5%), Feb 2021 (−11.8%) — every one a sharp market **rebound**, the classic momentum-crash signature (short book of crashed losers snaps back violently) |

The conclusion stays exactly as first reported, now with evidence it isn't
fragile: the long-only momentum premium survived this era in this universe;
the classic academic long-short version did not, consistent with published
post-2009 momentum-crash research (Daniel & Moskowitz). The 130/30 variant
(CAGR 16.2%, Sharpe 0.91) remains the practically-interesting long-short
result.

## 8. What changed, file by file

| File | Change |
|---|---|
| `src/evaluation/walk_forward.py` | **New** — rolling-window metrics + walk-forward blend test, with the design conventions (Sharpe criterion, coarse grid, rolling train window) argued in the module docstring |
| `tests/test_walk_forward.py` | **New** — 9 offline tests with hand-computable synthetic cases |
| `scripts/coverage_gap_analysis.py` | **New** — reproduces the §4 survivorship measurement offline |
| `scripts/cost_realism_analysis.py` | **New** — reproduces the §5 spread/capacity measurement offline |
| `notebooks/05_walk_forward_and_robustness.ipynb` | **New** — runs §6 and §7 end-to-end against the real cache |
| `README.md` | Status updated for Phase 5; run instructions include notebook 05 and the scripts |
| `REVIEW_PHASE5.md` | **New** — this document |

Nothing in `src/backtest/`, `src/strategy/`, `src/costs/`, or
`src/data_layer/` changed: the audit found nothing to fix in the engines,
and no result was altered. Every number in earlier documents still stands.

## 9. Verification evidence

- `python -m pytest tests/` → **106 passed**, offline, ~1s.
- The backtests re-run for this review reproduced REVIEW.md's canonical
  numbers exactly (momentum 15.7% / value 16.1% / SPY 14.5% net CAGR) —
  the reproducibility fix from Phase 3 is still holding.
- The ~150 price-download failures printed during any full run are the
  same known-missing tickers REVIEW.md §5.1 already flagged (no cached
  data, Yahoo throttles the retry every run); they fail identically every
  run, so results are unaffected. The one-off retry suggested there
  remains open and worthwhile.
- Both new scripts run offline from the repo root against the existing
  cache; every figure in §4 and §5 comes from their output.
