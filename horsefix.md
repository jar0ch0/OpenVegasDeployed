# Horse Racing: Replay-Based Animation with Real Overtakes

## Problem

Horses never overtake each other during the race animation. The fastest horse leads from frame 1 to the finish every time.

**Root cause**: `render()` uses a smooth deterministic formula based on odds alone:

```python
target = (frame / num_frames) * track_width * (spd / 1.5)
```

`spd` is constant per horse, so relative ordering never changes. Meanwhile `resolve()` already simulates real tick-by-tick movement with RNG variation and stamina decay that produces genuine upsets — but `render()` ignores all of it.

## Approach: Resolve-Replay Checkpoints

Use `resolve()` as the source of truth. Sample horse positions at regular tick intervals during the resolve simulation, store them in `outcome_data`, and have `render()` interpolate between those real checkpoints.

This gives:
- Real overtakes and upsets (from the actual RNG simulation)
- Guaranteed winner consistency (animation ends matching `resolve()` result)
- No synthetic blend artifacts (no late-frame backward corrections)

## Changes

### File: `openvegas/games/horse_racing.py`

**1. Sample checkpoints in `resolve()` (lines 100-158)**

Every N ticks during the resolve simulation, snapshot all horse positions. Store the sampled checkpoints in `outcome_data`:

```python
async def resolve(
    self, bet: dict, rng: ProvablyFairRNG, client_seed: str, nonce: int
) -> GameResult:
    self.setup_race(rng, client_seed, nonce)

    CHECKPOINT_INTERVAL = 5  # sample every 5 ticks

    tick = 0
    finish_order: list[Horse] = []
    checkpoints: list[dict[int, float]] = []  # list of {horse_num: position}

    while len(finish_order) < self.num_horses:
        tick += 1
        for horse in self.horses:
            if horse.finished:
                continue
            variation = rng.generate_outcome(
                client_seed, nonce + 1000 + tick * self.num_horses + horse.number, 100
            )
            speed = horse.speed_base * horse.stamina * (0.8 + variation / 250)
            horse.stamina *= 0.998
            horse.position += speed

            if horse.position >= TRACK_LENGTH:
                horse.finished = True
                finish_order.append(horse)

        # Sample checkpoint (unclamped — preserve real positions for ordering)
        if tick % CHECKPOINT_INTERVAL == 0 or len(finish_order) == self.num_horses:
            checkpoints.append({
                h.number: h.position for h in self.horses
            })

    finish_order_nums = [h.number for h in finish_order]

    # Apply rank offsets to final checkpoint so visual order matches finish_order_nums
    # even when multiple horses cross the line in the same tick.
    # Use sub-TRACK_LENGTH values so they survive the (pos / TRACK_LENGTH) scaling
    # in render() without being clamped to the same pixel.
    final = checkpoints[-1]
    for rank, num in enumerate(finish_order_nums):
        final[num] = TRACK_LENGTH - rank * 1.5

    # ... payout logic unchanged ...

    return GameResult(
        # ... existing fields unchanged ...
        outcome_data={
            "finish_order": [h.name for h in finish_order],
            "finish_order_nums": [h.number for h in finish_order],
            "winner": winner.name,
            "bet_type": bet_type,
            "bet_horse": bet_horse,
            "horses": [
                {"number": h.number, "name": h.name, "odds": str(h.odds)}
                for h in self.horses
            ],
            "checkpoints": checkpoints,
        },
        # ... rest unchanged ...
    )
```

**2. Rewrite `render()` animation loop (lines 160-202)**

Interpolate between checkpoints instead of using the smooth formula. Map animation frames to checkpoint pairs, lerp between them:

