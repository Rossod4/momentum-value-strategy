"""
Walk-forward and rolling-window evaluation (Phase 5).

Why this module exists
----------------------
Every result in this project so far - four strategies and a blend sweep -
was measured on the SAME 2012-2026 window, and conclusions like "the 50/50
blend has the best Sharpe" were drawn AFTER seeing all of that window's
data. That's called in-sample evaluation, and it has a known failure mode:
test enough ideas on one fixed stretch of history and some will look good
purely by luck (the "multiple comparisons" problem). The strategies
themselves are protected from the worst of this because none of their
parameters were fitted to the data (12-1 momentum and the value composite
are fixed textbook constructions). But one conclusion WAS effectively
fitted: the choice of the best momentum/value blend weight, which was read
off a table computed over the full window.

This module provides the two standard honesty checks:

1. rolling_window_metrics(): chops a return series into overlapping
   multi-year windows and reports each window's CAGR/vol/Sharpe/drawdown.
   This doesn't involve any fitting - it simply answers "is the headline
   number consistent across sub-periods, or is it one lucky stretch doing
   all the work?"

2. walk_forward_blend(): a true walk-forward test of the blend-weight
   choice. At each step, the "best" weight is chosen using ONLY a training
   window of past quarters, then applied to the following unseen test
   quarters. The stitched-together test-period returns are genuinely
   out-of-sample for the weight choice: no return ever influenced the
   weight that was applied to it. If the full-sample "50/50 is best"
   conclusion is real, walking forward should land on similar weights and
   deliver similar performance; if it was a full-sample artifact, this is
   where that shows up.

Conventions, stated so they can be challenged:
  - The training criterion is the SHARPE RATIO on the training window,
    because Sharpe is exactly the statistic the Phase 3 full-sample table
    used to call 50/50 "best" - the walk-forward should test the same
    claim, not a different one.
  - The weight grid defaults to the same coarse 0/25/50/75/100 sweep as
    the Phase 3 table. A finer grid (say, steps of 1%) would let the
    training window pick a hyper-specific weight like 47%, which is
    precisely the kind of overfitting this test exists to catch - the
    coarse grid keeps the choice honest.
  - The training window ROLLS (fixed length) rather than expands. A rolling
    window asks "would a consistent recent-history-based choice have
    worked?"; an expanding one increasingly averages over the whole past.
    Either is defensible; rolling is the stricter test of consistency, and
    the window length is a parameter so the choice can be stress-tested.
"""

from dataclasses import dataclass

import pandas as pd

from src.evaluation.comparison import QUARTERS_PER_YEAR, DEFAULT_SWEEP_WEIGHTS, blend_returns
from src.evaluation.metrics import annualized_vol, cagr, max_drawdown, sharpe_ratio


def _window_metrics(returns: pd.Series, periods_per_year: int, risk_free_rate: float) -> dict:
    """The standard four metrics for one window of periodic returns."""
    equity = (1 + returns).cumprod()
    return {
        "CAGR": cagr(equity),
        "Annualized Volatility": annualized_vol(returns, periods_per_year),
        "Sharpe Ratio": sharpe_ratio(returns, risk_free_rate, periods_per_year),
        "Max Drawdown": max_drawdown(equity),
    }


def rolling_window_metrics(
    returns: pd.Series,
    window_years: int,
    periods_per_year: int,
    risk_free_rate: float = 0.0,
) -> pd.DataFrame:
    """Metrics over every rolling `window_years`-long window of a return series.

    Each row is one window, indexed by the window's END date, stepping
    forward one period at a time. Overlapping windows are deliberate: the
    point is to see the metric as a moving picture ("what would an investor
    who held for exactly N years, starting anywhere, have experienced?"),
    not to produce independent samples.

    Raises ValueError if the series is shorter than one window - a partial
    window's "CAGR" would silently describe a different holding period than
    every other row, which is exactly the kind of quiet inconsistency this
    project tries to avoid.
    """
    window_len = window_years * periods_per_year
    if len(returns) < window_len:
        raise ValueError(
            f"Need at least {window_len} periods ({window_years} years at "
            f"{periods_per_year}/year) for one rolling window; got {len(returns)}."
        )
    rows = {}
    for end in range(window_len, len(returns) + 1):
        window = returns.iloc[end - window_len : end]
        rows[window.index[-1]] = _window_metrics(window, periods_per_year, risk_free_rate)
    return pd.DataFrame.from_dict(rows, orient="index")


