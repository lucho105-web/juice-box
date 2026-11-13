"""Plain-English wording for people new to betting. Pure string helpers; the
numbers come from the scanners, nothing is calculated here."""
from __future__ import annotations

import math

from edge import fmt


def odds_helper(price_am: int) -> str:
    """'+110 · $100 wins $110'  /  '-105 · bet $105 to win $100'."""
    if price_am >= 100:
        return f"{price_am:+d} · $100 wins ${price_am}"
    return f"{price_am:+d} · bet ${abs(price_am)} to win $100"


def _has_point(point: float | None) -> bool:
    return point is not None and not (isinstance(point, float) and math.isnan(point))


def bet_phrase(side: str, point: float | None, market: str, short: str | None = None) -> str:
    """What has to happen for this bet to win, in plain words.

    'Celtics to win', 'Heat to win by more than 2.5',
    'Bulls to win, or lose by less than 2.5', 'over 218.5 total points'.
    """
    name = short or side
    if market == "totals" and _has_point(point):
        return f"{side.lower()} {point:g} total points"
    if market == "spreads" and _has_point(point):
        if point < 0:
            return f"{name} to win by more than {abs(point):g}"
        if point > 0:
            return f"{name} to win, or lose by less than {point:g}"
        return f"{name} to win"
    return f"{name} to win"


def _legs_text(legs: list[tuple[float, str, str]]) -> str:
    """legs: (stake, bet phrase, book name)."""
    return " and ".join(f"{fmt.money(stake)} on {phrase} at {book}" for stake, phrase, book in legs)


def arb_sentence(legs: list[tuple[float, str, str]], worst_net: float, best_net: float) -> str:
    total = sum(stake for stake, _, _ in legs)
    if worst_net < 0:
        outcome = (
            f"After rounding the stakes this can lose: you end up between "
            f"{fmt.money(worst_net, signed=True)} and {fmt.money(best_net, signed=True)}."
        )
    elif round(worst_net, 2) == round(best_net, 2):
        outcome = f"Whichever bet wins, you make {fmt.money(worst_net)} on {fmt.money(total)}."
    else:
        outcome = (
            f"Whichever bet wins, you make between {fmt.money(worst_net)} and "
            f"{fmt.money(best_net)} on {fmt.money(total)}."
        )
    return f"Bet {_legs_text(legs)}. {outcome}"


def middle_sentence(
    legs: list[tuple[float, str, str]], miss_net: float, best_net: float, both_win: bool
) -> str:
    lose = f"Otherwise you lose about {fmt.money(abs(miss_net))}."
    if both_win:
        upside = f"If the result lands between the two lines, both bets win: {fmt.money(best_net, signed=True)}."
    else:
        upside = (
            f"No result wins both bets. Best case, it lands exactly on the line: one bet is "
            f"refunded and the other wins, {fmt.money(best_net, signed=True)}."
        )
    return f"Bet {_legs_text(legs)}. {upside} {lose}"


def ev_sentence(phrase: str, book: str, price_am: int, fair_am: int, ev_pct: float) -> str:
    return (
        f"{book} is paying {price_am:+d} on {phrase}. The fair price is about {fair_am:+d}, "
        f"so over many bets like this you'd expect to make about {ev_pct:.1f}% of what you stake. "
        f"Any single bet can still lose."
    )


TILE_CAPTION: dict[str, str] = {
    "arb": "Profit either way",
    "middle": "Small risk, big upside",
    "ev": "Better-than-fair",
}

LESSONS: list[tuple[str, str]] = [
    (
        "Reading the odds",
        "American odds show what you win. A plus number is what a $100 bet wins: +110 means "
        "$100 wins $110. A minus number is what you bet to win $100: -105 means you bet $105 "
        "to win $100. Plus is usually the underdog, minus the favorite.",
    ),
    (
        "Three kinds of bet",
        "Moneyline: you pick who wins. Spread: the favorite has to win by more than a set "
        "margin (-2.5), or the underdog has to stay within it (+2.5). Total: you bet whether "
        "the combined score goes over or under a number.",
    ),
    (
        "The juice",
        "Books build a fee into their prices, called the juice or vig. A fair coin flip "
        "would pay +100 on both sides; books usually offer -110 on both. That gap is why "
        "most bets lose money over time, and it's what this app looks for ways around.",
    ),
    (
        "Arbs: profit either way",
        "Sometimes two books disagree enough that betting one side at each locks in a small "
        "profit whoever wins. The profit is usually 1 to 2%, the prices vanish in seconds "
        "to minutes, and you need accounts and money at both books.",
    ),
    (
        "Middles: small risk, big upside",
        "Two bets on different lines, such as Over 218.5 at one book and Under 221.5 at "
        "another. If the score lands in between, both win. If not, one wins and one loses "
        "and you're down a little. A push middle can't win both; its best case is one bet "
        "refunded.",
    ),
    (
        "+EV: better-than-fair prices",
        "One book's price is better than the fair price worked out from the other books. "
        "It isn't a sure thing. It pays off over many bets, and any single one can lose.",
    ),
    (
        "Hedging",
        "If you already hold a bet, you can bet the other side to lock in a profit or cut "
        "a loss. The hedge calculator shows how much to bet and what you end up with.",
    ),
    (
        "Before you bet real money",
        "Always press Re-check prices first; the app's prices can be a minute old. Stake "
        "limits and rounding can wipe out a small arb. Books limit or close accounts that "
        "keep taking these bets. Only bet what you can afford to lose.",
    ),
]

GLOSSARY: list[tuple[str, str]] = [
    ("Arb (arbitrage)", "Betting both sides at different books for a guaranteed profit."),
    ("Bankroll", "The total amount you've set aside for a bet or for betting."),
    ("Book / sportsbook", "The company taking your bet, like DraftKings or FanDuel."),
    ("EV (expected value)", "What a bet is worth on average over many tries. +EV is good."),
    ("Fair price", "The price with the book's fee removed."),
    ("Hold", "For a middle, what you lose (as a %) when it doesn't land in between."),
    ("Juice / vig", "The fee built into a book's prices."),
    ("Leg", "One of the bets that make up an arb or middle."),
    ("Line", "The number a spread or total bet is set at, like -2.5 or 218.5."),
    ("Moneyline (ML)", "A bet on who wins, with no margin involved."),
    ("Push", "A tie with the line. Your stake is refunded."),
    ("Stake", "The amount you put on a bet."),
]
