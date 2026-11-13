"""Juice Box - Streamlit UI only. No math in here (see edge/).

Layout and palette follow docs/SPEC.md section 4e: a home dashboard with
drill-in screens, phone first, Graphite theme.
"""
from __future__ import annotations

import base64
import html
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
from dotenv import load_dotenv

from edge import api, books, explain, fmt, links, odds_math as om, service, teams
from edge.parse import filter_offers, parse_odds

load_dotenv()
ROOT = Path(__file__).parent
ASSETS = ROOT / "assets"
SCAN_LOG = ROOT / ".cache" / "scan_log.csv"
BET_LOG = ROOT / ".cache" / "bets.csv"
RECHECK_MAX_AGE_S = 120

KIND_LABEL = {"arb": "Arbs", "middle": "Middles", "ev": "+EV"}
REGIONS = ["us", "us2", "eu", "uk", "au"]
MARKETS = ["h2h", "spreads", "totals"]
STAKE_STEPS = {0.01: "Exact cents", 1.0: "Nearest $1", 5.0: "Nearest $5"}
REALITY = {
    "arb": "Arbs vanish within seconds to minutes. Re-check both prices in the sportsbook before you bet. Stake limits and rounding can wipe out a 1-2% arb.",
    "middle": "Middles usually lose a little and occasionally win big. Re-check both prices before you bet.",
    "ev": "+EV is a long-run edge. Individual bets still lose often, and books limit accounts that keep taking these prices.",
}
DEFAULTS: dict[str, Any] = {
    "sport": "basketball_nba",
    "bankroll": 100.0,
    "regions": ["us"],
    "markets": list(MARKETS),
    "stake_step": 1.0,
    "min_arb_pct": 0.0,
    "min_hold_pct": om.DEFAULT_MIN_MIDDLE_HOLD_PCT,
    "min_window": 0.5,
    "min_ev_pct": 1.0,
    "min_books": 3,
    "max_age_s": 120,
    "include_live": False,
    "use_pinnacle": False,
    "top_n": 10,
    "beginner": True,
    "show_logos": True,
    "my_books": sorted(books.DEFAULT_MY_BOOKS),
}

try:
    _sport_picker = components.declare_component(
        "sport_picker", path=str(ROOT / "components" / "sport_picker")
    )
except Exception:   # fall back to the plain dropdown
    _sport_picker = None

CSS = """
<style>
.block-container {padding-top: 3.6rem; padding-bottom: 3rem; max-width: 480px;}
.jb-title {font-size: 1.35rem; font-weight: 600; line-height: 2.5rem; text-align: left; width: 100%;
           white-space: nowrap;}
.jb-row {display: flex; justify-content: space-between; align-items: center; gap: 8px;}
.jb-pill {background: #B6F36A; color: #173404; border-radius: 6px; padding: 2px 8px;
          font-size: .82rem; font-weight: 600; white-space: nowrap;}
.jb-pill.flat {background: #2C2C31; color: #F4F4F5;}
.jb-muted {color: #A0A0A8; font-size: .85rem;}
.jb-strong {font-weight: 600;}
.jb-leg {background: #111113; border-radius: 8px; padding: 6px 10px; margin-top: 6px;}
.jb-big {font-size: 1.5rem; font-weight: 600;}
button[data-testid="stBaseButton-primary"], a[data-testid="stBaseLinkButton-primary"],
a[data-testid="stBaseLinkButton-primary"] p {color: #2A1400 !important; font-weight: 600;}
div[class*="st-key-tile_"] button {height: 4.6rem;}
div[class*="st-key-tile_"] button p {font-size: 1rem; line-height: 1.3;}
div[class*="st-key-tile_"] button strong {font-size: 1.5rem; display: block;}
.jb-tilecap {color: #A0A0A8; font-size: .72rem; line-height: 1.2; text-align: center; margin-top: -8px;}
.jb-say {background: #16261A; color: #D5F5B0; border-radius: 8px; padding: 8px 10px; margin-top: 8px;
         font-size: .9rem; line-height: 1.4;}
.jb-say.warn {background: #2B2416; color: #F5DFA8;}
.jb-book {border-radius: 7px; padding: 3px 9px; font-size: .85rem; font-weight: 700; white-space: nowrap;}
.jb-logo {vertical-align: middle; object-fit: contain; margin-right: 5px;}
.jb-badge {display: inline-flex; align-items: center; justify-content: center; border-radius: 50%;
           color: #fff; font-weight: 700; vertical-align: middle; margin-right: 5px;}
.jb-match {display: flex; align-items: center; flex-wrap: wrap; gap: 2px 4px; font-weight: 600; margin-top: 6px;}
@media (max-width: 640px) {
  div[data-testid="stHorizontalBlock"] {flex-wrap: nowrap !important; gap: .5rem;}
  div[data-testid="stHorizontalBlock"] > div[data-testid="stColumn"] {min-width: 0 !important; flex: 1 1 0 !important;}
  .st-key-hdr div[data-testid="stHorizontalBlock"] > div[data-testid="stColumn"]:first-child {flex: 4 1 0 !important;}
}
</style>
"""

st.set_page_config(
    page_title="Juice Box", page_icon=str(ASSETS / "favicon-32.png"), layout="centered"
)
st.markdown(CSS, unsafe_allow_html=True)


# ---------- state ----------

def _api_key() -> str | None:
    """Key from .env / environment, else Streamlit secrets. Never displayed."""
    try:
        return api.get_api_key()
    except api.OddsApiError:
        pass
    try:
        return str(st.secrets["ODDS_API_KEY"]).strip() or None
    except Exception:
        return None


