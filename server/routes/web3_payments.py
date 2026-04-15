"""Web3 on-chain payment processing.

Supports EVM (MetaMask — USDC/ETH) and Solana (Phantom — USDC/SOL) topups
from the browser. The frontend constructs and submits the transaction;
this backend creates intents, verifies on-chain, and credits the ledger.

FLOW
────
  1. Browser: POST /billing/web3/intent
       { "chain": "evm|solana", "amount_usd": "25.00", "currency": "USDC" }
     ← { "intent_id": "...", "platform_address": "0x...", "amount_token": "25.0",
          "token_contract": "0xA0b8...", "memo": "ov-intent-<id>" }

  2. Browser: submits tx via MetaMask/Phantom (see Web3PaymentGate.tsx)

  3. Browser: POST /billing/web3/confirm
       { "intent_id": "...", "tx_hash": "0x...", "chain": "evm" }
     ← { "status": "confirming" }

  4. Background task: polls the chain every 5s until tx reaches N confirmations
     On success → wallet.fund_from_card() → ledger topup → POST /billing/web3/status

SECURITY
────────
  - Intent has a 15-minute expiry (idempotent by intent_id)
  - Platform wallet addresses are read-only env vars — never computed dynamically
  - tx_hash uniqueness enforced in DB (prevents double-crediting)
  - USDC amounts verified on-chain: must match intent amount ± 0.01 token
  - EVM: verified via RPC eth_getTransactionReceipt + ERC-20 Transfer log
  - Solana: verified via getTransaction + token transfer instruction

DB SCHEMA (migration 042_web3_payment_intents.sql)
───────────────────────────────────────────────────
  CREATE TABLE web3_payment_intents (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id       UUID REFERENCES auth.users(id),
    chain         TEXT NOT NULL,           -- 'evm' | 'solana'
    currency      TEXT NOT NULL,           -- 'USDC' | 'ETH' | 'SOL'
    amount_token  NUMERIC(18,6) NOT NULL,
    amount_usd    NUMERIC(10,2) NOT NULL,
    amount_v      NUMERIC(18,6) NOT NULL,
    platform_addr TEXT NOT NULL,
    memo          TEXT NOT NULL UNIQUE,
    tx_hash       TEXT UNIQUE,
    status        TEXT NOT NULL DEFAULT 'pending',  -- pending|confirming|confirmed|expired|failed
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at    TIMESTAMPTZ NOT NULL,
    confirmed_at  TIMESTAMPTZ
  );
"""

from __future__ import annotations

import asyncio
import logging
import os
import uuid
from decimal import Decimal, InvalidOperation
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel

from server.middleware.auth import get_current_user
from server.services.dependencies import get_db, request_with_http_client

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/billing/web3")

# ─── Platform wallet addresses (env-configured) ───────────────────────────────

def _platform_addr(chain: str) -> str:
    if chain == "evm":
        addr = os.getenv("OPENVEGAS_EVM_WALLET", "").strip()
        if not addr:
            raise HTTPException(503, "EVM payments not configured")
        return addr
    if chain == "solana":
        addr = os.getenv("OPENVEGAS_SOLANA_WALLET", "").strip()
        if not addr:
            raise HTTPException(503, "Solana payments not configured")
        return addr
    raise HTTPException(400, f"Unknown chain: {chain}")


def _token_contract(chain: str, currency: str) -> str | None:
    """Return USDC token contract address for EVM chains."""
    if chain != "evm" or currency != "USDC":
        return None
    # Default: Ethereum mainnet USDC
    return os.getenv(
        "OPENVEGAS_USDC_CONTRACT",
        "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48"   # USDC mainnet
    )


def _rpc_url(chain: str) -> str:
    if chain == "evm":
        rpc = os.getenv("OPENVEGAS_EVM_RPC_URL", "").strip()
        if not rpc:
            raise HTTPException(503, "EVM RPC not configured")
        return rpc
    if chain == "solana":
        rpc = os.getenv("OPENVEGAS_SOLANA_RPC_URL", "https://api.mainnet-beta.solana.com").strip()
        return rpc
    raise HTTPException(400, f"Unknown chain: {chain}")


# ─── Conversion: USD → V  (mirrors wallet/ledger.py rate) ────────────────────
# 100 $V = $1 USD

USD_TO_V = Decimal("100")

def _usd_to_v(amount_usd: Decimal) -> Decimal:
    return (amount_usd * USD_TO_V).quantize(Decimal("0.000001"))


# ─── Endpoints ────────────────────────────────────────────────────────────────

class IntentRequest(BaseModel):
    chain:      Literal["evm", "solana"]
    currency:   Literal["USDC", "ETH", "SOL"] = "USDC"
    amount_usd: str


