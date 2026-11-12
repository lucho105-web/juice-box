# CLAUDE.md — Juice Box (betting edge dashboard)

## What this project is
A local Streamlit dashboard that pulls live odds from The Odds API (v4) and finds:
1. **Arbitrage** across moneylines (h2h), spreads, and totals
2. **Middles** on spreads and totals
3. **+EV outliers** versus a no-vig consensus price
4. A **manual hedge calculator** for a bet the user already holds

The user is a working IT manager (PowerShell/Azure background, comfortable in VS Code). He wants answers backed by data: show the math, not just a verdict.

## Stack and layout
- Python 3.11+, Streamlit, requests, pandas, python-dotenv, pytest
- Keep the math away from the UI so it can be tested:

```
betting_edge_app/
├── CLAUDE.md
├── assets/               # Juice Box logo + icon files (final)
├── .env                  # ODDS_API_KEY=...  (never committed)
├── .env.example
├── .gitignore            # .env, venv/, __pycache__/, .cache/
├── requirements.txt
├── app.py                # Streamlit UI only — no math in here
├── edge/
│   ├── __init__.py
│   ├── odds_math.py      # conversions, de-vig, stake splits, hedge
│   ├── api.py            # The Odds API client + caching + quota tracking
│   ├── parse.py          # raw JSON -> normalized offers table (keeps link fields)
│   ├── links.py          # deep-link fallback + state localization (nc)
│   └── scanners.py       # find_arbs(), find_middles(), find_ev()
├── tests/
│   ├── test_odds_math.py
│   ├── test_scanners.py
│   └── fixtures/sample_nba.json
└── docs/SPEC.md          # full functional spec — read before building
```

## Commands
- Setup: `python -m venv venv` → activate → `pip install -r requirements.txt`
- Run: `streamlit run app.py`
- Test: `pytest -q`  (run after every change to `edge/`)

## Name and logo
The app is called **Juice Box** ("juice" = the vig; the app squeezes it out). It's private, for one user. The logo is "Cool Box": a lime juice box in sunglasses on an orange tile. Final files are in `assets/` — don't redraw them.
- `assets/icon-square.svg`, `icon-512.png`, `icon-192.png`, `apple-touch-icon.png` (180 px): full-bleed, for home-screen icons (the phone rounds the corners)
- `assets/icon-rounded.svg`, `icon-rounded-512.png`, `favicon-32.png`: pre-rounded, for the browser tab and in-app header
- Logo colors: orange `#FF8A1F`, lime `#B6F36A`, dark green `#0F3D2E`, cream `#FFF8EE`, ink `#111111`.
- **App theme is "Graphite" (dark)** and the layout is a **home dashboard with drill-in screens, not tabs**. Both were approved by the user; see SPEC §4e for the screens and palette. The theme lives in `.streamlit/config.toml`. Orange is for primary buttons, lime for profit.
- Use `st.set_page_config(page_title="Juice Box", page_icon="assets/favicon-32.png")` and show the rounded icon next to the title.

## Primary device: phone
The user mostly runs this on his phone. Design for a ~390 px-wide screen first: cards over tables, big full-width buttons, settings in an expander. Every opportunity card gets an **"Open bet ↗"** button per leg that uses the API's bet-slip deep link (SPEC §4c). Links can open the book's app with the selection added, but they can't set the stake or place the bet, so add a "Copy stake" button.

## Rules (do not break)
- **API key comes from `.env`** (`ODDS_API_KEY`) via python-dotenv, or `st.secrets`. Never hard-code it, never print it, never commit `.env`.
- **Endpoint:** `https://api.the-odds-api.com/v4/sports/{sport}/odds`. The reference code had `https://the-odds-api.com{sport_key}/odds`, which is wrong. Don't copy it.
- **Quota:** each call costs `markets × regions` credits, and the free plan gets 500/month. Show `x-requests-remaining`, `x-requests-used` and `x-requests-last` after every call. Cache responses (default 60 s) so reruns don't spend credits. The free `/v4/sports` endpoint fills the sport picker.
- **No automatic polling** unless the user enables it, and always with a credit budget guard.
- **All math lives in `edge/odds_math.py` and gets unit tests**, with hand-checked expected values in the tests.
- **Don't let stale lines produce fake arbs.** Every bookmaker market has a `last_update`. Drop offers older than the user's max age (default 120 s) before scanning, and show line age in every result row.
- **Fixtures first:** develop and test against `tests/fixtures/*.json`. Hit the live API only when the user asks, or for one smoke test.
- Use 4-space indentation and type hints. Keep functions small and pure.
- When unsure about the API shape, check https://the-odds-api.com/liveapi/guides/v4/ instead of guessing.

## Known bugs in the original single-file draft (fixed by design here)
1. Wrong base URL (see above).
2. The spread scanner loops over both orderings, so every pair shows up twice. Dedupe by a sorted (team, point) key.
3. The +EV consensus includes the book being tested, which biases it toward that book. Leave that book out (leave-one-out), or use a sharp book (Pinnacle, `eu` region) as the reference when it's available.
4. Middle hold has a hard-coded −4.5% cutoff. Make it a sidebar setting.
5. Hedge calculator divides by zero or misbehaves on invalid American odds (−99..+99). Validate the input.
6. The pasted code lost its indentation after the spread loop. Rewrite it; don't patch it.
7. Arb stakes are exact cents. Add a "round to $1/$5" option and show the profit after rounding.

## Definition of done for any task
- `pytest -q` passes
- `streamlit run app.py` starts with no errors against fixture data (support `EDGE_USE_FIXTURES=1`)
- New math has tests; new UI has an empty state and an error state
