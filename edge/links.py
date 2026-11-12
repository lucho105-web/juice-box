"""Bet-slip deep links: fallback order and state localization (SPEC section 4c).

Fallback for each leg: outcome link (pre-filled bet slip) -> market link ->
event link (game page) -> the book's home page. A link that still has a
{placeholder} after localization is treated as unusable, because we can't
know what the book expects there.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any, Mapping
from urllib.parse import urlsplit, urlunsplit

LEVELS: tuple[tuple[str, str], ...] = (
    ("outcome_link", "Bet slip"),
    ("market_link", "Market"),
    ("event_link", "Game page"),
)

# Books whose host carries a two-letter state, and which host label it is.
# fanduel:  nj.sportsbook.fanduel.com  -> label 0 (only when 4+ labels)
# betmgm:   sports.nj.betmgm.com       -> label 1
# betrivers: nj.betrivers.com          -> label 0
STATE_HOST_LABEL: dict[str, tuple[str, int]] = {
    "fanduel": ("sportsbook.fanduel.com", 0),
    "betmgm": ("betmgm.com", 1),
    "betrivers": ("betrivers.com", 0),
}

BOOK_HOME: dict[str, str] = {
    "draftkings": "https://sportsbook.draftkings.com",
    "fanduel": "https://sportsbook.fanduel.com",
    "betmgm": "https://sports.{state}.betmgm.com",
    "betrivers": "https://{state}.betrivers.com",
    "williamhill_us": "https://sportsbook.caesars.com",
    "espnbet": "https://espnbet.com",
    "fanatics": "https://sportsbook.fanatics.com",
    "bovada": "https://www.bovada.lv",
    "betonlineag": "https://www.betonline.ag",
    "lowvig": "https://www.lowvig.ag",
}

_PLACEHOLDER = re.compile(r"\{[^{}]+\}")
_STATE = re.compile(r"^[a-z]{2}$")


@dataclass(frozen=True)
class BetLink:
    url: str
    level: str   # "Bet slip", "Market", "Game page" or "Sportsbook"


def _clean_state(state: str | None) -> str:
    """'' when no state is set; raises on anything that isn't two letters."""
    if not state:
        return ""
    value = state.strip().lower()
    if not _STATE.match(value):
        raise ValueError(f"State must be a two-letter code like 'nc', got {state!r}")
    return value


def has_placeholders(url: str) -> bool:
    return bool(_PLACEHOLDER.search(url))


def localize(url: str, book_key: str, state: str | None) -> str:
    """Fill {state} and rewrite known state-specific hosts (nj.betrivers.com ->
    nc.betrivers.com). Unknown books and stateless URLs come back unchanged."""
    st = _clean_state(state)
    if not st:
        return url
    url = url.replace("{state}", st)
    rule = STATE_HOST_LABEL.get(book_key)
    if rule is None:
        return url
    suffix, index = rule
    parts = urlsplit(url)
    host = parts.hostname or ""
    if not host.endswith(suffix):
        return url
    labels = host.split(".")
    expected_len = len(suffix.split(".")) + 1 + (1 if index == 1 else 0)
    if len(labels) != expected_len or not _STATE.match(labels[index]):
        return url
    labels[index] = st
    netloc = ".".join(labels) + (f":{parts.port}" if parts.port else "")
    return urlunsplit(parts._replace(netloc=netloc))


def _value(row: Mapping[str, Any], column: str) -> str | None:
    value = row.get(column)
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    text = str(value).strip()
    return text or None


def _usable(url: str | None, book_key: str, state: str) -> str | None:
    if not url:
        return None
    url = localize(url, book_key, state)
    if has_placeholders(url) or urlsplit(url).scheme != "https":
        return None
    return url


def pick_link(row: Mapping[str, Any], prefix: str, state: str | None) -> BetLink | None:
    """Best usable link for one leg. `prefix` is '' for +EV rows and
    'leg1_' / 'leg2_' for arb and middle rows."""
    st = _clean_state(state)
    book_key = _value(row, f"{prefix}book_key") or ""
    for column, level in LEVELS:
        url = _usable(_value(row, f"{prefix}{column}"), book_key, st)
        if url:
            return BetLink(url, level)
    home = _usable(BOOK_HOME.get(book_key), book_key, st)
    return BetLink(home, "Sportsbook") if home else None