@st.cache_resource(show_spinner=False)
def _client(key: str) -> api.OddsClient:
    return api.OddsClient(key)


def cfg() -> dict[str, Any]:
    if "cfg" not in st.session_state:
        no_key = _api_key() is None
        st.session_state["cfg"] = {**DEFAULTS, "use_fixtures": api.use_fixtures() or no_key}
    return st.session_state["cfg"]


def go(screen: str, **extra: Any) -> None:
    st.session_state["screen"] = screen
    st.session_state.update(extra)


def settings() -> service.ScanSettings:
    c = cfg()
    return service.ScanSettings(
        bankroll=float(c["bankroll"]),
        stake_step=float(c["stake_step"]),
        min_arb_pct=float(c["min_arb_pct"]),
        min_hold_pct=float(c["min_hold_pct"]),
        min_window=float(c["min_window"]),
        min_ev_pct=float(c["min_ev_pct"]),
        min_books=int(c["min_books"]),
        max_age_s=float(c["max_age_s"]),
        include_live=bool(c["include_live"]),
        use_pinnacle=bool(c["use_pinnacle"]),
        my_books=frozenset(c["my_books"]),
        hide_push_middles=bool(c["beginner"]),
    )


def sports() -> list[dict[str, str]]:
    """Sport picker options. Fixture mode never touches the network."""
    if cfg()["use_fixtures"]:
        return api.FIXTURE_SPORTS
    if "sports" not in st.session_state:
        key = _api_key()
        try:
            if not key:
                raise api.OddsApiError("No API key found.")
            st.session_state["sports"] = _client(key).fetch_sports()   # free endpoint
        except api.OddsApiError as exc:
            st.session_state["sports_error"] = exc.message
            return api.FIXTURE_SPORTS
    return st.session_state["sports"] or api.FIXTURE_SPORTS


def scan_cost() -> int:
    c = cfg()
    return 0 if c["use_fixtures"] else api.scan_cost(c["markets"], c["regions"])


def scan_label(again: bool = False) -> str:
    title = teams.league(cfg()["sport"]).title
    cost = scan_cost()
    credits = f"{cost} credit{'' if cost == 1 else 's'}"
    return f"Scan again · {credits}" if again else f"Scan {title} · {credits}"


def now_for(resp: api.OddsResponse) -> datetime:
    """Fixture data has a fixed clock; live data ages in real time."""
    return resp.fetched_at if resp.source == "fixture" else datetime.now(timezone.utc)


def current_results() -> service.ScanResults | None:
    resp = st.session_state.get("scan")
    if resp is None:
        return None
    return service.analyze(resp.events, now_for(resp), settings())


def do_scan() -> None:
    c = cfg()
    st.session_state.pop("scan_error", None)
    try:
        if c["use_fixtures"]:
            resp = api.fixture_response()
        else:
            key = _api_key()
            if not key:
                raise api.OddsApiError(
                    "No API key found. Add ODDS_API_KEY to your .env file, or turn on fixture data in settings."
                )
            if not c["markets"] or not c["regions"]:
                raise api.OddsApiError("Pick at least one region and one market in settings.")
            resp = _client(key).fetch_odds(c["sport"], c["regions"], c["markets"])
    except api.OddsApiError as exc:
        st.session_state["scan_error"] = exc.message
        return
    st.session_state["scan"] = resp
    st.session_state["scan_sport"] = "basketball_nba" if c["use_fixtures"] else c["sport"]
    try:
        results = service.analyze(resp.events, now_for(resp), settings())
        service.append_scan_log(
            SCAN_LOG, datetime.now(timezone.utc), c["sport"], resp.source, resp.credits_spent, results
        )
    except OSError:
        pass   # the log is a nice-to-have; never block a scan on it


# ---------- small render helpers ----------

def esc(value: Any) -> str:
    return html.escape(str(value))


def pill(text: str, positive: bool = True) -> str:
    return f'<span class="jb-pill{"" if positive else " flat"}">{esc(text)}</span>'


def row_html(left: str, right: str) -> str:
    return f'<div class="jb-row"><span>{left}</span><span class="jb-muted">{right}</span></div>'


def headline(kind: str, row: pd.Series) -> str:
    if kind == "arb":
        return pill(f"Arb {fmt.pct(row['profit_pct'])}")
    if kind == "middle":
        if row["both_win"]:
            return pill(f"Middle {row['window']:g} pts")
        return pill(f"Push middle {row['window']:g} pts", positive=False)
    return pill(f"+EV {fmt.pct(row['ev_pct'], 1, signed=False)}")


def oldest_age(kind: str, row: pd.Series) -> float:
    return row["age_s"] if kind == "ev" else row["max_age_s"]


def scan_sport() -> str:
    return st.session_state.get("scan_sport", cfg()["sport"])


