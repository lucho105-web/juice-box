"""Tests for edge/api.py. No network: a fake session stands in for requests."""
from datetime import datetime, timezone
from typing import Any

import pytest
import requests

from edge import api

KEY = "test-key-not-real-123"


class FakeResponse:
    def __init__(self, status: int = 200, body: Any = None, headers: dict | None = None) -> None:
        self.status_code = status
        self._body = [] if body is None else body
        self.headers = headers or {}

    def json(self) -> Any:
        return self._body


class FakeSession:
    def __init__(self, response: FakeResponse | Exception) -> None:
        self.response = response
        self.calls: list[tuple[str, dict]] = []

    def get(self, url: str, params: dict | None = None, timeout: float | None = None) -> FakeResponse:
        self.calls.append((url, dict(params or {})))
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


class Clock:
    def __init__(self, t: float = 1_800_000_000.0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t


QUOTA_HEADERS = {
    "X-Requests-Remaining": "487",
    "X-Requests-Used": "13",
    "X-Requests-Last": "3",
}


def make_client(response: FakeResponse | Exception, clock: Clock | None = None) -> tuple[api.OddsClient, FakeSession]:
    session = FakeSession(response)
    return api.OddsClient(KEY, session=session, clock=clock or Clock()), session


# ---------- pure helpers ----------

def test_scan_cost() -> None:
    assert api.scan_cost(["h2h", "spreads", "totals"], ["us"]) == 3
    assert api.scan_cost(["h2h", "spreads", "totals"], ["us", "eu"]) == 6
    assert api.scan_cost(["h2h"], ["us"]) == 1


def test_parse_quota_is_case_insensitive() -> None:
    q = api.parse_quota({"x-requests-remaining": "487", "X-REQUESTS-USED": "13", "X-Requests-Last": "3"})
    assert (q.remaining, q.used, q.last) == (487, 13, 3)


def test_parse_quota_missing_headers() -> None:
    assert api.parse_quota({}) == api.Quota(None, None, None)


def test_get_api_key() -> None:
    assert api.get_api_key({"ODDS_API_KEY": f"  {KEY} "}) == KEY
    with pytest.raises(api.OddsApiError):
        api.get_api_key({})
    with pytest.raises(api.OddsApiError):
        api.get_api_key({"ODDS_API_KEY": "  "})


def test_use_fixtures_flag() -> None:
    assert api.use_fixtures({"EDGE_USE_FIXTURES": "1"}) is True
    assert api.use_fixtures({"EDGE_USE_FIXTURES": "0"}) is False
    assert api.use_fixtures({}) is False


# ---------- fetch_odds ----------

def test_fetch_odds_uses_correct_endpoint_and_params() -> None:
    client, session = make_client(FakeResponse(headers=QUOTA_HEADERS))
    client.fetch_odds("basketball_nba", ["us"], ["h2h", "spreads", "totals"])
    url, params = session.calls[0]
    assert url == "https://api.the-odds-api.com/v4/sports/basketball_nba/odds"
    assert params["apiKey"] == KEY
    assert params["regions"] == "us"
    assert set(params["markets"].split(",")) == {"h2h", "spreads", "totals"}
    assert params["oddsFormat"] == "american"
    assert params["dateFormat"] == "iso"
    assert params["includeLinks"] == "true"
    assert params["includeSids"] == "true"
    assert "eventIds" not in params


def test_fetch_odds_event_ids_param() -> None:
    client, session = make_client(FakeResponse(headers=QUOTA_HEADERS))
    client.fetch_odds("basketball_nba", ["us"], ["h2h"], event_ids=["abc"])
    assert session.calls[0][1]["eventIds"] == "abc"


def test_fetch_odds_reports_quota_and_source() -> None:
    client, _ = make_client(FakeResponse(body=[{"id": "e1"}], headers=QUOTA_HEADERS))
    result = client.fetch_odds("basketball_nba")
    assert result.source == "live"
    assert result.events == [{"id": "e1"}]
    assert (result.quota.remaining, result.quota.used, result.quota.last) == (487, 13, 3)
    assert result.credits_spent == 3
    assert client.last_quota == result.quota
    assert result.fetched_at == datetime.fromtimestamp(1_800_000_000.0, tz=timezone.utc)


def test_fetch_odds_cache_hit_spends_nothing() -> None:
    clock = Clock()
    client, session = make_client(FakeResponse(headers=QUOTA_HEADERS), clock)
    first = client.fetch_odds("basketball_nba", ["us"], ["h2h", "totals"])
    clock.t += 59
    second = client.fetch_odds("basketball_nba", ["us"], ["totals", "h2h"])  # order-insensitive
    assert len(session.calls) == 1
    assert second.source == "cache"
    assert second.credits_spent == 0
    assert second.fetched_at == first.fetched_at  # ages stay honest on cached data


def test_fetch_odds_can_skip_the_cache() -> None:
    """The pre-bet re-check must see fresh prices even within the TTL."""
    clock = Clock()
    client, session = make_client(FakeResponse(headers=QUOTA_HEADERS), clock)
    client.fetch_odds("basketball_nba", ["us"], ["h2h"], event_ids=["e1"])
    clock.t += 10
    again = client.fetch_odds("basketball_nba", ["us"], ["h2h"], event_ids=["e1"], use_cache=False)
    assert again.source == "live"
    assert len(session.calls) == 2


def test_fetch_odds_cache_expires_after_ttl() -> None:
    clock = Clock()
    client, session = make_client(FakeResponse(headers=QUOTA_HEADERS), clock)
    client.fetch_odds("basketball_nba")
    clock.t += 61
    assert client.fetch_odds("basketball_nba").source == "live"
    assert len(session.calls) == 2


def test_fetch_odds_cache_is_keyed_on_request() -> None:
    client, session = make_client(FakeResponse(headers=QUOTA_HEADERS))
    client.fetch_odds("basketball_nba", ["us"], ["h2h"])
    client.fetch_odds("basketball_nba", ["us", "eu"], ["h2h"])
    client.fetch_odds("americanfootball_nfl", ["us"], ["h2h"])
    assert len(session.calls) == 3


# ---------- errors never leak the key ----------

def test_api_error_shows_api_message() -> None:
    body = {"message": "Usage quota has been reached.", "error_code": "OUT_OF_USAGE_CREDITS"}
    client, _ = make_client(FakeResponse(status=401, body=body))
    with pytest.raises(api.OddsApiError) as err:
        client.fetch_odds("basketball_nba")
    assert err.value.message == "Usage quota has been reached."
    assert err.value.status == 401


def test_api_error_scrubs_key_from_message() -> None:
    client, _ = make_client(FakeResponse(status=401, body={"message": f"Invalid key {KEY}"}))
    with pytest.raises(api.OddsApiError) as err:
        client.fetch_odds("basketball_nba")
    assert KEY not in str(err.value)


def test_api_error_without_json_message() -> None:
    client, _ = make_client(FakeResponse(status=500, body={}))
    with pytest.raises(api.OddsApiError) as err:
        client.fetch_odds("basketball_nba")
    assert "500" in err.value.message


def test_network_error_never_leaks_key() -> None:
    boom = requests.ConnectionError(f"Max retries: /v4/sports/x/odds?apiKey={KEY}")
    client, _ = make_client(boom)
    with pytest.raises(api.OddsApiError) as err:
        client.fetch_odds("basketball_nba")
    assert KEY not in str(err.value)
    assert err.value.__cause__ is None  # original exception text is not chained


def test_failed_call_is_not_cached() -> None:
    client, session = make_client(FakeResponse(status=500, body={}))
    for _ in range(2):
        with pytest.raises(api.OddsApiError):
            client.fetch_odds("basketball_nba")
    assert len(session.calls) == 2


def test_client_requires_a_key() -> None:
    with pytest.raises(api.OddsApiError):
        api.OddsClient("")


# ---------- sports list ----------

def test_fetch_sports_keeps_active_non_outright_only() -> None:
    body = [
        {"key": "basketball_nba", "title": "NBA", "group": "Basketball", "active": True, "has_outrights": False},
        {"key": "baseball_mlb", "title": "MLB", "group": "Baseball", "active": False, "has_outrights": False},
        {"key": "golf_masters_winner", "title": "Masters", "group": "Golf", "active": True, "has_outrights": True},
    ]
    client, session = make_client(FakeResponse(body=body))
    assert client.fetch_sports() == [{"key": "basketball_nba", "title": "NBA", "group": "Basketball"}]
    assert session.calls[0][0] == "https://api.the-odds-api.com/v4/sports"


# ---------- fixtures ----------

def test_fixture_response_spends_no_credits() -> None:
    result = api.fixture_response()
    assert result.source == "fixture"
    assert result.credits_spent == 0
    assert len(result.events) == 5
    assert result.fetched_at == datetime(2026, 11, 12, 23, 0, 0, tzinfo=timezone.utc)


def test_missing_fixture_raises_clean_error() -> None:
    with pytest.raises(api.OddsApiError):
        api.load_fixture("does_not_exist.json")
