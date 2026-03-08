# OpenVegas Cosmetic Revamp Plan

## Context
The current game visuals are minimal — dashes for tracks, plain text for cards, raw strings for symbols. This plan upgrades every game's look without touching game logic, RNG, ledger, or payout math. Pure rendering changes only.

**Critical contract rule:** All machine-facing outcome fields in `resolve()` return values (`player_cards`, `dealer_cards`, `reels`, `rank`, `result`, `hit`, etc.) remain **unchanged**. Cosmetic rendering adds **separate display methods** that format for human eyes. Casino API responses keep raw fields intact; display fields are additive.

---

## Unified Visual System

### Design Tokens (shared across all games)

```python
# openvegas/tui/theme.py
"""Visual system — colors, borders, spacing, terminal compatibility."""

import os
import sys


def ascii_safe_mode() -> bool:
    """True if terminal can't handle wide Unicode/emoji.
    Set OPENVEGAS_ASCII=1 to force ASCII mode."""
    if os.getenv("OPENVEGAS_ASCII", "0") == "1":
        return True
    # Auto-detect: if LANG/LC_ALL don't mention UTF, assume ASCII-only
    lang = os.getenv("LANG", "") + os.getenv("LC_ALL", "")
    if "UTF" not in lang.upper() and "utf" not in lang:
        return True
    return False


def terminal_width() -> int:
    try:
        return os.get_terminal_size().columns
    except OSError:
        return 80


def render_mode() -> str:
    """compact (<80), standard (80-119), cinematic (120+)."""
    w = terminal_width()
    if w < 80:
        return "compact"
    if w < 120:
        return "standard"
    return "cinematic"


# Color tokens — consistent palette across all games
COLORS = {
    "win": "bold green",
    "loss": "red",
    "push": "yellow",
    "accent": "bold cyan",
    "muted": "dim",
    "danger": "bold red",
    "gold": "bold yellow",
}

# Border styles
BORDER_HEAVY = {"tl": "╔", "tr": "╗", "bl": "╚", "br": "╝", "h": "═", "v": "║"}
BORDER_LIGHT = {"tl": "┌", "tr": "┐", "bl": "└", "br": "┘", "h": "─", "v": "│"}
BORDER_ASCII = {"tl": "+", "tr": "+", "bl": "+", "br": "+", "h": "-", "v": "|"}  # pure ASCII

# Animation cadence (seconds)
ANIM = {
    "intro_pause": 0.3,
    "frame_delay": 0.05,
    "resolve_pause": 0.5,
    "win_flash_count": 3,
    "win_flash_delay": 0.15,
}

# Themes (user-selectable via `openvegas config set theme <name>`)
THEMES = {
    "retro_ascii": {
        "horse_glyph": "H>",
        "trail": "=",
        "empty": ".",
        "finish": "|",
        "cursor": "V",
        "card_border": BORDER_ASCII,  # pure ASCII: + - |
    },
    "classic_casino": {
        "horse_glyph": "🐎>",
        "trail": "█",
        "empty": "░",
        "finish": "║",
        "cursor": "▼",
        "card_border": BORDER_LIGHT,
    },
    "neon_arcade": {
        "horse_glyph": "𓃗>",
        "trail": "█",
        "empty": "░",
        "finish": "║",
        "cursor": "▼",
        "card_border": BORDER_HEAVY,
    },
}


def get_theme() -> dict:
    """Load active theme. Falls back to retro_ascii in ASCII-safe mode."""
    if ascii_safe_mode():
        return THEMES["retro_ascii"]
    from openvegas.config import load_config
    config = load_config()
    name = config.get("theme", "classic_casino")
    return THEMES.get(name, THEMES["classic_casino"])
```

---

## 1. Horse Racing

### Current
- Track is 60 chars wide (feels cramped)
- Horses render as `>` on a dash track
- No color per horse, all look the same
- Confirmed: horses run head-first (position increases left-to-right, marker `>` points right)

### Revamp

**Track:** Widen to 80 chars (standard mode) or 100 (cinematic). Compact mode stays at 60.

**Horse direction:** Verified head-first. The sprite always ends with `>` to lock nose direction regardless of glyph font rendering.

**Horse sprite + colors:**

