"""Unit tests for edge/odds_math.py.

Expected values are hand-checked and come from docs/SPEC.md section 2.
"""
import pytest

from edge import odds_math as om


# ---------- conversions ----------

@pytest.mark.parametrize(
    "american, decimal",
    [
        (110, 2.10),
        (-105, 1.952381),
        (100, 2.0),
        (-100, 2.0),
        (250, 3.5),
        (-140, 1.714286),
        (-110, 1.909091),
    ],
)
def test_am_to_dec(american: int, decimal: float) -> None:
    assert om.am_to_dec(american) == pytest.approx(decimal, abs=1e-6)


@pytest.mark.parametrize("bad", [0, 50, 99, -99, -1, 1])
def test_am_to_dec_rejects_invalid_american_odds(bad: int) -> None:
    with pytest.raises(ValueError):
        om.am_to_dec(bad)


@pytest.mark.parametrize(
    "decimal, american",
    [
        (2.10, 110),
        (1.952381, -105),
        (2.0, 100),
        (3.5, 250),
        (1.714286, -140),
        (1.909091, -110),
    ],
)
def test_dec_to_am(decimal: float, american: int) -> None:
    assert om.dec_to_am(decimal) == american


@pytest.mark.parametrize("bad", [1.0, 0.5, 0.0, -2.0])
def test_dec_to_am_rejects_invalid_decimal_odds(bad: float) -> None:
    with pytest.raises(ValueError):
        om.dec_to_am(bad)


def test_implied() -> None:
    assert om.implied(2.0) == pytest.approx(0.5)
    assert om.implied(2.10) == pytest.approx(0.476190, abs=1e-6)


# ---------- two-way arbitrage ----------

def test_arb_spec_example() -> None:
    """SPEC: +110 / -105, B=$100 -> S=0.98839, 1.175%, $48.18 / $51.82, $101.18."""
    arb = om.arb_two_way(om.am_to_dec(110), om.am_to_dec(-105), 100.0)
    assert arb.is_arb is True
    assert arb.s == pytest.approx(0.98839, abs=1e-5)
    assert arb.profit_pct == pytest.approx(1.175, abs=1e-3)
    assert round(arb.stake1, 2) == 48.18
    assert round(arb.stake2, 2) == 51.82
    assert round(arb.payout, 2) == 101.18
    assert arb.stake1 + arb.stake2 == pytest.approx(100.0)


def test_arb_no_arb_at_standard_juice() -> None:
    arb = om.arb_two_way(om.am_to_dec(-110), om.am_to_dec(-110), 100.0)
    assert arb.is_arb is False
    assert arb.profit_pct < 0


def test_arb_rejects_bad_input() -> None:
    with pytest.raises(ValueError):
        om.arb_two_way(2.1, 1.95, 0.0)
    with pytest.raises(ValueError):
        om.arb_two_way(1.0, 1.95, 100.0)


# ---------- rounded stakes ----------

def _spec_arb() -> tuple[float, float, om.ArbResult]:
    d1, d2 = om.am_to_dec(110), om.am_to_dec(-105)
    return d1, d2, om.arb_two_way(d1, d2, 100.0)


def test_round_stakes_to_cents() -> None:
    d1, d2, arb = _spec_arb()
    r = om.round_stakes(arb.stake1, arb.stake2, d1, d2, 0.01)
    assert (r.stake1, r.stake2) == (48.18, 51.82)
    assert r.goes_negative is False


def test_round_stakes_to_one_dollar() -> None:
    """$48 / $52: 48*2.10-100 = +0.80 ; 52*1.952381-100 = +1.52."""
    d1, d2, arb = _spec_arb()
    r = om.round_stakes(arb.stake1, arb.stake2, d1, d2, 1.0)
    assert (r.stake1, r.stake2) == (48.0, 52.0)
    assert r.total == 100.0
    assert r.worst_net == pytest.approx(0.80, abs=0.005)
    assert r.best_net == pytest.approx(1.52, abs=0.005)
    assert r.goes_negative is False


def test_round_stakes_to_five_dollars_flags_negative() -> None:
    """$50 / $50: 50*2.10-100 = +5.00 ; 50*1.952381-100 = -2.38 -> flagged."""
    d1, d2, arb = _spec_arb()
    r = om.round_stakes(arb.stake1, arb.stake2, d1, d2, 5.0)
    assert (r.stake1, r.stake2) == (50.0, 50.0)
    assert r.worst_net == pytest.approx(-2.38, abs=0.005)
    assert r.best_net == pytest.approx(5.00, abs=0.005)
    assert r.goes_negative is True


