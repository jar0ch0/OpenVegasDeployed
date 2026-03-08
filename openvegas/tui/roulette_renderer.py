"""Roulette wheel result display."""

from __future__ import annotations

from openvegas.tui.theme import ascii_safe_mode

RED_NUMBERS = {1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36}


def number_color(n: int) -> str:
    if n == 0:
        return "green"
    return "red" if n in RED_NUMBERS else "white"


def render_result(result: int, bet_type: str, hit: bool, payout_mult: str) -> str:
    """Render roulette result display."""
    ascii_safe = ascii_safe_mode()
    hit_mark = "YES" if hit else "NO"
    bet_display = bet_type.replace("bet_", "").upper()

    if ascii_safe:
        return (
            f"+-------------------------+\n"
            f"|      ROULETTE           |\n"
            f"|      Result: {result:>2}         |\n"
            f"|      Bet: {bet_display:<13} |\n"
            f"|      Hit: {hit_mark:<13} |\n"
            f"|      Payout: {payout_mult}x        |\n"
            f"+-------------------------+"
        )

    color = number_color(result)
    n_str = f"[{color}]{result:>2}[/{color}]"

    return (
        f"╔═════════════════════════╗\n"
        f"║      ◎ ROULETTE ◎       ║\n"
        f"╠═════════════════════════╣\n"
        f"║  Result: {n_str}              ║\n"
        f"║  Bet: {bet_display:<18} ║\n"
        f"║  Hit: {hit_mark:<18} ║\n"
        f"║  Payout: {payout_mult}x              ║\n"
        f"╚═════════════════════════╝"
    )
