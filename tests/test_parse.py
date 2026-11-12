"""Tests for edge/parse.py against tests/fixtures/sample_nba.json."""
import math
from datetime import datetime, timezone

import pandas as pd
import pytest

from edge import api
from edge.parse import OFFER_COLUMNS, filter_offers, parse_odds

NOW = datetime(2026, 11, 12, 23, 0, 0, tzinfo=timezone.utc)


@pytest.fixture(scope="module")
def offers() -> pd.DataFrame:
    return parse_odds(api.load_fixture(), NOW)


def pick(df: pd.DataFrame, event_prefix: str, book_key: str, outcome: str) -> pd.Series:
    rows = df[
        df["event_id"].str.startswith(event_prefix)
        & (df["book_key"] == book_key)
        & (df["outcome"] == outcome)
    ]
    assert len(rows) == 1
    return rows.iloc[0]


# ---------- shape ----------

def test_one_row_per_outcome_per_book(offers: pd.DataFrame) -> None:
    assert list(offers.columns) == OFFER_COLUMNS
    assert len(offers) == 28
    assert offers["event_id"].nunique() == 5
    assert set(offers["market"]) == {"h2h", "spreads", "totals"}


def test_empty_response_gives_empty_table_with_columns() -> None:
    df = parse_odds([], NOW)
    assert df.empty
    assert list(df.columns) == OFFER_COLUMNS
    assert filter_offers(df).empty


# ---------- values ----------

def test_h2h_row_values(offers: pd.DataFrame) -> None:
    row = pick(offers, "evt_arb_h2h", "draftkings", "Boston Celtics")
    assert row["matchup"] == "Boston Celtics @ New York Knicks"
    assert row["book"] == "DraftKings"
    assert row["market"] == "h2h"
    assert row["price_am"] == 110
    assert row["price_dec"] == pytest.approx(2.10)
    assert math.isnan(row["point"])
    assert row["commence_time"] == pd.Timestamp("2026-11-13T00:30:00Z")
    assert row["last_update"] == pd.Timestamp("2026-11-12T22:59:26Z")
    assert row["age_s"] == pytest.approx(34.0)
    assert not row["is_live"]


def test_spread_and_total_points(offers: pd.DataFrame) -> None:
    heat = pick(offers, "evt_arb_spread", "draftkings", "Miami Heat")
    assert heat["point"] == -2.5
    assert heat["price_am"] == 105
    under = pick(offers, "evt_middle_total", "fanduel", "Under")
    assert under["point"] == 221.5
    assert under["price_dec"] == pytest.approx(1.909091, abs=1e-6)


def test_timestamps_are_utc(offers: pd.DataFrame) -> None:
    assert str(offers["commence_time"].dt.tz) == "UTC"
    assert str(offers["last_update"].dt.tz) == "UTC"


# ---------- bet-link fields ----------

def test_link_fields_are_kept(offers: pd.DataFrame) -> None:
    fd = pick(offers, "evt_arb_h2h", "fanduel", "New York Knicks")
    assert "addToBetslip" in fd["outcome_link"]
    assert fd["outcome_sid"] == "7002"
    assert fd["market_link"].endswith("?tab=moneyline")
    assert fd["event_link"].startswith("https://sportsbook.fanduel.com/")
    dk = pick(offers, "evt_arb_h2h", "draftkings", "Boston Celtics")
    assert pd.isna(dk["outcome_link"])
    assert dk["event_link"].startswith("https://sportsbook.draftkings.com/")


def test_missing_link_keys_become_missing_values(offers: pd.DataFrame) -> None:
    """pandas stores absent links as NaN; links.py must check with pd.isna."""
    row = pick(offers, "evt_middle_total", "draftkings", "Over")
    assert pd.isna(row["outcome_link"])
    assert pd.isna(row["market_link"])
    assert pd.isna(row["event_link"])


# ---------- filters ----------

def test_stale_line_is_flagged_and_filtered(offers: pd.DataFrame) -> None:
    stale = pick(offers, "evt_arb_h2h", "betmgm", "New York Knicks")
    assert stale["age_s"] == pytest.approx(1200.0)
    kept = filter_offers(offers)
    arb_event = kept[kept["event_id"].str.startswith("evt_arb_h2h")]
    assert "betmgm" not in set(arb_event["book_key"])
    assert set(arb_event["book_key"]) == {"draftkings", "fanduel"}


def test_default_filters_row_count(offers: pd.DataFrame) -> None:
    kept = filter_offers(offers)
    assert len(kept) == 22          # 28 - 2 stale - 4 live
    assert kept["age_s"].max() <= 120
    assert not kept["is_live"].any()


def test_fresh_betmgm_line_in_another_event_survives(offers: pd.DataFrame) -> None:
    kept = filter_offers(offers)
    row = pick(kept, "evt_ev_h2h", "betmgm", "Los Angeles Lakers")
    assert row["price_am"] == 108


def test_live_game_dropped_unless_included(offers: pd.DataFrame) -> None:
    live = offers[offers["event_id"].str.startswith("evt_live")]
    assert len(live) == 4 and live["is_live"].all()
    assert filter_offers(offers)["event_id"].str.startswith("evt_live").sum() == 0
    assert filter_offers(offers, include_live=True)["event_id"].str.startswith("evt_live").sum() == 4


def test_max_age_is_adjustable(offers: pd.DataFrame) -> None:
    assert len(filter_offers(offers, max_age_s=30, include_live=True)) < 26
    assert len(filter_offers(offers, max_age_s=5000, include_live=True)) == 28


# ---------- bad data ----------

def _event(price: object, last_update: object = "2026-11-12T22:59:00Z") -> list[dict]:
    return [{
        "id": "bad", "sport_key": "basketball_nba", "commence_time": "2026-11-13T00:30:00Z",
        "home_team": "H", "away_team": "A",
        "bookmakers": [{
            "key": "bk", "title": "Bk", "last_update": "2026-11-12T22:58:00Z",
            "markets": [{"key": "h2h", "last_update": last_update, "outcomes": [
                {"name": "H", "price": price}, {"name": "A", "price": -110},
            ]}],
        }],
    }]


@pytest.mark.parametrize("bad_price", [0, 50, -99, None, "abc"])
def test_invalid_prices_are_skipped_not_fatal(bad_price: object) -> None:
    df = parse_odds(_event(bad_price), NOW)
    assert list(df["outcome"]) == ["A"]


def test_market_last_update_falls_back_to_bookmaker() -> None:
    df = parse_odds(_event(-110, last_update=None), NOW)
    assert len(df) == 2
    assert (df["age_s"] == 120.0).all()
