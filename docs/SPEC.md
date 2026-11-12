# SPEC — Juice Box (betting edge dashboard)

Claude Code: read this whole file before writing code. Build one phase at a time (see "Build phases"). Stop after each phase for review.

---

## 1. Data source

**The Odds API v4**
- Odds: `GET https://api.the-odds-api.com/v4/sports/{sport}/odds`
  - params: `apiKey`, `regions` (default `us`), `markets` (default `h2h,spreads,totals`), `oddsFormat=american`, `dateFormat=iso`
  - cost = `len(markets) × len(regions)` credits. Example: 3 markets × 1 region = 3 credits.
- Sports list: `GET /v4/sports` (free; doesn't use credits). Use it to fill the sport dropdown with in-season sports only.
- Response headers to capture: `x-requests-remaining`, `x-requests-used`, `x-requests-last`
- Free plan: 500 credits a month, reset on the 1st.

Optional `eu` region adds Pinnacle (a sharp reference book). The UI must show what a scan will cost **before** the user clicks Scan, e.g. "This scan will use 6 credits (3 markets × 2 regions)."

### Normalized offer row (`edge/parse.py`)
Flatten the JSON into a pandas DataFrame with one row per outcome per book:

| col | example |
|---|---|
| event_id | `e912...` |
| commence_time | UTC datetime |
| matchup | `Celtics @ Knicks` |
| market | `h2h` / `spreads` / `totals` |
| book_key / book | `draftkings` / `DraftKings` |
| outcome | team name, `Over`, `Under` |
| point | float or NaN (h2h) |
| price_am | int, e.g. `-110` |
| price_dec | float |
| last_update | UTC datetime (bookmaker market `last_update`) |
| age_s | seconds since last_update |

Filters applied before any scanner runs: drop rows where `age_s > max_age_s`, and drop events that have already started unless "include live" is on.

---

## 2. Math (`edge/odds_math.py`) — every function unit-tested

```
am_to_dec(a):  a>0 → 1 + a/100 ; a<0 → 1 + 100/|a| ; -100<a<100 → ValueError
dec_to_am(d):  d>=2 → +round((d-1)*100) ; d<2 → -round(100/(d-1))
implied(d)  = 1/d
```

**Two-way arbitrage** (best price on each side, can be different books)
```
S        = 1/d1 + 1/d2          # arb exists when S < 1
profit%  = (1/S - 1) * 100
stake_i  = B * (1/d_i) / S      # B = total stake
payout   = B / S (same whichever side wins)
```
Test: +110 / −105, B=$100 → S=0.98839, profit 1.175%, stakes $48.18 / $51.82, payout $101.18.

**Rounded stakes:** round each stake to the nearest $1 or $5. Then report the worst-case and best-case net. An arb that goes negative after rounding gets flagged.

**Middles**
- Totals: Over X (book A) + Under Y (book B) where Y > X.
- Spreads: Team A at point a + Team B at point b where a + b > 0 (window = a + b). a + b = 0 is an arb candidate. a + b < 0 is a reverse middle; skip it.
- With equal-payout staking:
  - `miss_net = B/S − B` (one side wins; usually a small loss)
  - `hit_net = 2B/S − B` (both win)
  - Show both in dollars, plus the window width.
- Flag whole-number lines ("push risk"). Example: Over 218 / Under 221. A result of exactly 218 or 221 pushes one side.
- **Both legs can only win when a whole-number result fits strictly inside the window** (found in the Phase 5 live test). Over 225 / Under 225.5 has none: 225 refunds the Over and wins the Under. These are **push middles**: `hit_net` does not apply, and the best case is `push_net = B/S + stake_refunded − B` (−110/−110, $100: +$45.45, not +$90.91). Same rule for spreads using team A's margin (low = −a, high = b). Implemented as `odds_math.middle_landings()`; the scanner reports `both_win`, `hit_net` (NaN when impossible), `push_net` and `best_net`, and the UI labels push middles.
- Test: O218.5 −110 / U221.5 −110, B=$100 → hold −4.55%, miss −$4.55, hit +$90.91.
- ⚠️ Default min-hold cutoff = **−5.0%** (sidebar setting). The draft's −4.5% cutoff excluded the standard −110/−110 middle.

**+EV vs consensus (leave-one-out)**
For a target price at book K:
1. For every *other* book that has **both sides** of the same market and point, de-vig that book: `fair_i = (1/d_i) / (1/d_1 + 1/d_2)` (multiplicative).
2. Consensus fair prob `p` = **median** of those fair probs. If Pinnacle is present and "Use Pinnacle as truth" is on, use Pinnacle's de-vigged price instead.
3. `EV% = (p × d_K − 1) × 100`; `fair_odds = dec_to_am(1/p)`
4. Require at least 3 other books (setting). Show how many books were sampled.
- Test: p = 0.50, price +110 → EV +5.0%.
- Optional quarter-Kelly stake: `f = (p·d − 1)/(d − 1)`, stake = bankroll × f × 0.25. With p=0.5 and d=2.10, f = 4.55%.

**Hedge calculator**
```
D = am_to_dec(original), h = am_to_dec(hedge)
full_hedge H = s·D / h
net_if_original_wins = s·D − s − H
net_if_hedge_wins    = H·h − s − H        # equal to the line above at full hedge
```
- Add a slider for a partial hedge (0–100% of H) and show both outcomes live.
- Test: $100 at +250, hedge at −140 → H=$204.17, locked net +$45.83, ROI 15.07%.

---

## 3. Scanners (`edge/scanners.py`)
Pure functions: take the offers DataFrame plus settings, return DataFrames.

- `find_arbs(df, bankroll, min_profit_pct)`: h2h (two-outcome sports only; skip 3-way soccer), spreads where a + b = 0, totals with the same point. Dedupe so each pair appears once.
- `find_middles(df, bankroll, min_hold_pct, min_window)`
- `find_ev(df, min_ev_pct, min_books, use_pinnacle)`
- Every result row includes: matchup, start time (local ET), market, both legs (side, point, price, book), age of the oldest leg, and the metrics above.

Tests use `tests/fixtures/sample_nba.json`. Hand-build a small fixture with one known arb, one known middle, one known +EV line, one stale line that must be filtered out, and one duplicate pair that must appear only once.

---

## 4. UI (`app.py`)
Sidebar:
- Sport: in-season list from `/v4/sports`
- Regions (multiselect, default `us`) and markets (multiselect)
- Credit-cost preview and remaining credits
- Bankroll, stake rounding ($0.01 / $1 / $5)
- Thresholds: min arb %, min middle hold %, min middle window, min EV %, min books
- Max line age (s), include live games, use Pinnacle as truth
- "Use fixture data" toggle (also set by `EDGE_USE_FIXTURES=1`)

Main area: a **Scan** button. Cache results with `st.cache_data(ttl=60)`, keyed on sport, regions and markets. Four tabs:
1. ⚡ Arbitrage
2. 🎯 Middles
3. 📈 +EV
4. 🛡️ Hedge calculator (works without scanning)

Each table is sorted by its main metric, color-coded (green = positive), and has a "Download CSV" button. Every tab has an empty state and an error state. API errors show the API's `message` field and never the key.

Scan log: append each scan's summary (time, sport, credits used, counts per tab) to `.cache/scan_log.csv` so hit rates can be checked over time.

---

## 4b. Phone-first design (primary use is on a phone)
- Set `layout="centered"`, not wide. **No wide tables on mobile.** Each opportunity is a **card**, using `st.container(border=True)`:
  ```
  ⚡ ARB +1.18%   Celtics @ Knicks · 7:30 PM · lines 34s old
  Total stake $100 → payout $101.18 (net +$1.18)
  ┌ LEG 1 ─ DraftKings ───────────────────────┐
  │ Celtics ML  +110   Stake $48   [Open bet ↗] [Copy $48] │
  └───────────────────────────────────────────┘
  ┌ LEG 2 ─ FanDuel ──────────────────────────┐
  │ Knicks ML  −105    Stake $52   [Open bet ↗] [Copy $52] │
  └───────────────────────────────────────────┘
  [ ] Leg 1 placed   [ ] Leg 2 placed
  ```
- Buttons are thumb-sized and full width (`use_container_width=True`). There's a table/card toggle for desktop.
- Move rarely changed settings out of the sidebar into a ⚙️ expander (the sidebar is clumsy on phones). Keep sport, bankroll and Scan at the top.
- Show results for the top N opportunities (default 10) so the page stays short.
- Branding: `st.set_page_config(page_title="Juice Box", page_icon="assets/favicon-32.png")`, rounded logo beside the title, and the brand colors in `.streamlit/config.toml` (see CLAUDE.md).
- Home-screen icon: Streamlit doesn't let an app set its own `apple-touch-icon` or web manifest directly. Test "Add to Home Screen" on the user's phone. If the Juice Box icon doesn't show, document the workaround that works for the chosen hosting (e.g. serving `assets/` via `enableStaticServing` and injecting the link tags, or a reverse proxy on the Tailscale setup). Say plainly if neither works.

## 4c. Bet-slip deep links ("Open bet" button)
**Source:** request odds with `includeLinks=true&includeSids=true` (no extra credit cost). The API can return links at three levels:
- `bookmakers[].markets[].outcomes[].link`: a **pre-filled bet slip** for that exact selection. This is the best case. Example: FanDuel `.../addToBetslip?marketId=…&selectionId=…`
- `bookmakers[].markets[].link`: the market page
- `bookmakers[].link`: the event page

**Fallback order** for each leg: outcome link → market link → event link → book home page. Show which level was used with a small badge: "Bet slip" / "Market" / "Game page".

**State handling (user is in North Carolina):** some books use state subdomains (e.g. `nj.sportsbook.fanduel.com`). Add a `BET_STATE=nc` setting. Write `edge/links.py::localize(url, book_key, state)` to rewrite known state-specific hosts. Unit-test it with sample URLs. If the result is unknown, return the URL unchanged.

**What links can and can't do (show this once in the app's help):**
- A link can open the book's app or site with the selection on the slip. The phone's universal/app links hand it to the installed app.
- A link **cannot** fill in the stake or place the bet. No US sportsbook offers a public bet-placement API. The user types the stake, so a **"Copy $48"** button copies the rounded stake to the clipboard (use a tiny `st.components.v1.html` snippet with `navigator.clipboard.writeText`).
- The user must be logged in and location-verified in the book's app.

