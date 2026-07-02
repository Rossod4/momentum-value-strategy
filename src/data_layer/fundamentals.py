"""
Point-in-time fundamental data from SEC EDGAR - the data layer for the value
strategy, parallel to prices.py's role for momentum.

Why SEC EDGAR: yfinance only exposes today's snapshot fundamentals, which
would mean applying 2026's P/E to a 2013 rebalance decision - a serious
look-ahead bias. SEC EDGAR's XBRL "company facts" API is free, needs no API
key, and - critically - reports the actual date each figure was FILED with
the SEC, not just the fiscal period it describes. That `filed` date is what
lets this module enforce the same no-look-ahead invariant prices.py and
constituents.py already enforce: a fact is only usable for a decision made
on date t if it was filed on or before t.

Coverage caveat, stated plainly: SEC's ticker->CIK mapping only covers
companies CURRENTLY registered with the SEC. A company that was acquired or
delisted years ago (e.g. many older S&P 500 constituents) may no longer
appear in it at all, even though it's in the point-in-time constituents list
from constituents.py. This reintroduces a data-coverage-driven version of
survivorship bias that the price/momentum side of this project doesn't have
- worth knowing when interpreting value backtest coverage stats.

Two SEC fair-access requirements this module follows:
  - Always send a descriptive User-Agent identifying the requester.
  - Keep request volume well under their informal ~10 req/sec guidance.
See https://www.sec.gov/os/webmaster-faq#developers.
"""

import time
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import requests

from src.data_layer.cache_utils import read_cache, write_cache

SEC_USER_AGENT = "MomentumValueStrategy student research project (arwgard@icloud.com)"
TICKER_CIK_URL = "https://www.sec.gov/files/company_tickers.json"
COMPANY_FACTS_URL_TEMPLATE = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"

REQUEST_PAUSE_SECONDS = 0.15

TICKER_CIK_CACHE_FILENAME = "sec_ticker_cik_map.parquet"
FACTS_CACHE_SUBDIR = "fundamentals"

# The only XBRL concepts this module keeps when flattening a company's raw
# filing history - SEC's companyfacts payload contains hundreds of tags per
# company, most irrelevant to the four value ratios this project computes.
# Several concepts have more than one candidate tag because companies tag
# the same real-world figure inconsistently (e.g. some report a single
# combined "LongTermDebt", others split current/noncurrent) - both variants
# are kept here, and the extraction functions below try each in turn.
TAGS_OF_INTEREST = {
    "EntityCommonStockSharesOutstanding",
    "CommonStockSharesOutstanding",
    "StockholdersEquity",
    "NetIncomeLoss",
    "EarningsPerShareDiluted",
    "EarningsPerShareBasic",
    "OperatingIncomeLoss",
    "DepreciationDepletionAndAmortization",
    "DepreciationAmortizationAndAccretionNet",
    "CashAndCashEquivalentsAtCarryingValue",
    "LongTermDebtNoncurrent",
    "LongTermDebtCurrent",
    "LongTermDebt",
    "DebtAndCapitalLeaseObligations",
}


def _headers() -> dict:
    return {"User-Agent": SEC_USER_AGENT}


def load_ticker_cik_map(cache_dir: Path, force_refresh: bool = False) -> dict[str, int]:
    """Load SEC's ticker -> CIK (Central Index Key) mapping.

    SEC tickers already use the hyphenated share-class format this project
    uses elsewhere (e.g. "BRK-B"), matching constituents.normalize_ticker's
    output, so no extra normalization is needed here.
    """
    cache_path = cache_dir / TICKER_CIK_CACHE_FILENAME
    if not force_refresh:
        cached = read_cache(cache_path)
        if cached is not None:
            return dict(zip(cached["ticker"], cached["cik"]))

    response = requests.get(TICKER_CIK_URL, headers=_headers(), timeout=30)
    response.raise_for_status()
    raw = response.json()

    table = pd.DataFrame(
        [{"ticker": v["ticker"], "cik": v["cik_str"]} for v in raw.values()]
    )
    # A ticker can appear more than once if SEC's list includes stale
    # entries from a symbol reuse; keep the first (SEC's JSON is roughly
    # ordered by market cap, favoring the more prominent/current listing).
    table = table.drop_duplicates(subset="ticker", keep="first")
    write_cache(table, cache_path)
    return dict(zip(table["ticker"], table["cik"]))


def _facts_cache_path(ticker: str, cache_dir: Path) -> Path:
    return cache_dir / FACTS_CACHE_SUBDIR / f"{ticker}.parquet"