def test_round_stakes_rejects_bad_step() -> None:
    with pytest.raises(ValueError):
        om.round_stakes(48.18, 51.82, 2.1, 1.95, 0.0)


# ---------- middles ----------

def test_middle_spec_example() -> None:
    """SPEC: O218.5 -110 / U221.5 -110, B=$100 -> hold -4.55%, miss -$4.55, hit +$90.91."""
    d = om.am_to_dec(-110)
    mid = om.middle(d, d, 100.0)
    assert mid.hold_pct == pytest.approx(-4.55, abs=0.005)
    assert mid.miss_net == pytest.approx(-4.55, abs=0.005)
    assert mid.hit_net == pytest.approx(90.91, abs=0.005)
    assert mid.stake1 == pytest.approx(50.0)
    assert mid.stake2 == pytest.approx(50.0)


def test_middle_push_nets() -> None:
    """-110 / -110, $100: payout 95.45 each way, stakes $50 / $50.

    Landing exactly on a whole-number line refunds that leg's $50 and the other
    leg pays $95.45: 95.45 + 50 - 100 = +$45.45.
    """
    d = om.am_to_dec(-110)
    mid = om.middle(d, d, 100.0)
    assert mid.push1_net == pytest.approx(45.45, abs=0.005)
    assert mid.push2_net == pytest.approx(45.45, abs=0.005)


def test_middle_push_nets_uneven_prices() -> None:
    """+110 / -105, $100: payout 101.1751, stakes 48.1786 / 51.8214 (unrounded).

    Leg 1 refunded: 101.1751 + 48.1786 - 100 = +49.3537 -> $49.35.
    Leg 2 refunded: 101.1751 + 51.8214 - 100 = +52.9965 -> $53.00.
    (Adding the cent-rounded pieces would give 49.36; round only at the end.)
    """
    mid = om.middle(om.am_to_dec(110), om.am_to_dec(-105), 100.0)
    assert mid.push1_net == pytest.approx(49.35, abs=0.005)
    assert mid.push2_net == pytest.approx(53.00, abs=0.005)


@pytest.mark.parametrize(
    "low, high, both_win, push_low, push_high",
    [
        (218.5, 221.5, True, False, False),   # 219, 220, 221 win both
        (225.5, 226.5, True, False, False),   # 226 wins both
        (225.0, 226.5, True, True, False),    # 226 wins both; 225 refunds the Over
        (218.0, 221.0, True, True, True),     # 219, 220 win both; 218 and 221 push
        (225.0, 225.5, False, True, False),   # live case: nothing strictly between
        (213.5, 214.0, False, False, True),   # live case: 214 refunds the Under
        (225.0, 226.0, False, True, True),    # window 1, both whole: push at each end
        (-5.5, -5.0, False, False, True),     # spread: Mavs +5.5 / Wolves -5
        (1.5, 3.5, True, False, False),       # spread: Away -1.5 / Home +3.5 -> Away by 2 or 3
        (221.5, 221.5, False, False, False),  # same line: an arb candidate, not a middle
        (221.5, 218.5, False, False, False),  # reverse middle
    ],
)
def test_middle_landings(
    low: float, high: float, both_win: bool, push_low: bool, push_high: bool
) -> None:
    assert om.middle_landings(low, high) == om.MiddleLandings(both_win, push_low, push_high)


def test_middle_spec_example_passes_default_cutoff() -> None:
    """The draft's -4.5% cutoff wrongly excluded this; the default is -5.0%."""
    d = om.am_to_dec(-110)
    assert om.middle(d, d, 100.0).hold_pct >= om.DEFAULT_MIN_MIDDLE_HOLD_PCT


def test_totals_window() -> None:
    assert om.totals_window(218.5, 221.5) == pytest.approx(3.0)
    assert om.totals_window(221.5, 221.5) == 0.0
    assert om.totals_window(221.5, 218.5) < 0


def test_spread_window() -> None:
    assert om.spread_window(3.5, -1.5) == pytest.approx(2.0)   # middle
    assert om.spread_window(3.5, -3.5) == 0.0                  # arb candidate
    assert om.spread_window(1.5, -3.5) < 0                     # reverse middle


def test_push_risk() -> None:
    assert om.has_push_risk(218.0, 221.0) is True
    assert om.has_push_risk(218.5, 221.0) is True
    assert om.has_push_risk(218.5, 221.5) is False
    assert om.has_push_risk(-3.0, 4.5) is True


# ---------- de-vig, consensus, +EV ----------

def test_devig_even_market() -> None:
    d = om.am_to_dec(-110)
    p1, p2 = om.devig_two_way(d, d)
    assert p1 == pytest.approx(0.5)
    assert p2 == pytest.approx(0.5)


