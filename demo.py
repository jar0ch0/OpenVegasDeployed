"""
OpenVegas Offline Demo — play all games locally, no backend/credits needed.

Usage:
    python3 demo.py              # interactive menu
    python3 demo.py horse        # jump straight to horse racing
    python3 demo.py blackjack    # jump to blackjack
"""

import asyncio
import secrets
import sys
from decimal import Decimal

from rich.console import Console
from rich.prompt import IntPrompt, Prompt
from rich.table import Table

from openvegas.rng.provably_fair import ProvablyFairRNG
from openvegas.tui.theme import ascii_safe_mode
from openvegas.tui.cards import render_hand
from openvegas.tui.banners import result_banner
from openvegas.tui.slots_renderer import render_reels
from openvegas.tui.roulette_renderer import render_result as render_roulette
from openvegas.games.horse_racing import HorseRacing, HORSE_COLORS
from openvegas.games.skill_shot import SkillShotGame

console = Console()
STARTING_BALANCE = 100.0


# ---------------------------------------------------------------------------
# Horse Racing
# ---------------------------------------------------------------------------

async def play_horse_race(balance: float) -> float:
    game = HorseRacing(num_horses=8)
    rng = ProvablyFairRNG()
    commitment = rng.new_round()
    client_seed = secrets.token_hex(16)

    # Preview horses
    preview_rng = ProvablyFairRNG()
    preview_rng.server_seed = rng.server_seed
    preview_rng.server_seed_hash = rng.server_seed_hash
    game.setup_race(preview_rng, client_seed, 0)

    console.print("\n[bold cyan]--- HORSE RACING ---[/bold cyan]")
    console.print(f"Balance: [bold]{balance:.2f} $V[/bold]\n")

    table = Table(title="Horses")
    table.add_column("#", style="bold")
    table.add_column("Color")
    table.add_column("Name")
    table.add_column("Odds", justify="right")
    for i, h in enumerate(game.horses):
        color = HORSE_COLORS[i % len(HORSE_COLORS)]
        table.add_row(str(h.number), f"[bold {color}]■[/bold {color}]", h.name, f"{h.odds}x")
    console.print(table)

    stake = float(Prompt.ask("\nStake ($V)", default="5"))
    if stake > balance or stake <= 0:
        console.print("[red]Invalid stake.[/red]")
        return balance

    horse_num = IntPrompt.ask("Pick horse #", default=1)
    bet_type = Prompt.ask("Bet type", choices=["win", "place", "show"], default="win")

    bet = {
        "game_id": "demo",
        "player_id": "local",
        "amount": stake,
        "type": bet_type,
        "horse": horse_num,
    }

    if not await game.validate_bet(bet):
        console.print("[red]Invalid bet.[/red]")
        return balance

    game2 = HorseRacing(num_horses=8)
    rng2 = ProvablyFairRNG()
    rng2.server_seed = rng.server_seed
    rng2.server_seed_hash = rng.server_seed_hash

    result = await game2.resolve(bet, rng2, client_seed, 0)
    await game2.render(result, console)

    valid = ProvablyFairRNG.verify(result.server_seed, result.server_seed_hash)
    console.print(f"[dim]Provably fair: {'verified' if valid else 'FAILED'}[/dim]")

    new_balance = balance + float(result.net)
    console.print(f"Balance: [bold]{new_balance:.2f} $V[/bold]")
    return new_balance


# ---------------------------------------------------------------------------
# Skill Shot
# ---------------------------------------------------------------------------

async def play_skill_shot(balance: float) -> float:
    game = SkillShotGame()
    rng = ProvablyFairRNG()
    rng.new_round()
    client_seed = secrets.token_hex(16)

    console.print("\n[bold cyan]--- SKILL SHOT ---[/bold cyan]")
    console.print(f"Balance: [bold]{balance:.2f} $V[/bold]")
    console.print("Stop the cursor in the zone to win!\n")

    stake = float(Prompt.ask("Stake ($V)", default="5"))
    if stake > balance or stake <= 0:
        console.print("[red]Invalid stake.[/red]")
        return balance

    stop_pos = await game.render_interactive(console)

    bet = {
        "game_id": "demo",
        "player_id": "local",
        "amount": stake,
        "stop_position": stop_pos,
    }

    result = await game.resolve(bet, rng, client_seed, 0)
    await game.render(result, console)

    new_balance = balance + float(result.net)
    console.print(f"Balance: [bold]{new_balance:.2f} $V[/bold]")
    return new_balance


# ---------------------------------------------------------------------------
# Blackjack
# ---------------------------------------------------------------------------