def get_company_facts(
    ticker: str, cik: int, cache_dir: Path, force_refresh: bool = False
) -> pd.DataFrame | None:
    """Fetch (or load from cache) one company's full XBRL filing history,
    flattened to a long DataFrame of [tag, unit, start, end, val, filed, form].

    Returns None if the company has no XBRL data on file (common for
    smaller/older filers, or ones that stopped filing after being acquired)
    - this is a normal, expected outcome, not an error, and is reported back
    to the caller as a coverage gap rather than raised as an exception.
    """
    cache_path = _facts_cache_path(ticker, cache_dir)
    if not force_refresh:
        cached = read_cache(cache_path)
        if cached is not None:
            return cached

    url = COMPANY_FACTS_URL_TEMPLATE.format(cik=cik)
    try:
        response = requests.get(url, headers=_headers(), timeout=30)
        time.sleep(REQUEST_PAUSE_SECONDS)
        if response.status_code == 404:
            return None
        response.raise_for_status()
    except requests.RequestException:
        return None

    raw = response.json()
    rows = []
    for taxonomy, tags in raw.get("facts", {}).items():
        for tag, tag_data in tags.items():
            if tag not in TAGS_OF_INTEREST:
                continue
            for unit, entries in tag_data.get("units", {}).items():
                for entry in entries:
                    rows.append(
                        {
                            "taxonomy": taxonomy,
                            "tag": tag,
                            "unit": unit,
                            "start": entry.get("start"),
                            "end": entry["end"],
                            "val": entry["val"],
                            "filed": entry["filed"],
                            "form": entry.get("form"),
                        }
                    )
    if not rows:
        return None

    table = pd.DataFrame(rows)
    table["start"] = pd.to_datetime(table["start"])
    table["end"] = pd.to_datetime(table["end"])
    table["filed"] = pd.to_datetime(table["filed"])
    write_cache(table, cache_path)
    return table


def get_fundamentals_facts(
    tickers: list[str],
    cache_dir: Path,
    cik_map: dict[str, int] | None = None,
    force_refresh: bool = False,
) -> tuple[dict[str, pd.DataFrame], list[str]]:
    """Fetch flattened filing-history facts for a list of tickers.

    Mirrors prices.get_prices()'s (facts, failed_tickers) shape: successes
    are returned as a dict keyed by ticker, and every ticker with no usable
    data (no CIK match, or no XBRL facts) is reported explicitly rather than
    silently dropped, so coverage gaps are visible in the notebook.
    """
    if cik_map is None:
        cik_map = load_ticker_cik_map(cache_dir)

    facts_by_ticker = {}
    failed_tickers = []
    for ticker in tickers:
        cik = cik_map.get(ticker)
        if cik is None:
            failed_tickers.append(ticker)
            continue
        table = get_company_facts(ticker, cik, cache_dir, force_refresh=force_refresh)
        if table is None:
            failed_tickers.append(ticker)
            continue
        facts_by_ticker[ticker] = table

    return facts_by_ticker, failed_tickers


def _most_recent_instant_with_end(
    facts: pd.DataFrame, tag_candidates: list[str], as_of_date: pd.Timestamp
) -> tuple[float | None, pd.Timestamp | None]:
    """Most recent balance-sheet-style value known as of `as_of_date`, plus
    the balance-sheet date (`end`) it's as of.

    All tags in `tag_candidates` are pooled together and treated as
    alternative labels for the same real-world concept, then the single
    freshest fact (latest `end` date) among them is used - NOT "the first
    tag that has any data at all". That distinction matters: a company can
    switch which tag it reports under partway through its filing history
    (e.g. Apple reported a single combined "LongTermDebt" figure from
    2012-2015, then split it into current/noncurrent tags, then switched
    back in 2021). Preferring a fixed tag priority order would silently
    return a years-stale value for the years it wasn't being updated, even
    though a fresher value existed under the other tag the whole time.

    Only facts FILED on or before `as_of_date` are visible (the
    no-look-ahead gate).
    """
    subset = facts[
        facts["tag"].isin(tag_candidates) & facts["start"].isna() & (facts["filed"] <= as_of_date)
    ]
    if subset.empty:
        return None, None
    row = subset.sort_values(["end", "filed"]).iloc[-1]
    return float(row["val"]), row["end"]


def _most_recent_instant(
    facts: pd.DataFrame, tag_candidates: list[str], as_of_date: pd.Timestamp
) -> float | None:
    """Convenience wrapper around _most_recent_instant_with_end() for
    callers that only need the value, not its balance-sheet date."""
    value, _ = _most_recent_instant_with_end(facts, tag_candidates, as_of_date)
    return value


