# Beginner-friendly redesign: sport picker, logos, sportsbook chips

Date: 2026-11-12. Status: approved and built.

Built as designed, with two changes: in fixture mode the picker shows all seven
leagues with the others marked "Live only" (not NBA alone), and tile captions
sit under the tiles instead of inside them.

## Intent

The user is new to sports betting and uses the app on a phone. The plain sport
dropdown is hard to scan, cards are text-only, sportsbook names are small, and
the app assumes betting vocabulary. Make it readable at a glance and
understandable without prior knowledge.

## Goals

1. **Sport picker:** a horizontally scrolling row of league chips with logos,
   replacing the dropdown. Fixed list, in this order: NBA, NFL, NHL,
   College Football, College Basketball, Premier League, MLB.
2. **Team logos** on every opportunity card and on the bet screen.
3. **Sportsbook chips:** each book's name in bold on its brand color, larger
   than today's grey text.
4. **Beginner help:** plain-English wording throughout, plus a Learn screen.

## Non-goals

- F1. The Odds API has no motorsport, so it cannot be offered.
- Three-way soccer moneylines (win / draw / win). Premier League shows spread
  and total bets only, as the arb scanner does today.
- Player props, alerts, auto-refresh (still "extras" in SPEC section 5).

## Anti-goals

- A missing or broken logo must never break a card or hide a bet.
- Beginner wording must not hide the numbers; the math stays visible.
- No extra API credits: logos and help cost nothing per scan.

## Approaches (logos)

1. **Real logos from ESPN's image servers, badge fallback. Chosen by the user.**
   ESPN's public team lists cover all seven leagues (NBA 30, NHL 32, NFL 32,
   MLB 30, Premier League 20, college football 763, college basketball 365)
   with name, abbreviation, color and logo address. Looks like a real sports
   app. Logos are trademarked and ESPN doesn't officially offer them for this,
   so they can stop loading without notice.
2. **Badges made in the app** (team-color circle with abbreviation). Can't
   break, but not the real logos. Kept as the fallback for option 1.
3. Bundling logo image files in the repo. Rejected: copies trademarked
   artwork into the project and goes stale.

## Design

### Team and league data (`edge/teams.py`, `assets/teams.json`)
- A one-off script (`tools/build_teams.py`) reads ESPN's team lists and writes
  `assets/teams.json`: for each league, team name -> abbreviation, color, logo
  address. The file is committed; the app never calls ESPN's list at runtime,
  it only loads images by address.
- `teams.lookup(sport_key, team_name)` returns a `Team(name, abbr, color,
  logo_url)`. Matching: exact name, then a normalized match (case, punctuation,
  "St" / "State"). No match returns a badge-only Team with initials and a
  color derived from the name. Unit-tested, including the no-match case.
- League logos come from the same source; MLB shows greyed with
  "Out of season" when The Odds API marks it inactive.

### Sport picker
- A small custom Streamlit component: a scrolling row of chips, each a league
  logo over a short name; the selected chip is outlined in orange.
- Falls back to the current dropdown if the component fails to load.
- Fixture mode shows NBA only, as today.

### Cards and bet screen
- Matchup line shows both team logos (28 px) beside the names.
- Each leg shows the team logo for moneyline and spread bets; totals show an
  over/under arrow icon.
- Sportsbook shown as a chip: bold name, brand color background, e.g.
  DraftKings green, FanDuel blue, BetMGM gold. Unknown books get a neutral chip.
- Images use `onerror` to swap to the badge.

### Beginner help
- **Plain-English line on every card**, e.g. "Bet $48 on Celtics at DraftKings
  and $52 on Knicks at FanDuel. Whoever wins, you get about $101 back."
  Middles and +EV get their own sentence.
- **Tile captions:** Arbs "Profit either way", Middles "Small risk, big
  upside", +EV "Better-than-fair prices".
- **Odds helper** next to each price: "+110 · $100 wins $110",
  "-105 · bet $105 to win $100".
- **Learn screen** (a "?" button in the header): short lessons on reading
  odds, moneyline / spread / total, arbs, middles, +EV, hedging, why books
  limit accounts, and a glossary.
- **Beginner mode** toggle in Settings, on by default: shows the plain-English
  lines and odds helpers, and hides push-only middles.
- **My sportsbooks** list in Settings: only books ticked here are scanned for
  bets. Default: DraftKings, FanDuel, BetMGM, Caesars, ESPN BET, Fanatics,
  bet365 (believed licensed in North Carolina; the user should confirm).
  Offshore books (Bovada, BetOnline, LowVig, MyBookie, BetUS) start unticked.
  +EV consensus still uses every book as reference data.

## Left to the builder
- Exact chip sizes and spacing at 375 px.
- Brand colors per book.
- Wording of the lessons.

## Testing
- Unit tests for `teams.lookup`, the plain-English sentences, the odds helper
  and the sportsbook filter.
- Headless run and a 375 px browser check on fixture data. No credits spent.
