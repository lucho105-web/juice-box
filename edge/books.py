"""Sportsbook display data: a name chip in each book's brand color, and the
default 'My sportsbooks' list."""
from __future__ import annotations

from dataclasses import dataclass

NEUTRAL_BG = "#2C2C31"
NEUTRAL_FG = "#F4F4F5"

# key -> (label, chip background, chip text)
BOOKS: dict[str, tuple[str, str, str]] = {
    "draftkings": ("DraftKings", "#53D337", "#0B2A05"),
    "fanduel": ("FanDuel", "#1493FF", "#021B33"),
    "betmgm": ("BetMGM", "#C5A572", "#1A1405"),
    "williamhill_us": ("Caesars", "#0B4435", "#E9CF86"),
    "espnbet": ("ESPN BET", "#E03A3E", "#FFFFFF"),
    "fanatics": ("Fanatics", "#FFFFFF", "#111111"),
    "bet365": ("bet365", "#027B5B", "#FFDF1B"),
    "betrivers": ("BetRivers", "#1B3A6B", "#FFC72C"),
    "hardrockbet": ("Hard Rock Bet", "#6C2BD9", "#FFFFFF"),
    "bovada": ("Bovada", "#CC1F2D", "#FFFFFF"),
    "betonlineag": ("BetOnline", "#3A3A40", "#FF5A4F"),
    "lowvig": ("LowVig", "#3A3A40", "#8FD3FF"),
    "mybookieag": ("MyBookie", "#3A3A40", "#FFB347"),
    "betus": ("BetUS", "#3A3A40", "#7FB3FF"),
    "pinnacle": ("Pinnacle", "#FF5500", "#1A0A00"),
}

# Books believed to be licensed in North Carolina. The user edits this in Settings.
DEFAULT_MY_BOOKS: frozenset[str] = frozenset(
    {"draftkings", "fanduel", "betmgm", "williamhill_us", "espnbet", "fanatics", "bet365"}
)


@dataclass(frozen=True)
class Chip:
    label: str
    bg: str
    fg: str


def label(book_key: str) -> str:
    return BOOKS[book_key][0] if book_key in BOOKS else book_key


def chip(book_key: str, fallback_label: str | None = None) -> Chip:
    """Brand-colored chip for a known book; neutral grey for anything else."""
    if book_key in BOOKS:
        name, bg, fg = BOOKS[book_key]
        return Chip(name, bg, fg)
    return Chip(fallback_label or book_key, NEUTRAL_BG, NEUTRAL_FG)
