"""Game routes — play games and verify outcomes."""

from __future__ import annotations

import secrets
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from server.middleware.auth import get_current_user
from server.services.dependencies import get_wallet, get_fraud_engine, get_db
from openvegas.games.horse_racing import HorseRacing
from openvegas.games.skill_shot import SkillShotGame
from openvegas.rng.provably_fair import ProvablyFairRNG
from openvegas.wallet.ledger import InsufficientBalance

router = APIRouter()

GAMES = {
    "horse": HorseRacing,
    "skillshot": SkillShotGame,
}


class PlayRequest(BaseModel):
    amount: float
    type: str = "win"
    horse: int | None = None
    stop_position: int | None = None


@router.post("/{game_name}/play")
async def play_game(
    game_name: str,
    req: PlayRequest,
    user: dict = Depends(get_current_user),
):
    if game_name not in GAMES:
        raise HTTPException(400, f"Unknown game: {game_name}")

    fraud = get_fraud_engine()
    try:
        await fraud.check_bet(user["user_id"])
    except Exception as e:
        raise HTTPException(429, str(e))

    wallet = get_wallet()
    db = get_db()
    game_cls = GAMES[game_name]
    game = game_cls()

    game_id = str(uuid.uuid4())
    client_seed = secrets.token_hex(16)
    nonce = 0

    bet = {
        "game_id": game_id,
        "player_id": user["user_id"],
        "amount": req.amount,
        "type": req.type,
    }
    if req.horse is not None:
        bet["horse"] = req.horse
    if req.stop_position is not None:
        bet["stop_position"] = req.stop_position

    if not await game.validate_bet(bet):
        raise HTTPException(400, "Invalid bet")

    # Escrow the bet
    from decimal import Decimal
    bet_amount = Decimal(str(req.amount))
    account_id = f"user:{user['user_id']}"
    try:
        await wallet.ensure_escrow_account(game_id)
        await wallet.place_bet(account_id, bet_amount, game_id)
    except InsufficientBalance as e:
        raise HTTPException(400, str(e))

    # Resolve
    rng = ProvablyFairRNG()
    commitment = rng.new_round()

    result = await game.resolve(bet, rng, client_seed, nonce)

    # Settle
    if result.payout > 0:
        await wallet.settle_win(account_id, result.payout, game_id)
        remaining = bet_amount - result.payout
        if remaining > 0:
            await wallet.settle_loss(game_id, remaining)
    else:
        await wallet.settle_loss(game_id, bet_amount)

    # Record game history
    import json
    await db.execute(
        """INSERT INTO game_history
           (id, user_id, game_type, bet_amount, payout, outcome_data,
            server_seed, server_seed_hash, client_seed, nonce, provably_fair)
           VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)""",
        game_id, user["user_id"], game_name,
        result.bet_amount, result.payout,
        json.dumps(result.outcome_data),
        result.server_seed, result.server_seed_hash,
        result.client_seed, result.nonce, result.provably_fair,
    )

    return {
        "game_id": game_id,
        "bet_amount": str(result.bet_amount),
        "payout": str(result.payout),
        "net": str(result.net),
        "outcome_data": result.outcome_data,
        "server_seed_hash": result.server_seed_hash,
        "provably_fair": result.provably_fair,
    }


@router.get("/verify/{game_id}")
async def verify_game(
    game_id: str,
    user: dict = Depends(get_current_user),
):
    db = get_db()
    row = await db.fetchrow(
        "SELECT * FROM game_history WHERE id = $1 AND user_id = $2",
        game_id, user["user_id"],
    )
    if not row:
        raise HTTPException(404, "Game not found")

    return {
        "game_id": str(row["id"]),
        "server_seed": row["server_seed"],
        "server_seed_hash": row["server_seed_hash"],
        "client_seed": row["client_seed"],
        "nonce": row["nonce"],
        "provably_fair": row["provably_fair"],
    }
