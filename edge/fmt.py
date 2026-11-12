"""Display formatting for the UI. Pure string helpers, no math decisions."""
from __future__ import annotations

import math


def money(amount: float, signed: bool = False) -> str:
    """$48, $101.18, and with signed=True: +$1.18 / -$4.55."""
    value = round(float(amount), 2)
    if value == 0:
        value = 0.0   # avoid "-$0"
    body = f"{abs(value):,.2f}"
    if body.endswith(".00"):
        body = body[:-3]
    sign = "-" if value < 0 else ("+" if signed else "")
    return f"{sign}${body}"


def american(price: float) -> str:
    """+110 / -105."""
    return f"{int(price):+d}"


def pct(value: float, digits: int = 2, signed: bool = True) -> str:
    """+1.18% / -4.55%."""
    return f"{value:+.{digits}f}%" if signed else f"{value:.{digits}f}%"


def leg_label(side: str, point: float | None, market: str) -> str:
    """'Boston Celtics ML', 'Miami Heat -2.5', 'Over 218.5'."""
    if market == "h2h" or point is None or (isinstance(point, float) and math.isnan(point)):
        return f"{side} ML"
    if market == "spreads":
        return f"{side} {point:+g}"
    return f"{side} {point:g}"


def age(seconds: float) -> str:
    """34s, 20m, 3h."""
    s = max(0, int(seconds))
    if s < 90:
        return f"{s}s"
    if s < 5400:
        return f"{round(s / 60)}m"
    return f"{round(s / 3600)}h"