async def play_blackjack_demo(balance: float) -> float:
    from openvegas.casino.blackjack import BlackjackGame, hand_value, cards_str

    game = BlackjackGame()
    rng = ProvablyFairRNG()
    rng.new_round()
    client_seed = secrets.token_hex(16)
    state = game.initial_state(rng, client_seed, 0)
    ascii_safe = ascii_safe_mode()

    console.print("\n[bold cyan]--- BLACKJACK ---[/bold cyan]")
    console.print(f"Balance: [bold]{balance:.2f} $V[/bold]\n")

    stake = float(Prompt.ask("Stake ($V)", default="5"))
    if stake > balance or stake <= 0:
        console.print("[red]Invalid stake.[/red]")
        return balance

    # Show player hand
    console.print(render_hand(
        cards_str(state["player"]), "YOUR HAND",
        hand_value(state["player"]), ascii_safe,
    ))
    # Show dealer with one hidden
    dealer_show = cards_str(state["dealer"][:1]) + ["??"]
    console.print(render_hand(dealer_show, "DEALER", ascii_safe=ascii_safe))

    # Player action loop
    nonce_offset = 100
    while "hit" in game.valid_actions(state):
        action = Prompt.ask("Action", choices=["hit", "stand"], default="stand")
        state = game.apply_action(state, action, {}, rng, client_seed, nonce_offset)
        nonce_offset += 1
        console.print(render_hand(
            cards_str(state["player"]), "YOUR HAND",
            hand_value(state["player"]), ascii_safe,
        ))

    # Resolve
    mult, data = game.resolve(state)
    console.print(render_hand(data["dealer_cards"], "DEALER", data["dealer"], ascii_safe))

    payout = float(Decimal(str(stake)) * mult)
    net = payout - stake
    console.print(result_banner([
        f"Result: {data['result'].upper()}",
        f"Payout: {payout:.2f} $V ({'+' if net >= 0 else ''}{net:.2f} net)",
    ]))
    return balance + net


# ---------------------------------------------------------------------------
# Roulette
# ---------------------------------------------------------------------------

async def play_roulette_demo(balance: float) -> float:
    from openvegas.casino.roulette import RouletteGame

    game = RouletteGame()
    rng = ProvablyFairRNG()
    rng.new_round()
    client_seed = secrets.token_hex(16)
    state = game.initial_state(rng, client_seed, 0)

    console.print("\n[bold cyan]--- ROULETTE ---[/bold cyan]")
    console.print(f"Balance: [bold]{balance:.2f} $V[/bold]\n")

    stake = float(Prompt.ask("Stake ($V)", default="5"))
    if stake > balance or stake <= 0:
        console.print("[red]Invalid stake.[/red]")
        return balance

    bet_type = Prompt.ask("Bet", choices=["red", "black", "odd", "even", "number"], default="red")
    payload = {}
    if bet_type == "number":
        payload["number"] = IntPrompt.ask("Pick number (0-36)", default=17)

    state = game.apply_action(state, f"bet_{bet_type}", payload, rng, client_seed, 0)
    state = game.apply_action(state, "spin", {}, rng, client_seed, 1)

    mult, data = game.resolve(state)
    payout = float(Decimal(str(stake)) * mult)
    net = payout - stake

    console.print(render_roulette(data["result"], f"bet_{bet_type}", data["hit"], str(mult)))
    console.print(result_banner([
        f"Payout: {payout:.2f} $V ({'+' if net >= 0 else ''}{net:.2f} net)",
    ]))
    return balance + net


# ---------------------------------------------------------------------------
# Slots
# ---------------------------------------------------------------------------

async def play_slots_demo(balance: float) -> float:
    from openvegas.casino.slots import SlotsGame

    game = SlotsGame()
    rng = ProvablyFairRNG()
    rng.new_round()
    client_seed = secrets.token_hex(16)
    state = game.initial_state(rng, client_seed, 0)

    console.print("\n[bold cyan]--- SLOTS ---[/bold cyan]")
    console.print(f"Balance: [bold]{balance:.2f} $V[/bold]\n")

    stake = float(Prompt.ask("Stake ($V)", default="5"))
    if stake > balance or stake <= 0:
        console.print("[red]Invalid stake.[/red]")
        return balance

    state = game.apply_action(state, "spin", {}, rng, client_seed, 0)
    mult, data = game.resolve(state)
    payout = float(Decimal(str(stake)) * mult)
    net = payout - stake

    console.print(render_reels(data["reels"], data["hit"]))
    console.print(result_banner([
        f"Payout: {payout:.2f} $V ({'+' if net >= 0 else ''}{net:.2f} net)",
    ]))
    return balance + net


# ---------------------------------------------------------------------------
# Poker
# ---------------------------------------------------------------------------

