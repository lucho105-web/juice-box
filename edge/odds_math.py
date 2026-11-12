"""Odds math for Juice Box: conversions, arbitrage, middles, +EV and hedging.

Pure functions only. No I/O, no pandas, no Streamlit. Formulas follow
docs/SPEC.md section 2. Money values are returned unrounded unless a function
says otherwise; round for display in the UI.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from statistics import median
from typing import Sequence

DEFAULT_MIN_MIDDLE_HOLD_PCT: float = -5.0
DEFAULT_KELLY_MULTIPLIER: float = 0.25


# ---------- validation helpers ----------

def _check_decimal(d: float) -> None:
    if not math.isfinite(d) or d <= 1.0:
        raise ValueError(f"Decimal odds must be greater than 1.0, got {d}")


def _check_positive(value: float, name: str) -> None:
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be greater than 0, got {value}")


def _check_prob(p: float) -> None:
    if not math.isfinite(p) or not 0.0 < p < 1.0:
        raise ValueError(f"Probability must be between 0 and 1, got {p}")


# ---------- conversions ----------

def am_to_dec(american: float) -> float:
    """American odds -> decimal odds. Rejects values between -100 and +100."""
    if not math.isfinite(american) or -100 < american < 100:
        raise ValueError(
            f"American odds must be <= -100 or >= +100, got {american}"
        )
    if american > 0:
        return 1.0 + american / 100.0
    return 1.0 + 100.0 / abs(american)


def dec_to_am(decimal: float) -> int:
    """Decimal odds -> American odds, rounded to the nearest whole number."""
    _check_decimal(decimal)
    if decimal >= 2.0:
        return round((decimal - 1.0) * 100.0)
    return -round(100.0 / (decimal - 1.0))


def implied(decimal: float) -> float:
    """Implied probability of a decimal price (vig included)."""
    _check_decimal(decimal)
    return 1.0 / decimal


# ---------- two-way arbitrage ----------

@dataclass(frozen=True)
class ArbResult:
    s: float            # sum of implied probabilities; arb when < 1
    profit_pct: float   # (1/S - 1) * 100
    stake1: float
    stake2: float
    payout: float       # same whichever side wins
    is_arb: bool


def arb_two_way(d1: float, d2: float, bankroll: float) -> ArbResult:
    """Equal-payout stake split across the two sides of a market."""
    _check_decimal(d1)
    _check_decimal(d2)
    _check_positive(bankroll, "Bankroll")
    s = 1.0 / d1 + 1.0 / d2
    return ArbResult(
        s=s,
        profit_pct=(1.0 / s - 1.0) * 100.0,
        stake1=bankroll * (1.0 / d1) / s,
        stake2=bankroll * (1.0 / d2) / s,
        payout=bankroll / s,
        is_arb=s < 1.0,
    )


@dataclass(frozen=True)
class RoundedStakes:
    stake1: float
    stake2: float
    total: float
    net_if_1_wins: float
    net_if_2_wins: float
    worst_net: float
    best_net: float
    goes_negative: bool  # True when rounding turned the worst case into a loss


def round_to_step(amount: float, step: float) -> float:
    """Round to the nearest multiple of step, halves up (0.01, 1 or 5)."""
    _check_positive(step, "Rounding step")
    return round(math.floor(amount / step + 0.5) * step, 2)


def round_stakes(
    stake1: float, stake2: float, d1: float, d2: float, step: float
) -> RoundedStakes:
    """Round both stakes to a step and report the net for each outcome."""
    _check_decimal(d1)
    _check_decimal(d2)
    r1 = round_to_step(stake1, step)
    r2 = round_to_step(stake2, step)
    total = r1 + r2
    net1 = r1 * d1 - total
    net2 = r2 * d2 - total
    worst = min(net1, net2)
    return RoundedStakes(
        stake1=r1,
        stake2=r2,
        total=total,
        net_if_1_wins=net1,
        net_if_2_wins=net2,
        worst_net=worst,
        best_net=max(net1, net2),
        goes_negative=round(worst, 2) < 0,
    )


def equalizing_stake(stake1: float, d1: float, d2: float) -> float:
    """Stake on side 2 that pays out the same as stake1 at d1."""
    _check_positive(stake1, "Stake")
    _check_decimal(d1)
    _check_decimal(d2)
    return stake1 * d1 / d2


# ---------- middles ----------

@dataclass(frozen=True)
class MiddleResult:
    s: float
    hold_pct: float   # (1/S - 1) * 100; usually a small negative number
    stake1: float
    stake2: float
    miss_net: float   # one side wins: B/S - B
    hit_net: float    # both sides win: 2B/S - B


def middle(d1: float, d2: float, bankroll: float) -> MiddleResult:
    """Equal-payout staking for a middle. Says nothing about the window."""
    arb = arb_two_way(d1, d2, bankroll)
    return MiddleResult(
        s=arb.s,
        hold_pct=arb.profit_pct,
        stake1=arb.stake1,
        stake2=arb.stake2,
        miss_net=arb.payout - bankroll,
        hit_net=2.0 * arb.payout - bankroll,
    )


def totals_window(over_point: float, under_point: float) -> float:
    """Width of a totals middle. > 0 is a middle, 0 is an arb candidate."""
    return under_point - over_point


def spread_window(point_a: float, point_b: float) -> float:
    """Width of a spread middle (team A at a, team B at b).

    > 0 is a middle, 0 is an arb candidate, < 0 is a reverse middle (skip).
    """
    return point_a + point_b


def has_push_risk(point1: float, point2: float) -> bool:
    """True when either line is a whole number, so a result can push one side."""
    return float(point1).is_integer() or float(point2).is_integer()


# ---------- de-vig, consensus, +EV ----------

def devig_two_way(d1: float, d2: float) -> tuple[float, float]:
    """Multiplicative de-vig: fair probabilities for both sides of one book."""
    i1, i2 = implied(d1), implied(d2)
    total = i1 + i2
    return i1 / total, i2 / total


def consensus_prob(fair_probs: Sequence[float]) -> float:
    """Median of the other books' fair probabilities (leave-one-out upstream)."""
    if not fair_probs:
        raise ValueError("Need at least one fair probability for a consensus")
    return float(median(fair_probs))


