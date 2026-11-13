"""Tests for the beginner wording (edge/explain.py) and the 'My sportsbooks'
and push-middle filters in edge/service.py."""
from dataclasses import replace
from datetime import datetime, timezone

import pytest

from edge import api, explain, service

NOW = datetime(2026, 11, 12, 23, 0, 0, tzinfo=timezone.utc)
SETTINGS = service.ScanSettings()


# ---------- odds helper ----------

@pytest.mark.parametrize(
    "price, text",
    [
        (110, "+110 · $100 wins $110"),
        (100, "+100 · $100 wins $100"),
        (250, "+250 · $100 wins $250"),
        (-105, "-105 · bet $105 to win $100"),
        (-140, "-140 · bet $140 to win $100"),
    ],
)
def test_odds_helper(price: int, text: str) -> None:
    assert explain.odds_helper(price) == text


# ---------- bet phrases ----------

def test_bet_phrases() -> None:
    assert explain.bet_phrase("Boston Celtics", None, "h2h", "Celtics") == "Celtics to win"
    assert explain.bet_phrase("Boston Celtics", float("nan"), "h2h", "Celtics") == "Celtics to win"
    assert explain.bet_phrase("Miami Heat", -2.5, "spreads", "Heat") == "Heat to win by more than 2.5"
    assert explain.bet_phrase("Chicago Bulls", 2.5, "spreads", "Bulls") == "Bulls to win, or lose by less than 2.5"
    assert explain.bet_phrase("Over", 218.5, "totals") == "over 218.5 total points"
    assert explain.bet_phrase("Under", 221.0, "totals") == "under 221 total points"
    assert explain.bet_phrase("Duke Blue Devils", None, "h2h") == "Duke Blue Devils to win"


# ---------- sentences ----------

def test_arb_sentence() -> None:
    legs = [(48.0, "Celtics to win", "DraftKings"), (52.0, "Knicks to win", "FanDuel")]
    assert explain.arb_sentence(legs, 0.80, 1.52) == (
        "Bet $48 on Celtics to win at DraftKings and $52 on Knicks to win at FanDuel. "
        "Whichever bet wins, you make between $0.80 and $1.52 on $100."
    )


def test_arb_sentence_exact_stakes() -> None:
    legs = [(48.18, "Celtics to win", "DraftKings"), (51.82, "Knicks to win", "FanDuel")]
    assert explain.arb_sentence(legs, 1.175, 1.176).endswith("Whichever bet wins, you make $1.18 on $100.")


def test_arb_sentence_warns_when_rounding_loses() -> None:
    legs = [(50.0, "Celtics to win", "DraftKings"), (50.0, "Knicks to win", "FanDuel")]
    text = explain.arb_sentence(legs, -2.38, 5.0)
    assert "this can lose" in text
    assert "-$2.38" in text and "+$5" in text


def test_middle_sentences() -> None:
    legs = [(50.0, "over 218.5 total points", "DraftKings"), (50.0, "under 221.5 total points", "FanDuel")]
    real = explain.middle_sentence(legs, -4.55, 90.91, True)
    assert real == (
        "Bet $50 on over 218.5 total points at DraftKings and $50 on under 221.5 total points at FanDuel. "
        "If the result lands between the two lines, both bets win: +$90.91. "
        "Otherwise you lose about $4.55."
    )
    push = explain.middle_sentence(legs, -4.55, 45.45, False)
    assert "No result wins both bets" in push
    assert "+$45.45" in push and "lose about $4.55" in push


def test_ev_sentence() -> None:
    assert explain.ev_sentence("Lakers to win", "BetMGM", 108, 100, 4.0) == (
        "BetMGM is paying +108 on Lakers to win. The fair price is about +100, so over many "
        "bets like this you'd expect to make about 4.0% of what you stake. "
        "Any single bet can still lose."
    )


def test_lessons_and_glossary_are_filled_in() -> None:
    assert len(explain.LESSONS) >= 6 and len(explain.GLOSSARY) >= 10
    assert all(title and len(body) > 40 for title, body in explain.LESSONS)
    assert set(explain.TILE_CAPTION) == set(service.KINDS)


# ---------- My sportsbooks filter ----------

def test_my_books_none_means_every_book() -> None:
    r = service.analyze(api.load_fixture(), NOW, SETTINGS)
    assert (r.count("arb"), r.count("middle"), r.count("ev")) == (2, 1, 1)


def test_my_books_limits_bets_to_books_you_use() -> None:
    """Without BetMGM the +EV line (at BetMGM) is hidden; arbs at DK + FD stay."""
    mine = replace(SETTINGS, my_books=frozenset({"draftkings", "fanduel"}))
    r = service.analyze(api.load_fixture(), NOW, mine)
    assert (r.count("arb"), r.count("middle"), r.count("ev")) == (2, 1, 0)


def test_my_books_single_book_has_no_two_book_bets() -> None:
    r = service.analyze(api.load_fixture(), NOW, replace(SETTINGS, my_books=frozenset({"draftkings"})))
    assert (r.count("arb"), r.count("middle")) == (0, 0)


def test_ev_still_uses_every_book_as_reference() -> None:
    """Only BetMGM ticked: the Lakers +108 line still compares against the 4 other books."""
    r = service.analyze(api.load_fixture(), NOW, replace(SETTINGS, my_books=frozenset({"betmgm"})))
    assert r.count("ev") == 1
    assert r.evs.iloc[0]["n_books"] == 4
    assert r.evs.iloc[0]["ev_pct"] == pytest.approx(4.0)


# ---------- push-only middles ----------

PUSH_EVENT = [{
    "id": "push_evt", "sport_key": "basketball_nba", "commence_time": "2026-11-13T02:00:00Z",
    "home_team": "Home", "away_team": "Away",
    "bookmakers": [
        {"key": "draftkings", "title": "DraftKings", "last_update": "2026-11-12T22:59:30Z",
         "markets": [{"key": "totals", "last_update": "2026-11-12T22:59:30Z", "outcomes": [
             {"name": "Over", "price": -110, "point": 225.0}, {"name": "Under", "price": -110, "point": 225.0}]}]},
        {"key": "fanduel", "title": "FanDuel", "last_update": "2026-11-12T22:59:30Z",
         "markets": [{"key": "totals", "last_update": "2026-11-12T22:59:30Z", "outcomes": [
             {"name": "Over", "price": -110, "point": 225.5}, {"name": "Under", "price": -110, "point": 225.5}]}]},
    ],
}]


def test_push_middles_shown_by_default_and_hidden_on_request() -> None:
    shown = service.analyze(PUSH_EVENT, NOW, SETTINGS)
    assert shown.count("middle") == 1 and not shown.middles.iloc[0]["both_win"]
    hidden = service.analyze(PUSH_EVENT, NOW, replace(SETTINGS, hide_push_middles=True))
    assert hidden.count("middle") == 0


def test_hiding_push_middles_keeps_real_ones() -> None:
    r = service.analyze(api.load_fixture(), NOW, replace(SETTINGS, hide_push_middles=True))
    assert r.count("middle") == 1
