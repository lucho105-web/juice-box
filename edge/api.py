"""The Odds API v4 client: caching, quota tracking and a zero-credit fixture mode.

No Streamlit imports here. The API key is never logged, printed or put in an
error message.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

import requests
from dotenv import load_dotenv

BASE_URL = "https://api.the-odds-api.com/v4"
DEFAULT_REGIONS: tuple[str, ...] = ("us",)
DEFAULT_MARKETS: tuple[str, ...] = ("h2h", "spreads", "totals")
DEFAULT_CACHE_TTL_S = 60.0
DEFAULT_TIMEOUT_S = 15.0
FIXTURE_DIR = Path(__file__).resolve().parent.parent / "tests" / "fixtures"
DEFAULT_FIXTURE = "sample_nba.json"
FIXTURE_SPORTS: list[dict[str, str]] = [
    {"key": "basketball_nba", "title": "NBA", "group": "Basketball"}
]


class OddsApiError(Exception):
    """A user-safe API error. The message never contains the API key."""

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.status = status


@dataclass(frozen=True)
class Quota:
    remaining: int | None = None   # x-requests-remaining
    used: int | None = None        # x-requests-used
    last: int | None = None        # x-requests-last (cost of this call)


@dataclass(frozen=True)
class OddsResponse:
    events: list[dict[str, Any]]
    quota: Quota
    source: str                # "live", "cache" or "fixture"
    credits_spent: int         # 0 for cache and fixture
    fetched_at: datetime       # reference "now" for line ages


# ---------- small pure helpers ----------

def scan_cost(markets: Sequence[str], regions: Sequence[str]) -> int:
    """Credits one odds call costs: markets x regions."""
    return len(set(markets)) * len(set(regions))


def _to_int(value: Any) -> int | None:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def parse_quota(headers: Mapping[str, Any]) -> Quota:
    """Read the three quota headers (case-insensitive)."""
    lower = {str(k).lower(): v for k, v in headers.items()}
    return Quota(
        remaining=_to_int(lower.get("x-requests-remaining")),
        used=_to_int(lower.get("x-requests-used")),
        last=_to_int(lower.get("x-requests-last")),
    )


def get_api_key(env: Mapping[str, str] | None = None) -> str:
    """ODDS_API_KEY from .env / the environment. Raises if it is missing."""
    if env is None:
        load_dotenv()
        env = os.environ
    key = (env.get("ODDS_API_KEY") or "").strip()
    if not key:
        raise OddsApiError("No API key found. Add ODDS_API_KEY to your .env file.")
    return key


def use_fixtures(env: Mapping[str, str] | None = None) -> bool:
    """True when EDGE_USE_FIXTURES=1."""
    if env is None:
        load_dotenv()
        env = os.environ
    return (env.get("EDGE_USE_FIXTURES") or "").strip() == "1"


# ---------- fixtures ----------

def load_fixture(name: str = DEFAULT_FIXTURE) -> list[dict[str, Any]]:
    """Load a hand-built odds response from tests/fixtures."""
    path = FIXTURE_DIR / name
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise OddsApiError(f"Fixture file not found: {name}") from exc


def fixture_now(events: Sequence[Mapping[str, Any]]) -> datetime:
    """Newest market last_update in the data; the fixture's fixed 'now'."""
    stamps = [
        market["last_update"]
        for event in events
        for book in event.get("bookmakers", [])
        for market in book.get("markets", [])
        if market.get("last_update")
    ]
    if not stamps:
        return datetime.now(timezone.utc)
    return max(datetime.fromisoformat(s.replace("Z", "+00:00")) for s in stamps)


def fixture_response(name: str = DEFAULT_FIXTURE) -> OddsResponse:
    """An OddsResponse built from a fixture. Spends zero credits."""
    events = load_fixture(name)
    return OddsResponse(
        events=events,
        quota=Quota(),
        source="fixture",
        credits_spent=0,
        fetched_at=fixture_now(events),
    )


# ---------- live client ----------

CacheKey = tuple[str, tuple[str, ...], tuple[str, ...], tuple[str, ...], bool]


class OddsClient:
    """Thin client for The Odds API v4 with an in-memory TTL cache."""

    def __init__(
        self,
        api_key: str,
        session: Any = None,
        cache_ttl_s: float = DEFAULT_CACHE_TTL_S,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if not api_key:
            raise OddsApiError("No API key found. Add ODDS_API_KEY to your .env file.")
        self._api_key = api_key
        self._session = session or requests.Session()
        self._cache_ttl_s = cache_ttl_s
        self._clock = clock
        self._cache: dict[CacheKey, tuple[float, OddsResponse]] = {}
        self.last_quota = Quota()

    def _get(self, path: str, params: dict[str, str]) -> Any:
        """GET and return the raw response, with key-safe errors."""
        try:
            response = self._session.get(
                f"{BASE_URL}{path}",
                params={"apiKey": self._api_key, **params},
                timeout=DEFAULT_TIMEOUT_S,
            )
        except requests.RequestException as exc:
            # str(exc) can contain the full URL including apiKey; never pass it on.
            raise OddsApiError(
                "Couldn't reach The Odds API. Check your connection and try again."
            ) from None
        if response.status_code != 200:
            raise OddsApiError(self._error_message(response), response.status_code)
        return response

    def _error_message(self, response: Any) -> str:
        try:
            message = str(response.json().get("message") or "")
        except (ValueError, AttributeError):
            message = ""
        message = message or f"The Odds API returned HTTP {response.status_code}."
        return message.replace(self._api_key, "***")

    def fetch_sports(self) -> list[dict[str, str]]:
        """In-season sports for the picker. Free: costs no credits."""
        data = self._get("/sports", {}).json()
        return [
            {"key": s["key"], "title": s.get("title", s["key"]), "group": s.get("group", "")}
            for s in data
            if s.get("active") and not s.get("has_outrights")
        ]

    def fetch_odds(
        self,
        sport: str,
        regions: Sequence[str] = DEFAULT_REGIONS,
        markets: Sequence[str] = DEFAULT_MARKETS,
        event_ids: Sequence[str] | None = None,
        include_links: bool = True,
        use_cache: bool = True,
    ) -> OddsResponse:
        """Odds for one sport. Served from cache when younger than the TTL,
        unless use_cache is False (the pre-bet price re-check)."""
        key: CacheKey = (
            sport,
            tuple(sorted(set(regions))),
            tuple(sorted(set(markets))),
            tuple(sorted(set(event_ids or ()))),
            include_links,
        )
        now = self._clock()
        cached = self._cache.get(key) if use_cache else None
        if cached and now - cached[0] < self._cache_ttl_s:
            hit = cached[1]
            return OddsResponse(hit.events, hit.quota, "cache", 0, hit.fetched_at)

        params = {
            "regions": ",".join(key[1]),
            "markets": ",".join(key[2]),
            "oddsFormat": "american",
            "dateFormat": "iso",
        }
        if include_links:
            params["includeLinks"] = "true"
            params["includeSids"] = "true"
        if key[3]:
            params["eventIds"] = ",".join(key[3])

        response = self._get(f"/sports/{sport}/odds", params)
        quota = parse_quota(response.headers)
        self.last_quota = quota
        spent = quota.last if quota.last is not None else scan_cost(key[2], key[1])
        result = OddsResponse(
            events=response.json(),
            quota=quota,
            source="live",
            credits_spent=spent,
            fetched_at=datetime.fromtimestamp(now, tz=timezone.utc),
        )
        self._cache[key] = (now, result)
        return result