```python
# openvegas/games/horse_racing.py (additions to render logic)

HORSE_COLORS = ["red", "blue", "green", "yellow", "magenta", "cyan", "white", "bright_red"]

# Track dimensions by render mode
TRACK_WIDTHS = {"compact": 60, "standard": 80, "cinematic": 100}


def _horse_sprite(index: int, ascii_safe: bool) -> str:
    """Right-facing horse sprite with forced > nose marker."""
    color = HORSE_COLORS[index % len(HORSE_COLORS)]
    glyph = "H" if ascii_safe else "𓃗"
    # > after glyph locks head direction regardless of font rendering
    return f"[bold {color}]{glyph}[/bold {color}][bold white]>[/bold white]"


def _render_lane(pos: int, track_length: int, horse_index: int, ascii_safe: bool) -> str:
    """Render one lane: trail + horse + empty + finish line."""
    pos = max(0, min(track_length - 1, pos))
    trail_char = "=" if ascii_safe else "█"
    empty_char = "." if ascii_safe else "░"
    finish = "|" if ascii_safe else "[bold white]║[/bold white]"

    trail = f"[{HORSE_COLORS[horse_index % len(HORSE_COLORS)]}]{trail_char * pos}[/{HORSE_COLORS[horse_index % len(HORSE_COLORS)]}]"
    sprite = _horse_sprite(horse_index, ascii_safe)
    empty = empty_char * (track_length - pos - 1)
    return f"{trail}{sprite}{empty}{finish}"
```

**Regression test for head-first direction:**

```python
# tests/test_games/test_horse_direction.py

from openvegas.games.horse_racing import _horse_sprite, _render_lane, HORSE_COLORS
from openvegas.tui.theme import ascii_safe_mode
import re


def test_sprite_has_nose_marker():
    """Every sprite variant (UTF and ASCII) must end with > for head direction."""
    for ascii_safe in [True, False]:
        sprite = _horse_sprite(0, ascii_safe)
        # Strip Rich markup tags to get raw text
        raw = re.sub(r"\[.*?\]", "", sprite)
        assert raw.endswith(">"), f"Sprite '{raw}' missing > nose in ascii_safe={ascii_safe}"


def test_render_lane_nose_moves_right():
    """Assert nose marker index increases with larger positions (head-first)."""
    nose_positions = []
    for pos in [0, 10, 30, 60]:
        lane = _render_lane(pos, 80, 0, True)  # ASCII mode for easy index
        raw = re.sub(r"\[.*?\]", "", lane)
        nose_idx = raw.index(">")
        nose_positions.append(nose_idx)
    assert nose_positions == sorted(nose_positions), f"Nose not moving right: {nose_positions}"


def test_render_lane_all_colors():
    """Every horse color produces a renderable lane without error."""
    for i in range(len(HORSE_COLORS)):
        lane = _render_lane(20, 80, i, False)
        assert len(lane) > 0
        lane_ascii = _render_lane(20, 80, i, True)
        assert len(lane_ascii) > 0
```

**Results banner (shared `banners.py`):**
```
╔══════════════════════════════════════╗
║  WINNER: Null Pointer (#2)          ║
║  Odds: 2.1x  |  Your bet: WIN #2   ║
║  Payout: 21.00 $V (+11.00 net)      ║
╚══════════════════════════════════════╝
```

### Files to Modify
- `openvegas/games/horse_racing.py` — `TRACK_LENGTH` → `TRACK_WIDTHS`, add `HORSE_COLORS`, `_horse_sprite()`, `_render_lane()`, update `render()`
- `demo.py` — horse table display (add color column)
- `tests/test_games/test_horse_direction.py` — **Create** — regression test

---

## 2. Skill Shot

### Current
- Bar is 40 chars of `-` with a `V` cursor
- Zones shown as `=` in green/yellow after result

### Revamp

**Bar width:** 50 chars (standard), 40 (compact), 70 (cinematic).

**Zone rendering is deterministic:** The green/gold zone positions come from `rng.generate_outcome()` in `resolve()`. During interactive play, zones are hidden (only cursor visible). After the player stops, the **same seeded positions** are revealed in the result render. The render reads `result.outcome_data["green_zone"]` and `result.outcome_data["gold_zone"]` — never computes its own positions.

