# Fixtures

`sample_nba.json` is hand-built to match The Odds API v4 `/odds` response shape
(with `includeLinks=true&includeSids=true`). It is **not** real market data.

**Fixture "now" is `2026-11-12T23:00:00Z`** (the newest `last_update` in the file).
Line ages are measured from that moment, so results never change with the wall clock.

## Planted cases

| Event | Market | What is planted | Expected result |
|---|---|---|---|
| Celtics @ Knicks | h2h | DraftKings Celtics +110, FanDuel Knicks −105 | **Arb**, S = 0.98839, +1.175% |
| Celtics @ Knicks | h2h | BetMGM Knicks +150, 1200 s old | **Stale line**: must be filtered at the default 120 s. If it leaks, it makes a fake 14% arb with DK Celtics +110 |
| Heat @ Bulls | spreads | DraftKings Heat −2.5 +105, FanDuel Bulls +2.5 +102 | **Duplicate pair**: a spread arb (S = 0.98286, +1.744%) that the draft reported twice. Must appear once |
| Rockets @ Mavericks | totals | DraftKings Over 218.5 −110, FanDuel Under 221.5 −110 | **Middle**, window 3.0, hold −4.55%, miss −$4.55, hit +$90.91 on $100 |
| Lakers @ Nuggets | h2h | BetMGM Lakers +108; four other books at −110 / −110 | **+EV**, fair p = 0.50 from 4 books, EV +4.0% |
| Suns @ Warriors | h2h | Started 30 min before fixture "now"; DK Suns +120, FD Warriors +105 | **Live game**: dropped unless "include live" is on |

Row counts: 28 offers raw; 22 after the default filters (2 stale, 4 live removed).

Bet-link fields are only filled in on Celtics @ Knicks: FanDuel has outcome, market
and event links; DraftKings has an event link only; BetMGM has none. Other events
omit the link keys entirely, which the parser must also handle.