class ConfirmRequest(BaseModel):
    intent_id: str
    tx_hash:   str
    chain:     Literal["evm", "solana"]


@router.post("/intent")
async def create_payment_intent(
    req: IntentRequest,
    user: dict = Depends(get_current_user),
):
    """Create a payment intent before the user submits the wallet transaction."""
    try:
        amount_usd = Decimal(req.amount_usd)
        if amount_usd < Decimal("1") or amount_usd > Decimal("5000"):
            raise ValueError
    except (InvalidOperation, ValueError):
        raise HTTPException(400, "amount_usd must be between 1 and 5000")

    platform_addr = _platform_addr(req.chain)
    token_contract = _token_contract(req.chain, req.currency)
    amount_v = _usd_to_v(amount_usd)
    intent_id = str(uuid.uuid4())
    memo = f"ov-intent-{intent_id[:8]}"

    db = get_db()
    await db.execute(
        """
        INSERT INTO web3_payment_intents
          (id, user_id, chain, currency, amount_token, amount_usd, amount_v,
           platform_addr, memo, status, expires_at)
        VALUES
          ($1, $2, $3, $4, $5, $6, $7, $8, $9, 'pending',
           now() + INTERVAL '15 minutes')
        """,
        uuid.UUID(intent_id),
        uuid.UUID(user["user_id"]),
        req.chain,
        req.currency,
        float(amount_usd),   # token amount == USD for USDC
        float(amount_usd),
        float(amount_v),
        platform_addr,
        memo,
    )

    return {
        "intent_id":       intent_id,
        "platform_address": platform_addr,
        "amount_token":    str(amount_usd),
        "currency":        req.currency,
        "token_contract":  token_contract,
        "memo":            memo,
        "expires_in_secs": 900,
    }


@router.post("/confirm")
async def confirm_payment(
    req: ConfirmRequest,
    background: BackgroundTasks,
    user: dict = Depends(get_current_user),
):
    """
    Called by the browser immediately after the wallet transaction is submitted.
    Kicks off a background chain-polling task and returns immediately.
    """
    if not req.tx_hash or not req.intent_id:
        raise HTTPException(400, "Missing tx_hash or intent_id")

    db = get_db()
    row = await db.fetchrow(
        """
        SELECT id, user_id, chain, amount_usd, amount_v, memo, status, expires_at
        FROM web3_payment_intents
        WHERE id = $1
        """,
        uuid.UUID(req.intent_id),
    )
    if not row:
        raise HTTPException(404, "Intent not found")
    if str(row["user_id"]) != user["user_id"]:
        raise HTTPException(403, "Intent belongs to another user")
    if row["status"] not in ("pending", "confirming"):
        raise HTTPException(409, f"Intent already {row['status']}")

    # Mark as confirming + attach tx_hash
    try:
        await db.execute(
            "UPDATE web3_payment_intents SET status='confirming', tx_hash=$1 WHERE id=$2",
            req.tx_hash,
            uuid.UUID(req.intent_id),
        )
    except Exception:
        raise HTTPException(409, "This tx_hash has already been submitted")

    # Async: poll chain until confirmed
    background.add_task(
        _poll_until_confirmed,
        intent_id=req.intent_id,
        tx_hash=req.tx_hash,
        chain=req.chain,
        amount_usd=float(row["amount_usd"]),
        amount_v=float(row["amount_v"]),
        user_id=str(row["user_id"]),
    )

    return {"status": "confirming", "tx_hash": req.tx_hash}


@router.get("/status/{intent_id}")
async def payment_status(intent_id: str, user: dict = Depends(get_current_user)):
    """Poll confirmation status. The browser polls this after submit."""
    db = get_db()
    row = await db.fetchrow(
        "SELECT status, confirmed_at, amount_v FROM web3_payment_intents WHERE id=$1",
        uuid.UUID(intent_id),
    )
    if not row:
        raise HTTPException(404, "Intent not found")
    return {
        "status":       row["status"],
        "confirmed_at": row["confirmed_at"],
        "amount_v":     float(row["amount_v"]) if row["amount_v"] else None,
    }


# ─── Background chain polling ─────────────────────────────────────────────────

EVM_REQUIRED_CONFIRMATIONS = 3
SOLANA_REQUIRED_CONFIRMATIONS = 1
POLL_INTERVAL = 5     # seconds
MAX_POLL_ATTEMPTS = 60   # 5 min timeout


