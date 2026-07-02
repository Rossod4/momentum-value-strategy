"""
Direct comparison of the momentum and value strategies, plus blended
momentum/value portfolios at any weight split.

Why everything here works at QUARTERLY frequency
-------------------------------------------------
Momentum produces MONTHLY returns and value produces QUARTERLY returns, so
the two are only simultaneously observable at quarter-ends - the only dates
where a blend's return can be computed honestly. Momentum's monthly returns
are therefore compounded into quarterly returns first (an exact calculation,
since quarter-ends are month-ends - no information is invented), and every
blend is evaluated on the common quarter-end dates both strategies cover.

Blend convention, stated explicitly so it can be challenged:
  - The blend is REBALANCED BACK to its target weights every quarter. That
    is exactly what the formula

        blend_return = w * momentum_return + (1 - w) * value_return

    means when applied fresh each quarter: each period starts at the target
    split again. The alternative (letting the split drift toward whichever
    sleeve performed better) would make "a 50/50 portfolio" gradually stop
    being 50/50, so a fixed-weight comparison would no longer measure what
    it claims to.
  - Each sleeve's returns are NET of its own trading costs already. The
    small extra trades needed to pull the sleeves back to target weight each
    quarter are NOT costed - typically a few percent of portfolio value per
    quarter at 20bps round-trip, i.e. roughly a basis point per quarter of
    drag. Ignoring it slightly flatters every mixed blend (and doesn't
    affect the 100/0 or 0/100 endpoints at all).
"""

from dataclasses import dataclass

import pandas as pd

from src.evaluation.metrics import annualized_vol, cagr, max_drawdown, sharpe_ratio

QUARTERS_PER_YEAR = 4

# The default sweep shown in the comparison notebook: both pure strategies,
# plus three evenly-spaced mixes, so the shape of the risk/return trade-off
# across the whole momentum<->value spectrum is visible at a glance.
DEFAULT_SWEEP_WEIGHTS = (1.0, 0.75, 0.5, 0.25, 0.0)


def compound_to_quarterly(monthly_returns: pd.Series) -> pd.Series:
    """Compound monthly returns into quarterly returns.

    Growing at r1, then r2, then r3 over three months turns $1 into
    (1+r1)(1+r2)(1+r3), so the quarter's return is that product minus 1.
    Quarter-end dates are always month-end dates, so nothing is
    approximated - the monthly path is simply grouped by calendar quarter.

    A quarter with only partial data (e.g. the strategy started mid-quarter)
    still compounds whatever months it has; alignment against the value
    strategy's dates (see blend_returns) is what drops non-overlapping
    periods, not this function.
    """
    return (1 + monthly_returns).resample("QE").prod() - 1


def blend_returns(
    momentum_quarterly: pd.Series, value_quarterly: pd.Series, momentum_weight: float
) -> pd.Series:
    """Quarterly returns of a fixed-weight momentum/value blend.

    Only quarter-ends where BOTH strategies have a return are used (the
    common window) - a blend can't exist in a period where one of its
    sleeves has no result. Applying the weighted average fresh each quarter
    is what implements the quarterly-rebalance convention described in the
    module docstring.
    """
    if not 0.0 <= momentum_weight <= 1.0:
        raise ValueError(
            f"momentum_weight must be between 0 and 1, got {momentum_weight} "
            "(it's the FRACTION of the portfolio in momentum, not a percentage)."
        )
    common_dates = momentum_quarterly.index.intersection(value_quarterly.index)
    momentum_aligned = momentum_quarterly.loc[common_dates]
    value_aligned = value_quarterly.loc[common_dates]
    return momentum_weight * momentum_aligned + (1 - momentum_weight) * value_aligned


@dataclass
class BlendResult:
    """Everything combine_strategies() computes for one weight split."""

    momentum_weight: float
    returns: pd.Series  # quarterly blended returns (net of each sleeve's costs)
    equity: pd.Series  # growth of $1, compounded from `returns`
    metrics: pd.Series  # CAGR / Annualized Volatility / Sharpe / Max Drawdown


def combine_strategies(
    momentum_monthly_returns: pd.Series,
    value_quarterly_returns: pd.Series,
    momentum_weight: float,
    risk_free_rate: float = 0.0,
) -> BlendResult:
    """Full metric set for a momentum/value blend at any weight split.

    Usage (e.g. in the comparison notebook), for a 60% momentum / 40% value mix:

        blend = combine_strategies(momentum_result.net_returns,
                                   value_result.net_returns, 0.6)
        blend.metrics   # CAGR, vol, Sharpe, max drawdown
        blend.equity    # growth-of-$1 curve, plottable directly

    Pass each strategy's NET return series so the blend inherits realistic,
    cost-aware inputs; passing gross series works mechanically but would
    quietly drop transaction costs from the comparison.
    """
    momentum_quarterly = compound_to_quarterly(momentum_monthly_returns)
    returns = blend_returns(momentum_quarterly, value_quarterly_returns, momentum_weight)
    equity = (1 + returns).cumprod()
    metrics = pd.Series(
        {
            "CAGR": cagr(equity),
            "Annualized Volatility": annualized_vol(returns, QUARTERS_PER_YEAR),
            "Sharpe Ratio": sharpe_ratio(returns, risk_free_rate, QUARTERS_PER_YEAR),
            "Max Drawdown": max_drawdown(equity),
        }
    )
    return BlendResult(
        momentum_weight=momentum_weight, returns=returns, equity=equity, metrics=metrics
    )


