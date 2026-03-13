## OpenVegas UI Guided Mode Plan (Simple, Sequential, No Big Revamp)

### Summary
The goal is not a new UI framework or redesign. The goal is a **guided, click-through terminal flow** so users do not need to memorize commands.

`openvegas ui` should feel like the existing command flow, but with:
1. Radio selection for action/game/bet type.
2. Typed fields only where needed (stake, horse number, game id).
3. Step-by-step progression (Next/Back/Run).
4. Real game rendering (horse/skillshot) for both normal and demo play.

### Explicit Non-Goals
1. No full UI re-architecture.
2. No backend route redesign for this phase.
3. No new product flow changes (just easier interaction for non-technical users).

### Public Interface
Keep command surface minimal:

```bash
openvegas ui
```

No new required CLI commands. Existing commands (`openvegas play`, `openvegas deposit`, `openvegas verify`) remain unchanged.

---

## Implementation Plan

### 1) Convert current wizard to a sequential step flow
File: [/Users/stephenekwedike/Desktop/OpenVegas/openvegas/tui/wizard.py](/Users/stephenekwedike/Desktop/OpenVegas/openvegas/tui/wizard.py)

Use a small state machine so users move through one step at a time instead of filling a large form block.

```python
from enum import Enum
from dataclasses import dataclass

class Step(str, Enum):
    ACTION = "action"
    GAME = "game"
    BET_TYPE = "bet_type"
    INPUTS = "inputs"
    REVIEW = "review"
    RESULT = "result"

@dataclass
class WizardState:
    action: str = "Balance"
    game: str = "horse"
    bet_type: str = "win"
    amount: str = "1"
    horse: str = "1"
    game_id: str = ""
```

Add Next/Back controls:

```python
yield Button("Back", id="back")
yield Button("Next", id="next", variant="primary")
yield Button("Run", id="run", variant="success")
```

### 2) Show only relevant fields per chosen action
File: [/Users/stephenekwedike/Desktop/OpenVegas/openvegas/tui/wizard.py](/Users/stephenekwedike/Desktop/OpenVegas/openvegas/tui/wizard.py)

Dynamic field visibility rules:

```python
def _visible_fields_for_action(action: str) -> set[str]:
    if action in {"Balance", "History"}:
        return set()
    if action == "Deposit":
        return {"amount"}
    if action in {"Play", "Play (Demo Win)"}:
        return {"amount", "horse", "bet_type", "game"}
    if action in {"Verify", "Verify (Demo)"}:
        return {"game_id"}
    return set()
```

Validation before Run:

```python
def _validate_inputs(state: WizardState) -> str | None:
    if state.action == "Deposit":
        Decimal(state.amount)  # raises if invalid
    if state.action in {"Play", "Play (Demo Win)"}:
        Decimal(state.amount)
        if state.game == "horse":
            int(state.horse)
    if state.action in {"Verify", "Verify (Demo)"} and not state.game_id.strip():
        return "Game ID is required."
    return None
```

### 3) Keep action execution mapped directly to existing backend APIs
File: [/Users/stephenekwedike/Desktop/OpenVegas/openvegas/tui/wizard.py](/Users/stephenekwedike/Desktop/OpenVegas/openvegas/tui/wizard.py)

No new API contract needed for this phase.

```python
if state.action == "Balance":
    data = await self.client.get_balance()
elif state.action == "History":
    data = await self.client.get_history()
elif state.action == "Deposit":
    data = await self.client.create_topup_checkout(Decimal(state.amount))
elif state.action == "Play":
    data = await self.client.play_game(state.game, payload)
elif state.action == "Play (Demo Win)":
    data = await self.client.play_game_demo(state.game, payload)
elif state.action == "Verify":
    data = await self.client.verify_game(state.game_id)
elif state.action == "Verify (Demo)":
    data = await self.client.verify_demo_game(state.game_id)
```

### 4) Render games during UI play (normal + demo)
File: [/Users/stephenekwedike/Desktop/OpenVegas/openvegas/tui/wizard.py](/Users/stephenekwedike/Desktop/OpenVegas/openvegas/tui/wizard.py)

Current issue: UI only shows payout text. Fix by invoking the same renderers used by CLI while temporarily suspending Textual screen.

```python
from rich.console import Console
from openvegas.games.base import GameResult
from openvegas.games.horse_racing import HorseRacing
from openvegas.games.skill_shot import SkillShotGame

def _renderer_for(game: str):
    return {"horse": HorseRacing, "skillshot": SkillShotGame}.get(game)

def _to_game_result(data: dict, stake_fallback: Decimal) -> GameResult:
    return GameResult(
        game_id=str(data.get("game_id", "")),
        player_id="",
        bet_amount=Decimal(str(data.get("bet_amount", stake_fallback))),
        payout=Decimal(str(data.get("payout", "0"))),
        net=Decimal(str(data.get("net", "0"))),
        outcome_data=data.get("outcome_data", {}) or {},
        server_seed="",
        server_seed_hash=str(data.get("server_seed_hash", "")),
        client_seed="",
        nonce=0,
        provably_fair=bool(data.get("provably_fair", True)),
    )

renderer_cls = _renderer_for(state.game)
if renderer_cls is not None:
    gr = _to_game_result(data, Decimal(state.amount))
    with self.suspend():
        await renderer_cls().render(gr, Console())
```