def _duration_facts(
    facts: pd.DataFrame, tag_candidates: list[str], as_of_date: pd.Timestamp
) -> pd.DataFrame:
    """Every duration (flow) fact for `tag_candidates`, visible as of
    `as_of_date`, with a `duration_days` column added.

    As with _most_recent_instant_with_end(), all candidate tags are pooled
    together rather than tried in priority order - see that function's
    docstring for why (a company can switch which tag it reports a concept
    under partway through its history, e.g. D&A is commonly reported under
    either DepreciationDepletionAndAmortization or
    DepreciationAmortizationAndAccretionNet depending on the filer/year).
    """
    subset = facts[
        facts["tag"].isin(tag_candidates) & facts["start"].notna() & (facts["filed"] <= as_of_date)
    ].copy()
    subset["duration_days"] = (subset["end"] - subset["start"]).dt.days
    return subset


def _ttm_duration(
    facts: pd.DataFrame, tag_candidates: list[str], as_of_date: pd.Timestamp
) -> float | None:
    """Trailing-twelve-month sum for a flow concept (diluted EPS, operating
    income, D&A), built from the four most recent non-overlapping
    single-quarter figures filed by `as_of_date`.

    XBRL duration facts aren't reliably labeled as "standalone quarter" vs.
    "cumulative half-year/9-month/full-year" - both get filed under the same
    tag, and the `fp` field behaves inconsistently across filers. Instead,
    standalone quarters are isolated by duration length (~80-100 days),
    which is robust across filers regardless of how they label periods.

    Falls back to the single most recent annual (~350-386 day) figure filed
    by `as_of_date` if fewer than four usable quarters are available - a
    slightly-stale TTM proxy, needed because some smaller filers only report
    annually.
    """
    subset = _duration_facts(facts, tag_candidates, as_of_date)
    if subset.empty:
        return None

    quarterly = subset[(subset["duration_days"] >= 80) & (subset["duration_days"] <= 100)]
    if not quarterly.empty:
        # A given quarter can be restated in a later filing - keep only the
        # most-recently-filed version of each quarter (still gated to
        # filed <= as_of_date above).
        quarterly = quarterly.sort_values("filed").drop_duplicates(subset="end", keep="last")
        quarterly = quarterly.sort_values("end", ascending=False)
        last_four = quarterly.head(4)
        if len(last_four) == 4:
            return float(last_four["val"].sum())

    annual = subset[(subset["duration_days"] >= 350) & (subset["duration_days"] <= 386)]
    if not annual.empty:
        annual = annual.sort_values(["end", "filed"])
        return float(annual.iloc[-1]["val"])

    return None


def _annual_growth(
    facts: pd.DataFrame, tag_candidates: list[str], as_of_date: pd.Timestamp
) -> float | None:
    """Year-over-year growth from the two most recent annual (~350-386 day)
    figures filed by `as_of_date`.

    This is the trailing-growth proxy behind the "growth-adjusted value"
    factor in src/strategy/value.py. It is deliberately NOT called PEG:
    real PEG divides by a FORWARD analyst growth estimate (a live market
    expectation), which isn't available point-in-time for free. Realized
    historical growth is a different, weaker signal - kept honestly
    separate rather than mislabeled.
    """
    subset = _duration_facts(facts, tag_candidates, as_of_date)
    if subset.empty:
        return None

    annual = subset[(subset["duration_days"] >= 350) & (subset["duration_days"] <= 386)]
    if annual.empty:
        return None

    annual = annual.sort_values("filed").drop_duplicates(subset="end", keep="last")
    annual = annual.sort_values("end", ascending=False)
    if len(annual) < 2:
        return None

    latest, prior = annual.iloc[0]["val"], annual.iloc[1]["val"]
    if prior == 0:
        return None
    return float(latest / prior - 1)