**Placement workflow (protects against a one-legged arb):**
1. Before showing "Open bet", re-check prices with a cheap refresh. Use the `eventIds=` param with only that event and only that market (cost 1 credit at 1 region). If either price moved, re-run the math and show the new profit, or "ARB GONE".
2. Open the **harder leg first**: the book with the lower limit or the faster-moving line (default: the softer book).
3. "Leg placed" checkboxes are kept in `st.session_state`. Leg 2 shows "Place now!" once leg 1 is checked.
4. Below each leg, the user can enter the price he actually got. The card recomputes the second-leg stake to still lock in equal payouts. This reuses the hedge math.
5. Log placed bets to `.cache/bets.csv` (time, legs, books, prices, stakes, expected net) so results can be tracked.

## 4d. Hosting so the phone can reach it
Pick one (document both in README):
- **Streamlit Community Cloud (free):** private app, key in Secrets, open from anywhere. Limitation: the app sleeps when idle and takes about 30 s to wake.
- **Home PC + Tailscale (free):** run `streamlit run app.py --server.address 0.0.0.0` and open `http://<pc-tailscale-name>:8501` on the phone. Nothing is exposed to the internet. Requires the PC to be on.
- Either way, add a simple password gate (`st.secrets["APP_PASSWORD"]`) so a leaked URL can't spend credits.

