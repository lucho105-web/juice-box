"""Tests for edge/links.py. Sample URLs are the real templates from the Phase 5
live response (ids shortened)."""
import math

import pytest

from edge import links

DK_SLIP = "https://sportsbook.draftkings.com/?outcomes=0ML87198509_3"
DK_EVENT = "https://sportsbook.draftkings.com/event/34988946"
FD_SLIP = "https://sportsbook.fanduel.com/addToBetslip?marketId=42.623958647&selectionId=237492"
MGM_SLIP = "https://sports.{state}.betmgm.com/en/sports?options=20050724-1571894113-2333266156&type=Single"
MGM_EVENT = "https://sports.{state}.betmgm.com/en/sports/events/denver-nuggets-at-memphis-grizzlies-20050724"
BR_SLIP = "https://{state}.betrivers.com/?page=sportsbook#event/1028754050?coupon={pickType}|4412318002|{wagerAmount}"
BR_EVENT = "https://{state}.betrivers.com/?page=sportsbook#event/1028754050"
BOVADA_EVENT = "https://www.bovada.lv/sports/basketball/nba/denver-nuggets-memphis-grizzlies-202611112000"


# ---------- localize ----------

def test_localize_fills_state_placeholder() -> None:
    assert links.localize(MGM_SLIP, "betmgm", "nc") == (
        "https://sports.nc.betmgm.com/en/sports?options=20050724-1571894113-2333266156&type=Single"
    )
    assert links.localize(BR_EVENT, "betrivers", "NC") == "https://nc.betrivers.com/?page=sportsbook#event/1028754050"


def test_localize_rewrites_known_state_hosts() -> None:
    assert links.localize("https://nj.sportsbook.fanduel.com/addToBetslip?x=1", "fanduel", "nc") == (
        "https://nc.sportsbook.fanduel.com/addToBetslip?x=1"
    )
    assert links.localize("https://sports.nj.betmgm.com/en/sports/events/x-1", "betmgm", "nc") == (
        "https://sports.nc.betmgm.com/en/sports/events/x-1"
    )
    assert links.localize("https://pa.betrivers.com/?page=sportsbook", "betrivers", "nc") == (
        "https://nc.betrivers.com/?page=sportsbook"
    )


def test_localize_leaves_stateless_and_unknown_urls_alone() -> None:
    assert links.localize(DK_SLIP, "draftkings", "nc") == DK_SLIP
    assert links.localize(FD_SLIP, "fanduel", "nc") == FD_SLIP
    assert links.localize(BOVADA_EVENT, "bovada", "nc") == BOVADA_EVENT
    # Unknown book with a state-looking host: unchanged
    assert links.localize("https://nj.example.com/bet", "somebook", "nc") == "https://nj.example.com/bet"
    # Path segments that look like a state are not touched
    assert links.localize("https://sportsbook.fanduel.com/nj/game", "fanduel", "nc") == (
        "https://sportsbook.fanduel.com/nj/game"
    )


def test_localize_without_state_keeps_placeholder() -> None:
    assert links.localize(MGM_SLIP, "betmgm", "") == MGM_SLIP
    assert links.localize(MGM_SLIP, "betmgm", None) == MGM_SLIP


@pytest.mark.parametrize("bad_state", ["north carolina", "n", "n1", "x/y"])
def test_localize_rejects_bad_state(bad_state: str) -> None:
    with pytest.raises(ValueError):
        links.localize(MGM_SLIP, "betmgm", bad_state)


def test_has_placeholders() -> None:
    assert links.has_placeholders(MGM_SLIP)
    assert links.has_placeholders(links.localize(BR_SLIP, "betrivers", "nc"))   # {pickType}, {wagerAmount}
    assert not links.has_placeholders(links.localize(MGM_SLIP, "betmgm", "nc"))
    assert not links.has_placeholders(DK_SLIP)


# ---------- pick_link fallback order ----------

def row(outcome=None, market=None, event=None, book_key="draftkings", prefix="") -> dict:
    return {
        f"{prefix}book_key": book_key,
        f"{prefix}outcome_link": outcome,
        f"{prefix}market_link": market,
        f"{prefix}event_link": event,
    }


def test_outcome_link_wins() -> None:
    link = links.pick_link(row(DK_SLIP, None, DK_EVENT), "", "nc")
    assert link == links.BetLink(DK_SLIP, "Bet slip")


def test_market_link_is_second() -> None:
    market = "https://sportsbook.fanduel.com/basketball/nba/x-1?tab=moneyline"
    link = links.pick_link(row(None, market, DK_EVENT, "fanduel"), "", "nc")
    assert link == links.BetLink(market, "Market")


def test_event_link_is_third_and_nan_counts_as_missing() -> None:
    link = links.pick_link(row(math.nan, math.nan, BOVADA_EVENT, "bovada"), "", "nc")
    assert link == links.BetLink(BOVADA_EVENT, "Game page")


def test_book_home_is_last() -> None:
    link = links.pick_link(row(None, None, None, "draftkings"), "", "nc")
    assert link == links.BetLink("https://sportsbook.draftkings.com", "Sportsbook")
    link = links.pick_link(row(None, None, None, "betmgm"), "", "nc")
    assert link == links.BetLink("https://sports.nc.betmgm.com", "Sportsbook")


def test_no_link_for_unknown_book() -> None:
    assert links.pick_link(row(None, None, None, "mybookieag"), "", "nc") is None


def test_betmgm_slip_is_localized() -> None:
    link = links.pick_link(row(MGM_SLIP, None, MGM_EVENT, "betmgm"), "", "nc")
    assert link.level == "Bet slip"
    assert link.url.startswith("https://sports.nc.betmgm.com/")


def test_betrivers_slip_with_unknown_blanks_falls_back_to_game_page() -> None:
    """We don't guess {pickType} / {wagerAmount}; a link with blanks left is unusable."""
    link = links.pick_link(row(BR_SLIP, None, BR_EVENT, "betrivers"), "", "nc")
    assert link == links.BetLink("https://nc.betrivers.com/?page=sportsbook#event/1028754050", "Game page")


def test_state_links_unusable_without_state() -> None:
    """No BET_STATE: BetMGM slip and event both keep {state}, so fall through to... nothing usable."""
    assert links.pick_link(row(MGM_SLIP, None, MGM_EVENT, "betmgm"), "", "") is None


def test_non_https_links_are_ignored() -> None:
    link = links.pick_link(row("javascript:alert(1)", "http://insecure.example/x", DK_EVENT), "", "nc")
    assert link == links.BetLink(DK_EVENT, "Game page")


def test_prefix_for_scanner_legs() -> None:
    leg = row(FD_SLIP, None, None, "fanduel", prefix="leg2_")
    assert links.pick_link(leg, "leg2_", "nc") == links.BetLink(FD_SLIP, "Bet slip")