@dataclass
class WalkForwardResult:
    """Everything walk_forward_blend() produces.

    oos_returns:    the stitched out-of-sample quarterly returns - each
                    quarter's return came from a weight chosen WITHOUT
                    seeing that quarter (or anything after it).
    chosen_weights: the momentum weight picked at each selection point,
                    indexed by the first test quarter it was applied to.
                    Reading this Series IS the result in many ways: stable
                    weights mean the full-sample conclusion was robust,
                    erratic weights mean the training windows kept
                    "discovering" different answers.
    comparison:     metrics table over the SAME out-of-sample window for the
                    walk-forward portfolio, every fixed weight in the grid,
                    and the pure strategies - so the walk-forward result has
                    an apples-to-apples baseline.
    """

    oos_returns: pd.Series
    chosen_weights: pd.Series
    comparison: pd.DataFrame


def walk_forward_blend(
    momentum_quarterly: pd.Series,
    value_quarterly: pd.Series,
    train_years: int = 5,
    test_years: int = 1,
    weights: tuple = DEFAULT_SWEEP_WEIGHTS,
    risk_free_rate: float = 0.0,
) -> WalkForwardResult:
    """Walk-forward test of the momentum/value blend-weight choice.

    Mechanics: align both series to their common quarter-ends, then repeat

        train  = the `train_years` * 4 quarters before the test block
        choose = the weight in `weights` with the highest training Sharpe
        test   = apply that weight to the next `test_years` * 4 quarters

    stepping forward one test-block at a time, and stitch all the test
    blocks into one out-of-sample series. The final (possibly partial)
    test block is kept: real time doesn't arrive in tidy multiples of the
    test length, and dropping the tail would quietly discard the most
    recent data.

    Both inputs must already be QUARTERLY returns (pass momentum through
    comparison.compound_to_quarterly() first) - taking quarterly input
    directly, rather than resampling internally, keeps this function's job
    single and testable.
    """
    common = momentum_quarterly.index.intersection(value_quarterly.index)
    momentum_aligned = momentum_quarterly.loc[common]
    value_aligned = value_quarterly.loc[common]

    train_len = train_years * QUARTERS_PER_YEAR
    test_len = test_years * QUARTERS_PER_YEAR
    if len(common) < train_len + 1:
        raise ValueError(
            f"Need more than {train_len} common quarters ({train_years} training "
            f"years) to run at least one walk-forward step; got {len(common)}."
        )

    oos_chunks = []
    chosen = {}
    for test_start in range(train_len, len(common), test_len):
        train_slice = slice(test_start - train_len, test_start)
        test_slice = slice(test_start, min(test_start + test_len, len(common)))

        # Pick the grid weight with the best TRAINING-window Sharpe. Ties
        # go to the first weight in the grid - with a coarse grid and real
        # data, exact ties effectively never happen.
        best_weight, best_sharpe = None, None
        for w in weights:
            train_returns = blend_returns(
                momentum_aligned.iloc[train_slice], value_aligned.iloc[train_slice], w
            )
            s = sharpe_ratio(train_returns, risk_free_rate, QUARTERS_PER_YEAR)
            if best_sharpe is None or s > best_sharpe:
                best_weight, best_sharpe = w, s

        test_returns = blend_returns(
            momentum_aligned.iloc[test_slice], value_aligned.iloc[test_slice], best_weight
        )
        chosen[common[test_start]] = best_weight
        oos_chunks.append(test_returns)

    oos_returns = pd.concat(oos_chunks)
    chosen_weights = pd.Series(chosen).sort_index()

    # Baselines over the SAME out-of-sample window: every fixed grid weight
    # (including the pure strategies at 1.0 and 0.0), so "did adapting the
    # weight beat just picking one and holding it?" is directly answerable.
    oos_dates = oos_returns.index
    columns = {
        "Walk-Forward": _window_metrics(oos_returns, QUARTERS_PER_YEAR, risk_free_rate)
    }
    for w in weights:
        fixed = blend_returns(
            momentum_aligned.loc[oos_dates], value_aligned.loc[oos_dates], w
        )
        label = f"Fixed {w:.0%} Mom / {1 - w:.0%} Val"
        columns[label] = _window_metrics(fixed, QUARTERS_PER_YEAR, risk_free_rate)
    comparison = pd.DataFrame(columns)

    return WalkForwardResult(
        oos_returns=oos_returns, chosen_weights=chosen_weights, comparison=comparison
    )