## 4e. Approved design (2026-11-11) — overrides the tab layout in §4 and the light colors in CLAUDE.md

**Layout: home dashboard with drill-in screens, not four tabs.** Use `st.session_state["screen"]` to switch screens; every drill-in screen has a "← Home" (or "← back to list") button at the top.

1. **Home:** logo + title, gear icon for settings. Sport picker and bankroll on one row. Status line ("Scanned 20s ago · 487 credits left"). Three count tiles (Arbs / Middles / +EV); tapping one opens its list. "Best right now": the single best opportunity as a card with one orange "Place this bet" button. A "Hedge a bet you hold" row. "Scan again · N credits" at the bottom. **Before the first scan** the tiles are replaced by one big "Scan · N credits" button (empty state).
2. **List (per bet type):** cards sorted best first, top N (default 10), each with "Place this bet". Reality-check caption from §6 at the bottom. CSV download stays here.
3. **Guided placement:** price re-check banner first (§4c step 1), then one card per leg with "Open bet" (primary) and "Copy $stake", a "Placed" checkbox and a "price I got" input. Leg 2 shows "Place now" once leg 1 is ticked. Footer shows net range after stake rounding.
4. **Hedge calculator:** stake + odds inputs, hedge odds, partial-hedge slider, result card (hedge amount, net if original wins, net if hedge wins, locked return), "Copy $amount". Works without scanning.
5. **Settings (gear):** thresholds, max line age, regions, markets, stake rounding, include live, Pinnacle as truth, fixture toggle.

**Palette: "Graphite" (dark).** Set in `.streamlit/config.toml`.

| Role | Color |
|---|---|
| Background | `#111113` |
| Cards and tiles | `#1C1C1F` |
| Borders | `#2C2C31` |
| Text | `#F4F4F5` |
| Secondary text | `#A0A0A8` |
| Primary buttons | orange `#FF8A1F` with dark text `#2A1400` |
| Profit / positive | lime `#B6F36A` with dark text `#173404` |

The logo files keep their original orange and lime. Only one orange primary button per card.

## 5. Build phases (stop and review after each)
0. **Scaffold:** folders, requirements.txt, .gitignore, .env.example, README with run steps.
1. **Math:** `odds_math.py` plus tests using every test value above. Must pass before moving on.
2. **API + parse:** client with caching, quota headers, and a fixture mode. Parser with a stale-line filter. Tests.
3. **Scanners:** arbs, middles, +EV with dedupe. Tests against the fixture.
4. **UI:** Streamlit app wired to the scanners. Runs in fixture mode with zero credits.
5. **Live smoke test:** one real call (3 credits). Confirm headers, parsing, and which books return outcome-level links.
5b. **Mobile + bet links:** card layout, `links.py` with tests, copy-stake button, re-check before bet, leg tracker, bets.csv, password gate, hosting README. Test on a real phone.
6. **Extras (only on request):** Discord webhook alerts for arbs above X%, player props through `/v4/sports/{sport}/events/{id}/odds` (costs per event; warn about credit use), auto-refresh with a daily credit budget.

## 6. Reality checks to show in the UI (one-line caption per tab)
- Arbs and middles disappear within seconds to minutes. Re-check prices in the sportsbook before betting.
- Books limit accounts that consistently take arbs or +EV prices.
- Stake limits and rounding can wipe out a 1–2% arb.
- +EV is a long-run edge. Individual bets still lose often.