```python
async def render(self, result: GameResult, console: Console):
    ascii_safe = ascii_safe_mode()
    mode = render_mode()
    track_width = TRACK_WIDTHS.get(mode, 80)
    num_frames = int(RACE_DURATION_SEC / ANIM["frame_delay"])

    horses_data = result.outcome_data["horses"]
    # Normalize checkpoint keys to int (JSON serialization may stringify them)
    checkpoints = [
        {int(k): v for k, v in cp.items()}
        for cp in result.outcome_data["checkpoints"]
    ]
    num_checkpoints = len(checkpoints)

    # Race header
    if not ascii_safe:
        console.print(f"\n[bold cyan]    ★ OPENVEGAS DERBY ★[/bold cyan]\n")
    else:
        console.print(f"\n    * OPENVEGAS DERBY *\n")

    with Live(console=console, refresh_per_second=15) as live:
        for frame in range(num_frames):
            # Map frame to checkpoint pair
            progress = frame / max(num_frames - 1, 1)
            cp_pos = progress * (num_checkpoints - 1)
            cp_lo = int(cp_pos)
            cp_hi = min(cp_lo + 1, num_checkpoints - 1)
            t = cp_pos - cp_lo  # interpolation factor 0..1

            table = Table(show_header=False, box=None, padding=(0, 0))
            table.add_column(width=16)
            table.add_column(width=track_width + 5)
            table.add_column(width=6, justify="right")

            for idx, h in enumerate(horses_data):
                num = h["number"]
                # Lerp between two checkpoints
                pos_lo = checkpoints[cp_lo][num]
                pos_hi = checkpoints[cp_hi][num]
                raw_pos = pos_lo + (pos_hi - pos_lo) * t
                # Scale from TRACK_LENGTH to track_width
                scaled = (raw_pos / TRACK_LENGTH) * (track_width - 2)
                pos = int(max(0, min(track_width - 2, scaled)))

                lane = _render_lane(pos, track_width, idx, ascii_safe)
                color = HORSE_COLORS[idx % len(HORSE_COLORS)]
                label = f"[bold {color}]#{num}[/bold {color}] {h['name'][:10]}"
                odds_str = f"[dim]{h['odds']}x[/dim]"
                table.add_row(label, lane, odds_str)

            live.update(table)
            await asyncio.sleep(ANIM["frame_delay"])

    # Results banner (unchanged)
    ...
```

Key properties:
- Positions come from the real `resolve()` simulation — overtakes are genuine
- Linear interpolation between checkpoints produces smooth movement
- No synthetic noise, surge, or late-frame blend — no backward correction artifacts
- Final checkpoint has sub-`TRACK_LENGTH` rank offsets (`TRACK_LENGTH - rank * 1.5`) so visual finish order survives scaling and clamping in `render()`, matching `finish_order_nums` even when horses cross the line in the same tick
- Checkpoint keys normalized to `int` in `render()` for JSON round-trip safety

### File: `tests/test_games/test_horse_racing.py`

Add two tests — checkpoint existence and final ordering alignment:

```python
@pytest.mark.asyncio
async def test_resolve_has_checkpoints(rng):
    game = HorseRacing(num_horses=6)
    bet = {
        "game_id": "test-1",
        "player_id": "user-1",
        "amount": 10.0,
        "type": "win",
        "horse": 1,
    }
    result = await game.resolve(bet, rng, "client_seed", 0)
    assert "checkpoints" in result.outcome_data
    assert len(result.outcome_data["checkpoints"]) > 0
    assert "finish_order_nums" in result.outcome_data
    assert len(result.outcome_data["finish_order_nums"]) == len(result.outcome_data["horses"])


@pytest.mark.asyncio
async def test_final_checkpoint_matches_finish_order(rng):
    """Final checkpoint positions must be ordered consistently with finish_order_nums."""
    game = HorseRacing(num_horses=6)
    bet = {
        "game_id": "test-1",
        "player_id": "user-1",
        "amount": 10.0,
        "type": "win",
        "horse": 1,
    }
    result = await game.resolve(bet, rng, "client_seed", 0)
    final_cp = result.outcome_data["checkpoints"][-1]
    finish_nums = result.outcome_data["finish_order_nums"]
    # Winner (index 0) should have highest position in final checkpoint
    for i in range(len(finish_nums) - 1):
        assert final_cp[finish_nums[i]] >= final_cp[finish_nums[i + 1]], (
            f"Rank {i} (horse {finish_nums[i]}) at {final_cp[finish_nums[i]]} "
            f"should be >= rank {i+1} (horse {finish_nums[i+1]}) at {final_cp[finish_nums[i+1]]}"
        )
```

### File: `tests/test_games/test_horse_direction.py`

No changes — direction tests already check `<` nose and decreasing index.

## Verification

1. `pytest tests/` — all existing tests pass + new checkpoint test
2. `python3 demo.py horse` — watch for mid-race overtakes
3. Run 3-4 races — confirm different lead-change patterns each time
4. Final positions always match the announced winner
