"""Tests for edge/scanners.py.

Fixture tests: every planted case in tests/fixtures/README.md must be found
exactly once, and the stale line must not produce a fake arb.
"""
from datetime import datetime, timezone

import pandas as pd
import pytest

from edge import api
from edge.parse import filter_offers, parse_odds
from edge.scanners import (
    ARB_COLUMNS, EV_COLUMNS, MIDDLE_COLUMNS, find_arbs, find_ev, find_middles,
)

NOW = datetime(2026, 11, 12, 23, 0, 0, tzinfo=timezone.utc)


@pytest.fixture(scope="module")
def raw() -> pd.DataFrame:
    return parse_odds(api.load_fixture(), NOW)


@pytest.fixture(scope="module")
def offers(raw: pd.DataFrame) -> pd.DataFrame:
    return filter_offers(raw)


def make_offers(market: str, books: dict[str, list[tuple]]) -> pd.DataFrame:
    """Small synthetic event: {book_key: [(outcome, price, point-or-None), ...]}."""
    event = {
        "id": "synthetic", "sport_key": "test", "commence_time": "2026-11-13T00:30:00Z",
        "home_team": "Home", "away_team": "Away",
        "bookmakers": [
            {
                "key": key, "title": key.title(), "last_update": "2026-11-12T22:59:30Z",
                "markets": [{
                    "key": market, "last_update": "2026-11-12T22:59:30Z",
                    "outcomes": [
                        {"name": n, "price": p, **({"point": pt} if pt is not None else {})}
                        for n, p, pt in outcomes
                    ],
                }],
            }
            for key, outcomes in books.items()
        ],
    }
    return filter_offers(parse_odds([event], NOW))


# ---------- arbs: fixture ----------

def test_arbs_finds_each_planted_arb_exactly_once(offers: pd.DataFrame) -> None:
    arbs = find_arbs(offers, bankroll=100.0)
    assert list(arbs.columns) == ARB_COLUMNS
    assert len(arbs) == 2
    assert list(arbs["market"]) == ["spreads", "h2h"]   # sorted by profit, best first


def test_h2h_arb_values(offers: pd.DataFrame) -> None:
    """SPEC: +110 / -105, $100 -> S 0.98839, 1.175%, $48.18 / $51.82, $101.18."""
    arbs = find_arbs(offers, bankroll=100.0)
    arb = arbs[arbs["market"] == "h2h"].iloc[0]
    assert arb["matchup"] == "Boston Celtics @ New York Knicks"
    assert arb["start_et"] == "Thu 7:30 PM"
    assert (arb["leg1_side"], arb["leg1_book"], arb["leg1_price_am"]) == ("Boston Celtics", "DraftKings", 110)
    assert (arb["leg2_side"], arb["leg2_book"], arb["leg2_price_am"]) == ("New York Knicks", "FanDuel", -105)
    assert arb["s"] == pytest.approx(0.98839, abs=1e-5)
    assert arb["profit_pct"] == pytest.approx(1.175, abs=1e-3)
    assert round(arb["stake1"], 2) == 48.18
    assert round(arb["stake2"], 2) == 51.82
    assert round(arb["payout"], 2) == 101.18
    assert arb["net"] == pytest.approx(1.18, abs=0.005)
    assert arb["max_age_s"] == pytest.approx(34.0)       # DK leg is the older one
    assert "addToBetslip" in arb["leg2_outcome_link"]    # link fields carried through


def test_duplicate_spread_pair_appears_once(offers: pd.DataFrame) -> None:
    """Draft bug #2: 1/2.05 + 1/2.02 = 0.982855 -> +1.744%, reported once."""
    spreads = find_arbs(offers)
    spreads = spreads[spreads["market"] == "spreads"]
    assert len(spreads) == 1
    arb = spreads.iloc[0]
    assert {arb["leg1_side"], arb["leg2_side"]} == {"Miami Heat", "Chicago Bulls"}
    assert arb["leg1_point"] + arb["leg2_point"] == 0
    assert arb["s"] == pytest.approx(0.982855, abs=1e-6)
    assert arb["profit_pct"] == pytest.approx(1.744, abs=1e-3)


