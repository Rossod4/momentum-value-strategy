"""
Cost-model realism check (Phase 5 audit).

The backtests charge a flat blended 10bps one-way (so 20bps round-trip per
name replaced - see src/costs/transaction_costs.py). This script asks two
questions of the actual cached market data instead of taking that figure on
faith:

1. SPREAD: how wide were the bid-ask spreads of the stocks this universe
   actually contains? Estimated with the Corwin-Schultz (2012) high-low
   estimator, which infers the spread from daily high/low ranges (the
   intuition: the daily range reflects both real volatility and the
   bid-ask bounce, while a two-day range reflects proportionally less
   bounce - comparing them isolates the spread). IMPORTANT caveat: CS is
   known to OVERSTATE spreads for liquid large-caps because overnight
   price gaps and volatility leak into the estimate - so read its numbers
   as a generous upper bound, not a measurement. Real quoted half-spreads
   for S&P 500 names are typically 1-5bps.

2. CAPACITY: at what portfolio size does the flat-cost assumption break
   down? An equal-weight 50-name portfolio puts 2% of capital in each
   name; a replaced name trades its whole 2% slice. A standard prudence
   bound is trading no more than 5-10% of a stock's average daily dollar
   volume (ADV) in a day - beyond that, market impact (pushing the price
   against yourself) grows well past anything a flat 10bps covers. The
   binding constraint is the LEAST liquid holding, proxied here by the
   10th/25th-percentile-ADV member of the universe.

Run from the repo root (offline - uses the existing data cache):

    python scripts/cost_realism_analysis.py
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import DEFAULT_CONFIG as CFG
from src.data_layer.constituents import get_membership, load_constituents_table

CACHE = CFG.cache_dir

constituents = load_constituents_table(cache_dir=CACHE)
month_ends = pd.date_range(CFG.start_date, CFG.end_date, freq="ME")
ever_members: set[str] = set()
for d in month_ends:
    ever_members.update(get_membership(d, constituents))

# --- Load daily OHLCV for all priceable members ---
frames = {}
for t in sorted(ever_members):
    p = CACHE / "prices" / f"{t}.parquet"
    if not p.exists():
        continue
    df = pd.read_parquet(p)
    need = {"High", "Low", "Close", "Volume"}
    if df.empty or not need.issubset(df.columns):
        continue
    df = df.loc[(df.index >= pd.Timestamp(CFG.start_date)) &
                (df.index <= pd.Timestamp(CFG.end_date)), sorted(need)]
    if len(df) < 60:  # too little history for a meaningful estimate
        continue
    frames[t] = df

print(f"Tickers with usable OHLCV: {len(frames)}")


def corwin_schultz_spread(high: pd.Series, low: pd.Series) -> float:
    """Median Corwin-Schultz estimated full spread, as a fraction of price.

    beta = sum of squared log(high/low) over two consecutive days;
    gamma = squared log of the two-day high over the two-day low. Solving
    the model for the spread gives alpha below; negative alphas (where the
    model breaks) are floored at zero, the standard treatment. The MEDIAN
    across days is reported - the estimator is noisy day to day, and the
    median resists its extreme tails.
    """
    h, l = high.values, low.values
    with np.errstate(divide="ignore", invalid="ignore"):
        hl = np.log(h / l) ** 2
        beta = hl[:-1] + hl[1:]
        h2 = np.maximum(h[:-1], h[1:])
        l2 = np.minimum(l[:-1], l[1:])
        gamma = np.log(h2 / l2) ** 2
    k = 3 - 2 * np.sqrt(2)
    alpha = (np.sqrt(2 * beta) - np.sqrt(beta)) / k - np.sqrt(gamma / k)
    alpha = np.where(alpha < 0, 0, alpha)
    s = 2 * (np.exp(alpha) - 1) / (1 + np.exp(alpha))
    s = s[np.isfinite(s)]
    return float(np.median(s)) if len(s) else np.nan


spreads = {}
advs = {}
for t, df in frames.items():
    spreads[t] = corwin_schultz_spread(df["High"], df["Low"])
    advs[t] = float((df["Close"] * df["Volume"]).median())  # median daily $ volume

spreads = pd.Series(spreads).dropna()
advs = pd.Series(advs).dropna()

full_bps = spreads * 10_000
half_bps = full_bps / 2
print("\nCorwin-Schultz FULL spread estimate (bps) across members, 2012-2026")
print("(upper-bound-ish - see this file's docstring):")
for q in [0.10, 0.25, 0.50, 0.75, 0.90, 0.99]:
    print(f"  p{int(q*100):02d}: {full_bps.quantile(q):6.1f} bps  "
          f"(half-spread {half_bps.quantile(q):5.1f} bps)")

print("\nMedian daily dollar volume (ADV) across members ($M):")
for q in [0.01, 0.05, 0.10, 0.25, 0.50]:
    print(f"  p{int(q*100):02d}: {advs.quantile(q)/1e6:10.0f}")

position_frac = 1 / 50  # equal-weight slice of capital per name
print("\nCapacity estimates (AUM at which one replaced holding's trade hits")
print("the participation bound against the least liquid likely holding):")
for participation in [0.05, 0.10]:
    for adv_pctl in [0.10, 0.25]:
        adv = advs.quantile(adv_pctl)
        capacity = participation * adv / position_frac
        print(f"  @ {participation:.0%} of ADV, p{int(adv_pctl*100)}-ADV holding: "
              f"${capacity/1e6:,.0f}M AUM")

print(f"""
Interpretation:
  - one_way_cost_bps=10 must cover half-spread + commission + impact.
  - CS-estimated median half-spread ~{half_bps.median():.1f}bps (upper bound); true
    quoted half-spreads for these names are typically 1-5bps.
  - At retail/small-fund scale (well below the capacity numbers above),
    impact is negligible and 10bps one-way is comfortable-to-conservative.
  - The flat figure is thinnest for the LONG-SHORT strategy's short book:
    bottom-momentum names have the widest spreads (p90 half-spread
    ~{half_bps.quantile(0.9):.0f}bps) and can be hard/expensive to borrow - see notebook 04's
    borrow-fee sensitivity for how that's handled.
""")