def blend_sweep(
    momentum_monthly_returns: pd.Series,
    value_quarterly_returns: pd.Series,
    weights: tuple = DEFAULT_SWEEP_WEIGHTS,
    risk_free_rate: float = 0.0,
) -> pd.DataFrame:
    """Metrics for a whole range of momentum/value splits, side by side.

    Columns are labelled by split (e.g. "75% Mom / 25% Val") so the table
    reads left-to-right from pure momentum to pure value. The endpoints ARE
    the pure strategies, evaluated on the common quarterly window - so this
    table is internally consistent, with every column computed from the same
    dates at the same frequency.
    """
    columns = {}
    for w in weights:
        label = f"{w:.0%} Mom / {1 - w:.0%} Val"
        columns[label] = combine_strategies(
            momentum_monthly_returns, value_quarterly_returns, w, risk_free_rate
        ).metrics
    return pd.DataFrame(columns)


def strategy_comparison_table(
    momentum_result,
    value_result,
    benchmark_monthly_returns: pd.Series,
    benchmark_monthly_equity: pd.Series,
    risk_free_rate: float = 0.0,
) -> pd.DataFrame:
    """Side-by-side table of the two strategies (net of costs) and SPY.

    `momentum_result` / `value_result` are the BacktestResult objects the
    two engines return (anything with .net_returns/.net_equity/.gross_equity/
    .turnover_history attributes works). Each strategy is evaluated at its
    OWN native frequency - monthly for momentum, quarterly for value - which
    is the most faithful view of each (annualized figures are directly
    comparable either way). The blend_sweep() table is the place where both
    are deliberately forced onto one common quarterly footing instead.

    Two rows beyond the standard metric set:
      - "CAGR vs SPY": strategy net CAGR minus benchmark CAGR - the headline
        "did this beat buying the index" number.
      - "Cost Drag (CAGR)": gross CAGR minus net CAGR - how much annualized
        return transaction costs consumed.
      - "Avg Turnover / Rebalance": NOT annualized, and the two strategies
        rebalance at different frequencies (monthly vs quarterly) - so
        compare cost drag, not raw turnover, across columns.
    """
    benchmark_cagr = cagr(benchmark_monthly_equity)

    def strategy_column(result, periods_per_year: int) -> dict:
        net_cagr = cagr(result.net_equity)
        return {
            "CAGR (Net)": net_cagr,
            "Annualized Volatility": annualized_vol(result.net_returns, periods_per_year),
            "Sharpe Ratio (Net)": sharpe_ratio(result.net_returns, risk_free_rate, periods_per_year),
            "Max Drawdown (Net)": max_drawdown(result.net_equity),
            "CAGR vs SPY": net_cagr - benchmark_cagr,
            "Cost Drag (CAGR)": cagr(result.gross_equity) - net_cagr,
            "Avg Turnover / Rebalance": result.turnover_history.mean(),
        }

    table = {
        "Momentum (monthly)": strategy_column(result=momentum_result, periods_per_year=12),
        "Value (quarterly)": strategy_column(result=value_result, periods_per_year=QUARTERS_PER_YEAR),
        "SPY Buy & Hold": {
            "CAGR (Net)": benchmark_cagr,
            "Annualized Volatility": annualized_vol(benchmark_monthly_returns, 12),
            "Sharpe Ratio (Net)": sharpe_ratio(benchmark_monthly_returns, risk_free_rate, 12),
            "Max Drawdown (Net)": max_drawdown(benchmark_monthly_equity),
            "CAGR vs SPY": 0.0,
            "Cost Drag (CAGR)": float("nan"),  # buy-and-hold: no rebalancing trades modeled
            "Avg Turnover / Rebalance": float("nan"),
        },
    }
    # Explicit row order (dict insertion order), so the table always renders
    # with the headline return/risk rows first.
    row_order = [
        "CAGR (Net)",
        "Annualized Volatility",
        "Sharpe Ratio (Net)",
        "Max Drawdown (Net)",
        "CAGR vs SPY",
        "Cost Drag (CAGR)",
        "Avg Turnover / Rebalance",
    ]
    return pd.DataFrame(table).loc[row_order]
