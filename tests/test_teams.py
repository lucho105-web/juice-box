"""Tests for edge/teams.py and edge/books.py against the committed assets/teams.json."""
import pytest

from edge import books, teams


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("Boston Celtics", "boston celtics"),
        ("Brighton & Hove Albion", "brighton and hove albion"),
        ("Brighton and Hove Albion", "brighton and hove albion"),
        ("San José St Spartans", "san jose st spartans"),
        ("San Jose State Spartans", "san jose st spartans"),
        ("Mt. St. Mary's Mountaineers", "mount st marys mountaineers"),
        ("Mount Saint Mary's Mountaineers", "mount st marys mountaineers"),
        ("Hawai'i Rainbow Warriors", "hawaii rainbow warriors"),
        ("  Miami   (OH) RedHawks ", "miami oh redhawks"),
    ],
)
def test_normalize(raw: str, expected: str) -> None:
    assert teams.normalize(raw) == expected


def test_lookup_pro_team() -> None:
    team = teams.lookup("basketball_nba", "Boston Celtics")
    assert team.name == "Boston Celtics"
    assert team.short == "Celtics"
    assert team.abbr == "BOS"
    assert team.color.startswith("#") and len(team.color) == 7
    assert team.logo_url.startswith("https://a.espncdn.com/")


@pytest.mark.parametrize(
    "sport, name, abbr",
    [
        ("basketball_nba", "Los Angeles Clippers", "LAC"),       # ESPN says "LA Clippers"
        ("soccer_epl", "Bournemouth", "BOU"),                    # ESPN says "AFC Bournemouth"
        ("soccer_epl", "Brighton and Hove Albion", "BHA"),       # ESPN uses "&"
        ("basketball_ncaab", "Michigan St Spartans", "MSU"),     # feed abbreviates State
        ("americanfootball_ncaaf", "UMass Minutemen", "MASS"),
        ("americanfootball_nfl", "Kansas City Chiefs", "KC"),
        ("icehockey_nhl", "Boston Bruins", "BOS"),
        ("baseball_mlb", "New York Yankees", "NYY"),
    ],
)
def test_lookup_handles_name_differences(sport: str, name: str, abbr: str) -> None:
    team = teams.lookup(sport, name)
    assert team.abbr == abbr
    assert team.logo_url is not None


def test_same_name_resolves_per_league() -> None:
    """Boston has a Celtics and a Bruins; the sport key keeps them apart."""
    assert teams.lookup("icehockey_nhl", "Boston Celtics").logo_url is None
    assert teams.lookup("basketball_nba", "Boston Bruins").logo_url is None


def test_unknown_team_gets_a_badge_not_an_error() -> None:
    team = teams.lookup("basketball_nba", "Springfield Isotopes")
    assert team.logo_url is None
    assert team.abbr == "SI"
    assert team.short == "Springfield Isotopes"
    assert team.color in teams.FALLBACK_COLORS
    assert teams.lookup("basketball_nba", "Springfield Isotopes") == team   # stable color


@pytest.mark.parametrize("name", ["", None, "???", "Over"])
def test_lookup_never_raises(name: object) -> None:
    team = teams.lookup("made_up_sport", name)  # type: ignore[arg-type]
    assert team.logo_url is None
    assert team.abbr


def test_league_data() -> None:
    assert teams.LEAGUE_KEYS == (
        "basketball_nba", "americanfootball_nfl", "icehockey_nhl", "americanfootball_ncaaf",
        "basketball_ncaab", "soccer_epl", "baseball_mlb",
    )
    nba = teams.league("basketball_nba")
    assert (nba.title, nba.short) == ("NBA", "NBA")
    assert nba.logo_url.startswith("https://")
    assert teams.league("soccer_epl").title == "Premier League"
    other = teams.league("tennis_atp_wimbledon")
    assert other.logo_url is None and other.title == "WIMBLEDON"


def test_every_listed_league_has_teams_and_a_logo() -> None:
    for key in teams.LEAGUE_KEYS:
        assert teams.league(key).logo_url, key
        assert len(teams._data()["teams"][key]) >= 20, key


# ---------- sportsbooks ----------

def test_known_book_chip() -> None:
    chip = books.chip("draftkings", "DraftKings")
    assert chip.label == "DraftKings"
    assert chip.bg.startswith("#") and chip.fg.startswith("#") and chip.bg != chip.fg


def test_unknown_book_gets_neutral_chip() -> None:
    chip = books.chip("somenewbook", "Some New Book")
    assert (chip.label, chip.bg, chip.fg) == ("Some New Book", books.NEUTRAL_BG, books.NEUTRAL_FG)


def test_default_books_exclude_offshore() -> None:
    assert {"draftkings", "fanduel", "betmgm"} <= books.DEFAULT_MY_BOOKS
    assert not books.DEFAULT_MY_BOOKS & {"bovada", "betonlineag", "lowvig", "mybookieag", "betus"}


def test_book_label() -> None:
    assert books.label("williamhill_us") == "Caesars"
    assert books.label("unknown_key") == "unknown_key"
