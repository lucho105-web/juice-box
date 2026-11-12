"""Raw Odds API JSON -> normalized offers table (one row per outcome per book).

See docs/SPEC.md section 1 for the column list. Bet-link fields are kept so
edge/links.py can build "Open bet" buttons later.
"""
from __future__ import annotations

import math
from datetime import datetime
from typing import Any, Mapping, Sequence

import pandas as pd

from edge.odds_math import am_to_dec

DEFAULT_MAX_AGE_S = 120.0

OFFER_COLUMNS: list[str] = [
    "event_id",
    "sport_key",
    "commence_time",
    "home_team",
    "away_team",
    "matchup",
    "is_live",
    "market",
    "book_key",
    "book",
    "outcome",
    "point",
    "price_am",
    "price_dec",
    "last_update",
    "age_s",
    "outcome_link",
    "market_link",
    "event_link",
    "outcome_sid",
    "market_sid",
    "event_sid",
]


def _parse_time(value: Any) -> datetime | None:
    """ISO-8601 string (with Z) -> aware datetime, or None if unusable."""
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _point(outcome: Mapping[str, Any]) -> float:
    value = outcome.get("point")
    return float(value) if value is not None else math.nan


def _outcome_row(
    event: Mapping[str, Any],
    book: Mapping[str, Any],
    market: Mapping[str, Any],
    outcome: Mapping[str, Any],
    now: datetime,
) -> dict[str, Any] | None:
    """One offer row, or None when the price or timestamps are unusable."""
    try:
        price_am = int(outcome["price"])
        price_dec = am_to_dec(price_am)
    except (KeyError, TypeError, ValueError):
        return None
    commence = _parse_time(event.get("commence_time"))
    updated = _parse_time(market.get("last_update")) or _parse_time(book.get("last_update"))
    if commence is None or updated is None:
        return None
    home, away = event.get("home_team", ""), event.get("away_team", "")
    return {
        "event_id": event.get("id"),
        "sport_key": event.get("sport_key"),
        "commence_time": commence,
        "home_team": home,
        "away_team": away,
        "matchup": f"{away} @ {home}",
        "is_live": commence <= now,
        "market": market.get("key"),
        "book_key": book.get("key"),
        "book": book.get("title") or book.get("key"),
        "outcome": outcome.get("name"),
        "point": _point(outcome),
        "price_am": price_am,
        "price_dec": price_dec,
        "last_update": updated,
        "age_s": max(0.0, (now - updated).total_seconds()),
        "outcome_link": outcome.get("link"),
        "market_link": market.get("link"),
        "event_link": book.get("link"),
        "outcome_sid": outcome.get("sid"),
        "market_sid": market.get("sid"),
        "event_sid": book.get("sid"),
    }


def parse_odds(events: Sequence[Mapping[str, Any]], now: datetime) -> pd.DataFrame:
    """Flatten an /odds response. `now` is the reference time for line ages."""
    rows = [
        row
        for event in events
        for book in event.get("bookmakers", [])
        for market in book.get("markets", [])
        for outcome in market.get("outcomes", [])
        if (row := _outcome_row(event, book, market, outcome, now)) is not None
    ]
    df = pd.DataFrame(rows, columns=OFFER_COLUMNS)
    for col in ("commence_time", "last_update"):
        df[col] = pd.to_datetime(df[col], utc=True)
    return df


def filter_offers(
    df: pd.DataFrame,
    max_age_s: float = DEFAULT_MAX_AGE_S,
    include_live: bool = False,
) -> pd.DataFrame:
    """Drop stale lines and (unless include_live) games already started.

    Run this before any scanner so a stale price can't make a fake arb.
    """
    keep = df["age_s"] <= max_age_s
    if not include_live:
        keep &= ~df["is_live"].astype(bool)
    return df[keep].reset_index(drop=True)