def team_html(team: teams.Team, size: int = 22) -> str:
    """Team logo, or a colored badge with its abbreviation when there's no logo."""
    if team.logo_url and cfg()["show_logos"]:
        return (f'<img class="jb-logo" src="{esc(team.logo_url)}" width="{size}" height="{size}" '
                f'alt="{esc(team.abbr)}">')
    font = max(8, size // 3)
    return (f'<span class="jb-badge" style="background:{esc(team.color)};width:{size}px;'
            f'height:{size}px;font-size:{font}px">{esc(team.abbr[:3])}</span>')


def side_html(row: pd.Series, prefix: str, size: int = 20) -> str:
    """Logo for a team bet; an up / down marker for totals."""
    side = row[f"{prefix}side"]
    if row["market"] == "totals":
        arrow = "▲" if side == "Over" else "▼"
        return (f'<span class="jb-badge" style="background:#2C2C31;width:{size}px;height:{size}px;'
                f'font-size:{size // 2}px">{arrow}</span>')
    return team_html(teams.lookup(scan_sport(), side), size)


def book_html(row: pd.Series, prefix: str) -> str:
    chip = books.chip(row[f"{prefix}book_key"], row[f"{prefix}book"])
    return f'<span class="jb-book" style="background:{chip.bg};color:{chip.fg}">{esc(chip.label)}</span>'


def bet_text(row: pd.Series, prefix: str) -> str:
    """Beginner mode: 'Celtics to win'. Otherwise: 'Boston Celtics ML'."""
    side, point, market = row[f"{prefix}side"], row[f"{prefix}point"], row["market"]
    if not cfg()["beginner"]:
        return fmt.leg_label(side, point, market)
    short = None if market == "totals" else teams.lookup(scan_sport(), side).short
    text = explain.bet_phrase(side, point, market, short)
    return text[0].upper() + text[1:]


def price_html(price_am: int) -> str:
    if cfg()["beginner"]:
        return f'<div class="jb-muted">{esc(explain.odds_helper(int(price_am)))}</div>'
    return ""


def matchup_html(row: pd.Series, size: int = 24) -> str:
    away, _, home = str(row["matchup"]).partition(" @ ")
    if not home:
        return f'<div class="jb-match">{esc(row["matchup"])}</div>'
    a, h = teams.lookup(scan_sport(), away), teams.lookup(scan_sport(), home)
    return (f'<div class="jb-match"><span>{team_html(a, size)}{esc(a.short)}</span>'
            f'<span class="jb-muted">@</span><span>{team_html(h, size)}{esc(h.short)}</span></div>')


def leg_line(row: pd.Series, prefix: str) -> str:
    price = int(row[f"{prefix}price_am"])
    shown = "" if cfg()["beginner"] else f" <span class='jb-strong'>{fmt.american(price)}</span>"
    left = f"{side_html(row, prefix)}{esc(bet_text(row, prefix))}{shown}"
    return (f'<div class="jb-leg"><div class="jb-row"><span>{left}</span>{book_html(row, prefix)}</div>'
            f'{price_html(price)}</div>')


def plain_sentence(kind: str, row: pd.Series) -> str:
    """The one-line 'what do I actually do' explanation for beginners."""
    def phrase(prefix: str) -> str:
        side, market = row[f"{prefix}side"], row["market"]
        short = None if market == "totals" else teams.lookup(scan_sport(), side).short
        return explain.bet_phrase(side, row[f"{prefix}point"], market, short)

    def book(prefix: str) -> str:
        return books.chip(row[f"{prefix}book_key"], row[f"{prefix}book"]).label

    if kind == "ev":
        return explain.ev_sentence(phrase(""), book(""), int(row["price_am"]),
                                   int(row["fair_odds_am"]), float(row["ev_pct"]))
    if kind == "arb":
        legs = [(row["r_stake1"], phrase("leg1_"), book("leg1_")),
                (row["r_stake2"], phrase("leg2_"), book("leg2_"))]
        return explain.arb_sentence(legs, float(row["worst_net"]), float(row["best_net"]))
    legs = [(row["stake1"], phrase("leg1_"), book("leg1_")), (row["stake2"], phrase("leg2_"), book("leg2_"))]
    return explain.middle_sentence(legs, float(row["miss_net"]), float(row["best_net"]), bool(row["both_win"]))


def say_html(kind: str, row: pd.Series) -> str:
    if not cfg()["beginner"]:
        return ""
    warn = (kind == "arb" and row["goes_negative"]) or (kind == "middle" and not row["both_win"])
    return f'<div class="jb-say{" warn" if warn else ""}">{esc(plain_sentence(kind, row))}</div>'


def summary_line(kind: str, row: pd.Series) -> str:
    bankroll = settings().bankroll
    if kind == "arb":
        return f"{fmt.money(bankroll)} → {fmt.money(row['payout'])} (net {fmt.money(row['net'], signed=True)})"
    if kind == "middle":
        best = "Hit" if row["both_win"] else "Push"
        return f"Miss {fmt.money(row['miss_net'], signed=True)} · {best} {fmt.money(row['best_net'], signed=True)}"
    return f"Fair price {fmt.american(row['fair_odds_am'])} from {int(row['n_books'])} book{'s' if row['n_books'] != 1 else ''}"


def card(kind: str, row: pd.Series, where: str) -> None:
    """One opportunity card with a single orange button."""
    key = service.opportunity_key(kind, row)
    with st.container(border=True):
        legs = leg_line(row, "") if kind == "ev" else leg_line(row, "leg1_") + leg_line(row, "leg2_")
        st.markdown(
            row_html(headline(kind, row), f"lines {fmt.age(oldest_age(kind, row))} old")
            + matchup_html(row)
            + f'<div class="jb-muted">{esc(row["start_et"])} ET</div>'
            + say_html(kind, row)
            + legs
            + ("" if cfg()["beginner"] else
               f'<div class="jb-muted" style="margin-top:8px">{esc(summary_line(kind, row))}</div>'),
            unsafe_allow_html=True,
        )
        st.button(
            "Place this bet", key=f"{where}_{key}", type="primary", width="stretch",
            on_click=go, args=("detail",), kwargs={"kind": kind, "opp_key": key, "back": where},
        )


@st.cache_data(show_spinner=False)
def _logo_b64() -> str:
    return base64.b64encode((ASSETS / "icon-192.png").read_bytes()).decode("ascii")


def header(show_gear: bool = True) -> None:
    title, learn, gear = st.container(key="hdr").columns([4.4, 1.1, 1.1], vertical_alignment="center")
    title.markdown(
        f'<div class="jb-title"><img src="data:image/png;base64,{_logo_b64()}" width="38" height="38" '
        f'alt="" style="vertical-align:middle;margin-right:10px;border-radius:9px">Juice Box</div>',
        unsafe_allow_html=True, width="stretch",
    )
    if show_gear:
        learn.button("", icon=":material/help:", key="learn", help="Learn the basics",
                     on_click=go, args=("learn",), width="stretch")
        gear.button("", icon=":material/settings:", key="gear", help="Settings",
                    on_click=go, args=("settings",), width="stretch")


def back(label: str, screen: str, **extra: Any) -> None:
    st.button(f"← {label}", key=f"back_{screen}", on_click=go, args=(screen,), kwargs=extra)


# ---------- screens ----------

def screen_home() -> None:
    c = cfg()
    header()
    sport_picker()
    c["bankroll"] = st.number_input(
        "How much to bet in total ($)" if c["beginner"] else "Bankroll $",
        min_value=1.0, value=float(c["bankroll"]), step=50.0, key="w_bankroll",
        help="The total you want to put on one opportunity, split across its bets.",
    )
    if "sports_error" in st.session_state:
        st.caption(f"Couldn't load the sport list: {st.session_state['sports_error']}")

    if "scan_error" in st.session_state:
        st.error(st.session_state["scan_error"])

    resp: api.OddsResponse | None = st.session_state.get("scan")
    results = current_results()
    if resp is None or results is None:
        with st.container(border=True):
            st.markdown(
                '<div class="jb-strong">Ready when you are</div>'
                '<div class="jb-muted">Scan to compare prices across sportsbooks and find bets '
                "where the numbers are in your favor. You'll see the credit cost before every scan."
                + (" New to betting? Tap the ? at the top first." if c["beginner"] else "")
                + "</div>",
                unsafe_allow_html=True,
            )
            st.button(scan_label(), key="scan_first", type="primary", width="stretch", on_click=do_scan)
        hedge_row()
        if c["use_fixtures"]:
            st.caption("Using fixture data. Scans are free and don't touch the live API.")
        return

    st.markdown(f'<div class="jb-muted">{esc(status_line(resp))}</div>', unsafe_allow_html=True)
    tiles = st.columns(3)
    for col, kind in zip(tiles, service.KINDS):
        col.button(
            f"**{results.count(kind)}** {KIND_LABEL[kind]}", key=f"tile_{kind}", width="stretch",
            on_click=go, args=("list",), kwargs={"kind": kind},
        )
        if c["beginner"]:
            col.markdown(f'<div class="jb-tilecap">{esc(explain.TILE_CAPTION[kind])}</div>',
                         unsafe_allow_html=True)

    best = service.best_opportunity(results)
    if best is not None:
        st.markdown('<div class="jb-muted">Best right now</div>', unsafe_allow_html=True)
        card(best[0], best[1], "home")
    elif results.n_raw and not results.n_fresh:
        st.info(f"Every line is now older than {int(c['max_age_s'])}s. Scan again for fresh prices.")
    else:
        st.info("Nothing worth betting at your sportsbooks right now. That's normal; good prices come "
                "and go. Scan again in a bit, or add more books under My sportsbooks in settings.")

    hedge_row()
    st.button(scan_label(again=True), key="scan_again", width="stretch", on_click=do_scan)
    st.caption(REALITY["arb"])


def on_sport_change(key: str) -> None:
    """A different sport makes the old scan meaningless; clear it."""
    c = cfg()
    if key != c["sport"]:
        c["sport"] = key
        for name in ("scan", "scan_error", "scan_sport"):
            st.session_state.pop(name, None)


def sport_picker() -> None:
    """Scrolling row of league chips; falls back to a dropdown if it can't load."""
    c = cfg()
    keys = list(teams.LEAGUE_KEYS)
    note = "Out of season"
    if c["use_fixtures"]:
        active, note = {"basketball_nba"}, "Live only"   # the sample data is NBA
    else:
        active = {s["key"] for s in sports()} & set(keys)
        if "sports_error" in st.session_state:
            active = set(keys)   # can't tell what's in season; let the scan decide
    if c["sport"] not in active:
        c["sport"] = next((k for k in keys if k in active), keys[0])
    if _sport_picker is None:
        chosen = st.selectbox("Sport", keys, index=keys.index(c["sport"]), key="w_sport",
                              format_func=lambda k: teams.league(k).title)
    else:
        items = [
            {"key": k, "label": teams.league(k).short, "active": k in active, "note": note,
             "logo": teams.league(k).logo_url if c["show_logos"] else None}
            for k in keys
        ]
        chosen = _sport_picker(items=items, selected=c["sport"], default=c["sport"], key="sport_picker")
    if chosen in active and chosen != c["sport"]:
        on_sport_change(chosen)
        st.rerun()


def status_line(resp: api.OddsResponse) -> str:
    if resp.source == "fixture":
        return "Fixture data · no credits used"
    ago = (datetime.now(timezone.utc) - resp.fetched_at).total_seconds()
    q = resp.quota
    parts = [f"Scanned {fmt.age(ago)} ago"]
    if q.remaining is not None:
        parts.append(f"{q.remaining} credits left")
    parts.append("from cache, 0 credits" if resp.source == "cache" else f"used {resp.credits_spent}")
    return " · ".join(parts)


def hedge_row() -> None:
    st.button("Hedge a bet you hold", icon=":material/shield:", key="go_hedge",
              width="stretch", on_click=go, args=("hedge",))


def screen_list() -> None:
    kind = st.session_state.get("kind", "arb")
    back("Home", "home")
    results = current_results()
    if results is None:
        st.info("Run a scan from the home screen first.")
        return
    table = results.table(kind)
    st.markdown(f'<div class="jb-title">{esc(KIND_LABEL[kind])} · {len(table)}</div>', unsafe_allow_html=True)
    if table.empty:
        st.info(f"No {KIND_LABEL[kind].lower()} clear your thresholds right now.")
        st.caption(REALITY[kind])
        return
    top = table.head(int(cfg()["top_n"]))
    if st.toggle("Table view", key=f"table_{kind}", help="Easier on a desktop screen"):
        st.dataframe(table_view(kind, top), hide_index=True, width="stretch")
    else:
        for _, row in top.iterrows():
            card(kind, row, "list")
    if len(table) > len(top):
        st.caption(f"Showing the top {len(top)} of {len(table)}.")
    st.download_button(
        "Download CSV", table.to_csv(index=False), file_name=f"juice_box_{kind}.csv",
        mime="text/csv", key=f"csv_{kind}", width="stretch",
    )
    st.caption(REALITY[kind])


def table_view(kind: str, table: pd.DataFrame) -> pd.DataFrame:
    """Compact, readable columns for the desktop table."""
    def leg(prefix: str) -> pd.Series:
        return table.apply(
            lambda r: f"{fmt.leg_label(r[f'{prefix}side'], r[f'{prefix}point'], r['market'])} "
                      f"{fmt.american(r[f'{prefix}price_am'])} · {r[f'{prefix}book']}", axis=1)
    out = pd.DataFrame({"Game": table["matchup"], "Start (ET)": table["start_et"]})
    if kind == "ev":
        out["Bet"] = leg("")
        out["EV %"] = table["ev_pct"].round(2)
        out["Fair"] = table["fair_odds_am"].map(fmt.american)
        out["Books"] = table["n_books"]
        out["Age s"] = table["age_s"].round(0)
        return out
    out["Leg 1"], out["Leg 2"] = leg("leg1_"), leg("leg2_")
    if kind == "arb":
        out["Profit %"] = table["profit_pct"].round(2)
        out["Net $"] = table["net"].round(2)
    else:
        out["Type"] = table["both_win"].map({True: "Middle", False: "Push only"})
        out["Window"] = table["window"]
        out["Hold %"] = table["hold_pct"].round(2)
        out["Miss $"] = table["miss_net"].round(2)
        out["Best $"] = table["best_net"].round(2)
    out["Age s"] = table["max_age_s"].round(0)
    return out


def bet_state() -> str:
    return os.environ.get("BET_STATE", "nc").strip().lower()


def copy_button(amount: float) -> None:
    """Copies the stake (a bare number, e.g. 48 or 51.63) to the clipboard."""
    text = f"{amount:.2f}".removesuffix(".00")
    label = fmt.money(amount)
    st.iframe(
        f"""<body style="margin:0;background:transparent">
<button id="b" style="width:100%;height:40px;border-radius:8px;border:1px solid #2C2C31;
 background:#1C1C1F;color:#F4F4F5;font:600 15px 'Source Sans Pro',sans-serif;cursor:pointer">Copy {label}</button>
<script>
const b = document.getElementById('b');
b.onclick = async () => {{
  const t = {json.dumps(text)}; let ok = false;
  try {{ await navigator.clipboard.writeText(t); ok = true; }} catch (e) {{
    const a = document.createElement('textarea'); a.value = t; document.body.appendChild(a); a.select();
    try {{ ok = document.execCommand('copy'); }} catch (e2) {{}} a.remove();
  }}
  b.textContent = ok ? 'Copied {label}' : 'Copy failed. Stake is ' + t;
}};
</script></body>""",
        height=44,
    )


def do_recheck(kind: str, key: str, row: pd.Series) -> None:
    """Fresh prices for this one event and market. 1 credit per region live."""
    c = cfg()
    st.session_state.pop(f"rc_err_{key}", None)
    try:
        if c["use_fixtures"]:
            resp = api.fixture_response()
        else:
            api_key = _api_key()
            if not api_key:
                raise api.OddsApiError("No API key found. Add ODDS_API_KEY to your .env file.")
            resp = _client(api_key).fetch_odds(
                c["sport"], c["regions"], [row["market"]], event_ids=[row["event_id"]], use_cache=False
            )
    except api.OddsApiError as exc:
        st.session_state[f"rc_err_{key}"] = exc.message
        return
    result = service.recheck(kind, row, resp.events, now_for(resp), settings())
    st.session_state[f"rc_{key}"] = (result, datetime.now(timezone.utc), resp.credits_spent)


def recheck_banner(kind: str, key: str, row: pd.Series) -> service.Recheck | None:
    """Shows the re-check state; returns the result while it's fresh and still good."""
    cost = 0 if cfg()["use_fixtures"] else service.recheck_cost(cfg()["regions"])
    cost_txt = f"{cost} credit{'' if cost == 1 else 's'}"
    if err := st.session_state.get(f"rc_err_{key}"):
        st.error(err)
    saved = st.session_state.get(f"rc_{key}")
    age_s = (datetime.now(timezone.utc) - saved[1]).total_seconds() if saved else None
    if saved is None or age_s > RECHECK_MAX_AGE_S:
        if saved is not None:
            st.caption(f"Last re-check was {fmt.age(age_s)} ago. Check again before you bet.")
        st.info("Re-check both prices before you bet. Lines move fast.")
        st.button(f"Re-check prices · {cost_txt}", key=f"rc_btn_{key}", type="primary",
                  width="stretch", on_click=do_recheck, args=(kind, key, row))
        return None
    result: service.Recheck = saved[0]
    metric_name = {"arb": "profit", "middle": "hold", "ev": "EV"}[kind]
    when = f"re-checked {fmt.age(age_s)} ago"
    if result.status == "gone":
        st.error(f"Line gone: a book pulled or changed this line ({when}). Don't bet it.")
    elif not result.still_good:
        gone = "ARB GONE" if kind == "arb" else "No longer worth it"
        st.error(f"{gone}: {metric_name} is now {fmt.pct(result.metric)} ({when}).")
    elif result.status == "moved":
        st.warning(f"Price moved, still good: {metric_name} now {fmt.pct(result.metric)} ({when}). Stakes updated.")
    else:
        st.success(f"Prices {when}: unchanged, still good.")
    st.button(f"Re-check again · {cost_txt}", key=f"rc_again_{key}", width="stretch",
              on_click=do_recheck, args=(kind, key, row))
    return result if result.status != "gone" and result.still_good else None


def screen_detail() -> None:
    kind = st.session_state.get("kind", "arb")
    where = st.session_state.get("back", "list")
    if where == "home":
        back("Home", "home")
    else:
        back(KIND_LABEL[kind], "list", kind=kind)
    resp: api.OddsResponse | None = st.session_state.get("scan")
    results = current_results()
    key = st.session_state.get("opp_key", "")
    row = service.find_by_key(results, kind, key) if results else None
    if row is None or resp is None:
        st.warning("This one is gone. The lines moved or went stale. Scan again for fresh prices.")
        return
    st.markdown(
        row_html(headline(kind, row), f"lines {fmt.age(oldest_age(kind, row))} old")
        + f'<div style="font-size:1.2rem">{matchup_html(row, 30)}</div>'
        + f'<div class="jb-muted">{esc(row["start_et"])} ET</div>',
        unsafe_allow_html=True,
    )
    s = settings()
    checked = recheck_banner(kind, key, row)
    prefixes = service.leg_prefixes(kind)
    prices = list(checked.prices) if checked else [int(row[f"{p}price_am"]) for p in prefixes]
    fair = float(row["fair_prob"]) if kind == "ev" else None
    stakes = dict(zip(prefixes, service.leg_stakes(kind, prices, s, fair)))
    price_of = dict(zip(prefixes, prices))
    offers = filter_offers(parse_odds(resp.events, now_for(resp)), s.max_age_s, s.include_live)
    order = service.leg_order(kind, row, offers)

    placed: list[service.PlacedLeg] = []
    first_got: int | None = None
    for i, prefix in enumerate(order):
        stake = stakes[prefix]
        price = price_of[prefix]
        if i == 1 and first_got is not None and first_got != price_of[order[0]]:
            stake = om.round_to_step(service.rebalanced_stake(stakes[order[0]], first_got, price), s.stake_step)
        title = "Bet" if kind == "ev" else f"Leg {i + 1}"
        is_placed = st.session_state.get(f"placed_{key}_{prefix}", False)
        nudge = i == 1 and placed and not is_placed
        bet = fmt.leg_label(row[f"{prefix}side"], row[f"{prefix}point"], row["market"])
        link = links.pick_link(row, prefix, bet_state())
        with st.container(border=True):
            st.markdown(
                f'<div class="jb-row"><span class="jb-strong">{esc(title)}</span>'
                f'<span>{pill("Place now") + " " if nudge else ""}{book_html(row, prefix)}</span></div>'
                + f'<div style="margin-top:6px">{side_html(row, prefix, 24)}{esc(bet_text(row, prefix))} '
                  f"<span class='jb-strong'>{fmt.american(price)}</span></div>"
                + price_html(price)
                + f'<div class="jb-big">{"Bet" if cfg()["beginner"] else "Stake"} {fmt.money(stake)}</div>'
                + f'<div class="jb-muted">Link opens: {esc(link.level.lower() if link else "nothing, no link")}</div>',
                unsafe_allow_html=True,
            )
            if i == 0 and kind != "ev":
                st.caption("Place this leg first: its price is furthest above the other books, so it's the likeliest to move.")
            if checked is None:
                st.caption("Re-check prices to unlock Open bet.")
            elif link is None:
                st.caption("This book sent no link. Open its app and find the game.")
            else:
                st.link_button("Open bet ↗", link.url, type="primary", width="stretch")
            copy_button(stake)
            got = price
            if i == 0:
                got = int(st.number_input(
                    "Price you got", value=price, step=1, key=f"got_{key}_{prefix}",
                    help="If the book gave you a different price, enter it to rebalance the next leg.",
                ))
                if -100 < got < 100:
                    st.caption("Enter American odds of -100 or lower, or +100 or higher.")
                    got = price
                first_got = got
            st.checkbox("Placed", key=f"placed_{key}_{prefix}")
            if is_placed:
                placed.append(service.PlacedLeg(row[f"{prefix}book"], bet, got, stake))

    all_placed = len(placed) == len(prefixes)
    shown = [service.PlacedLeg(row[f"{p}book"], "", price_of[p], stakes[p]) for p in prefixes]
    legs_for_net = placed if all_placed else shown
    worst, best = service.placed_nets(legs_for_net)
    if kind == "arb":
        staked = fmt.money(sum(leg.stake for leg in legs_for_net))
        msg = f"Net {fmt.money(worst, signed=True)} to {fmt.money(best, signed=True)} on {staked} staked"
        if worst >= 0:
            st.success(f"{msg}{' as placed' if all_placed else ''}.")
        elif all_placed:
            st.warning(f"{msg} as placed. The prices you got can lose money on one side.")
        else:
            st.warning(f"{msg}. Rounding the stakes makes this a possible loss.")
    elif kind == "middle":
        miss = f"{fmt.money(row['miss_net'], signed=True)} (hold {fmt.pct(row['hold_pct'])})"
        if row["both_win"]:
            st.info(
                f"Window {row['window']:g} points. If it lands in the middle both bets win: "
                f"{fmt.money(row['hit_net'], signed=True)}. Otherwise: {miss}."
            )
            if row["push_risk"]:
                st.caption(
                    f"One line is a whole number. Landing exactly on it refunds that bet "
                    f"and the other wins: {fmt.money(row['push_net'], signed=True)}."
                )
        else:
            st.warning(
                f"Push middle: no final score wins both bets. The best case is landing exactly "
                f"on the whole-number line, which refunds one bet while the other wins: "
                f"{fmt.money(row['push_net'], signed=True)}. Otherwise: {miss}."
            )
        st.caption("Amounts above are from the scan at the original prices.")
    else:
        ref = "Pinnacle's no-vig price" if row["reference"] == "pinnacle" else f"the median no-vig price of {int(row['n_books'])} other books"
        st.info(
            f"EV {fmt.pct(row['ev_pct'])}. Fair price is {fmt.american(row['fair_odds_am'])} "
            f"({row['fair_prob'] * 100:.1f}% to win), from {ref}."
        )
        st.caption(f"Stake shown is quarter-Kelly on a {fmt.money(s.bankroll)} bankroll.")

    if len(placed) == len(prefixes):
        logged: set[str] = st.session_state.setdefault("logged_bets", set())
        if key not in logged:
            try:
                service.append_bet_log(BET_LOG, datetime.now(timezone.utc), kind, row["matchup"],
                                       row["market"], placed, fair_prob=fair)
                logged.add(key)
            except OSError:
                st.error("Couldn't write to .cache/bets.csv. Your bets are placed; note them down.")
        if key in logged:
            st.success("All placed. Logged to .cache/bets.csv.")
    st.caption(REALITY[kind])


def screen_hedge() -> None:
    back("Home", "home")
    st.markdown('<div class="jb-title">Hedge a bet</div>', unsafe_allow_html=True)
    st.markdown('<div class="jb-muted">Your original bet</div>', unsafe_allow_html=True)
    left, right = st.columns(2)
    stake = left.number_input("Stake $", min_value=0.0, value=100.0, step=10.0, key="h_stake")
    original = right.number_input("Odds", value=250, step=5, key="h_orig", help="American odds, like +250 or -110")
    st.markdown('<div class="jb-muted">Price on the other side</div>', unsafe_allow_html=True)
    hedge_odds = st.number_input("Hedge odds", value=-140, step=5, key="h_hedge")
    share = st.slider("Hedge amount", 0, 100, 100, step=5, format="%d%%", key="h_share")
    try:
        result = om.hedge(float(stake), int(original), int(hedge_odds), share / 100)
    except ValueError:
        st.warning("Enter a stake above $0 and American odds of -100 or lower, or +100 or higher.")
        return
    locked = share == 100
    with st.container(border=True):
        st.markdown(
            row_html("Bet on the hedge", f'<span class="jb-big" style="color:#F4F4F5">{fmt.money(result.hedge_stake)}</span>')
            + row_html("If your original wins", pill(fmt.money(result.net_if_original_wins, signed=True), result.net_if_original_wins >= 0))
            + '<div style="height:6px"></div>'
            + row_html("If the hedge wins", pill(fmt.money(result.net_if_hedge_wins, signed=True), result.net_if_hedge_wins >= 0))
            + '<div style="height:6px"></div>'
            + row_html("Locked return" if locked else "Worst-case return", fmt.pct(result.roi_pct)),
            unsafe_allow_html=True,
        )
    if not locked:
        st.caption(f"A full hedge would be {fmt.money(result.full_hedge)}.")
    st.caption("Check the hedge price in the sportsbook before you bet. Prices move.")


def screen_settings() -> None:
    c = cfg()
    back("Home", "home")
    st.markdown('<div class="jb-title">Settings</div>', unsafe_allow_html=True)

    c["beginner"] = st.toggle(
        "Beginner mode", value=c["beginner"], key="w_beginner",
        help="Plain-English explanations on every bet, and hides push-only middles.",
    )
    c["show_logos"] = st.toggle("Show team and league logos", value=c["show_logos"], key="w_logos",
                                help="Turn off if logos stop loading; colored badges are used instead.")
    resp_now: api.OddsResponse | None = st.session_state.get("scan")
    seen = {b["key"] for e in (resp_now.events if resp_now else []) for b in e.get("bookmakers", [])}
    book_options = sorted(set(books.BOOKS) | seen | set(c["my_books"]), key=lambda k: books.label(k).lower())
    c["my_books"] = st.multiselect(
        "My sportsbooks", book_options, default=c["my_books"], key="w_books_mine",
        format_func=books.label,
        help="Only bets at these books are shown. Tick the ones you have accounts with.",
    )
    if not c["my_books"]:
        st.warning("No sportsbooks ticked, so no bets will show.")
    st.caption("The starting list is books believed to be licensed in North Carolina. Check that "
               "a book is legal where you are before betting there.")

    c["use_fixtures"] = st.toggle(
        "Use fixture data", value=c["use_fixtures"], key="w_fix",
        help="Sample NBA data. Free: never calls the live API.",
    )
    if not c["use_fixtures"] and _api_key() is None:
        st.error("No API key found. Add ODDS_API_KEY to your .env file to scan live odds.")
    c["regions"] = st.multiselect("Regions", REGIONS, default=c["regions"], key="w_regions",
                                  help="eu adds Pinnacle, a sharp reference book")
    c["markets"] = st.multiselect("Markets", MARKETS, default=c["markets"], key="w_markets")
    if c["use_fixtures"]:
        st.caption("Each scan uses 0 credits (fixture data).")
    else:
        st.caption(
            f"Each scan will use {scan_cost()} credits "
            f"({len(c['markets'])} markets × {len(c['regions'])} regions)."
        )

    st.markdown('<div class="jb-muted">Stakes</div>', unsafe_allow_html=True)
    steps = list(STAKE_STEPS)
    c["stake_step"] = st.selectbox("Round stakes", steps, index=steps.index(c["stake_step"]),
                                   format_func=STAKE_STEPS.get, key="w_step")
    c["top_n"] = st.number_input("Show top N per list", 1, 50, int(c["top_n"]), key="w_top")

    st.markdown('<div class="jb-muted">Thresholds</div>', unsafe_allow_html=True)
    a, b = st.columns(2)
    c["min_arb_pct"] = a.number_input("Min arb %", 0.0, 20.0, float(c["min_arb_pct"]), 0.1, key="w_arb")
    c["min_ev_pct"] = b.number_input("Min EV %", 0.0, 50.0, float(c["min_ev_pct"]), 0.5, key="w_ev")
    c["min_hold_pct"] = a.number_input("Min middle hold %", -20.0, 5.0, float(c["min_hold_pct"]), 0.5, key="w_hold")
    c["min_window"] = b.number_input("Min middle window", 0.5, 20.0, float(c["min_window"]), 0.5, key="w_win")
    c["min_books"] = a.number_input("Min books for EV", 1, 15, int(c["min_books"]), key="w_books")
    c["max_age_s"] = b.number_input("Max line age (s)", 10, 3600, int(c["max_age_s"]), 10, key="w_age")
    c["include_live"] = st.toggle("Include live games", value=c["include_live"], key="w_live")
    c["use_pinnacle"] = st.toggle("Use Pinnacle as truth for +EV", value=c["use_pinnacle"], key="w_pin",
                                  help="Needs the eu region. Falls back to consensus when Pinnacle is missing.")

    resp: api.OddsResponse | None = st.session_state.get("scan")
    if resp is not None and resp.source != "fixture":
        q = resp.quota
        st.caption(f"API usage: {q.remaining} remaining · {q.used} used · last call {q.last}")
    st.caption(f"Bet links use state: {bet_state().upper() or 'not set'} (BET_STATE in .env).")
    if app_password():
        st.caption("Password protection is on.")
    elif not c["use_fixtures"]:
        st.warning("No password is set. Anyone who can reach this app can spend your credits. "
                   "Add APP_PASSWORD to .env.")
    with st.expander("What bet links can and can't do"):
        st.write(
            "A link can open the sportsbook with your selection on the slip. It can't fill in the "
            "stake or place the bet, and you need to be logged in and location-verified in the book's app."
        )


def screen_learn() -> None:
    back("Home", "home")
    st.markdown('<div class="jb-title">Learn the basics</div>', unsafe_allow_html=True)
    for title, body in explain.LESSONS:
        with st.container(border=True):
            st.markdown(
                f'<div class="jb-strong">{esc(title)}</div><div class="jb-muted">{esc(body)}</div>',
                unsafe_allow_html=True,
            )
    with st.expander("Glossary"):
        st.markdown(
            "".join(
                f'<div style="margin-bottom:8px"><span class="jb-strong">{esc(term)}</span>'
                f'<div class="jb-muted">{esc(meaning)}</div></div>'
                for term, meaning in explain.GLOSSARY
            ),
            unsafe_allow_html=True,
        )
    st.caption("If betting stops being fun, the National Problem Gambling Helpline is 1-800-522-4700.")


def app_password() -> str:
    """APP_PASSWORD from .env / environment, else Streamlit secrets. '' = no gate."""
    value = os.environ.get("APP_PASSWORD", "").strip()
    if value:
        return value
    try:
        return str(st.secrets["APP_PASSWORD"]).strip()
    except Exception:
        return ""


def password_gate() -> None:
    """Stops the script until the right password is entered, when one is set."""
    expected = app_password()
    if not expected or st.session_state.get("authed"):
        return
    header(show_gear=False)
    with st.form("login"):
        entered = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Unlock", type="primary", width="stretch")
    if submitted:
        if service.check_password(entered, expected):
            st.session_state["authed"] = True
            st.rerun()
        st.error("That password didn't match. Try again.")
    st.stop()


SCREENS = {
    "home": screen_home,
    "list": screen_list,
    "detail": screen_detail,
    "hedge": screen_hedge,
    "settings": screen_settings,
    "learn": screen_learn,
}
password_gate()
SCREENS.get(st.session_state.get("screen", "home"), screen_home)()