def test_dedupe_does_not_depend_on_row_order(offers: pd.DataFrame) -> None:
    reversed_offers = offers.iloc[::-1].reset_index(drop=True)
    assert len(find_arbs(reversed_offers)) == 2
    assert len(find_middles(reversed_offers)) == 1
    assert len(find_ev(reversed_offers)) == 1


def test_stale_line_makes_a_fake_arb_only_when_unfiltered(raw: pd.DataFrame, offers: pd.DataFrame) -> None:
    """BetMGM Knicks +150 (1200 s old) + DK Celtics +110 would 'pay' 14%."""
    unfiltered = find_arbs(filter_offers(raw, max_age_s=5000))
    fake = unfiltered[unfiltered["event_id"] == "evt_arb_h2h_0001"].iloc[0]
    assert fake["leg2_book"] == "BetMGM"
    assert fake["profit_pct"] > 14
    real = find_arbs(offers)
    assert "BetMGM" not in set(real["leg1_book"]) | set(real["leg2_book"])
    assert real["max_age_s"].max() <= 120


def test_live_game_arb_only_when_included(raw: pd.DataFrame, offers: pd.DataFrame) -> None:
    assert "evt_live_h2h_0005" not in set(find_arbs(offers)["event_id"])
    with_live = find_arbs(filter_offers(raw, include_live=True))
    assert len(with_live) == 3
    assert "evt_live_h2h_0005" in set(with_live["event_id"])


def test_min_profit_threshold(offers: pd.DataFrame) -> None:
    assert len(find_arbs(offers, min_profit_pct=1.5)) == 1
    assert len(find_arbs(offers, min_profit_pct=2.0)) == 0


def test_stake_rounding_columns(offers: pd.DataFrame) -> None:
    """$1: 48/52 -> +0.80..+1.52.  $5: 50/50 -> worst -2.38, flagged (draft bug #7)."""
    one = find_arbs(offers, stake_step=1.0)
    one = one[one["market"] == "h2h"].iloc[0]
    assert (one["r_stake1"], one["r_stake2"]) == (48.0, 52.0)
    assert one["worst_net"] == pytest.approx(0.80, abs=0.005)
    assert one["best_net"] == pytest.approx(1.52, abs=0.005)
    assert not one["goes_negative"]
    five = find_arbs(offers, stake_step=5.0)
    five = five[five["market"] == "h2h"].iloc[0]
    assert five["worst_net"] == pytest.approx(-2.38, abs=0.005)
    assert five["goes_negative"]


def test_bankroll_scales_stakes(offers: pd.DataFrame) -> None:
    arb = find_arbs(offers, bankroll=1000.0)
    arb = arb[arb["market"] == "h2h"].iloc[0]
    assert arb["stake1"] + arb["stake2"] == pytest.approx(1000.0)
    assert arb["net"] == pytest.approx(11.75, abs=0.01)


# ---------- arbs: synthetic ----------

def test_three_way_h2h_is_skipped() -> None:
    soccer = make_offers("h2h", {
        "booka": [("Home", 300, None), ("Away", 300, None), ("Draw", 300, None)],
        "bookb": [("Home", 320, None), ("Away", 320, None), ("Draw", 320, None)],
    })
    assert find_arbs(soccer).empty
    assert find_ev(soccer, min_books=1).empty


def test_totals_arb_at_same_point() -> None:
    totals = make_offers("totals", {
        "booka": [("Over", 105, 220.5), ("Under", -125, 220.5)],
        "bookb": [("Over", -125, 220.5), ("Under", 105, 220.5)],
    })
    arbs = find_arbs(totals)
    assert len(arbs) == 1
    assert (arbs.iloc[0]["leg1_side"], arbs.iloc[0]["leg2_side"]) == ("Over", "Under")
    assert arbs.iloc[0]["profit_pct"] == pytest.approx(2.5, abs=1e-6)   # 2.05/2 - 1