def _total_debt(facts: pd.DataFrame, as_of_date: pd.Timestamp) -> float:
    """Total debt as of `as_of_date`, from whichever debt tags the filer uses.

    Some filers report a single combined debt figure ("LongTermDebt" or
    "DebtAndCapitalLeaseObligations"); others split it into
    separately-tagged current + noncurrent portions - and, as with the
    other fields above, a filer can switch between conventions partway
    through its history (Apple did exactly this: a combined tag
    2012-2015, split tags 2015-2021, then combined again from 2021).
    Rather than a fixed preference order, this compares the underlying
    balance-sheet date of each source and uses whichever is actually more
    recent - the same freshest-wins principle as
    _most_recent_instant_with_end(), just applied across two different
    reporting conventions instead of two alternate tag names.

    KNOWN LIMITATION: some filers - particularly ones with large captive
    finance subsidiaries, e.g. auto manufacturers financing car loans
    through a credit arm - report debt through company-specific or
    segment-dimensional tags not covered by the small set tried here. Ford
    is a concrete example found during development: its real ~$150B of
    combined auto + financing debt was captured correctly through 2017 by
    "DebtAndCapitalLeaseObligations", but from 2018 onward it re-tagged in
    a way this module can't follow, and total_debt silently drops to a few
    hundred million - understating EV for that stock from that point on.
    This wasn't fixed by chasing more tags because the tail of possible
    company-specific conventions is effectively unbounded; it's flagged
    here, and should be flagged again in the notebook, rather than hidden.

    If none of these sources have any data anywhere in the filer's history,
    debt is assumed to be zero rather than unknown - a reasonable
    simplification for large, disclosure-heavy S&P 500 filers (material
    debt is normally disclosed under some standard tag), but subject to
    the same non-standard-tagging caveat above. This assumption is why
    total_debt returns a float, not an Optional float, unlike every other
    field in PointInTimeFundamentals.
    """
    combined_val, combined_end = _most_recent_instant_with_end(
        facts, ["LongTermDebt", "DebtAndCapitalLeaseObligations"], as_of_date
    )
    noncurrent_val, noncurrent_end = _most_recent_instant_with_end(
        facts, ["LongTermDebtNoncurrent"], as_of_date
    )
    current_val, _ = _most_recent_instant_with_end(facts, ["LongTermDebtCurrent"], as_of_date)

    if noncurrent_end is not None and (combined_end is None or noncurrent_end >= combined_end):
        return (noncurrent_val or 0.0) + (current_val or 0.0)
    if combined_val is not None:
        return combined_val
    return 0.0


@dataclass
class PointInTimeFundamentals:
    """Raw fundamental building blocks as they were knowable on a given date.

    Every field except `total_debt` is Optional - a None means the filer
    simply didn't report that concept in a usable form as of this date, not
    that the value is zero. src/strategy/value.py is responsible for
    deciding how to handle a None when computing ratios (see its
    docstring for the negative/missing-ratio ranking convention).
    """

    shares_outstanding: float | None
    stockholders_equity: float | None
    ttm_eps: float | None
    ttm_ebitda: float | None
    total_debt: float
    cash: float | None
    annual_eps_growth: float | None


def get_point_in_time_fundamentals(
    facts: pd.DataFrame, as_of_date
) -> PointInTimeFundamentals:
    """Extract every fundamental building block needed for the value
    composite, as it was knowable on `as_of_date` (no-look-ahead enforced
    via each fact's `filed` date - see the extraction helpers above).
    """
    as_of_date = pd.Timestamp(as_of_date)

    shares_outstanding = _most_recent_instant(
        facts, ["EntityCommonStockSharesOutstanding", "CommonStockSharesOutstanding"], as_of_date
    )
    stockholders_equity = _most_recent_instant(facts, ["StockholdersEquity"], as_of_date)
    cash = _most_recent_instant(facts, ["CashAndCashEquivalentsAtCarryingValue"], as_of_date)
    total_debt = _total_debt(facts, as_of_date)

    # Diluted and basic EPS are reported SIMULTANEOUSLY every period (unlike
    # the debt/shares/D&A tags above, which are alternate conventions a
    # filer picks between over time) - so they must NOT be pooled together.
    # Pooling them let the TTM/growth dedup logic mix a diluted-EPS quarter
    # against a basic-EPS quarter, quietly distorting the ratio. Instead,
    # diluted is preferred wholesale, falling back to basic wholesale only
    # if this filer has zero diluted EPS data anywhere in its history.
    ttm_eps = _ttm_duration(facts, ["EarningsPerShareDiluted"], as_of_date)
    if ttm_eps is None:
        ttm_eps = _ttm_duration(facts, ["EarningsPerShareBasic"], as_of_date)

    operating_income = _ttm_duration(facts, ["OperatingIncomeLoss"], as_of_date)
    d_and_a = _ttm_duration(
        facts,
        ["DepreciationDepletionAndAmortization", "DepreciationAmortizationAndAccretionNet"],
        as_of_date,
    )
    ttm_ebitda = (
        operating_income + d_and_a if operating_income is not None and d_and_a is not None else None
    )

    annual_eps_growth = _annual_growth(facts, ["EarningsPerShareDiluted"], as_of_date)
    if annual_eps_growth is None:
        annual_eps_growth = _annual_growth(facts, ["EarningsPerShareBasic"], as_of_date)

    return PointInTimeFundamentals(
        shares_outstanding=shares_outstanding,
        stockholders_equity=stockholders_equity,
        ttm_eps=ttm_eps,
        ttm_ebitda=ttm_ebitda,
        total_debt=total_debt,
        cash=cash,
        annual_eps_growth=annual_eps_growth,
    )
