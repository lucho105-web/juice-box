"""Tests for edge/service.py and edge/fmt.py."""
import csv
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import pytest

from edge import api, fmt, service

NOW = datetime(2026, 11, 12, 23, 0, 0, tzinfo=timezone.utc)
SETTINGS = service.ScanSettings()


@pytest.fixture(scope="module")
def results() -> service.ScanResults:
    return service.analyze(api.load_fixture(), NOW, SETTINGS)


# ---------- analyze ----------

def test_analyze_counts_match_fixture(results: service.ScanResults) -> None:
    assert (results.n_raw, results.n_fresh) == (28, 22)
    assert (results.count("arb"), results.count("middle"), results.count("ev")) == (2, 1, 1)


def test_analyze_applies_settings() -> None:
    live = service.analyze(api.load_fixture(), NOW, replace(SETTINGS, include_live=True))
    assert live.count("arb") == 3
    strict = service.analyze(api.load_fixture(), NOW, replace(SETTINGS, min_arb_pct=1.5, min_hold_pct=-4.5, min_ev_pct=5.0))
    assert (strict.count("arb"), strict.count("middle"), strict.count("ev")) == (1, 0, 0)
    big = service.analyze(api.load_fixture(), NOW, replace(SETTINGS, bankroll=1000.0, stake_step=5.0))
    h2h = big.arbs[big.arbs["market"] == "h2h"].iloc[0]
    assert (h2h["r_stake1"], h2h["r_stake2"]) == (480.0, 520.0)


def test_analyze_when_every_line_is_stale() -> None:
    later = datetime(2026, 11, 12, 23, 30, 0, tzinfo=timezone.utc)
    stale = service.analyze(api.load_fixture(), later, SETTINGS)
    assert stale.n_raw == 28 and stale.n_fresh == 0
    assert service.best_opportunity(stale) is None


def test_analyze_empty_response() -> None:
    empty = service.analyze([], NOW, SETTINGS)
    assert (empty.n_raw, empty.count("arb"), empty.count("middle"), empty.count("ev")) == (0, 0, 0, 0)


# ---------- best / keys ----------

def test_best_opportunity_prefers_top_arb(results: service.ScanResults) -> None:
    kind, row = service.best_opportunity(results)
    assert kind == "arb"
    assert row["market"] == "spreads"           # +1.744% beats +1.175%


def test_best_opportunity_falls_back_to_ev_then_middle() -> None:
    no_arbs = service.analyze(api.load_fixture(), NOW, replace(SETTINGS, min_arb_pct=50.0))
    assert service.best_opportunity(no_arbs)[0] == "ev"
    only_mid = service.analyze(api.load_fixture(), NOW, replace(SETTINGS, min_arb_pct=50.0, min_ev_pct=50.0))
    assert service.best_opportunity(only_mid)[0] == "middle"


def test_keys_are_unique_and_round_trip(results: service.ScanResults) -> None:
    keys = [
        service.opportunity_key(kind, row)
        for kind in service.KINDS
        for _, row in results.table(kind).iterrows()
    ]
    assert len(keys) == len(set(keys)) == 4
    for kind in service.KINDS:
        row = results.table(kind).iloc[0]
        found = service.find_by_key(results, kind, service.opportunity_key(kind, row))
        assert found is not None and found.equals(row)


def test_find_by_key_returns_none_when_gone(results: service.ScanResults) -> None:
    assert service.find_by_key(results, "arb", "arb|nope") is None


# ---------- scan log ----------

def test_scan_log_appends_with_one_header(tmp_path: Path, results: service.ScanResults) -> None:
    log = tmp_path / ".cache" / "scan_log.csv"
    service.append_scan_log(log, NOW, "basketball_nba", "fixture", 0, results)
    service.append_scan_log(log, NOW, "basketball_nba", "live", 3, results)
    rows = list(csv.reader(log.open(encoding="utf-8")))
    assert rows[0] == service.SCAN_LOG_COLUMNS
    assert len(rows) == 3
    assert rows[1] == ["2026-11-12T23:00:00+00:00", "basketball_nba", "fixture", "0", "22", "2", "1", "1"]
    assert rows[2][2:4] == ["live", "3"]


# ---------- formatting ----------

def test_money() -> None:
    assert fmt.money(48) == "$48"
    assert fmt.money(101.1751) == "$101.18"
    assert fmt.money(1234.5) == "$1,234.50"
    assert fmt.money(1.18, signed=True) == "+$1.18"
    assert fmt.money(-4.5455, signed=True) == "-$4.55"
    assert fmt.money(-0.001, signed=True) == "+$0"


def test_american_and_pct() -> None:
    assert fmt.american(110) == "+110"
    assert fmt.american(-105) == "-105"
    assert fmt.pct(1.17506) == "+1.18%"
    assert fmt.pct(-4.545, 1) == "-4.5%"
    assert fmt.pct(4.0, 1, signed=False) == "4.0%"


def test_leg_label() -> None:
    assert fmt.leg_label("Boston Celtics", None, "h2h") == "Boston Celtics ML"
    assert fmt.leg_label("Boston Celtics", float("nan"), "h2h") == "Boston Celtics ML"
    assert fmt.leg_label("Miami Heat", -2.5, "spreads") == "Miami Heat -2.5"
    assert fmt.leg_label("Chicago Bulls", 2.5, "spreads") == "Chicago Bulls +2.5"
    assert fmt.leg_label("Over", 218.5, "totals") == "Over 218.5"


def test_age() -> None:
    assert fmt.age(34) == "34s"
    assert fmt.age(1200) == "20m"
    assert fmt.age(7200) == "2h"
    assert fmt.age(-5) == "0s"