def test_no_arb_at_standard_juice() -> None:
    flat = make_offers("h2h", {
        "booka": [("Home", -110, None), ("Away", -110, None)],
        "bookb": [("Home", -110, None), ("Away", -110, None)],
    })
    assert find_arbs(flat).empty


# ---------- middles ----------

def test_middle_found_exactly_once_with_spec_values(offers: pd.DataFrame) -> None:
    """SPEC: O218.5 -110 / U221.5 -110, $100 -> hold -4.55%, miss -$4.55, hit +$90.91."""
    mids = find_middles(offers, bankroll=100.0)
    assert list(mids.columns) == MIDDLE_COLUMNS
    assert len(mids) == 1
    mid = mids.iloc[0]
    assert mid["matchup"] == "Houston Rockets @ Dallas Mavericks"
    assert (mid["leg1_side"], mid["leg1_point"], mid["leg1_book"]) == ("Over", 218.5, "DraftKings")
    assert (mid["leg2_side"], mid["leg2_point"], mid["leg2_book"]) == ("Under", 221.5, "FanDuel")
    assert mid["window"] == pytest.approx(3.0)
    assert mid["hold_pct"] == pytest.approx(-4.55, abs=0.005)
    assert mid["miss_net"] == pytest.approx(-4.55, abs=0.005)
    assert mid["hit_net"] == pytest.approx(90.91, abs=0.005)
    assert not mid["push_risk"]


def test_middle_hold_cutoff_is_a_setting(offers: pd.DataFrame) -> None:
    """Draft bug #4: a hard-coded -4.5% hid the standard -110 / -110 middle."""
    assert len(find_middles(offers, min_hold_pct=-5.0)) == 1
    assert len(find_middles(offers, min_hold_pct=-4.5)) == 0


def test_middle_min_window(offers: pd.DataFrame) -> None:
    assert len(find_middles(offers, min_window=3.0)) == 1
    assert len(find_middles(offers, min_window=3.5)) == 0


def test_spread_middle_once_and_reverse_middle_skipped() -> None:
    """Home +3.5 (A) with Away -1.5 (B): window 2. Home +1.5 with Away -3.5: reverse."""
    spreads = make_offers("spreads", {
        "booka": [("Home", -110, 3.5), ("Away", -110, -3.5)],
        "bookb": [("Home", -110, 1.5), ("Away", -110, -1.5)],
    })
    mids = find_middles(spreads)
    assert len(mids) == 1
    mid = mids.iloc[0]
    legs = {(mid["leg1_side"], mid["leg1_point"]), (mid["leg2_side"], mid["leg2_point"])}
    assert legs == {("Home", 3.5), ("Away", -1.5)}
    assert mid["window"] == pytest.approx(2.0)


def test_whole_number_lines_flag_push_risk() -> None:
    totals = make_offers("totals", {
        "booka": [("Over", -110, 218.0), ("Under", -110, 218.0)],
        "bookb": [("Over", -110, 221.0), ("Under", -110, 221.0)],
    })
    mids = find_middles(totals)
    assert len(mids) == 1
    assert mids.iloc[0]["push_risk"]


# ---------- +EV ----------

def test_ev_found_exactly_once_with_expected_values(offers: pd.DataFrame) -> None:
    """BetMGM Lakers +108 vs four books at -110/-110: p = 0.50, EV = 0.5*2.08-1 = +4.0%."""
    evs = find_ev(offers, bankroll=1000.0)
    assert list(evs.columns) == EV_COLUMNS
    assert len(evs) == 1
    ev = evs.iloc[0]
    assert (ev["side"], ev["book"], ev["price_am"]) == ("Los Angeles Lakers", "BetMGM", 108)
    assert ev["fair_prob"] == pytest.approx(0.50)
    assert ev["fair_odds_am"] == 100
    assert ev["ev_pct"] == pytest.approx(4.0)
    assert ev["n_books"] == 4                      # leave-one-out: BetMGM not in its own consensus
    assert ev["reference"] == "consensus"
    # Kelly f = 0.04/1.08 = 3.70%; quarter-Kelly on $1000 = $9.26
    assert ev["kelly_stake"] == pytest.approx(9.26, abs=0.005)