**Characters (theme-aware):**

```python
# openvegas/games/skill_shot.py (render changes)

def _render_bar(bar_width: int, position: int, green_zone: list | None,
                gold_zone: list | None, ascii_safe: bool) -> str:
    """Render the skill shot bar. Zones only shown if provided (post-result)."""
    chars = []
    empty = "." if ascii_safe else "░"
    cursor = "V" if ascii_safe else "▼"

    for i in range(bar_width):
        if i == position:
            chars.append(f"[bold white on red]{cursor}[/bold white on red]")
        elif gold_zone and gold_zone[0] <= i < gold_zone[1]:
            chars.append("[on yellow] [/on yellow]")
        elif green_zone and green_zone[0] <= i < green_zone[1]:
            chars.append("[on green] [/on green]")
        else:
            chars.append(empty)
    return "".join(chars)
```

### Files to Modify
- `openvegas/games/skill_shot.py` — `BAR_WIDTH` → width by mode, add `_render_bar()`, update `render()` and `render_interactive()`

---

## 3. Blackjack

### Current
- Cards are plain text: `"2S"`, `"KH"`

### Revamp

**Raw outcome fields preserved:** `player_cards`, `dealer_cards`, `player`, `dealer`, `result` stay exactly as-is in `resolve()`. Card art is a separate display layer.

**Shared card renderer:**

```python
# openvegas/tui/cards.py
"""Shared card rendering for blackjack, poker, baccarat."""

SUIT_SYMBOLS = {"S": "♠", "H": "♥", "D": "♦", "C": "♣"}
SUIT_ASCII = {"S": "S", "H": "H", "D": "D", "C": "C"}
RED_SUITS = {"H", "D"}


def render_card(rank: str, suit: str, ascii_safe: bool = False, hidden: bool = False) -> list[str]:
    """Return 3-line ASCII card art."""
    if hidden:
        if ascii_safe:
            return ["+---+", "|? ?|", "+---+"]
        return ["┌───┐", "│? ?│", "└───┘"]

    sym = SUIT_ASCII[suit] if ascii_safe else SUIT_SYMBOLS[suit]
    r = rank.rjust(2)

    if ascii_safe:
        return ["+---+", f"|{r}{sym}|", "+---+"]  # pure ASCII: + - |

    color = "red" if suit in RED_SUITS else "white"
    return [
        "┌───┐",
        f"│[{color}]{r}{sym}[/{color}]│",
        "└───┘",
    ]


def render_hand(
    cards: list[str], label: str = "", value: int | None = None,
    ascii_safe: bool = False, show_positions: bool = False,
) -> str:
    """Render multiple cards side-by-side.
    cards: list of "RankSuit" strings (e.g., ["KH", "9S"]).
    """
    parsed = []
    for c in cards:
        if len(c) == 2:
            rank, suit = c[0], c[1]
        elif len(c) == 3:
            rank, suit = c[:2], c[2]
        else:
            rank, suit = c[:-1], c[-1]
        parsed.append(render_card(rank, suit, ascii_safe))

    lines = []

    # Header
    header = label
    if value is not None:
        header += f" ({value})"
    if header:
        lines.append(f"  {header}")

    # Cards side-by-side (3 rows)
    for row in range(3):
        line = "  " + " ".join(card[row] for card in parsed)
        lines.append(line)

    # Position labels
    if show_positions:
        positions = "  " + " ".join(f" [{i+1}] " for i in range(len(parsed)))
        lines.append(positions)

    return "\n".join(lines)
```

**Blackjack display:**
```
  YOUR HAND (19)
  ┌───┐ ┌───┐
  │ K♥│ │ 9♠│
  └───┘ └───┘

  DEALER (17)
  ┌───┐ ┌───┐
  │ 7♦│ │ J♣│
  └───┘ └───┘
```

### Files to Modify
- `openvegas/tui/cards.py` — **Create** — shared card renderer
- `openvegas/casino/blackjack.py` — add `render_display()` method (does NOT change `resolve()` or `cards_str()`)

---

## 4. Roulette

### Current
- No visual — just returns a number

### Revamp

