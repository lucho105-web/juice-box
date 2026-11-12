"""Tests for the placement helpers in edge/service.py: price re-check, which leg
to place first, actual-bet math, the bet log and the password check."""
import copy
import csv
from datetime import datetime, timezone
from pathlib import Path

import pytest

from edge import api, service
from edge.parse import filter_offers, parse_odds

NOW = datetime(2026, 11, 12, 23, 0, 0, tzinfo=timezone.utc)
SETTINGS = service.ScanSettings()


@pytest.fixture(scope="module")
def events() -> list[dict]:
    return api.load_fixture()


@pytest.fixture(scope="module")
def results(events: list[dict]) -> service.ScanResults:
    return service.analyze(events, NOW, SETTINGS)


def h2h_arb(results: service.ScanResults):
    return results.arbs[results.arbs["market"] == "h2h"].iloc[0]


def set_price(events: list[dict], event_id: str, book: str, market: str, outcome: str, price: int) -> list[dict]:
    """Deep copy of the fixture with one price changed."""
    out = copy.deepcopy(events)
    for e in out:
        if e["id"] != event_id:
            continue
        for b in e["bookmakers"]:
            if b["key"] != book:
                continue
            for m in b["markets"]:
                if m["key"] != market:
                    continue
                for o in m["outcomes"]:
                    if o["name"] == outcome:
                        o["price"] = price
    return out


def drop_book(events: list[dict], event_id: str, book: str) -> list[dict]:
    out = copy.deepcopy(events)
    for e in out:
        if e["id"] == event_id:
            e["bookmakers"] = [b for b in e["bookmakers"] if b["key"] != book]
    return out


# ---------- recheck ----------

def test_recheck_same_prices(events: list[dict], results: service.ScanResults) -> None:
    r = service.recheck("arb", h2h_arb(results), events, NOW, SETTINGS)
    assert r.status == "same"
    assert r.prices == (110, -105)
    assert r.metric == pytest.approx(1.175, abs=1e-3)
    assert r.still_good


def test_recheck_price_moved_but_still_an_arb(events: list[dict], results: service.ScanResults) -> None:
    """DK Celtics +110 -> +108: 1/2.08 + 1/1.952381 = 0.480769 + 0.512195 = 0.992964 -> +0.709%."""
    moved = set_price(events, "evt_arb_h2h_0001", "draftkings", "h2h", "Boston Celtics", 108)
    r = service.recheck("arb", h2h_arb(results), moved, NOW, SETTINGS)
    assert r.status == "moved"
    assert r.prices == (108, -105)
    assert r.metric == pytest.approx(0.709, abs=1e-3)
    assert r.still_good


def test_recheck_break_even_is_not_an_arb(events: list[dict], results: service.ScanResults) -> None:
    """+105 / -105: 0.487805 + 0.512195 = 1.000000 -> 0%, no longer an arb."""
    moved = set_price(events, "evt_arb_h2h_0001", "draftkings", "h2h", "Boston Celtics", 105)
    r = service.recheck("arb", h2h_arb(results), moved, NOW, SETTINGS)
    assert r.metric == pytest.approx(0.0, abs=1e-6)
    assert not r.still_good


def test_recheck_arb_gone(events: list[dict], results: service.ScanResults) -> None:
    """DK Celtics +110 -> +100: 0.5 + 0.512195 = 1.012195 -> -1.205%: ARB GONE."""
    moved = set_price(events, "evt_arb_h2h_0001", "draftkings", "h2h", "Boston Celtics", 100)
    r = service.recheck("arb", h2h_arb(results), moved, NOW, SETTINGS)
    assert r.status == "moved"
    assert r.metric == pytest.approx(-1.205, abs=1e-3)
    assert not r.still_good


def test_recheck_leg_missing(events: list[dict], results: service.ScanResults) -> None:
    gone = drop_book(events, "evt_arb_h2h_0001", "fanduel")
    r = service.recheck("arb", h2h_arb(results), gone, NOW, SETTINGS)
    assert r.status == "gone"
    assert r.prices == (110, None)
    assert r.metric is None
    assert not r.still_good


def test_recheck_stale_leg_counts_as_missing(events: list[dict], results: service.ScanResults) -> None:
    later = datetime(2026, 11, 12, 23, 1, 30, tzinfo=timezone.utc)   # DK line now 124 s old
    r = service.recheck("arb", h2h_arb(results), events, later, SETTINGS)
    assert r.status == "gone"


def test_recheck_middle(events: list[dict], results: service.ScanResults) -> None:
    mid = results.middles.iloc[0]
    assert service.recheck("middle", mid, events, NOW, SETTINGS).status == "same"
    worse = set_price(events, "evt_middle_total_0003", "fanduel", "totals", "Under", -130)
    r = service.recheck("middle", mid, worse, NOW, SETTINGS)
    # 1/1.909091 + 1/1.769231 = 0.523810 + 0.565217 = 1.089027 -> hold -8.175%: below -5%
    assert r.status == "moved"
    assert r.metric == pytest.approx(-8.175, abs=1e-3)
    assert not r.still_good