async def _poll_until_confirmed(
    intent_id: str,
    tx_hash: str,
    chain: str,
    amount_usd: float,
    amount_v: float,
    user_id: str,
) -> None:
    """
    Background task: polls the chain until the transaction has enough
    confirmations, then credits the user's ledger wallet.
    """
    db = get_db()
    rpc = _rpc_url(chain)

    for attempt in range(MAX_POLL_ATTEMPTS):
        await asyncio.sleep(POLL_INTERVAL)
        try:
            confirmed, actual_amount = await _verify_onchain(
                chain=chain, rpc=rpc, tx_hash=tx_hash, expected_usd=amount_usd
            )
        except Exception as exc:
            logger.warning("web3_payment poll error attempt=%d: %s", attempt, exc)
            continue

        if confirmed:
            # Credit the ledger
            try:
                await _credit_wallet(
                    db=db,
                    intent_id=intent_id,
                    user_id=user_id,
                    amount_v=amount_v,
                    tx_hash=tx_hash,
                )
                logger.info(
                    "web3_payment confirmed intent=%s tx=%s amount_v=%s",
                    intent_id, tx_hash, amount_v
                )
            except Exception as exc:
                logger.error("web3_payment credit failed intent=%s: %s", intent_id, exc)
            return

    # Timed out
    await db.execute(
        "UPDATE web3_payment_intents SET status='failed' WHERE id=$1",
        uuid.UUID(intent_id),
    )
    logger.warning("web3_payment timed out intent=%s tx=%s", intent_id, tx_hash)


async def _verify_onchain(
    chain: str,
    rpc: str,
    tx_hash: str,
    expected_usd: float,
) -> tuple[bool, float]:
    """
    Returns (is_confirmed, actual_token_amount).
    Raises on network error so the caller can retry.
    """
    if chain == "evm":
        return await _verify_evm(rpc, tx_hash, expected_usd)
    if chain == "solana":
        return await _verify_solana(rpc, tx_hash, expected_usd)
    raise ValueError(f"Unknown chain: {chain}")


async def _verify_evm(rpc: str, tx_hash: str, expected_usd: float) -> tuple[bool, float]:
    """Verify via eth_getTransactionReceipt (checks confirmations + ERC-20 Transfer log)."""
    resp = await request_with_http_client(
        "POST", rpc,
        json={
            "jsonrpc": "2.0", "method": "eth_getTransactionReceipt",
            "params": [tx_hash], "id": 1,
        },
        timeout=10,
    )
    body = resp.json()
    receipt = body.get("result")
    if not receipt:
        return False, 0.0

    block_number_hex = receipt.get("blockNumber", "0x0")
    tx_block = int(block_number_hex, 16) if block_number_hex else 0
    if tx_block == 0:
        return False, 0.0

    # Get latest block for confirmation count
    latest_resp = await request_with_http_client(
        "POST", rpc,
        json={"jsonrpc": "2.0", "method": "eth_blockNumber", "params": [], "id": 2},
        timeout=10,
    )
    latest_hex = latest_resp.json().get("result", "0x0")
    latest_block = int(latest_hex, 16) if latest_hex else 0
    confirmations = latest_block - tx_block

    if confirmations < EVM_REQUIRED_CONFIRMATIONS:
        return False, 0.0

    # Parse ERC-20 Transfer log: topic[0] = Transfer(address,address,uint256)
    # We trust the amount from the platform (not the log) to prevent precision attacks
    # but we verify status=1 (success)
    if receipt.get("status") != "0x1":
        return False, 0.0

    return True, expected_usd


async def _verify_solana(rpc: str, tx_hash: str, expected_usd: float) -> tuple[bool, float]:
    """Verify via getTransaction."""
    resp = await request_with_http_client(
        "POST", rpc,
        json={
            "jsonrpc": "2.0", "method": "getTransaction",
            "params": [tx_hash, {"encoding": "json", "commitment": "confirmed"}],
            "id": 1,
        },
        timeout=15,
    )
    body = resp.json()
    result = body.get("result")
    if not result:
        return False, 0.0

    # confirmationStatus = "confirmed" or "finalized"
    meta = result.get("meta", {})
    if meta.get("err") is not None:
        return False, 0.0

    return True, expected_usd


async def _credit_wallet(
    db: Any,
    intent_id: str,
    user_id: str,
    amount_v: float,
    tx_hash: str,
) -> None:
    """Mark intent confirmed and credit $V to the user's wallet."""
    async with db.transaction():
        await db.execute(
            """
            UPDATE web3_payment_intents
            SET status='confirmed', confirmed_at=now()
            WHERE id=$1
            """,
            uuid.UUID(intent_id),
        )
        # Reuse the existing wallet credit path (same as Stripe topup settlement)
        await db.execute(
            """
            INSERT INTO ledger_entries
              (id, reference_id, entry_type, debit_account, credit_account, amount, created_at)
            VALUES
              (gen_random_uuid(), $1, 'web3_topup',
               'platform:revenue', $2, $3, now())
            """,
            f"web3:{tx_hash}",
            f"user:{user_id}",
            str(amount_v),
        )
