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
| 5 | Live smoke test, mobile cards, bet links | not started |

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
