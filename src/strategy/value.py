"""
Composite value signal: P/B, P/E, EV/EBITDA, and a trailing-growth-adjusted
value factor, combined into one "cheapness" ranking per rebalance date.

Design decisions agreed before writing this module (see the project chat
history / memory for the full reasoning):

  - Percentile ranks, not z-scores, are used to combine the four metrics.
    P/E and EV/EBITDA both have earnings-like figures in the denominator,
    which can be near-zero for perfectly normal S&P 500 companies in a
    weak quarter - producing wild outlier ratios (a P/E of 500 isn't rare
    at this scale). Z-scores are sensitive to exactly that kind of
    outlier (one wild value distorts the mean/stdev for everyone else);
    percentile ranks only use ordering, so they're robust to it.

  - Loss-making companies are NOT filtered out of the universe. Instead,
    for every ratio here, a non-positive value is deliberately ranked as
    the LEAST attractive end of that metric (not sorted in numerically
    with positive values) - a negative P/E or EV/EBITDA signals distress,
    not a bargain, and letting it sort in naturally would make lossmakers
    look artificially cheap. See _rank_lower_is_better().

  - The fourth factor is explicitly NOT called PEG. Real PEG divides P/E
    by a FORWARD analyst consensus growth estimate - a live market
    expectation - which isn't available point-in-time for free. This
    factor instead uses REALIZED historical (trailing) EPS growth, which
    is a different, weaker signal (past growth doesn't reliably predict
    future growth - growth rates mean-revert). Calling it "growth-adjusted
    value" rather than PEG keeps that distinction honest.
"""

import numpy as np
import pandas as pd

from src.data_layer.fundamentals import PointInTimeFundamentals

# A ticker needs at least this many of the four ratios available to receive
# a composite score at all. Without a floor, a stock missing three of four
# metrics (e.g. a bank, where EV/EBITDA is structurally unavailable - see
# fundamentals.py) would have its entire composite decided by one lonely
# ratio, which is noisier and less robust than a genuine multi-metric read.
MIN_AVAILABLE_METRICS = 2

VALUE_METRIC_COLUMNS = ["pb", "pe", "ev_ebitda", "growth_adjusted_value"]


def compute_value_ratios(
    fundamentals_by_ticker: dict[str, PointInTimeFundamentals],
    prices: dict[str, float],
) -> pd.DataFrame:
    """Raw (not yet ranked) value ratios for every ticker with both a price
    and usable fundamental data, as a DataFrame indexed by ticker with
    columns VALUE_METRIC_COLUMNS.

    Every ratio follows a "lower is more attractive" convention. A missing
    underlying input (e.g. no EBITDA data at all for a bank) produces NaN
    for that one ratio - that ticker is simply not scored on that metric,
    not penalized for it (see compute_composite_score). A non-positive
    ratio is a real computed number, not a missing one, and is handled by
    the ranking step's least-attractive rule instead.
    """
    rows = {}
    for ticker, f in fundamentals_by_ticker.items():
        price = prices.get(ticker)
        if price is None or not f.shares_outstanding:
            continue  # can't establish market cap at all - not scorable this period

        market_cap = price * f.shares_outstanding

        pb = market_cap / f.stockholders_equity if f.stockholders_equity else float("nan")
        pe = price / f.ttm_eps if f.ttm_eps else float("nan")

        if f.ttm_ebitda:
            enterprise_value = market_cap + f.total_debt - (f.cash or 0.0)
            ev_ebitda = enterprise_value / f.ttm_ebitda
        else:
            ev_ebitda = float("nan")

        # The growth-adjusted ratio needs BOTH a positive P/E and positive
        # trailing growth to mean anything as "cheap relative to growth" -
        # e.g. a P/E of -5 divided by growth of -2 gives +2.5, which LOOKS
        # like a plausible ratio but is economically meaningless (both
        # ingredients are actually bad news). Rather than let that kind of
        # sign-cancellation slip through as a false-positive result, both
        # legs are checked explicitly before dividing, and the ambiguous
        # case is marked least-attractive (+inf) directly - a company
        # that's either unprofitable or shrinking shouldn't score well on
        # "cheap relative to growth", regardless of how the raw division
        # happens to come out.
        if f.ttm_eps is None or f.annual_eps_growth is None:
            growth_adjusted_value = float("nan")
        elif pe > 0 and f.annual_eps_growth > 0:
            growth_adjusted_value = pe / f.annual_eps_growth
        else:
            growth_adjusted_value = float("inf")

        rows[ticker] = {
            "pb": pb,
            "pe": pe,
            "ev_ebitda": ev_ebitda,
            "growth_adjusted_value": growth_adjusted_value,
        }

    return pd.DataFrame.from_dict(rows, orient="index", columns=VALUE_METRIC_COLUMNS)


def _rank_lower_is_better(values: pd.Series) -> pd.Series:
    """Cross-sectional percentile rank for one metric, where a LOWER raw
    value is more attractive (cheaper) and a lower percentile is better.

    Non-positive values are shifted to +inf before ranking, which forces
    them to tie for the worst percentile as a group, entirely separate from
    (and always worse than) every positive value's ordering - implementing
    the "negative ratios are least attractive, not artificially cheap" rule
    from this module's docstring. NaN (genuinely missing data) is left as
    NaN, which pandas' rank() naturally excludes rather than penalizes.

    KNOWN LIMITATION: for EV/EBITDA specifically, a non-positive result can
    come from either negative EBITDA (distress - correctly penalized here)
    OR a negative enterprise value, i.e. a company holding more net cash
    than its market cap plus debt (a classic deep-value "net-net" signal -
    arguably one of the CHEAPEST possible situations, not a bad one). This
    rule can't distinguish the two cases and treats both as least
    attractive. This is a deliberate simplification, not an oversight: the
    negative-EBITDA case is far more common for S&P 500-sized companies,
    and a mis-ranked net-cash stock can still score well through its other
    three metrics rather than being excluded outright.
    """
    sortable = values.where(~(values <= 0), other=np.inf)
    return sortable.rank(pct=True, ascending=True)


def compute_composite_score(raw_ratios: pd.DataFrame) -> pd.Series:
    """Combine the four value ratios into one composite score per ticker.

    Each column is percentile-ranked independently (see
    _rank_lower_is_better), then averaged across whichever ranks are
    available for that ticker. The result runs 0 (cheapest across
    available metrics) to 1 (most expensive) - lower is more attractive,
    matching every individual metric's convention.

    Tickers with fewer than MIN_AVAILABLE_METRICS available ratios get NaN
    (excluded from selection that period) rather than a score built from
    too little information - see MIN_AVAILABLE_METRICS above.
    """
    ranks = raw_ratios[VALUE_METRIC_COLUMNS].apply(_rank_lower_is_better)
    available_count = ranks.notna().sum(axis=1)
    composite = ranks.mean(axis=1, skipna=True)
    composite = composite.where(available_count >= MIN_AVAILABLE_METRICS)
    return composite


def select_top_n(composite_scores: pd.Series, n: int) -> list[str]:
    """Pick the `n` tickers with the lowest (cheapest) composite score.

    Tickers with no score (NaN - insufficient data, see
    compute_composite_score) are dropped before ranking. If fewer than `n`
    scored tickers are available, returns all of them rather than erroring,
    mirroring src/strategy/momentum.py's select_top_n for the same reason:
    the eligible universe can occasionally be thin.
    """
    valid = composite_scores.dropna()
    return valid.sort_values(ascending=True).head(n).index.tolist()