**Raw outcome preserved:** `result` (int), `bet_type`, `hit` (bool) stay unchanged.

```python
# openvegas/tui/roulette_renderer.py

from openvegas.tui.theme import ascii_safe_mode

RED_NUMBERS = {1,3,5,7,9,12,14,16,18,19,21,23,25,27,30,32,34,36}


def number_color(n: int) -> str:
    if n == 0:
        return "green"
    return "red" if n in RED_NUMBERS else "white"


def render_result(result: int, bet_type: str, hit: bool, payout_mult: str) -> str:
    ascii_safe = ascii_safe_mode()
    color = number_color(result)
    n_str = f"[{color}]{result}[/{color}]"
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

    return (
        f"╔═════════════════════════╗\n"
        f"║      ◎ ROULETTE ◎       ║\n"
        f"╠═════════════════════════╣\n"
        f"║      Result: {n_str:>14}    ║\n"
        f"║      Bet: {bet_display:<14}║\n"
        f"║      Hit: {hit_mark:<14}║\n"
        f"║      Payout: {payout_mult}x          ║\n"
        f"╚═════════════════════════╝"
    )
```

### Files to Modify
- `openvegas/tui/roulette_renderer.py` — **Create**
- `openvegas/casino/roulette.py` — add optional `render_display()` (does NOT change `resolve()`)

---

## 5. Slots

### Current
- Symbols are plain strings: `"7"`, `"BAR"`, `"CHERRY"`

### Revamp

**Raw outcome preserved:** `reels` list of strings and `hit` bool stay unchanged.

```python
# openvegas/tui/slots_renderer.py

from openvegas.tui.theme import ascii_safe_mode

SYMBOL_DISPLAY = {
    "7":      {"utf": "[bold red]⑦[/bold red]",  "ascii": "7"},
    "BAR":    {"utf": "[bold white]▬[/bold white]", "ascii": "B"},
    "CHERRY": {"utf": "[red]C[/red]",             "ascii": "C"},
    "LEMON":  {"utf": "[yellow]L[/yellow]",        "ascii": "L"},
    "BELL":   {"utf": "[bold yellow]b[/bold yellow]", "ascii": "b"},
    "STAR":   {"utf": "[bold cyan]★[/bold cyan]",  "ascii": "*"},
}


def _sym(name: str, ascii_safe: bool) -> str:
    d = SYMBOL_DISPLAY.get(name, {"utf": name, "ascii": name})
    return d["ascii"] if ascii_safe else d["utf"]


def render_reels(reels: list[str], hit: bool) -> str:
    """Render 3-reel slot machine display."""
    ascii_safe = ascii_safe_mode()
    s = [_sym(r, ascii_safe) for r in reels]

    if ascii_safe:
        line = f"| {s[0]} | {s[1]} | {s[2]} |"
        border = "+---+---+---+"
        return f"{border}\n{line}\n{border}"

    win_style = "[bold on green]" if hit else ""
    end_style = "[/bold on green]" if hit else ""

    return (
        f"╔═══╦═══╦═══╗\n"
        f"║{win_style} {s[0]} {end_style}║{win_style} {s[1]} {end_style}║{win_style} {s[2]} {end_style}║\n"
        f"╚═══╩═══╩═══╝"
    )
```

### Files to Modify
- `openvegas/tui/slots_renderer.py` — **Create**
- `openvegas/casino/slots.py` — add optional `render_display()` (does NOT change `resolve()`)

---

## 6. Poker

### Current
- Cards same as blackjack: `"2S"`, `"JH"`
- Hand rank is a plain string

### Revamp

**Uses shared `tui/cards.py`.** Adds position labels for hold selection.

**Hand rank banner:**

```python
# In poker render_display()
RANK_DISPLAY = {
    "royal_flush": "ROYAL FLUSH",
    "straight_flush": "STRAIGHT FLUSH",
    "four_of_a_kind": "FOUR OF A KIND",
    "full_house": "FULL HOUSE",
    "flush": "FLUSH",
    "straight": "STRAIGHT",
    "three_of_a_kind": "THREE OF A KIND",
    "two_pair": "TWO PAIR",
    "jacks_or_better": "JACKS OR BETTER",
    "nothing": "NO HAND",
}
```

