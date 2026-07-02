"""
Coverage-gap bias quantification (Phase 5 audit).

The value strategy can only rank names that have SEC fundamentals coverage.
The uncovered remainder of the point-in-time universe skews toward
delisted/acquired names, which raises the survivorship question: does
excluding them bias the value backtest's returns UP (if the excluded names
underperformed) or DOWN (if they were, say, acquisition targets that got
bought out at a premium)?

Rather than footnoting that as an unknown, this script measures it, as far
as the data allows. At each quarter-end formation date, the point-in-time
S&P 500 membership splits into three groups:

  - covered:     fundamentals exist in the cache - the names the value
                 strategy could actually rank (same set the backtest's
                 facts_by_ticker contains)
  - uncovered:   no fundamentals, but price data exists - so their
                 subsequent returns ARE measurable, and the covered-vs-
                 uncovered return spread is a direct estimate of the
                 selection tilt
  - unpriceable: no price data at all - unmeasurable either way. These
                 names are invisible to EVERY strategy in this project
                 (momentum included), not just value, so they're a
                 project-wide data limitation, not a value-specific one.

Each group's equal-weight next-quarter return uses the SAME logic as the
engines (compute_holding_period_return, including the >300% vendor-glitch
guard - which matters here, because delisted tickers are exactly where
glitches like the CBE case live).

Interpretation caveat, stated up front: the uncovered group's members
frequently delist mid-quarter, and a delisting quarter is DROPPED from the
group average (same optimistic simplification as the engines, disclosed in
notebook 01). Delistings are more often bad news than good, so the
uncovered group's measured return is likely somewhat overstated - meaning
the covered-minus-uncovered spread printed here is best read as a LOWER
bound on the tilt, not a precise estimate.

Run from the repo root (offline - uses the existing data cache):

    python scripts/coverage_gap_analysis.py
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.backtest.engine import compute_holding_period_return
from src.config import DEFAULT_VALUE_CONFIG as CFG
from src.data_layer.constituents import get_membership, load_constituents_table

CACHE = CFG.cache_dir

# --- 1. Coverage sets, straight from what's on disk (offline) ---
fundamentals_covered = {p.stem for p in (CACHE / "fundamentals").glob("*.parquet")}
priced = {p.stem for p in (CACHE / "prices").glob("*.parquet")}

# --- 2. Point-in-time membership at each quarter-end ---
constituents = load_constituents_table(cache_dir=CACHE)
quarter_ends = pd.date_range(CFG.start_date, CFG.end_date, freq=CFG.rebalance_freq)

ever_members: set[str] = set()
membership_by_date = {}
for d in quarter_ends:
    m = get_membership(d, constituents)
    membership_by_date[d] = m
    ever_members.update(m)

# --- 3. Quarter-end price panel, read from the cached parquets only ---
series = {}
for t in sorted(ever_members & priced):
    df = pd.read_parquet(CACHE / "prices" / f"{t}.parquet")
    if not df.empty and "Adj Close" in df:
        series[t] = df["Adj Close"]
prices = pd.DataFrame(series).sort_index()
prices = prices.loc[(prices.index >= pd.Timestamp(CFG.start_date)) &
                    (prices.index <= pd.Timestamp(CFG.end_date))]
qe_prices = prices.resample(CFG.rebalance_freq).last()

# --- 4. Per-quarter equal-weight forward returns per group ---
rows = []
dates = list(qe_prices.index)
for i, d in enumerate(dates[:-1]):
    nxt = dates[i + 1]
    members = membership_by_date.get(d)
    if members is None:
        continue
    members = set(members)
    covered = sorted(members & fundamentals_covered & set(qe_prices.columns))
    uncovered = sorted((members - fundamentals_covered) & set(qe_prices.columns))
    unpriceable = members - set(qe_prices.columns)

    r_cov, miss_c, ext_c = compute_holding_period_return(
        qe_prices.loc[d, covered], qe_prices.loc[nxt, covered])
    r_unc, miss_u, ext_u = compute_holding_period_return(
        qe_prices.loc[d, uncovered], qe_prices.loc[nxt, uncovered])

    rows.append({
        "date": d, "n_members": len(members), "n_covered": len(covered),
        "n_uncovered_priced": len(uncovered), "n_unpriceable": len(unpriceable),
        "ret_covered": r_cov, "ret_uncovered": r_unc,
        "excluded_extreme_cov": ext_c, "excluded_extreme_unc": ext_u,
        "missing_fwd_cov": miss_c, "missing_fwd_unc": miss_u,
    })

df = pd.DataFrame(rows).set_index("date")
df["spread"] = df["ret_covered"] - df["ret_uncovered"]

n = len(df)
mean_cov, mean_unc = df["ret_covered"].mean(), df["ret_uncovered"].mean()
spread = df["spread"]
# A t-statistic asks: is the average spread large relative to how noisy the
# spread is quarter to quarter? |t| > ~2 is the usual bar for "probably not
# just noise" at the 5% level.
t_stat = spread.mean() / (spread.std(ddof=1) / np.sqrt(n))

ann = lambda q: (1 + q) ** 4 - 1  # quarterly -> annualized

print(f"Quarters analyzed: {n}  ({df.index[0].date()} .. {df.index[-1].date()})")
print(f"Avg universe size: {df['n_members'].mean():.0f}")
print(f"Avg covered (fundamentals+price): {df['n_covered'].mean():.0f} "
      f"({df['n_covered'].mean()/df['n_members'].mean():.1%})")
print(f"Avg uncovered but priced (measurable): {df['n_uncovered_priced'].mean():.0f} "
      f"({df['n_uncovered_priced'].mean()/df['n_members'].mean():.1%})")
print(f"Avg unpriceable (unmeasurable): {df['n_unpriceable'].mean():.0f} "
      f"({df['n_unpriceable'].mean()/df['n_members'].mean():.1%})")
print()
print(f"Mean quarterly return, covered:   {mean_cov:+.4%}  (~{ann(mean_cov):+.2%}/yr)")
print(f"Mean quarterly return, uncovered: {mean_unc:+.4%}  (~{ann(mean_unc):+.2%}/yr)")
print(f"Mean quarterly spread (cov - unc): {spread.mean():+.4%}  "
      f"(~{ann(mean_cov) - ann(mean_unc):+.2%}/yr equivalent)")
print(f"t-stat of spread: {t_stat:+.2f}   (|t|>2 ~ significant at 5%)")
print()
print(f"Glitch-guard exclusions: covered={df['excluded_extreme_cov'].sum()}, "
      f"uncovered={df['excluded_extreme_unc'].sum()}")
print(f"Missing-forward-price drops: covered={df['missing_fwd_cov'].sum()}, "
      f"uncovered={df['missing_fwd_unc'].sum()} "
      f"(see the interpretation caveat in this file's docstring)")
print()
print("Group sizes, first 4 and last 4 quarters (the uncovered/unpriceable")
print("groups shrink over time as old delisted names age out of the window):")
cols = ["n_members", "n_covered", "n_uncovered_priced", "n_unpriceable"]
print(pd.concat([df[cols].head(4), df[cols].tail(4)]).to_string())
