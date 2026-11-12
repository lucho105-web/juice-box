"""Glue between the API response and the UI: run every scanner with one
settings object, pick the best opportunity, and keep the scan log.

No Streamlit imports, so all of it is unit-tested.
"""
from __future__ import annotations

import csv
import hmac
import math
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from statistics import median
from typing import Any, Mapping, Sequence

import pandas as pd

from edge import odds_math as om
from edge.parse import DEFAULT_MAX_AGE_S, filter_offers, parse_odds
from edge.scanners import find_arbs, find_ev, find_middles

KINDS: tuple[str, ...] = ("arb", "middle", "ev")
SCAN_LOG_COLUMNS = ["time_utc", "sport", "source", "credits", "offers", "arbs", "middles", "ev"]
BET_LOG_COLUMNS = [
    "time_utc", "kind", "matchup", "market", "books", "bets", "prices", "stakes",
    "total_staked", "worst_net", "best_net", "expected_net",
]


@dataclass(frozen=True)
class ScanSettings:
    bankroll: float = 100.0
    stake_step: float = 0.01
    min_arb_pct: float = 0.0
    min_hold_pct: float = om.DEFAULT_MIN_MIDDLE_HOLD_PCT
    min_window: float = 0.5
    min_ev_pct: float = 1.0
    min_books: int = 3
    max_age_s: float = DEFAULT_MAX_AGE_S
    include_live: bool = False
    use_pinnacle: bool = False


@dataclass(frozen=True)
class ScanResults:
    n_raw: int               # offers in the response
    n_fresh: int             # offers left after the stale / live filters
    arbs: pd.DataFrame
    middles: pd.DataFrame
    evs: pd.DataFrame

    def table(self, kind: str) -> pd.DataFrame:
        return {"arb": self.arbs, "middle": self.middles, "ev": self.evs}[kind]

    def count(self, kind: str) -> int:
        return len(self.table(kind))


def analyze(
    events: Sequence[Mapping[str, Any]], now: datetime, settings: ScanSettings
) -> ScanResults:
    """Parse, filter stale / live lines, then run all three scanners."""
    raw = parse_odds(events, now)
    offers = filter_offers(raw, settings.max_age_s, settings.include_live)
    return ScanResults(
        n_raw=len(raw),
        n_fresh=len(offers),
        arbs=find_arbs(offers, settings.bankroll, settings.min_arb_pct, settings.stake_step),
        middles=find_middles(offers, settings.bankroll, settings.min_hold_pct, settings.min_window),
        evs=find_ev(
            offers, settings.min_ev_pct, settings.min_books, settings.use_pinnacle, settings.bankroll
        ),
    )


def best_opportunity(results: ScanResults) -> tuple[str, pd.Series] | None:
    """The one to show on the home screen: best arb, else best +EV, else best middle."""
    for kind in ("arb", "ev", "middle"):
        table = results.table(kind)
        if not table.empty:
            return kind, table.iloc[0]
    return None


def opportunity_key(kind: str, row: Mapping[str, Any]) -> str:
    """Stable id for one result row, so a selection survives a re-scan."""
    if kind == "ev":
        parts = [row["event_id"], row["market"], row["side"], row["point"], row["book_key"]]
    else:
        parts = [
            row["event_id"], row["market"],
            row["leg1_side"], row["leg1_point"], row["leg1_book_key"],
            row["leg2_side"], row["leg2_point"], row["leg2_book_key"],
        ]
    return "|".join([kind, *(str(p) for p in parts)])


def find_by_key(results: ScanResults, kind: str, key: str) -> pd.Series | None:
    """The row with this key, or None if the opportunity is gone."""
    for _, row in results.table(kind).iterrows():
        if opportunity_key(kind, row) == key:
            return row
    return None


# ---------- placement: re-check, leg order, placed-bet math ----------

def leg_prefixes(kind: str) -> list[str]:
    return [""] if kind == "ev" else ["leg1_", "leg2_"]