def test_recheck_ev(events: list[dict], results: service.ScanResults) -> None:
    ev = results.evs.iloc[0]
    assert service.recheck("ev", ev, events, NOW, SETTINGS).still_good
    worse = set_price(events, "evt_ev_h2h_0004", "betmgm", "h2h", "Los Angeles Lakers", 100)
    r = service.recheck("ev", ev, worse, NOW, SETTINGS)
    # fair p stays 0.50 (other books unchanged): EV = 0.5 * 2.0 - 1 = 0.0%
    assert r.status == "moved"
    assert r.prices == (100,)
    assert r.metric == pytest.approx(0.0)
    assert not r.still_good


# ---------- which leg first ----------

def test_leg_order_puts_the_outlier_price_first(events: list[dict], results: service.ScanResults) -> None:
    """Celtics +110 at DK is 12.3% above FanDuel's -115; Knicks -105 at FD is
    10.4% above DK's -130. The DK leg is likelier to move, so it goes first."""
    offers = filter_offers(parse_odds(events, NOW))
    assert service.leg_order("arb", h2h_arb(results), offers) == ["leg1_", "leg2_"]


def test_leg_order_can_flip(events: list[dict], results: service.ScanResults) -> None:
    """Spread arb: leg 1 is FD Bulls +2.5 +102 (12.2% above DK's -125), leg 2 is
    DK Heat -2.5 +105 (13.9% above FD's -125). The Heat leg goes first."""
    offers = filter_offers(parse_odds(events, NOW))
    spread = results.arbs[results.arbs["market"] == "spreads"].iloc[0]
    assert spread["leg1_side"] == "Chicago Bulls"
    assert service.leg_order("arb", spread, offers) == ["leg2_", "leg1_"]


def test_leg_order_single_leg(events: list[dict], results: service.ScanResults) -> None:
    offers = filter_offers(parse_odds(events, NOW))
    assert service.leg_order("ev", results.evs.iloc[0], offers) == [""]


# ---------- placed-bet math and log ----------

def test_placed_nets_two_legs() -> None:
    """$48 on +110 and $52 on -105: 48*2.10-100 = +0.80 ; 52*1.952381-100 = +1.52."""
    legs = [
        service.PlacedLeg("DraftKings", "Boston Celtics ML", 110, 48.0),
        service.PlacedLeg("FanDuel", "New York Knicks ML", -105, 52.0),
    ]
    worst, best = service.placed_nets(legs)
    assert worst == pytest.approx(0.80, abs=0.005)
    assert best == pytest.approx(1.52, abs=0.005)


def test_placed_nets_single_leg() -> None:
    worst, best = service.placed_nets([service.PlacedLeg("BetMGM", "Lakers ML", 108, 10.0)])
    assert worst == pytest.approx(-10.0)
    assert best == pytest.approx(10.8)


def test_leg_stakes() -> None:
    """Arb +110/-105 on $100, nearest $1 -> $48 / $52.
    +EV p=0.5 at +108 on $1000: quarter-Kelly $9.26 -> $9."""
    ones = service.ScanSettings(bankroll=100.0, stake_step=1.0)
    assert service.leg_stakes("arb", [110, -105], ones) == [48.0, 52.0]
    assert service.leg_stakes("middle", [-110, -110], ones) == [50.0, 50.0]
    big = service.ScanSettings(bankroll=1000.0, stake_step=1.0)
    assert service.leg_stakes("ev", [108], big, fair_prob=0.5) == [9.0]
    with pytest.raises(ValueError):
        service.leg_stakes("ev", [108], big)


def test_rebalance_after_worse_first_price() -> None:
    """Got +105 (not +110) on $48: payout 98.40, so leg 2 needs 98.40/1.952381 = $50.40."""
    assert service.rebalanced_stake(48.0, 105, -105) == pytest.approx(50.40, abs=0.005)


def test_bet_log(tmp_path: Path) -> None:
    log = tmp_path / ".cache" / "bets.csv"
    legs = [
        service.PlacedLeg("DraftKings", "Boston Celtics ML", 110, 48.0),
        service.PlacedLeg("FanDuel", "New York Knicks ML", -105, 52.0),
    ]
    service.append_bet_log(log, NOW, "arb", "Boston Celtics @ New York Knicks", "h2h", legs)
    service.append_bet_log(log, NOW, "ev", "Lakers @ Nuggets", "h2h",
                           [service.PlacedLeg("BetMGM", "Lakers ML", 108, 10.0)], fair_prob=0.5)
    rows = list(csv.DictReader(log.open(encoding="utf-8")))
    assert len(rows) == 2
    arb = rows[0]
    assert arb["books"] == "DraftKings | FanDuel"
    assert arb["prices"] == "+110 | -105"
    assert arb["stakes"] == "48.00 | 52.00"
    assert (arb["total_staked"], arb["worst_net"], arb["best_net"], arb["expected_net"]) == (
        "100.00", "0.80", "1.52", "0.80"
    )
    ev = rows[1]
    assert ev["expected_net"] == "0.40"     # 10 * (0.5 * 2.08 - 1)
    assert (ev["worst_net"], ev["best_net"]) == ("-10.00", "10.80")


# ---------- password ----------

def test_check_password() -> None:
    assert service.check_password("hunter2", "hunter2")
    assert not service.check_password("hunter3", "hunter2")
    assert not service.check_password("", "hunter2")
    assert not service.check_password("anything", "")


def test_recheck_cost() -> None:
    """One market for one event: 1 credit per region."""
    assert service.recheck_cost(["us"]) == 1
    assert service.recheck_cost(["us", "eu"]) == 2
