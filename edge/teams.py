"""Team and league display data: logo address, color, abbreviation, short name.

Data lives in assets/teams.json, built once by tools/build_teams.py from ESPN's
public team lists. The app never calls ESPN's lists at runtime; the browser
only loads logo images by address. A team with no match gets a badge made
from its initials, so a missing logo never breaks a card.
"""
from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

DATA_FILE = Path(__file__).resolve().parent.parent / "assets" / "teams.json"

# The sports the app offers, in picker order: (Odds API key, title, short label, ESPN path)
LEAGUES: tuple[tuple[str, str, str, str], ...] = (
    ("basketball_nba", "NBA", "NBA", "basketball/nba"),
    ("americanfootball_nfl", "NFL", "NFL", "football/nfl"),
    ("icehockey_nhl", "NHL", "NHL", "hockey/nhl"),
    ("americanfootball_ncaaf", "College Football", "College FB", "football/college-football"),
    ("basketball_ncaab", "College Basketball", "College BB", "basketball/mens-college-basketball"),
    ("soccer_epl", "Premier League", "Premier", "soccer/eng.1"),
    ("baseball_mlb", "MLB", "MLB", "baseball/mlb"),
)
LEAGUE_KEYS: tuple[str, ...] = tuple(key for key, *_ in LEAGUES)

# The Odds API name -> ESPN name, after normalize(). Only where they differ.
ALIASES: dict[str, str] = {
    "los angeles clippers": "la clippers",
    "bournemouth": "afc bournemouth",
    "appalachian st mountaineers": "app st mountaineers",
    "sam houston st bearkats": "sam houston bearkats",
    "southern mississippi golden eagles": "southern miss golden eagles",
    "umass minutemen": "massachusetts minutemen",
    "gw revolutionaries": "george washington revolutionaries",
    "se missouri st redhawks": "southeast missouri st redhawks",
}
_TOKEN_SWAPS: dict[str, str] = {"saint": "st", "state": "st", "mt": "mount"}

FALLBACK_COLORS: tuple[str, ...] = (
    "#3B6FB6", "#B6483B", "#3B9B6F", "#8A5BB8", "#B8873B", "#3B9BB6", "#B63B7C", "#6B7A3B",
)


@dataclass(frozen=True)
class Team:
    name: str             # full name as the odds feed gives it
    short: str            # "Celtics", "Duke", "Arsenal"
    abbr: str             # "BOS"
    color: str            # "#007A33"
    logo_url: str | None  # None -> draw the badge


@dataclass(frozen=True)
class League:
    key: str
    title: str
    short: str
    logo_url: str | None


def normalize(name: str) -> str:
    """Lowercase, no accents or punctuation, '&' -> 'and', and 'State' /
    'Saint' -> 'st' so 'Michigan St' and 'Michigan State' meet."""
    text = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    text = text.lower().replace("&", " and ").replace("'", "")
    text = re.sub(r"[^a-z0-9]+", " ", text).strip()
    return " ".join(_TOKEN_SWAPS.get(t, t) for t in text.split())


@lru_cache(maxsize=1)
def _data() -> dict[str, Any]:
    try:
        return json.loads(DATA_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _initials(name: str) -> str:
    words = [w for w in re.split(r"[^A-Za-z0-9]+", name) if w]
    if not words:
        return "?"
    if len(words) == 1:
        return words[0][:3].upper()
    return "".join(w[0] for w in words[:3]).upper()


def _fallback(name: str) -> Team:
    color = FALLBACK_COLORS[sum(name.encode("utf-8")) % len(FALLBACK_COLORS)]
    return Team(name=name, short=name, abbr=_initials(name), color=color, logo_url=None)


def lookup(sport_key: str, team_name: str) -> Team:
    """Display data for a team. Never raises; unknown teams get a badge."""
    teams = _data().get("teams", {}).get(sport_key, {})
    key = normalize(team_name or "")
    entry = teams.get(key) or teams.get(ALIASES.get(key, ""))
    if not entry:
        return _fallback(team_name or "?")
    return Team(
        name=team_name,
        short=entry.get("short") or team_name,
        abbr=entry.get("abbr") or _initials(team_name),
        color=entry.get("color") or _fallback(team_name).color,
        logo_url=entry.get("logo") or None,
    )


def league(sport_key: str) -> League:
    """Display data for a league. Unknown keys get a title made from the key."""
    logo = _data().get("leagues", {}).get(sport_key, {}).get("logo")
    for key, title, short, _ in LEAGUES:
        if key == sport_key:
            return League(key, title, short, logo or None)
    title = sport_key.split("_")[-1].upper()
    return League(sport_key, title, title, None)