### Files to Modify
- `openvegas/casino/poker.py` — add `render_display()` method with position labels
- Reuse `openvegas/tui/cards.py`

---

## 7. Baccarat

### Current
- Same plain card strings as others

### Revamp

**Uses shared `tui/cards.py`.** Side-by-side hands:

```
  PLAYER (7)            BANKER (5)
  ┌───┐ ┌───┐ ┌───┐   ┌───┐ ┌───┐
  │ 3♥│ │ 4♠│ │ K♦│   │ A♣│ │ 4♥│
  └───┘ └───┘ └───┘   └───┘ └───┘

  Result: PLAYER WINS  •  Bet: Player  •  Payout: 2x
```

### Files to Modify
- `openvegas/casino/baccarat.py` — add `render_display()` method
- Reuse `openvegas/tui/cards.py`

---

## Shared Modules

### `openvegas/tui/banners.py` — result boxes

```python
"""Shared result banner rendering."""

from openvegas.tui.theme import ascii_safe_mode, BORDER_HEAVY, BORDER_LIGHT, BORDER_ASCII


def result_banner(lines: list[str], width: int = 40) -> str:
    """Render a box around result lines."""
    ascii_safe = ascii_safe_mode()
    b = BORDER_ASCII if ascii_safe else BORDER_HEAVY

    box_lines = []
    box_lines.append(f"{b['tl']}{b['h'] * width}{b['tr']}")
    for line in lines:
        padded = line.ljust(width)[:width]
        box_lines.append(f"{b['v']} {padded} {b['v']}")
    box_lines.append(f"{b['bl']}{b['h'] * width}{b['br']}")
    return "\n".join(box_lines)
```

---

## Demo + CLI Integration

Casino games currently have no CLI/demo surface for visuals. This must be added or the rendering stays unused.

### demo.py updates

Add all 7 games to the demo menu. Each function below is complete — exact imports, signatures, game loop, and rendering calls.

```python
# demo.py — full casino demo additions
# These go alongside existing play_horse_race() and play_skill_shot()

import secrets
from decimal import Decimal

from rich.console import Console
from rich.prompt import Prompt, IntPrompt

from openvegas.rng.provably_fair import ProvablyFairRNG
from openvegas.tui.theme import ascii_safe_mode
from openvegas.tui.cards import render_hand
from openvegas.tui.banners import result_banner
from openvegas.tui.slots_renderer import render_reels
from openvegas.tui.roulette_renderer import render_result as render_roulette

console = Console()


async def play_blackjack_demo(balance: float) -> float:
    """Offline blackjack with card art."""
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

    # Player action loop
    while "hit" in game.valid_actions(state):
        action = Prompt.ask("Action", choices=["hit", "stand"], default="stand")
        state = game.apply_action(state, action, {}, rng, client_seed, 100)
        console.print(render_hand(
            cards_str(state["player"]), "YOUR HAND",
            hand_value(state["player"]), ascii_safe,
        ))

    # Resolve
    mult, data = game.resolve(state)
    console.print(render_hand(
        data["dealer_cards"], "DEALER", data["dealer"], ascii_safe,
    ))

    payout = float(Decimal(str(stake)) * mult)
    net = payout - stake
    console.print(result_banner([
        f"Result: {data['result'].upper()}",
        f"Payout: {payout:.2f} $V ({'+' if net >= 0 else ''}{net:.2f} net)",
    ]))
    return balance + net


async def play_roulette_demo(balance: float) -> float:
    """Offline roulette."""
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


async def play_slots_demo(balance: float) -> float:
    """Offline slots."""
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


async def play_poker_demo(balance: float) -> float:
    """Offline poker (5-card draw, jacks or better)."""
    from openvegas.casino.poker import PokerGame
    ascii_safe = ascii_safe_mode()

    game = PokerGame()
    rng = ProvablyFairRNG()
    rng.new_round()
    client_seed = secrets.token_hex(16)
    state = game.initial_state(rng, client_seed, 0)

    console.print("\n[bold cyan]--- POKER (Jacks or Better) ---[/bold cyan]")
    console.print(f"Balance: [bold]{balance:.2f} $V[/bold]\n")

    stake = float(Prompt.ask("Stake ($V)", default="5"))
    if stake > balance or stake <= 0:
        console.print("[red]Invalid stake.[/red]")
        return balance

    # Show hand with position numbers
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


async def play_baccarat_demo(balance: float) -> float:
    """Offline baccarat."""
    from openvegas.casino.baccarat import BaccaratGame, cards_str
    ascii_safe = ascii_safe_mode()

    game = BaccaratGame()
    rng = ProvablyFairRNG()
    rng.new_round()
    client_seed = secrets.token_hex(16)
    state = game.initial_state(rng, client_seed, 0)

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
```

