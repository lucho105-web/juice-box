"""Juice Box - Streamlit UI only. No math in here (see edge/).

Layout and palette follow docs/SPEC.md section 4e: a home dashboard with
drill-in screens, phone first, Graphite theme.
"""
from __future__ import annotations

import html
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

from edge import api, fmt, odds_math as om, service

ROOT = Path(__file__).parent
ASSETS = ROOT / "assets"
SCAN_LOG = ROOT / ".cache" / "scan_log.csv"

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
}

CSS = """
<style>
.block-container {padding-top: 3.6rem; padding-bottom: 3rem; max-width: 480px;}
.jb-title {font-size: 1.35rem; font-weight: 600; line-height: 2.5rem; text-align: left; width: 100%;}
.jb-row {display: flex; justify-content: space-between; align-items: center; gap: 8px;}
.jb-pill {background: #B6F36A; color: #173404; border-radius: 6px; padding: 2px 8px;
          font-size: .82rem; font-weight: 600; white-space: nowrap;}
.jb-pill.flat {background: #2C2C31; color: #F4F4F5;}
.jb-muted {color: #A0A0A8; font-size: .85rem;}
.jb-strong {font-weight: 600;}
.jb-leg {background: #111113; border-radius: 8px; padding: 6px 10px; margin-top: 6px;}
.jb-big {font-size: 1.5rem; font-weight: 600;}
button[data-testid="stBaseButton-primary"] {color: #2A1400; font-weight: 600;}
div[class*="st-key-tile_"] button {height: 4.6rem;}
div[class*="st-key-tile_"] button p {font-size: 1rem; line-height: 1.3;}
div[class*="st-key-tile_"] button strong {font-size: 1.5rem; display: block;}
@media (max-width: 640px) {
  div[data-testid="stHorizontalBlock"] {flex-wrap: nowrap !important; gap: .5rem;}
  div[data-testid="stHorizontalBlock"] > div[data-testid="stColumn"] {min-width: 0 !important; flex: 1 1 0 !important;}
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
    title = next((s["title"] for s in sports() if s["key"] == cfg()["sport"]), "")
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


def leg_line(row: pd.Series, prefix: str) -> str:
    label = fmt.leg_label(row[f"{prefix}side"], row[f"{prefix}point"], row["market"])
    left = f"{esc(label)} <span class='jb-strong'>{fmt.american(row[f'{prefix}price_am'])}</span>"
    return f'<div class="jb-leg">{row_html(left, esc(row[f"{prefix}book"]))}</div>'


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
            + f'<div class="jb-strong" style="margin-top:6px">{esc(row["matchup"])}</div>'
            + f'<div class="jb-muted">{esc(row["start_et"])} ET</div>'
            + legs
            + f'<div class="jb-muted" style="margin-top:8px">{esc(summary_line(kind, row))}</div>',
            unsafe_allow_html=True,
        )
        st.button(
            "Place this bet", key=f"{where}_{key}", type="primary", width="stretch",
            on_click=go, args=("detail",), kwargs={"kind": kind, "opp_key": key, "back": where},
        )


def header(show_gear: bool = True) -> None:
    logo, title, gear = st.columns([1, 5, 1], vertical_alignment="center")
    logo.image(str(ASSETS / "icon-rounded-512.png"), width=40)
    title.markdown('<div class="jb-title">Juice Box</div>', unsafe_allow_html=True, width="stretch")
    if show_gear:
        gear.button("", icon=":material/settings:", key="gear", help="Settings",
                    on_click=go, args=("settings",), width="stretch")


def back(label: str, screen: str, **extra: Any) -> None:
    st.button(f"← {label}", key=f"back_{screen}", on_click=go, args=(screen,), kwargs=extra)


# ---------- screens ----------

def screen_home() -> None:
    c = cfg()
    header()
    options = sports()
    keys = [s["key"] for s in options]
    if c["sport"] not in keys:
        c["sport"] = keys[0]
    left, right = st.columns([3, 2])
    c["sport"] = left.selectbox(
        "Sport", keys, index=keys.index(c["sport"]), key="w_sport",
        format_func=lambda k: next(s["title"] for s in options if s["key"] == k),
    )
    c["bankroll"] = right.number_input(
        "Bankroll $", min_value=1.0, value=float(c["bankroll"]), step=50.0, key="w_bankroll"
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
                '<div class="jb-muted">Scan the board to find arbs, middles and +EV prices. '
                "You'll see the credit cost before every scan.</div>",
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

    best = service.best_opportunity(results)
    if best is not None:
        st.markdown('<div class="jb-muted">Best right now</div>', unsafe_allow_html=True)
        card(best[0], best[1], "home")
    elif results.n_raw and not results.n_fresh:
        st.info(f"Every line is now older than {int(c['max_age_s'])}s. Scan again for fresh prices.")
    else:
        st.info("Nothing clears your thresholds right now. Scan again in a bit, or loosen them in settings.")

    hedge_row()
    st.button(scan_label(again=True), key="scan_again", width="stretch", on_click=do_scan)
    st.caption(REALITY["arb"])


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


def leg_card(title: str, row: pd.Series, prefix: str, stake: float | None) -> None:
    label = fmt.leg_label(row[f"{prefix}side"], row[f"{prefix}point"], row["market"])
    with st.container(border=True):
        st.markdown(
            row_html(f'<span class="jb-strong">{esc(title)} · {esc(row[f"{prefix}book"])}</span>',
                     f"{fmt.age(row[f'{prefix}age_s'])} old")
            + f"<div>{esc(label)} <span class='jb-strong'>{fmt.american(row[f'{prefix}price_am'])}</span></div>"
            + (f'<div class="jb-big">Stake {fmt.money(stake)}</div>' if stake is not None else ""),
            unsafe_allow_html=True,
        )


def screen_detail() -> None:
    kind = st.session_state.get("kind", "arb")
    where = st.session_state.get("back", "list")
    if where == "home":
        back("Home", "home")
    else:
        back(KIND_LABEL[kind], "list", kind=kind)
    results = current_results()
    row = service.find_by_key(results, kind, st.session_state.get("opp_key", "")) if results else None
    if row is None:
        st.warning("This one is gone. The lines moved or went stale. Scan again for fresh prices.")
        return
    st.markdown(
        row_html(headline(kind, row), f"lines {fmt.age(oldest_age(kind, row))} old")
        + f'<div class="jb-title">{esc(row["matchup"])}</div>'
        + f'<div class="jb-muted">{esc(row["start_et"])} ET</div>',
        unsafe_allow_html=True,
    )
    s = settings()
    if kind == "arb":
        leg_card("Leg 1", row, "leg1_", row["r_stake1"])
        leg_card("Leg 2", row, "leg2_", row["r_stake2"])
        if row["goes_negative"]:
            st.warning(
                f"Rounding to {STAKE_STEPS[s.stake_step].lower()} turns this into a possible loss: "
                f"net {fmt.money(row['worst_net'], signed=True)} to {fmt.money(row['best_net'], signed=True)}."
            )
        else:
            st.success(
                f"Net {fmt.money(row['worst_net'], signed=True)} to {fmt.money(row['best_net'], signed=True)} "
                f"on {fmt.money(row['r_stake1'] + row['r_stake2'])} staked."
            )
        st.caption(f"Exact split: {fmt.money(row['stake1'])} / {fmt.money(row['stake2'])} pays {fmt.money(row['payout'])} either way ({fmt.pct(row['profit_pct'])}).")
    elif kind == "middle":
        leg_card("Leg 1", row, "leg1_", row["stake1"])
        leg_card("Leg 2", row, "leg2_", row["stake2"])
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
    else:
        leg_card("Bet", row, "", row["kelly_stake"] if pd.notna(row["kelly_stake"]) else None)
        ref = "Pinnacle's no-vig price" if row["reference"] == "pinnacle" else f"the median no-vig price of {int(row['n_books'])} other books"
        st.info(
            f"EV {fmt.pct(row['ev_pct'])}. Fair price is {fmt.american(row['fair_odds_am'])} "
            f"({row['fair_prob'] * 100:.1f}% to win), from {ref}."
        )
        st.caption(f"Stake shown is quarter-Kelly on a {fmt.money(s.bankroll)} bankroll.")
    st.caption(REALITY[kind])
    st.caption("Open-bet links, copy-stake buttons and the price re-check arrive with the bet-link phase.")


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
    with st.expander("What bet links can and can't do"):
        st.write(
            "A link can open the sportsbook with your selection on the slip. It can't fill in the "
            "stake or place the bet, and you need to be logged in and location-verified in the book's app."
        )


SCREENS = {
    "home": screen_home,
    "list": screen_list,
    "detail": screen_detail,
    "hedge": screen_hedge,
    "settings": screen_settings,
}
SCREENS.get(st.session_state.get("screen", "home"), screen_home)()