def ev_pct(p: float, decimal: float) -> float:
    """Expected value of a price, in percent of stake, at fair probability p."""
    _check_prob(p)
    _check_decimal(decimal)
    return (p * decimal - 1.0) * 100.0


def fair_odds_am(p: float) -> int:
    """American odds with zero vig for fair probability p."""
    _check_prob(p)
    return dec_to_am(1.0 / p)


def kelly_fraction(p: float, decimal: float) -> float:
    """Full-Kelly fraction of bankroll; 0 when there is no edge."""
    _check_prob(p)
    _check_decimal(decimal)
    return max(0.0, (p * decimal - 1.0) / (decimal - 1.0))


def kelly_stake(
    bankroll: float,
    p: float,
    decimal: float,
    multiplier: float = DEFAULT_KELLY_MULTIPLIER,
) -> float:
    """Fractional-Kelly stake in dollars (quarter-Kelly by default)."""
    _check_positive(bankroll, "Bankroll")
    return bankroll * kelly_fraction(p, decimal) * multiplier


# ---------- hedge ----------

@dataclass(frozen=True)
class HedgeResult:
    full_hedge: float            # H = s*D / h, locks equal nets
    hedge_stake: float           # fraction * H
    net_if_original_wins: float
    net_if_hedge_wins: float
    roi_pct: float               # worst-case net / total staked * 100


def hedge(
    stake: float, original_am: float, hedge_am: float, fraction: float = 1.0
) -> HedgeResult:
    """Hedge a bet already held. fraction is the share of the full hedge (0-1)."""
    _check_positive(stake, "Stake")
    if not math.isfinite(fraction) or not 0.0 <= fraction <= 1.0:
        raise ValueError(f"Hedge fraction must be between 0 and 1, got {fraction}")
    d = am_to_dec(original_am)
    h = am_to_dec(hedge_am)
    full = stake * d / h
    hedge_stake = full * fraction
    net_original = stake * d - stake - hedge_stake
    net_hedge = hedge_stake * h - stake - hedge_stake
    outlay = stake + hedge_stake
    return HedgeResult(
        full_hedge=full,
        hedge_stake=hedge_stake,
        net_if_original_wins=net_original,
        net_if_hedge_wins=net_hedge,
        roi_pct=min(net_original, net_hedge) / outlay * 100.0,
    )
