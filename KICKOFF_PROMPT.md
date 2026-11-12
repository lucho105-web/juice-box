# Paste these into Claude Code, one at a time

## Prompt 1 — kickoff (use plan mode: Shift+Tab until "plan mode" shows)
Read CLAUDE.md and docs/SPEC.md completely. I'm building Juice Box, the betting edge dashboard they describe. The logo files are already in assets/. Treat the original single-file draft as a reference for features only. It has the bugs listed in CLAUDE.md, so don't copy its code. Give me a short plan for Phase 0 and Phase 1, then wait for my approval.

## Prompt 2 — after approving the plan
Do Phase 0 and Phase 1. Write the tests in tests/test_odds_math.py first, using every test value from SPEC §2, then implement edge/odds_math.py until `pytest -q` passes. Show me the test output.

## Prompt 3
Do Phase 2. Build tests/fixtures/sample_nba.json by hand to match the real v4 response shape. It needs one known arb, one middle, one +EV line, one stale line, and one duplicate spread pair. Don't call the live API yet.

## Prompt 4
Do Phase 3 (scanners) with tests against the fixture. Each planted case must be found exactly once, and the stale line must be filtered out.

## Prompt 5
Do Phase 4 (Streamlit UI). It must run with EDGE_USE_FIXTURES=1 and spend zero credits. When it's done, tell me the exact command to launch it.

## Prompt 6 — when you're ready to spend 3 credits
My key is in .env. Do Phase 5: make one live call for basketball_nba with regions=us and markets=h2h,spreads,totals. Print the quota headers and row counts per market, then confirm the parser handled the real response.

## Prompt 7 — phone + sportsbook links
Do Phase 5b from SPEC §4b–4d. Add includeLinks=true and includeSids=true to the odds call and keep the outcome, market and event link fields in the parser. Build edge/links.py with the fallback order and NC state localization, with tests first. Switch results to mobile cards with an "Open bet ↗" button and a "Copy $stake" button per leg, plus a price re-check before betting and the leg-placed tracker. Then tell me from the smoke-test data which books gave real bet-slip links and which only gave game pages.

## Prompt 8 — get it on my phone
Add a password gate and write the README hosting section. Walk me step by step through Tailscale on my PC and my phone, then through deploying to Streamlit Community Cloud as a private app with secrets.

## Optional follow-ups
- "Add Discord webhook alerts for arbs ≥ 1.5%; webhook URL goes in .env."
- "Add player props via the event-odds endpoint, with a credit-cost warning before each scan."
- "Add an auto-refresh toggle with a daily credit budget; stop when it's reached."
