"""Scanners: find_arbs(), find_middles(), find_ev().

Pure functions: offers DataFrame (already passed through parse.filter_offers)
plus settings in, result DataFrame out. All math comes from edge.odds_math.
"""
from __future__ import annotations

import math
from itertools import combinations
from typing import Any, Iterable

import pandas as pd

from edge import odds_math as om

Row = dict[str, Any]
SideKey = tuple[str, float | None]       # (outcome name, point or None)
Pair = tuple[Row, Row, float]            # leg 1, leg 2, window

LOCAL_TZ = "America/New_York"
PINNACLE_KEY = "pinnacle"
LEG_FIELDS = (
    "side", "point", "price_am", "price_dec", "book", "book_key", "age_s",
    "outcome_link", "market_link", "event_link",
)
BASE_COLUMNS = ["event_id", "matchup", "commence_time", "start_et", "market"]
LEG_COLUMNS = [f"leg{n}_{f}" for n in (1, 2) for f in LEG_FIELDS]
ARB_COLUMNS = BASE_COLUMNS + LEG_COLUMNS + [
    "max_age_s", "s", "profit_pct", "stake1", "stake2", "payout", "net",
    "r_stake1", "r_stake2", "worst_net", "best_net", "goes_negative",
]
MIDDLE_COLUMNS = BASE_COLUMNS + LEG_COLUMNS + [
    "max_age_s", "window", "push_risk", "s", "hold_pct", "stake1", "stake2",
    "miss_net", "hit_net",
]
EV_COLUMNS = BASE_COLUMNS + list(LEG_FIELDS) + [
    "fair_prob", "fair_odds_am", "ev_pct", "n_books", "reference", "kelly_stake",
]


# ---------- shared helpers ----------

def _point(row: Row) -> float | None:
    value = row.get("point")
    return None if value is None or math.isnan(value) else float(value)


def _start_et(ts: pd.Timestamp) -> str:
    """Start time in US Eastern, e.g. 'Thu 7:30 PM'."""
    t = ts.tz_convert(LOCAL_TZ)
    return f"{t:%a} {t.hour % 12 or 12}:{t:%M} {t:%p}"


def _base(row: Row) -> Row:
    return {
        "event_id": row["event_id"],
        "matchup": row["matchup"],
        "commence_time": row["commence_time"],
        "start_et": _start_et(row["commence_time"]),
        "market": row["market"],
    }


def _leg(row: Row, prefix: str = "") -> Row:
    values = {**row, "side": row["outcome"], "point": _point(row)}
    return {f"{prefix}{f}": values[f] for f in LEG_FIELDS}


def _groups(df: pd.DataFrame) -> Iterable[tuple[str, list[Row]]]:
    """(market, rows) for each event + market in the offers table."""
    for (_, market), group in df.groupby(["event_id", "market"], sort=True):
        yield market, group.to_dict("records")


def _best_sides(rows: list[Row]) -> dict[SideKey, Row]:
    """Best price for each (outcome, point); ties go to the fresher line."""
    best: dict[SideKey, Row] = {}
    for row in rows:
        key = (row["outcome"], _point(row))
        held = best.get(key)
        if held is None or (row["price_dec"], -row["age_s"]) > (held["price_dec"], -held["age_s"]):
            best[key] = row
    return best


def _pairs(market: str, sides: dict[SideKey, Row]) -> list[Pair]:
    """Every opposing pair once, with its window (0 = same line = arb candidate)."""
    keys = sorted(sides, key=lambda k: (k[0], k[1] if k[1] is not None else 0.0))
    if market == "h2h":
        # Two-outcome sports only; 3-way soccer (with a Draw) is skipped.
        return [(sides[keys[0]], sides[keys[1]], 0.0)] if len(keys) == 2 else []
    if market == "spreads":
        # combinations() over sorted keys visits each pair once (draft bug #2).
        return [
            (sides[a], sides[b], round(om.spread_window(a[1], b[1]), 6))
            for a, b in combinations(keys, 2)
            if a[0] != b[0] and a[1] is not None and b[1] is not None
        ]
    if market == "totals":
        overs = [k for k in keys if k[0] == "Over" and k[1] is not None]
        unders = [k for k in keys if k[0] == "Under" and k[1] is not None]
        return [
            (sides[o], sides[u], round(om.totals_window(o[1], u[1]), 6))
            for o in overs
            for u in unders
        ]
    return []


def _two_leg_row(a: Row, b: Row) -> Row:
    return {
        **_base(a),
        **_leg(a, "leg1_"),
        **_leg(b, "leg2_"),
        "max_age_s": max(a["age_s"], b["age_s"]),
    }


def _frame(rows: list[Row], columns: list[str], sort_by: str) -> pd.DataFrame:
    df = pd.DataFrame(rows, columns=columns)
    return df.sort_values(sort_by, ascending=False, kind="stable").reset_index(drop=True)


# ---------- arbitrage ----------