def recheck_cost(regions: Sequence[str]) -> int:
    """One event, one market: 1 credit per region."""
    return max(1, len(set(regions)))


def _same_point(a: Any, b: Any) -> bool:
    a_nan = a is None or (isinstance(a, float) and math.isnan(a))
    b_nan = b is None or (isinstance(b, float) and math.isnan(b))
    return (a_nan and b_nan) or (not a_nan and not b_nan and float(a) == float(b))


def _find_leg(offers: pd.DataFrame, row: Mapping[str, Any], prefix: str) -> pd.Series | None:
    """The same book / side / line as one leg of a result row, or None."""
    candidates = offers[
        (offers["event_id"] == row["event_id"])
        & (offers["market"] == row["market"])
        & (offers["book_key"] == row[f"{prefix}book_key"])
        & (offers["outcome"] == row[f"{prefix}side"])
    ]
    for _, offer in candidates.iterrows():
        if _same_point(offer["point"], row[f"{prefix}point"]):
            return offer
    return None


@dataclass(frozen=True)
class Recheck:
    status: str                        # "same", "moved" or "gone"
    prices: tuple[int | None, ...]     # fresh American price per leg; None if missing or stale
    metric: float | None               # fresh profit % (arb), hold % (middle) or EV % (ev)
    still_good: bool                   # still clears the user's threshold


def recheck(
    kind: str,
    row: Mapping[str, Any],
    events: Sequence[Mapping[str, Any]],
    now: datetime,
    settings: ScanSettings,
) -> Recheck:
    """Compare one opportunity's legs against a fresh odds response.

    Stale and started lines count as missing. For +EV the fair probability
    from the original scan is kept; the re-check only refreshes the price.
    """
    offers = filter_offers(parse_odds(events, now), settings.max_age_s, settings.include_live)
    fresh = [_find_leg(offers, row, prefix) for prefix in leg_prefixes(kind)]
    prices = tuple(None if leg is None else int(leg["price_am"]) for leg in fresh)
    if any(p is None for p in prices):
        return Recheck("gone", prices, None, False)
    old = tuple(int(row[f"{prefix}price_am"]) for prefix in leg_prefixes(kind))
    status = "same" if prices == old else "moved"
    decs = [om.am_to_dec(p) for p in prices]
    if kind == "arb":
        arb = om.arb_two_way(decs[0], decs[1], settings.bankroll)
        metric, good = arb.profit_pct, arb.is_arb and arb.profit_pct >= settings.min_arb_pct
    elif kind == "middle":
        metric = om.middle(decs[0], decs[1], settings.bankroll).hold_pct
        good = metric >= settings.min_hold_pct
    else:
        metric = om.ev_pct(float(row["fair_prob"]), decs[0])
        good = metric >= settings.min_ev_pct
    return Recheck(status, prices, metric, good)


def leg_order(kind: str, row: Mapping[str, Any], offers: pd.DataFrame) -> list[str]:
    """Placement order: the leg whose price is furthest above the other books
    goes first, since it's the one most likely to move or be limited."""
    prefixes = leg_prefixes(kind)
    if len(prefixes) == 1:
        return prefixes

    def edge(prefix: str) -> float:
        same_side = offers[
            (offers["event_id"] == row["event_id"])
            & (offers["market"] == row["market"])
            & (offers["outcome"] == row[f"{prefix}side"])
            & (offers["book_key"] != row[f"{prefix}book_key"])
        ]
        others = [
            o["price_dec"] for _, o in same_side.iterrows()
            if _same_point(o["point"], row[f"{prefix}point"])
        ]
        return float(row[f"{prefix}price_dec"]) / median(others) if others else 1.0

    return sorted(prefixes, key=edge, reverse=True)   # stable: ties keep leg 1 first