Keep the suspend block minimal. If async render inside `with self.suspend()` behaves awkwardly on a target runtime, use a small helper and keep orchestration simple:

```python
async def _render_game(self, renderer_cls, gr: GameResult) -> None:
    with self.suspend():
        await renderer_cls().render(gr, Console())
```

### 5) Keep result output simple and instructional
File: [/Users/stephenekwedike/Desktop/OpenVegas/openvegas/tui/wizard.py](/Users/stephenekwedike/Desktop/OpenVegas/openvegas/tui/wizard.py)

After render, show just the key result + next action.

```python
mode = "DEMO MODE (canonical: false)" if data.get("demo_mode") else "LIVE MODE"
verify_hint = (
    f"openvegas verify {data.get('game_id')} --demo"
    if data.get("demo_mode")
    else f"openvegas verify {data.get('game_id')}"
)

self._set_output(
    f"{mode}\n"
    f"Payout: {data.get('payout')} | Net: {data.get('net')}\n"
    f"Game ID: {data.get('game_id')}\n"
    f"Verify: {verify_hint}"
)
```

### 6) Preserve blue radio-selected style and readability
File: [/Users/stephenekwedike/Desktop/OpenVegas/openvegas/tui/wizard.py](/Users/stephenekwedike/Desktop/OpenVegas/openvegas/tui/wizard.py)

```css
RadioButton.-selected {
    color: #60a5fa;
    text-style: bold;
}

#output {
    border: round #1d4ed8;
    padding: 1;
    min-height: 6;
}
```

Default selection note: constructor-level defaults like `RadioButton("Deposit", value=True)` should be verified against the pinned Textual version during implementation. The `on_mount()` fallback remains the canonical safety guard:

```python
def on_mount(self) -> None:
    self.client = OpenVegasClient()
    for rid in ("action", "game", "bet_type"):
        radio = self.query_one(f"#{rid}", RadioSet)
        if radio.pressed_button is None:
            for child in radio.children:
                if isinstance(child, RadioButton):
                    child.value = True
                    break
```

---

## Test Plan

### 1) Sequential navigation and validation
Add tests in [/Users/stephenekwedike/Desktop/OpenVegas/tests/test_tui/test_wizard_flow.py](/Users/stephenekwedike/Desktop/OpenVegas/tests/test_tui/test_wizard_flow.py)

```python
def test_next_back_transitions_are_valid(...):
    ...

def test_required_fields_block_run(...):
    ...

def test_back_next_preserves_entered_values(...):
    ...

def test_action_switch_hides_fields_without_validation_noise_and_restores_values(...):
    # 1) choose Play, fill amount/horse/type
    # 2) switch action to Verify: hidden Play-only fields must not trigger validation errors
    # 3) switch back to Play: previously entered Play values are restored
    #    (or reset only if explicitly defined by state-reset policy)
    ...
```

### 2) API mapping correctness

```python
def test_play_calls_play_game(...):
    ...

def test_demo_play_calls_play_game_demo(...):
    ...

def test_verify_demo_calls_verify_demo_game(...):
    ...
```

### 3) Renderer invocation
Add tests in [/Users/stephenekwedike/Desktop/OpenVegas/tests/test_tui/test_wizard_render.py](/Users/stephenekwedike/Desktop/OpenVegas/tests/test_tui/test_wizard_render.py)

```python
def test_play_invokes_horse_renderer(...):
    ...

def test_demo_play_invokes_horse_renderer(...):
    ...
```

### 4) Regression checks

```bash
pytest tests/test_tui tests/test_games/test_demo_mode.py tests/test_cli
```

---

## Acceptance Criteria

1. `openvegas ui` is usable as a guided step-by-step flow without memorizing commands.
2. Users can select options via radio buttons and enter only required values.
3. Play and Play (Demo Win) render actual game animations, not payout-only text.
4. Verify actions still work and show the correct verify hint.
5. No backend route changes are required for this scope.
6. Back/Next navigation preserves previously entered values across steps.
7. Switching actions (e.g., Play -> Verify -> Play) does not produce validation noise from hidden fields, and state persistence/reset behavior matches the defined rule.

## Assumptions

1. Existing backend endpoints remain stable.
2. Textual suspend integration is available in the installed Textual runtime.
3. This phase intentionally prioritizes usability and parity over advanced UI effects.
