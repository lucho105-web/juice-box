"""Build assets/teams.json from ESPN's public team lists.

Run from the project root when a season's teams change:

    python tools/build_teams.py

It needs no API key and sends nothing but plain GET requests. The output is
committed, so the app itself never calls these lists.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from edge.teams import DATA_FILE, LEAGUES, normalize  # noqa: E402

BASE = "https://site.api.espn.com/apis/site/v2/sports"
TIMEOUT_S = 30


def get(url: str) -> dict[str, Any]:
    response = requests.get(url, timeout=TIMEOUT_S)
    response.raise_for_status()
    return response.json()


def pick_logo(logos: list[dict[str, Any]]) -> str | None:
    """Prefer the variant drawn for dark backgrounds; the app theme is dark."""
    if not logos:
        return None
    for logo in logos:
        if "dark" in (logo.get("rel") or []) and logo.get("href"):
            return logo["href"]
    return logos[0].get("href")


def team_entry(team: dict[str, Any]) -> dict[str, str | None]:
    color = (team.get("color") or "").strip()
    return {
        "short": team.get("shortDisplayName") or team.get("name") or team.get("displayName"),
        "abbr": team.get("abbreviation"),
        "color": f"#{color}" if color else None,
        "logo": pick_logo(team.get("logos") or []),
    }


def league_teams(path: str) -> dict[str, dict[str, str | None]]:
    data = get(f"{BASE}/{path}/teams?limit=1000")
    out: dict[str, dict[str, str | None]] = {}
    for item in data["sports"][0]["leagues"][0]["teams"]:
        team = item["team"]
        entry = team_entry(team)
        names = {team.get("displayName"), f"{team.get('location', '')} {team.get('name', '')}".strip()}
        for name in names:
            if name:
                out.setdefault(normalize(name), entry)
    return out


def league_logo(path: str) -> str | None:
    try:
        leagues = get(f"{BASE}/{path}/scoreboard").get("leagues") or []
        return pick_logo(leagues[0].get("logos") or []) if leagues else None
    except (requests.RequestException, KeyError, ValueError):
        return None


def main() -> None:
    result: dict[str, Any] = {"source": "ESPN public team lists", "teams": {}, "leagues": {}}
    for key, title, _short, path in LEAGUES:
        teams = league_teams(path)
        logo = league_logo(path)
        result["teams"][key] = teams
        result["leagues"][key] = {"logo": logo}
        with_logo = sum(1 for t in teams.values() if t["logo"])
        print(f"{title:<20} {len(teams):>4} names, {with_logo:>4} with a logo, league logo: {bool(logo)}")
    DATA_FILE.write_text(json.dumps(result, indent=1, sort_keys=True), encoding="utf-8")
    print(f"Wrote {DATA_FILE.relative_to(ROOT)} ({DATA_FILE.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