@dataclass(frozen=True)
class PlacedLeg:
    book: str
    bet: str          # e.g. "Boston Celtics ML"
    price_am: int     # the price actually taken
    stake: float


def placed_nets(legs: Sequence[PlacedLeg]) -> tuple[float, float]:
    """(worst, best) net across 'exactly one leg wins' outcomes. A single leg
    is (lose the stake, win). Middle hits (both legs win) are not included."""
    total = sum(leg.stake for leg in legs)
    if len(legs) == 1:
        leg = legs[0]
        return -leg.stake, leg.stake * (om.am_to_dec(leg.price_am) - 1.0)
    nets = [leg.stake * om.am_to_dec(leg.price_am) - total for leg in legs]
    return min(nets), max(nets)


def leg_stakes(
    kind: str,
    prices_am: Sequence[int],
    settings: ScanSettings,
    fair_prob: float | None = None,
) -> list[float]:
    """Stakes to bet at these prices, rounded to the user's step.

    Arbs and middles: equal-payout split of the bankroll. +EV: quarter-Kelly.
    """
    step = settings.stake_step
    decs = [om.am_to_dec(p) for p in prices_am]
    if kind == "ev":
        if fair_prob is None:
            raise ValueError("+EV stakes need the fair probability")
        return [om.round_to_step(om.kelly_stake(settings.bankroll, fair_prob, decs[0]), step)]
    split = om.arb_two_way(decs[0], decs[1], settings.bankroll)
    rounded = om.round_stakes(split.stake1, split.stake2, decs[0], decs[1], step)
    return [rounded.stake1, rounded.stake2]


def rebalanced_stake(stake1: float, got_price1_am: int, price2_am: int) -> float:
    """Leg 2 stake that matches leg 1's payout at the price actually taken."""
    return om.equalizing_stake(stake1, om.am_to_dec(got_price1_am), om.am_to_dec(price2_am))


def append_bet_log(
    path: Path,
    when: datetime,
    kind: str,
    matchup: str,
    market: str,
    legs: Sequence[PlacedLeg],
    fair_prob: float | None = None,
) -> None:
    """Append one placed bet to .cache/bets.csv so results can be tracked.

    expected_net: the locked worst case for arbs and middles; stake x EV for +EV.
    """
    worst, best = placed_nets(legs)
    if kind == "ev" and fair_prob is not None:
        leg = legs[0]
        expected = leg.stake * (fair_prob * om.am_to_dec(leg.price_am) - 1.0)
    else:
        expected = worst
    path.parent.mkdir(parents=True, exist_ok=True)
    is_new = not path.exists()
    with path.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        if is_new:
            writer.writerow(BET_LOG_COLUMNS)
        writer.writerow([
            when.isoformat(timespec="seconds"), kind, matchup, market,
            " | ".join(leg.book for leg in legs),
            " | ".join(leg.bet for leg in legs),
            " | ".join(f"{leg.price_am:+d}" for leg in legs),
            " | ".join(f"{leg.stake:.2f}" for leg in legs),
            f"{sum(leg.stake for leg in legs):.2f}", f"{worst:.2f}", f"{best:.2f}", f"{expected:.2f}",
        ])


def check_password(entered: str, expected: str) -> bool:
    """Constant-time compare; an empty password never matches."""
    if not entered or not expected:
        return False
    return hmac.compare_digest(entered.encode("utf-8"), expected.encode("utf-8"))


def append_scan_log(
    path: Path, when: datetime, sport: str, source: str, credits: int, results: ScanResults
) -> None:
    """Append one line per scan so hit rates can be checked over time."""
    path.parent.mkdir(parents=True, exist_ok=True)
    is_new = not path.exists()
    with path.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        if is_new:
            writer.writerow(SCAN_LOG_COLUMNS)
        writer.writerow([
            when.isoformat(timespec="seconds"), sport, source, credits, results.n_fresh,
            results.count("arb"), results.count("middle"), results.count("ev"),
        ])
