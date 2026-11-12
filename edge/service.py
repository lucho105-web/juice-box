"""Glue between the API response and the UI: run every scanner with one
settings object, pick the best opportunity, and keep the scan log.

No Streamlit imports, so all of it is unit-tested.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

import pandas as pd

from edge import odds_math as om
from edge.parse import DEFAULT_MAX_AGE_S, filter_offers, parse_odds
from edge.scanners import find_arbs, find_ev, find_middles

KINDS: tuple[str, ...] = ("arb", "middle", "ev")
SCAN_LOG_COLUMNS = ["time_utc", "sport", "source", "credits", "offers", "arbs", "middles", "ev"]


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
