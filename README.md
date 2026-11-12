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
| 2 | API client + parser | not started |
| 3 | Scanners | not started |
| 4 | Streamlit UI | not started |
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

`app.py` arrives in Phase 4. Once it exists:

```powershell
$env:EDGE_USE_FIXTURES = "1"   # fixture data, zero API credits
streamlit run app.py
```
