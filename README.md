# Juice Box

A private, phone-first dashboard that pulls live odds from The Odds API and finds
arbitrage, middles and +EV prices, plus a hedge calculator. "Juice" is the vig;
the app squeezes it out.

Full spec: [docs/SPEC.md](docs/SPEC.md). Build rules: [CLAUDE.md](CLAUDE.md).

## Status

| Phase | What | State |
|---|---|---|
| 0 | Scaffold | done |
| 1 | Odds math + tests (`edge/odds_math.py`) | done |
| 2 | API client + parser + fixture (`edge/api.py`, `edge/parse.py`) | done |
| 3 | Scanners: arbs, middles, +EV (`edge/scanners.py`) | done |
| 4 | Streamlit UI: home, lists, bet detail, hedge, settings (`app.py`) | done |
| 5 | Live smoke test (3 credits) | done |
| 5b | Bet links, copy stake, price re-check, leg tracker, bet log, password gate | done |

## Setup (PowerShell)

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env   # then put your key in .env
```

## Test

```powershell
pytest -q
```

## Run

```powershell
.\venv\Scripts\Activate.ps1
$env:EDGE_USE_FIXTURES = "1"   # fixture data, zero API credits
streamlit run app.py
```

Then open http://localhost:8501. With no `ODDS_API_KEY` in `.env`, the app
starts in fixture mode on its own. The fixture toggle is in Settings (gear icon).

Each scan appends a summary line to `.cache/scan_log.csv`.

## Placing a bet

"Place this bet" opens a guided screen:

1. **Re-check prices.** One event, one market: 1 credit per region (free on fixture data).
   "Open bet" stays hidden until a re-check passes, and expires after 2 minutes.
2. **Leg 1** is the leg whose price is furthest above the other books, since it's the
   likeliest to move. "Open bet" opens the sportsbook; "Copy $48" copies the stake.
3. If the book gave you a different price, enter it under "Price you got" and the
   second stake rebalances.
4. Tick "Placed" on each leg. When all legs are ticked the bet is appended to
   `.cache/bets.csv`.

What the links can do, by book (from the Phase 5 live test):

| Book | Link opens |
|---|---|
| DraftKings, FanDuel | Bet slip with the selection added |
| BetMGM | Bet slip; `{state}` is filled from `BET_STATE` |
| BetRivers | Game page (its slip link has blanks we don't guess) |
| BetOnline, Bovada, LowVig | Game page |
| BetUS, MyBookie | No link |

A link can't fill in the stake or place the bet. You must be logged in and
location-verified in the book's app.

## Password

Set `APP_PASSWORD` in `.env` (or in Streamlit secrets when hosted). When it is set,
the app asks for it before showing anything. Set one before using a live key on
your network or hosting the app, so a leaked URL can't spend your credits.

## Getting it on your phone

Pick one. Both are free.

### Option A: home PC + Tailscale (nothing exposed to the internet)

1. Install Tailscale on the PC and the phone, and sign in to the same account on both.
2. On the PC, start the app listening on all interfaces:

   ```powershell
   streamlit run app.py --server.address 0.0.0.0
   ```

3. On the phone, with Tailscale on, open `http://<pc-tailscale-name>:8501`.
   The PC's Tailscale name is in the Tailscale app's device list.
4. The PC has to be on and awake. Set `APP_PASSWORD` anyway.

### Option B: Streamlit Community Cloud (works anywhere)

1. Push this repo to GitHub (it is private; keep it that way).
2. At share.streamlit.io, create an app from the repo with `app.py` as the entry point.
3. In the app's **Secrets**, add:

   ```toml
   ODDS_API_KEY = "your key"
   APP_PASSWORD = "a password you choose"
   BET_STATE = "nc"
   ```

4. In the app's sharing settings, restrict viewers to your own account.
5. The app sleeps when idle and takes about 30 seconds to wake.

`.cache/scan_log.csv` and `.cache/bets.csv` don't persist on Community Cloud: the
disk resets when the app restarts. Use Option A if you want to keep the bet log.

### Home-screen icon

Streamlit doesn't let an app set its own home-screen icon. "Add to Home Screen"
will show a generic or Streamlit icon unless a reverse proxy injects the icon tags.
This hasn't been tested on a phone yet.