def test_devig_lopsided_market() -> None:
    """-150 / +130: 0.6 and 0.434783, sum 1.034783 -> 0.579832 / 0.420168."""
    p1, p2 = om.devig_two_way(om.am_to_dec(-150), om.am_to_dec(130))
    assert p1 == pytest.approx(0.579832, abs=1e-6)
    assert p2 == pytest.approx(0.420168, abs=1e-6)
    assert p1 + p2 == pytest.approx(1.0)


def test_consensus_is_median() -> None:
    assert om.consensus_prob([0.53, 0.48, 0.50]) == pytest.approx(0.50)
    assert om.consensus_prob([0.48, 0.50]) == pytest.approx(0.49)
    with pytest.raises(ValueError):
        om.consensus_prob([])


def test_ev_spec_example() -> None:
    """SPEC: p = 0.50, price +110 -> EV +5.0%."""
    assert om.ev_pct(0.50, om.am_to_dec(110)) == pytest.approx(5.0)


def test_ev_negative_at_standard_juice() -> None:
    assert om.ev_pct(0.50, om.am_to_dec(-110)) == pytest.approx(-4.545, abs=1e-3)


def test_fair_odds_am() -> None:
    assert om.fair_odds_am(0.5) == 100
    assert om.fair_odds_am(0.6) == -150
    assert om.fair_odds_am(0.4) == 150
    with pytest.raises(ValueError):
        om.fair_odds_am(0.0)
    with pytest.raises(ValueError):
        om.fair_odds_am(1.0)


def test_kelly_spec_example() -> None:
    """SPEC: p=0.5, d=2.10 -> f = 4.55%; quarter-Kelly on $1000 = $11.36."""
    assert om.kelly_fraction(0.5, 2.10) == pytest.approx(0.0455, abs=1e-4)
    assert om.kelly_stake(1000.0, 0.5, 2.10) == pytest.approx(11.36, abs=0.005)


def test_kelly_is_zero_without_an_edge() -> None:
    assert om.kelly_fraction(0.5, om.am_to_dec(-110)) == 0.0
    assert om.kelly_stake(1000.0, 0.5, om.am_to_dec(-110)) == 0.0


# ---------- hedge ----------

def test_hedge_spec_example() -> None:
    """SPEC: $100 at +250, hedge at -140 -> H=$204.17, net +$45.83, ROI 15.07%."""
    h = om.hedge(100.0, 250, -140)
    assert h.full_hedge == pytest.approx(204.17, abs=0.005)
    assert h.hedge_stake == pytest.approx(204.17, abs=0.005)
    assert h.net_if_original_wins == pytest.approx(45.83, abs=0.005)
    assert h.net_if_hedge_wins == pytest.approx(45.83, abs=0.005)
    assert h.roi_pct == pytest.approx(15.07, abs=0.005)


def test_hedge_half() -> None:
    """50% of H = $102.08: original wins 350-100-102.08 = +147.92 ; hedge wins 175-202.08 = -27.08."""
    h = om.hedge(100.0, 250, -140, fraction=0.5)
    assert h.hedge_stake == pytest.approx(102.08, abs=0.005)
    assert h.net_if_original_wins == pytest.approx(147.92, abs=0.005)
    assert h.net_if_hedge_wins == pytest.approx(-27.08, abs=0.005)


def test_hedge_none() -> None:
    h = om.hedge(100.0, 250, -140, fraction=0.0)
    assert h.hedge_stake == 0.0
    assert h.net_if_original_wins == pytest.approx(250.0)
    assert h.net_if_hedge_wins == pytest.approx(-100.0)


@pytest.mark.parametrize(
    "stake, original, hedge_odds, fraction",
    [
        (100.0, 50, -140, 1.0),    # invalid American odds (draft bug #5)
        (100.0, 250, -99, 1.0),
        (100.0, 250, 0, 1.0),
        (0.0, 250, -140, 1.0),
        (-5.0, 250, -140, 1.0),
        (100.0, 250, -140, 1.5),
        (100.0, 250, -140, -0.1),
    ],
)
def test_hedge_rejects_bad_input(
    stake: float, original: int, hedge_odds: int, fraction: float
) -> None:
    with pytest.raises(ValueError):
        om.hedge(stake, original, hedge_odds, fraction=fraction)


def test_equalizing_stake() -> None:
    """Leg 1 placed at $48 on 2.10 -> leg 2 at 1.952381 needs 100.80/1.952381 = $51.63."""
    assert om.equalizing_stake(48.0, 2.10, om.am_to_dec(-105)) == pytest.approx(51.63, abs=0.005)