**Updated main() menu with all games:**

```python
# In demo.py main()
GAME_DISPATCH = {
    "horse": play_horse_race,
    "skillshot": play_skill_shot,
    "blackjack": play_blackjack_demo,
    "roulette": play_roulette_demo,
    "slots": play_slots_demo,
    "poker": play_poker_demo,
    "baccarat": play_baccarat_demo,
}

while balance > 0:
    choice = Prompt.ask(
        "Pick a game",
        choices=list(GAME_DISPATCH.keys()) + ["quit"],
        default="horse",
    )
    if choice == "quit":
        break
    balance = await GAME_DISPATCH[choice](balance)
    # ... rest of loop
```

---

## Verification

### Automated Tests
- `pytest tests/` — all 25 existing tests still pass (rendering is additive, game logic untouched)
- `tests/test_games/test_horse_direction.py` — horse marker moves right
- `tests/test_tui/test_cards.py` — card renderer outputs correct line count, suit symbols
- `tests/test_tui/test_theme.py` — ASCII-safe mode returns correct fallbacks

### Width Matrix Testing
Run manual checks across terminal widths:

| Width | Mode | Horse Track | Skill Bar | Card Art |
|-------|------|------------|-----------|----------|
| 60 | compact | 60 chars | 40 chars | same |
| 80 | standard | 80 chars | 50 chars | same |
| 120 | cinematic | 100 chars | 70 chars | same |

### UTF / ASCII Compatibility
```bash
# Normal mode (UTF terminals)
python3 demo.py horse

# Forced ASCII-safe mode
OPENVEGAS_ASCII=1 python3 demo.py horse
```

Both must render without crashes or garbled output.

---

## Files Summary

| File | Action | Purpose |
|------|--------|---------|
| `openvegas/tui/theme.py` | **Create** | Visual system: themes, ASCII-safe mode, render modes, color tokens |
| `openvegas/tui/cards.py` | **Create** | Shared ASCII card rendering (♠♥♦♣) with hidden card support |
| `openvegas/tui/banners.py` | **Create** | Shared result box/banner rendering |
| `openvegas/tui/slots_renderer.py` | **Create** | Slot machine reel display with symbol glyphs |
| `openvegas/tui/roulette_renderer.py` | **Create** | Roulette wheel result display with number coloring |
| `tests/test_games/test_horse_direction.py` | **Create** | Regression test for head-first horse direction |
| `tests/test_tui/__init__.py` | **Create** | Test package |
| `tests/test_tui/test_cards.py` | **Create** | Card renderer format tests |
| `tests/test_tui/test_theme.py` | **Create** | Theme/ASCII-safe mode tests |
| `openvegas/games/horse_racing.py` | **Modify** | `TRACK_WIDTHS`, `HORSE_COLORS`, `_horse_sprite()`, `_render_lane()`, updated `render()` |
| `openvegas/games/skill_shot.py` | **Modify** | Width by mode, `_render_bar()`, zone reveal from seeded positions |
| `openvegas/casino/blackjack.py` | **Modify** | Add `render_display()` (raw `resolve()` output unchanged) |
| `openvegas/casino/roulette.py` | **Modify** | Add `render_display()` (raw `resolve()` output unchanged) |
| `openvegas/casino/slots.py` | **Modify** | Add `render_display()` (raw `resolve()` output unchanged) |
| `openvegas/casino/poker.py` | **Modify** | Add `render_display()` with position labels (raw output unchanged) |
| `openvegas/casino/baccarat.py` | **Modify** | Add `render_display()` side-by-side (raw output unchanged) |
| `demo.py` | **Modify** | Add all casino games to menu, use card art + banner renderers |