async def play_poker_demo(balance: float) -> float:
    from openvegas.casino.poker import PokerGame

    game = PokerGame()
    rng = ProvablyFairRNG()
    rng.new_round()
    client_seed = secrets.token_hex(16)
    state = game.initial_state(rng, client_seed, 0)
    ascii_safe = ascii_safe_mode()

    console.print("\n[bold cyan]--- POKER (Jacks or Better) ---[/bold cyan]")
    console.print(f"Balance: [bold]{balance:.2f} $V[/bold]\n")

    stake = float(Prompt.ask("Stake ($V)", default="5"))
    if stake > balance or stake <= 0:
        console.print("[red]Invalid stake.[/red]")
        return balance

    card_strs = [f"{c[0]}{c[1]}" for c in state["hand"]]
    console.print(render_hand(card_strs, "YOUR HAND", ascii_safe=ascii_safe, show_positions=True))

    hold_input = Prompt.ask("Hold positions (e.g., 1,3,5 or 'none')", default="none")
    if hold_input.strip().lower() == "none":
        state = game.apply_action(state, "stand", {}, rng, client_seed, 100)
    else:
        positions = [int(x.strip()) - 1 for x in hold_input.split(",") if x.strip().isdigit()]
        state = game.apply_action(state, "hold", {"positions": positions}, rng, client_seed, 100)

    mult, data = game.resolve(state)
    payout = float(Decimal(str(stake)) * mult)
    net = payout - stake

    console.print(render_hand(data["hand"], "FINAL HAND", ascii_safe=ascii_safe))
    console.print(result_banner([
        f"Hand: {data['rank'].replace('_', ' ').upper()}",
        f"Payout: {payout:.2f} $V ({'+' if net >= 0 else ''}{net:.2f} net)",
    ]))
    return balance + net


# ---------------------------------------------------------------------------
# Baccarat
# ---------------------------------------------------------------------------

async def play_baccarat_demo(balance: float) -> float:
    from openvegas.casino.baccarat import BaccaratGame, cards_str

    game = BaccaratGame()
    rng = ProvablyFairRNG()
    rng.new_round()
    client_seed = secrets.token_hex(16)
    state = game.initial_state(rng, client_seed, 0)
    ascii_safe = ascii_safe_mode()

    console.print("\n[bold cyan]--- BACCARAT ---[/bold cyan]")
    console.print(f"Balance: [bold]{balance:.2f} $V[/bold]\n")

    stake = float(Prompt.ask("Stake ($V)", default="5"))
    if stake > balance or stake <= 0:
        console.print("[red]Invalid stake.[/red]")
        return balance

    bet = Prompt.ask("Bet", choices=["player", "banker", "tie"], default="player")
    state = game.apply_action(state, f"bet_{bet}", {}, rng, client_seed, 0)

    mult, data = game.resolve(state)
    payout = float(Decimal(str(stake)) * mult)
    net = payout - stake

    console.print(render_hand(data["player_cards"], "PLAYER", data["player_total"], ascii_safe))
    console.print(render_hand(data["banker_cards"], "BANKER", data["banker_total"], ascii_safe))
    console.print(result_banner([
        f"Result: {data['result'].replace('_', ' ').upper()}",
        f"Payout: {payout:.2f} $V ({'+' if net >= 0 else ''}{net:.2f} net)",
    ]))
    return balance + net


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

GAME_DISPATCH = {
    "horse": play_horse_race,
    "skillshot": play_skill_shot,
    "blackjack": play_blackjack_demo,
    "roulette": play_roulette_demo,
    "slots": play_slots_demo,
    "poker": play_poker_demo,
    "baccarat": play_baccarat_demo,
}


async def main():
    game_choice = sys.argv[1] if len(sys.argv) > 1 else None

    console.print("[bold]OpenVegas Demo[/bold] — offline mode, no real credits used")
    console.print(f"Starting balance: {STARTING_BALANCE} $V (fake)\n")

    balance = STARTING_BALANCE

    while balance > 0:
        if game_choice is None:
            choice = Prompt.ask(
                "Pick a game",
                choices=list(GAME_DISPATCH.keys()) + ["quit"],
                default="horse",
            )
        else:
            choice = game_choice
            game_choice = None

        if choice == "quit":
            break

        handler = GAME_DISPATCH.get(choice)
        if handler:
            balance = await handler(balance)
        else:
            console.print(f"[red]Unknown game: {choice}[/red]")

        if balance <= 0:
            console.print("\n[bold red]You're broke! Game over.[/bold red]")
            break

        if Prompt.ask("\nPlay again?", choices=["y", "n"], default="y") != "y":
            break

    console.print(f"\n[bold]Final balance: {balance:.2f} $V[/bold]")
    console.print("[dim]No real credits were used.[/dim]")


if __name__ == "__main__":
    asyncio.run(main())