def test_ev_needs_min_books(offers: pd.DataFrame) -> None:
    assert len(find_ev(offers, min_books=4)) == 1
    assert len(find_ev(offers, min_books=5)) == 0


def test_ev_threshold(offers: pd.DataFrame) -> None:
    assert len(find_ev(offers, min_ev_pct=4.5)) == 0


def test_ev_is_leave_one_out() -> None:
    """Draft bug #3. Target +120 with 3 others at -110/-110.

    Leave-one-out: p = 0.50 -> EV = 0.5 * 2.20 - 1 = +10.0%.
    If the target book were included in its own median the answer would differ
    whenever it shifts the middle; n_books must be 3, not 4.
    """
    h2h = make_offers("h2h", {
        "booka": [("Home", -110, None), ("Away", -110, None)],
        "bookb": [("Home", -110, None), ("Away", -110, None)],
        "bookc": [("Home", -110, None), ("Away", -110, None)],
        "target": [("Home", 120, None), ("Away", -140, None)],
    })
    evs = find_ev(h2h)
    assert len(evs) == 1
    assert evs.iloc[0]["book_key"] == "target"
    assert evs.iloc[0]["n_books"] == 3
    assert evs.iloc[0]["ev_pct"] == pytest.approx(10.0)


def test_ev_pinnacle_as_truth() -> None:
    """Pinnacle Home -120 / Away +110 -> fair Home = 0.545455/1.021645 = 0.533898.

    Target Home +105: EV = 0.533898 * 2.05 - 1 = +9.449% (pinnacle),
    versus median(0.5, 0.5, 0.5, 0.5339) = 0.50 -> +2.5% (consensus).
    """
    h2h = make_offers("h2h", {
        "booka": [("Home", -110, None), ("Away", -110, None)],
        "bookb": [("Home", -110, None), ("Away", -110, None)],
        "bookc": [("Home", -110, None), ("Away", -110, None)],
        "pinnacle": [("Home", -120, None), ("Away", 110, None)],
        "target": [("Home", 105, None), ("Away", -125, None)],
    })
    sharp = find_ev(h2h, use_pinnacle=True)
    row = sharp[sharp["book_key"] == "target"].iloc[0]
    assert row["reference"] == "pinnacle"
    assert row["n_books"] == 1
    assert row["fair_prob"] == pytest.approx(0.533898, abs=1e-6)
    assert row["ev_pct"] == pytest.approx(9.449, abs=1e-3)

    soft = find_ev(h2h, use_pinnacle=False)
    row = soft[soft["book_key"] == "target"].iloc[0]
    assert row["reference"] == "consensus"
    assert row["n_books"] == 4
    assert row["ev_pct"] == pytest.approx(2.5)


def test_ev_on_totals_only_compares_same_point() -> None:
    totals = make_offers("totals", {
        "booka": [("Over", -110, 220.5), ("Under", -110, 220.5)],
        "bookb": [("Over", -110, 220.5), ("Under", -110, 220.5)],
        "bookc": [("Over", -110, 220.5), ("Under", -110, 220.5)],
        "bookd": [("Over", 115, 221.5), ("Under", -135, 221.5)],   # different line: no comparison
        "target": [("Over", 104, 220.5), ("Under", -124, 220.5)],
    })
    evs = find_ev(totals)
    assert len(evs) == 1
    row = evs.iloc[0]
    assert (row["book_key"], row["side"], row["point"]) == ("target", "Over", 220.5)
    assert row["n_books"] == 3
    assert row["ev_pct"] == pytest.approx(2.0)


# ---------- empty input ----------

def test_empty_offers_give_empty_results_with_columns() -> None:
    empty = filter_offers(parse_odds([], NOW))
    assert list(find_arbs(empty).columns) == ARB_COLUMNS
    assert list(find_middles(empty).columns) == MIDDLE_COLUMNS
    assert list(find_ev(empty).columns) == EV_COLUMNS
    assert find_arbs(empty).empty and find_middles(empty).empty and find_ev(empty).empty
