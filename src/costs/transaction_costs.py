"""
Transaction cost model.

Backtests that ignore trading costs routinely overstate real-world returns,
especially for a monthly-rebalanced strategy like this one where a
meaningful chunk of the portfolio turns over every period. This module
applies a simple, transparent, turnover-based cost so the backtest reports
a realistic net-of-cost result rather than an unrealistically clean gross
number.

The cost is a single blended "one-way cost in basis points" figure meant to
represent commission + bid-ask spread + market impact combined, rather than
three separately-modeled components. A component-by-component model would
need reliable historical bid-ask spread and trading volume data that this
project doesn't have - modeling each piece "precisely" without that data
would be false precision, not more realism. The blended bps figure is
config-driven (`config.one_way_cost_bps`) specifically so it can be
sensitivity-tested (see the notebook's robustness appendix) instead of
being trusted as a single point estimate.
"""


def compute_turnover(old_portfolio: list[str], new_portfolio: list[str], top_n: int) -> float:
    """Fraction of the equal-weight portfolio that had to change hands.

    Since every holding is equal-weighted, turnover is simply the fraction
    of names that are NOT held in both the old and new portfolio:

        turnover = 1 - |old ∩ new| / top_n

    turnover=0 means the portfolio didn't change at all; turnover=1 means
    every single holding was replaced.

    On the very first rebalance there's no "old" portfolio to compare
    against - pass an empty list to treat every position as newly bought
    (turnover=1.0), since establishing the initial portfolio does incur
    real trading costs.
    """
    if top_n == 0:
        return 0.0
    overlap = len(set(old_portfolio) & set(new_portfolio))
    return 1 - (overlap / top_n)


def apply_transaction_costs(gross_return: float, turnover: float, one_way_cost_bps: float) -> float:
    """Subtract the turnover-based transaction cost from a period's gross return.

    Replacing a holding is TWO trades, not one: the outgoing stock has to be
    SOLD and the incoming stock has to be BOUGHT, and each of those trades
    pays the one-way cost (its own commission, its own half-spread, its own
    market impact). Since `turnover` counts the fraction of the portfolio
    replaced, the value traded is 2 x turnover (that fraction sold, plus the
    same fraction bought), so:

        net_return = gross_return - 2 * turnover * one_way_cost_bps / 10000

    e.g. replacing half the portfolio (turnover=0.5) at a 10bps one-way cost
    charges 2 * 0.5 * 10bps = 10bps for the period.

    Known simplification: on the very FIRST rebalance there is nothing to
    sell (the portfolio is bought from cash), so doubling overstates that one
    period's cost by one_way_cost_bps at most. This is accepted as a small,
    conservative (costs-overstated, never understated) one-off rather than
    special-casing the first period in both backtest engines.
    """
    cost = 2 * turnover * (one_way_cost_bps / 10_000)
    return gross_return - cost