def find_arbs(
    df: pd.DataFrame,
    bankroll: float = 100.0,
    min_profit_pct: float = 0.0,
    stake_step: float = 0.01,
) -> pd.DataFrame:
    """Two-way arbs on h2h, spreads (a + b = 0) and totals (same point)."""
    out: list[Row] = []
    for market, rows in _groups(df):
        for a, b, window in _pairs(market, _best_sides(rows)):
            if window != 0.0:
                continue
            arb = om.arb_two_way(a["price_dec"], b["price_dec"], bankroll)
            if not arb.is_arb or arb.profit_pct < min_profit_pct:
                continue
            r = om.round_stakes(arb.stake1, arb.stake2, a["price_dec"], b["price_dec"], stake_step)
            out.append({
                **_two_leg_row(a, b),
                "s": arb.s,
                "profit_pct": arb.profit_pct,
                "stake1": arb.stake1,
                "stake2": arb.stake2,
                "payout": arb.payout,
                "net": arb.payout - bankroll,
                "r_stake1": r.stake1,
                "r_stake2": r.stake2,
                "worst_net": r.worst_net,
                "best_net": r.best_net,
                "goes_negative": r.goes_negative,
            })
    return _frame(out, ARB_COLUMNS, "profit_pct")


# ---------- middles ----------

def find_middles(
    df: pd.DataFrame,
    bankroll: float = 100.0,
    min_hold_pct: float = om.DEFAULT_MIN_MIDDLE_HOLD_PCT,
    min_window: float = 0.5,
) -> pd.DataFrame:
    """Middles on spreads (a + b > 0) and totals (Under point > Over point)."""
    out: list[Row] = []
    for market, rows in _groups(df):
        for a, b, window in _pairs(market, _best_sides(rows)):
            if window <= 0.0 or window < min_window:
                continue
            mid = om.middle(a["price_dec"], b["price_dec"], bankroll)
            if mid.hold_pct < min_hold_pct:
                continue
            out.append({
                **_two_leg_row(a, b),
                "window": window,
                "push_risk": om.has_push_risk(_point(a), _point(b)),
                "s": mid.s,
                "hold_pct": mid.hold_pct,
                "stake1": mid.stake1,
                "stake2": mid.stake2,
                "miss_net": mid.miss_net,
                "hit_net": mid.hit_net,
            })
    return _frame(out, MIDDLE_COLUMNS, "hold_pct")


# ---------- +EV versus consensus ----------

Quote = tuple[Row, Row]   # one book's two sides of the same line


def _book_quotes(market: str, rows: list[Row]) -> dict[tuple[SideKey, ...], dict[str, Quote]]:
    """line key -> {book_key: (side A row, side B row)} for books with both sides."""
    by_book: dict[str, list[Row]] = {}
    for row in rows:
        by_book.setdefault(row["book_key"], []).append(row)
    n_outcomes = len({r["outcome"] for r in rows})
    lines: dict[tuple[SideKey, ...], dict[str, Quote]] = {}
    for book_key, book_rows in by_book.items():
        if market == "h2h" and n_outcomes != 2:
            continue
        for a, b, window in _pairs(market, _best_sides(book_rows)):
            if window == 0.0:
                line = ((a["outcome"], _point(a)), (b["outcome"], _point(b)))
                lines.setdefault(line, {})[book_key] = (a, b)
    return lines


def _reference_prob(
    others: dict[str, Quote], side: int, min_books: int, use_pinnacle: bool
) -> tuple[float, int, str] | None:
    """(fair prob, books sampled, reference name), or None when too few books."""
    if use_pinnacle and PINNACLE_KEY in others:
        quote = others[PINNACLE_KEY]
        return om.devig_two_way(quote[0]["price_dec"], quote[1]["price_dec"])[side], 1, "pinnacle"
    if len(others) < min_books:
        return None
    probs = [om.devig_two_way(q[0]["price_dec"], q[1]["price_dec"])[side] for q in others.values()]
    return om.consensus_prob(probs), len(probs), "consensus"


def find_ev(
    df: pd.DataFrame,
    min_ev_pct: float = 1.0,
    min_books: int = 3,
    use_pinnacle: bool = False,
    bankroll: float | None = None,
) -> pd.DataFrame:
    """Prices that beat the no-vig consensus of the *other* books (leave-one-out)."""
    out: list[Row] = []
    for market, rows in _groups(df):
        for quotes in _book_quotes(market, rows).values():
            for book_key, quote in quotes.items():
                others = {k: q for k, q in quotes.items() if k != book_key}
                for side in (0, 1):
                    ref = _reference_prob(others, side, min_books, use_pinnacle)
                    if ref is None:
                        continue
                    p, n_books, reference = ref
                    row = quote[side]
                    ev = om.ev_pct(p, row["price_dec"])
                    if ev < min_ev_pct:
                        continue
                    out.append({
                        **_base(row),
                        **_leg(row),
                        "fair_prob": p,
                        "fair_odds_am": om.fair_odds_am(p),
                        "ev_pct": ev,
                        "n_books": n_books,
                        "reference": reference,
                        "kelly_stake": (
                            om.kelly_stake(bankroll, p, row["price_dec"]) if bankroll else math.nan
                        ),
                    })
    return _frame(out, EV_COLUMNS, "ev_pct")
