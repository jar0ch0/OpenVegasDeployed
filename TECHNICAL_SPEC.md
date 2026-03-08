# OpenVegas — Technical Specification (v2 — Ship-Ready)

> Terminal-based arcade gaming platform where developers mint, wager, and redeem **$V** for AI inference across OpenAI, Anthropic, and Google Gemini.

---

## Ship Readiness

This spec addresses the following P0 blockers from v1:

| # | Blocker | Resolution |
|---|---------|-----------|
| 1 | Mint receipt verification trusted client-submitted token counts | Server-side verification via provider response metadata in a trusted path |
| 2 | "Provably fair" claim conflicts with nondeterministic live model calls in Prompt Parlay | Prompt Parlay excluded from fairness claims and Phase 1; deterministic corpus mode spec'd for Phase 3 |
| 3 | Phase 1 was Anthropic-only | Multi-provider (OpenAI/Anthropic/Gemini) from day 1 |
| 4 | Storage/auth stack mismatch | Supabase Postgres + Auth + RLS as foundation |
| 5 | Ledger lacked idempotency and overdraft protection | Strict invariants, idempotency keys, CHECK constraints |

---

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Supabase Foundation](#supabase-foundation)
3. [Currency System ($V)](#currency-system-v)
4. [Minting Engine (BYOK Proof-of-Burn)](#minting-engine-byok-proof-of-burn)
5. [Mint Modes — Solo / Split / Sponsor](#mint-modes)
6. [Wallet & Ledger (Double-Entry)](#wallet--ledger)
7. [Security & Integrity](#security--integrity)
8. [Provably Fair RNG (Commit-Reveal)](#provably-fair-rng)
9. [The 7 Games](#the-7-games)
   - 9.1 Horse Racing
   - 9.2 Plinko Drop
   - 9.3 Crash Rocket
   - 9.4 Skill Shot Timing Bar
   - 9.5 Typing Duel (PvP)
   - 9.6 Maze Runner
   - 9.7 Prompt Parlay (AI-Native) — Phase 3, non-provably-fair
10. [AI Inference Gateway](#ai-inference-gateway)
11. [Provider Catalog](#provider-catalog)
12. [Redemption Store](#redemption-store)
13. [Business Models & Unit Economics](#business-models--unit-economics)
14. [CLI UX & Commands](#cli-ux--commands)
15. [Phase Roadmap](#phase-roadmap)
16. [Test Cases & Acceptance Scenarios](#test-cases--acceptance-scenarios)
17. [Project Structure](#project-structure)

---

## Architecture Overview

```
┌──────────────────────────────────────────────────────────┐
│                     TERMINAL (CLI)                       │
│  openvegas login | mint | play | redeem | ask            │
└──────────────┬───────────────────────────┬───────────────┘
               │ WebSocket (live games)    │ REST (wallet/auth)
               │                           │
               │  Supabase JWT bearer      │
               ▼                           ▼
┌──────────────────────────────────────────────────────────┐
│                    BACKEND (FastAPI)                      │
│                                                          │
│  ┌─────────┐ ┌──────────┐ ┌───────────┐ ┌────────────┐  │
│  │  Auth    │ │  Wallet  │ │   Game    │ │    AI      │  │
│  │(Supabase│ │  Ledger  │ │  Engine   │ │  Gateway   │  │
│  │  JWT)   │ │          │ │           │ │            │  │
│  └─────────┘ └──────────┘ └───────────┘ └────────────┘  │
│                                                          │
│  ┌────────────┐ ┌───────────────┐ ┌──────────────────┐   │
│  │  Mint      │ │  Redemption   │ │  Fraud / Anti-   │   │
│  │  Service   │ │  Store        │ │  Abuse Engine    │   │
│  └────────────┘ └───────────────┘ └──────────────────┘   │
└──────────────────────────────────────────────────────────┘
               │                           │
               ▼                           ▼
┌──────────────────────────┐   ┌───────────────────────────┐
│  Supabase                │   │   Provider APIs            │
│  ├─ Postgres (ledger,    │   │   - OpenAI                 │
│  │   users, game history,│   │   - Anthropic (Claude)     │
│  │   mint events,        │   │   - Google Gemini          │
│  │   provider_catalog)   │   │                            │
│  ├─ Auth (JWT + refresh) │   │                            │
│  ├─ RLS (row isolation)  │   │                            │
│  └─ Realtime (optional)  │   │                            │
└──────────────────────────┘   └───────────────────────────┘
               │
               ▼
┌──────────────────────────┐
│  Redis                   │
│  ├─ Live game state      │
│  ├─ PvP matchmaking      │
│  ├─ Rate limit counters  │
│  └─ Fraud velocity cache │
└──────────────────────────┘
```

### Tech Stack

| Layer | Technology |
|-------|-----------|
| CLI / TUI | Python + [Rich](https://github.com/Textualize/rich) + [Textual](https://github.com/Textualize/textual) |
| Backend API | FastAPI + WebSockets |
| Database | **Supabase Postgres** (ledger, users, game history, provider catalog) |
| Auth | **Supabase Auth** (JWT issuance + refresh, RLS enforcement) |
| Cache / Realtime | Redis (sessions, live game state, rate limits, fraud velocity) |
| Task Queue | Celery + Redis (company task processing) |
| Payments | Stripe SDK |
| AI Providers | `openai`, `anthropic`, `google-generativeai` SDKs |
| Distribution | **npm** (`npm i -g openvegas`) — Node launcher package that ships prebuilt Python binaries per OS/arch. Fallback: `npx openvegas` for no-install one-offs. PyPI (`pip install openvegas`) available as secondary channel. |

---

## Supabase Foundation

All user identity and row-level isolation flows through Supabase.

### Schema (Core Tables)

```sql
-- User profiles (extends Supabase auth.users)
CREATE TABLE profiles (
    id UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
    username TEXT UNIQUE NOT NULL,
    display_name TEXT,
    tier TEXT NOT NULL DEFAULT 'free' CHECK (tier IN ('free', 'pro', 'whale')),
    default_provider TEXT DEFAULT 'openai' CHECK (default_provider IN ('openai', 'anthropic', 'gemini')),
    default_model_by_provider JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

-- Wallet accounts (one per user + system accounts)
CREATE TABLE wallet_accounts (
    account_id TEXT PRIMARY KEY,       -- "user:<uuid>", "house", "escrow:<id>", etc.
    balance NUMERIC(18,2) NOT NULL DEFAULT 0.00
        CHECK (
            -- System accounts can go negative; user accounts cannot
            account_id NOT LIKE 'user:%' OR balance >= 0
        ),
    updated_at TIMESTAMPTZ DEFAULT now()
);

-- Double-entry ledger
CREATE TABLE ledger_entries (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    debit_account TEXT NOT NULL REFERENCES wallet_accounts(account_id),
    credit_account TEXT NOT NULL REFERENCES wallet_accounts(account_id),
    amount NUMERIC(18,2) NOT NULL CHECK (amount > 0),
    entry_type TEXT NOT NULL,          -- 'mint', 'bet', 'win', 'loss', 'redeem', 'rake'
    reference_id TEXT NOT NULL,        -- game_id, mint_id, etc.
    created_at TIMESTAMPTZ DEFAULT now(),
    -- Idempotency: one mutation per (reference_id, entry_type, debit_account, credit_account).
    -- This prevents the exact same logical transfer from duplicating, while still
    -- allowing multiple participants in the same game (e.g., Player A bets on game X,
    -- then Player B bets on game X — different debit_account, so both are allowed).
    UNIQUE (reference_id, entry_type, debit_account, credit_account)
);

-- Mint challenges (server-issued, single-use, expiring)
CREATE TABLE mint_challenges (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES auth.users(id),
    nonce TEXT UNIQUE NOT NULL,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    mode TEXT NOT NULL CHECK (mode IN ('solo', 'split', 'sponsor')),
    task_prompt TEXT NOT NULL,
    company_prompt TEXT,
    target_cost_usd NUMERIC(10,4) NOT NULL,
    max_credit_v NUMERIC(18,2) NOT NULL,  -- cap on $V payout
    expires_at TIMESTAMPTZ NOT NULL,      -- 5 min TTL
    consumed BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT now()
);

-- Mint events (verified burns)
CREATE TABLE mint_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    challenge_id UUID UNIQUE NOT NULL REFERENCES mint_challenges(id),
    user_id UUID NOT NULL REFERENCES auth.users(id),
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    mode TEXT NOT NULL,
    provider_request_id TEXT NOT NULL,    -- from provider response metadata
    input_tokens INT NOT NULL,           -- from provider response (trusted)
    output_tokens INT NOT NULL,          -- from provider response (trusted)
    burn_cost_usd NUMERIC(10,6) NOT NULL,
    v_credited NUMERIC(18,2) NOT NULL,
    response_hash TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT now()
);

-- Provider catalog (centralized, hot-toggleable)
CREATE TABLE provider_catalog (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    provider TEXT NOT NULL,
    model_id TEXT NOT NULL,
    display_name TEXT NOT NULL,
    enabled BOOLEAN DEFAULT TRUE,        -- disable blocks routing instantly, no deploy
    cost_input_per_1m NUMERIC(10,4) NOT NULL,   -- our cost
    cost_output_per_1m NUMERIC(10,4) NOT NULL,
    v_price_input_per_1m NUMERIC(10,2) NOT NULL, -- user price in $V
    v_price_output_per_1m NUMERIC(10,2) NOT NULL,
    max_tokens INT DEFAULT 4096,
    updated_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE (provider, model_id)
);

-- AI inference usage log
CREATE TABLE inference_usage (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES auth.users(id),
    provider TEXT NOT NULL,
    model_id TEXT NOT NULL,
    input_tokens INT NOT NULL,
    output_tokens INT NOT NULL,
    v_cost NUMERIC(18,2) NOT NULL,
    actual_cost_usd NUMERIC(10,6) NOT NULL,
    created_at TIMESTAMPTZ DEFAULT now()
);

-- Fraud events / holds
CREATE TABLE fraud_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES auth.users(id),
    event_type TEXT NOT NULL,    -- 'velocity_breach', 'anomaly_hold', 'manual_review'
    details JSONB,
    resolved BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT now()
);
```

### Row-Level Security (RLS) Policies

```sql
-- Enable RLS on all user-facing tables
ALTER TABLE profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE wallet_accounts ENABLE ROW LEVEL SECURITY;
ALTER TABLE ledger_entries ENABLE ROW LEVEL SECURITY;
ALTER TABLE mint_challenges ENABLE ROW LEVEL SECURITY;
ALTER TABLE mint_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE inference_usage ENABLE ROW LEVEL SECURITY;

-- Profiles: users read/update own row only
CREATE POLICY profiles_select ON profiles
    FOR SELECT USING (auth.uid() = id);
CREATE POLICY profiles_update ON profiles
    FOR UPDATE USING (auth.uid() = id);

-- Wallet: users read own balance only
CREATE POLICY wallet_select ON wallet_accounts
    FOR SELECT USING (account_id = 'user:' || auth.uid()::text);
-- Writes go through service role (backend) only — no direct user writes

-- Ledger: users read own entries only
CREATE POLICY ledger_select ON ledger_entries
    FOR SELECT USING (
        debit_account = 'user:' || auth.uid()::text
        OR credit_account = 'user:' || auth.uid()::text
    );

-- Mint challenges: users read own only
CREATE POLICY mint_challenges_select ON mint_challenges
    FOR SELECT USING (user_id = auth.uid());

-- Mint events: users read own only
CREATE POLICY mint_events_select ON mint_events
    FOR SELECT USING (user_id = auth.uid());

-- Inference usage: users read own only
CREATE POLICY inference_usage_select ON inference_usage
    FOR SELECT USING (user_id = auth.uid());

-- Provider catalog: public read (anyone can see available models)
ALTER TABLE provider_catalog ENABLE ROW LEVEL SECURITY;
CREATE POLICY catalog_public_read ON provider_catalog
    FOR SELECT USING (true);
```

### Auth Flow (CLI ↔ Supabase)

```python
from supabase import create_client
import httpx
import json
from pathlib import Path

CONFIG_DIR = Path.home() / ".openvegas"
CONFIG_FILE = CONFIG_DIR / "config.json"


class SupabaseAuth:
    """Supabase Auth for CLI token issuance and refresh."""

    def __init__(self, supabase_url: str, supabase_anon_key: str):
        self.client = create_client(supabase_url, supabase_anon_key)

    async def login_with_email(self, email: str, password: str) -> dict:
        """Sign in and persist JWT locally."""
        resp = self.client.auth.sign_in_with_password({
            "email": email,
            "password": password,
        })
        self._save_session(resp.session)
        return {"user_id": resp.user.id, "email": resp.user.email}

    async def login_with_otp(self, email: str) -> None:
        """Send magic link OTP for passwordless login."""
        self.client.auth.sign_in_with_otp({"email": email})

    async def refresh_token(self) -> str:
        """Refresh expired JWT using stored refresh token."""
        session = self._load_session()
        resp = self.client.auth.refresh_session(session["refresh_token"])
        self._save_session(resp.session)
        return resp.session.access_token

    def get_bearer_token(self) -> str:
        """Get current JWT for API requests. Auto-refreshes if expired."""
        session = self._load_session()
        # In production: check exp claim and refresh if needed
        return session["access_token"]

    def _save_session(self, session) -> None:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        config = self._load_config()
        config["session"] = {
            "access_token": session.access_token,
            "refresh_token": session.refresh_token,
        }
        CONFIG_FILE.write_text(json.dumps(config, indent=2))

    def _load_session(self) -> dict:
        config = self._load_config()
        return config.get("session", {})

    def _load_config(self) -> dict:
        if CONFIG_FILE.exists():
            return json.loads(CONFIG_FILE.read_text())
        return {}
```

### FastAPI JWT Validation Middleware

```python
from fastapi import Depends, HTTPException, Request
from jose import jwt, JWTError
import os

SUPABASE_JWT_SECRET = os.environ["SUPABASE_JWT_SECRET"]


async def get_current_user(request: Request) -> dict:
    """Extract and verify Supabase JWT from Authorization header."""
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(401, "Missing bearer token")

    token = auth.removeprefix("Bearer ")
    try:
        payload = jwt.decode(
            token,
            SUPABASE_JWT_SECRET,
            algorithms=["HS256"],
            audience="authenticated",
        )
        return {
            "user_id": payload["sub"],
            "role": payload.get("role", "authenticated"),
        }
    except JWTError:
        raise HTTPException(401, "Invalid or expired token")
```

---

## Currency System ($V)

**$V** is OpenVegas's internal arcade currency — analogous to Chuck E. Cheese tokens/tickets.

### Rules

- **Non-transferable** between users (except via PvP game outcomes where the platform mediates).
- **Non-withdrawable** as cash. No cash-out path.
- **Redeemable** for: AI inference packs, cosmetics, tournament entries, terminal themes.
- **Earnable** via: purchase (Stripe), BYOK minting, game wins, daily streaks, referrals.
- **Single unified balance** per user. Provider toggle controls where inference routes, not which wallet is charged.

### $V Data Model

```python
from dataclasses import dataclass, field
from enum import Enum
from decimal import Decimal
from datetime import datetime
import uuid


class VSource(Enum):
    PURCHASE = "purchase"          # bought with cash (Stripe)
    MINT_SOLO = "mint_solo"        # BYOK proof-of-burn (solo)
    MINT_SPLIT = "mint_split"      # BYOK proof-of-burn (split — company gets work)
    MINT_SPONSOR = "mint_sponsor"  # BYOK proof-of-burn (sponsor — company primary)
    GAME_WIN = "game_win"          # won in a game
    REFERRAL = "referral"          # referral bonus
    DAILY_STREAK = "daily_streak"  # daily login reward


class VSink(Enum):
    GAME_BET = "game_bet"          # wagered in a game
    GAME_LOSS = "game_loss"        # lost in a game
    REDEEM_AI = "redeem_ai"        # redeemed for AI inference
    REDEEM_COSMETIC = "redeem_cosmetic"
    TOURNAMENT_ENTRY = "tournament_entry"
    MINT_FEE = "mint_fee"          # fee deducted during minting


@dataclass
class VBalance:
    user_id: str
    balance: Decimal = Decimal("0.00")
    lifetime_minted: Decimal = Decimal("0.00")
    lifetime_won: Decimal = Decimal("0.00")
    lifetime_spent: Decimal = Decimal("0.00")
    updated_at: datetime = field(default_factory=datetime.utcnow)
```

---

## Minting Engine (BYOK Proof-of-Burn)

The core innovation: users "burn" their own LLM tokens to mint $V. The burn isn't wasted — it produces useful output for the user (and optionally for OpenVegas).

### How It Works

The fundamental problem with BYOK minting is that if the user controls the API call, they control the response. A fabricated `raw_provider_response` JSON is trivial to forge. We solve this with a **two-tier verification model**:

**Tier 1 — Server-Proxied Mint (default, high trust)**
The user sends their API key to the backend over TLS for the duration of a single mint call. The server makes the provider call directly, so the response is unforgeably authentic. The key is used once and discarded (never stored).

**Tier 2 — Client-Side Mint with Server Verification (opt-in, for key-paranoid users)**
The user runs the call locally, then the server independently verifies the burn happened by calling the provider's usage/billing API with a read-only audit key, or by re-fetching the response via request ID. This is slower and not all providers support it equally, so it's the fallback path.

```
Tier 1 (default — server-proxied):
1. User runs: openvegas mint --amount 5.00 --provider anthropic --mode split
2. CLI reads user's API key from local config (~/.openvegas/keys.json)
3. Backend issues a challenge (nonce + task + max_credit_v + expires_at)
4. CLI sends API key + challenge_id to backend over TLS
5. BACKEND calls the provider API directly using the user's key
6. Backend observes the real response (token counts are authentic)
7. Backend discards the API key (never stored), credits $V

Tier 2 (opt-in — client-side with server audit):
1-3. Same as Tier 1
4. CLI calls the provider API LOCALLY
5. CLI posts the provider's request_id + response hash to backend
6. Backend calls provider audit/retrieval API to independently verify
   the request_id exists, matches the challenge prompt, and confirms token usage
7. Backend credits $V based on server-verified usage
```

### Mint Challenge & Verification (Hardened)

```python
import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from decimal import Decimal
from datetime import datetime, timedelta, timezone


@dataclass
class MintChallenge:
    """Server-generated challenge for a mint request."""
    id: str                   # challenge UUID
    nonce: str                # unique per-mint, prevents replay
    task_prompt: str          # the prompt to execute (user sees this)
    company_prompt: str | None  # additional company task (Split/Sponsor only)
    min_output_tokens: int    # minimum output length to prevent cheap burns
    target_cost_usd: Decimal  # approximate target burn cost
    max_credit_v: Decimal     # hard cap on $V payout for this challenge
    provider: str             # "anthropic" | "openai" | "gemini"
    model: str                # e.g. "claude-sonnet-4-20250514"
    expires_at: datetime      # challenge expires after 5 minutes


@dataclass
class MintReceipt:
    """Receipt structure depends on mint tier."""
    challenge_id: str
    nonce: str
    provider: str
    model: str
    tier: str                         # "proxied" or "client_side"
    # Tier 1 (proxied): client sends API key for one-time use
    api_key: str | None = None        # sent over TLS, used once, never stored
    # Tier 2 (client-side): client sends request_id for server audit
    provider_request_id: str | None = None
    response_hash: str | None = None  # SHA-256 of response text


def extract_usage_from_response(provider: str, raw_response: dict) -> dict:
    """
    Extract token counts from a provider response object.
    ONLY called on responses the server itself received (Tier 1),
    so the data is authentic — the server made the call.
    """
    if provider == "anthropic":
        usage = raw_response.get("usage", {})
        return {
            "input_tokens": usage.get("input_tokens", 0),
            "output_tokens": usage.get("output_tokens", 0),
            "request_id": raw_response.get("id", ""),
            "model": raw_response.get("model", ""),
        }
    elif provider == "openai":
        usage = raw_response.get("usage", {})
        return {
            "input_tokens": usage.get("prompt_tokens", 0),
            "output_tokens": usage.get("completion_tokens", 0),
            "request_id": raw_response.get("id", ""),
            "model": raw_response.get("model", ""),
        }
    elif provider == "gemini":
        meta = raw_response.get("usage_metadata", {})
        return {
            "input_tokens": meta.get("prompt_token_count", 0),
            "output_tokens": meta.get("candidates_token_count", 0),
            "request_id": raw_response.get("response_id", ""),
            "model": raw_response.get("model", ""),
        }
    else:
        raise ValueError(f"Unknown provider: {provider}")


async def execute_proxied_mint(
    api_key: str,
    challenge: MintChallenge,
) -> tuple[dict, str]:
    """
    Tier 1: Server calls provider directly using user's key.
    The response is unforgeable because the server controls the HTTP call.
    The API key is used for this one call and immediately discarded.
    """
    if challenge.provider == "anthropic":
        import anthropic
        client = anthropic.AsyncAnthropic(api_key=api_key)
        msg = await client.messages.create(
            model=challenge.model,
            max_tokens=challenge.min_output_tokens + 500,
            messages=[{"role": "user", "content": challenge.task_prompt}],
        )
        raw = msg.model_dump()
        text = msg.content[0].text
    elif challenge.provider == "openai":
        import openai
        client = openai.AsyncOpenAI(api_key=api_key)
        resp = await client.chat.completions.create(
            model=challenge.model,
            max_tokens=challenge.min_output_tokens + 500,
            messages=[{"role": "user", "content": challenge.task_prompt}],
        )
        raw = resp.model_dump()
        text = resp.choices[0].message.content
    elif challenge.provider == "gemini":
        import google.generativeai as genai
        genai.configure(api_key=api_key)
        model_obj = genai.GenerativeModel(challenge.model)
        resp = await model_obj.generate_content_async(challenge.task_prompt)
        raw = {"usage_metadata": resp.usage_metadata.__dict__, "response_id": ""}
        text = resp.text
    else:
        raise MintError(f"Unknown provider: {challenge.provider}")

    # api_key goes out of scope here — never stored, never logged
    return raw, text


async def verify_client_side_mint(
    receipt: MintReceipt,
    challenge: MintChallenge,
) -> dict:
    """
    Tier 2: Independently verify a client-side burn by calling the provider's
    audit/retrieval API using our platform credentials.

    NOT IMPLEMENTED — MVP ships Tier 1 (proxied) only.
    Tier 2 is disabled in CLI and API until provider audit endpoints are integrated.
    """
    # Provider-specific verification (future work):
    # - Anthropic: GET /v1/messages/{request_id} (requires beta header)
    # - OpenAI: check usage dashboard API or re-retrieve via request ID
    # - Gemini: limited audit support; may require billing API check
    #
    # If the provider doesn't support request-level retrieval,
    # fall back to requiring Tier 1 (proxied) for that provider.
    raise NotImplementedError(
        "Tier 2 verification is disabled in MVP. "
        "Use Tier 1 (proxied) mint. Tier 2 will ship when provider audit APIs are integrated."
    )


async def verify_and_credit_mint(
    receipt: MintReceipt,
    challenge: MintChallenge,
    wallet: "WalletService",
    catalog: "ProviderCatalog",
) -> dict:
    """
    Server-side mint verification.

    Tier 1 (proxied): Server made the API call, so response is authentic.
    Tier 2 (client-side): Server independently verifies via provider audit API.

    In both tiers, token counts come from a source the server controls or
    independently verified — never from unverified client-submitted data.
    """
    now = datetime.now(timezone.utc)

    # 1. Challenge must exist and not be consumed
    if challenge is None:
        raise MintError("Challenge not found")
    if challenge.nonce != receipt.nonce:
        raise MintError("Nonce mismatch")

    # 2. Challenge must not be expired
    if now > challenge.expires_at:
        raise MintError("Challenge expired (5 min TTL)")

    # 3. Challenge must not be already consumed (single-use)
    # (enforced by UNIQUE constraint on mint_events.challenge_id)

    # 4. Provider/model must match
    if receipt.provider != challenge.provider or receipt.model != challenge.model:
        raise MintError("Provider/model mismatch")

    # 5. Get authentic token counts (Tier 1 only in MVP)
    if receipt.tier == "proxied":
        # Server makes the call — response is unforgeable
        raw_response, response_text = await execute_proxied_mint(
            receipt.api_key, challenge
        )
        trusted = extract_usage_from_response(receipt.provider, raw_response)
    elif receipt.tier == "client_side":
        # Tier 2 is disabled in MVP — reject at the gate
        raise MintError("Client-side mint (Tier 2) is not available yet. Use proxied mint.")
    else:
        raise MintError(f"Unknown mint tier: {receipt.tier}")

    if trusted["output_tokens"] < challenge.min_output_tokens:
        raise MintError(
            f"Output too short: {trusted['output_tokens']} < {challenge.min_output_tokens}"
        )

    # 6. Calculate $V from server-verified counts
    pricing = await catalog.get_pricing(receipt.provider, receipt.model)
    input_cost = Decimal(str(trusted["input_tokens"])) * pricing["cost_input_per_1m"] / Decimal("1000000")
    output_cost = Decimal(str(trusted["output_tokens"])) * pricing["cost_output_per_1m"] / Decimal("1000000")
    total_burn_usd = input_cost + output_cost

    RATES = {
        "solo":    Decimal("0.92"),   # 8% spread — company revenue
        "split":   Decimal("1.00"),   # break-even for user; company gets task value
        "sponsor": Decimal("1.15"),   # 15% bonus — company gets primary task value
    }
    rate = RATES[challenge.mode]
    v_amount = (total_burn_usd / Decimal("0.01")) * rate
    v_amount = v_amount.quantize(Decimal("0.01"))

    # 7. Enforce max credit cap from challenge
    v_amount = min(v_amount, challenge.max_credit_v)

    # 8. Insert mint_events + credit wallet IN THE SAME TRANSACTION.
    #    The UNIQUE constraint on mint_events.challenge_id is what actually
    #    prevents replay — if this insert fails (duplicate), the wallet credit
    #    is also rolled back. Both writes must be atomic.
    mint_id = f"mint:{receipt.challenge_id}"
    response_hash = hashlib.sha256(
        (response_text if receipt.tier == "proxied" else "").encode()
    ).hexdigest()

    async with wallet.db.transaction() as tx:
        # 8a. Record the mint event (replay protection via UNIQUE challenge_id)
        await tx.execute(
            """INSERT INTO mint_events
               (challenge_id, user_id, provider, model, mode,
                provider_request_id, input_tokens, output_tokens,
                burn_cost_usd, v_credited, response_hash)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)""",
            challenge.id, challenge.user_id, receipt.provider, receipt.model,
            challenge.mode, trusted["request_id"],
            trusted["input_tokens"], trusted["output_tokens"],
            total_burn_usd, v_amount, response_hash,
        )

        # 8b. Mark challenge as consumed
        await tx.execute(
            "UPDATE mint_challenges SET consumed = TRUE WHERE id = $1",
            challenge.id,
        )

        # 8c. Credit user wallet — pass tx so wallet._execute doesn't open
        #     a nested transaction (single service-owned tx for all 3 writes)
        await wallet.mint(
            user_id=challenge.user_id,
            amount=v_amount,
            mint_id=mint_id,
            tx=tx,
        )

    return {
        "v_credited": str(v_amount),
        "cost_usd": str(total_burn_usd),
        "input_tokens": trusted["input_tokens"],
        "output_tokens": trusted["output_tokens"],
        "provider_request_id": trusted["request_id"],
    }


class MintError(Exception):
    pass
```

### CLI Minting Flow

```python
import httpx
import uuid
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm

console = Console()

RATES_DISPLAY = {"solo": "standard rate", "split": "+8% $V bonus", "sponsor": "+15% $V bonus"}


async def mint_v(amount_usd: float, provider: str, mode: str):
    """Full mint flow — runs locally, posts receipt to backend."""
    config = load_config()  # reads ~/.openvegas/keys.json + session
    api_key = config["providers"][provider]["api_key"]
    auth = SupabaseAuth(config["supabase_url"], config["supabase_anon_key"])
    bearer = auth.get_bearer_token()

    # 1. Get challenge from OpenVegas backend
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{config['backend_url']}/mint/challenge",
            json={"amount_usd": amount_usd, "provider": provider, "mode": mode},
            headers={"Authorization": f"Bearer {bearer}"},
        )
        challenge = resp.json()

    # 2. Show disclosure to user BEFORE burning
    console.print(Panel(
        f"[bold]Mint Mode:[/bold] {mode.title()} Mint ({RATES_DISPLAY[mode]})\n"
        f"[bold]Provider:[/bold] {provider} ({challenge['model']})\n"
        f"[bold]Estimated cost:[/bold] ~${amount_usd:.2f} on your account\n"
        f"[bold]Token budget:[/bold] ~{challenge['min_output_tokens']} output tokens\n"
        f"[bold]Max $V credit:[/bold] {challenge['max_credit_v']} $V\n"
        f"[bold]Expires:[/bold] {challenge['expires_at']}\n"
        f"[bold]Your task:[/bold] {challenge['task_prompt'][:80]}...\n"
        + (f"[bold]Company task:[/bold] {challenge.get('company_task_category', 'N/A')}\n"
           f"[dim]Data policy: no local files sent; only the task prompt below.[/dim]\n"
           if mode != "solo" else ""),
        title="OpenVegas Mint",
        border_style="green",
    ))

    if not Confirm.ask("Proceed with mint?"):
        console.print("[yellow]Mint cancelled.[/yellow]")
        return

    # 3. Send API key to backend for server-proxied mint (Tier 1)
    # Key is sent over TLS, used for one call, then discarded server-side.
    # The server makes the provider call directly so the response is authentic.
    console.print("[dim]Sending key to server for proxied mint (key used once, never stored)...[/dim]")

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{config['backend_url']}/mint/verify",
            json={
                "challenge_id": challenge["id"],
                "nonce": challenge["nonce"],
                "provider": provider,
                "model": challenge["model"],
                "tier": "proxied",
                "api_key": api_key,  # TLS-encrypted, used once, discarded
            },
            headers={"Authorization": f"Bearer {bearer}"},
        )
        result = resp.json()

    console.print(
        f"[bold green]Minted {result['v_credited']} $V[/bold green] "
        f"(burned ~${float(result['cost_usd']):.4f} on {provider})"
    )
```

---

## Mint Modes

### Solo Mint (Default)

The burned tokens produce **only user-facing output**: code review, test generation, log analysis, etc.

```python
SOLO_TASK_TEMPLATES = [
    "Review this git diff and suggest improvements:\n{diff}",
    "Generate unit tests for this function:\n{code}",
    "Explain this error and suggest a fix:\n{traceback}",
    "Summarize these logs and flag anomalies:\n{logs}",
    "Refactor this code for readability:\n{code}",
]
```

### Split Mint (Opt-In, +5–10% $V Bonus)

User gets their output **AND** a second (clearly labeled) company task runs in the same call budget.

```python
SPLIT_TASK_TEMPLATES = [
    # Company tasks — safe, non-creepy, disclosed
    {
        "category": "model_evaluation",
        "prompt": "Rate the following AI output on accuracy (1-5) and explain: {sample}",
    },
    {
        "category": "synthetic_content",
        "prompt": "Generate 5 creative horse names and ASCII art sprites for a racing game.",
    },
    {
        "category": "prompt_quality",
        "prompt": "Rewrite this prompt to be clearer and more specific: {prompt}",
    },
    {
        "category": "latency_benchmark",
        "prompt": "Respond with exactly 500 words about terminal UI best practices.",
    },
]
```

### Sponsor Mint (Opt-In, +15–25% $V Bonus)

Burn is used **primarily** for company work. User gets a small utility output + a higher $V payout.

```python
SPONSOR_TASK_TEMPLATES = [
    {
        "category": "red_team_eval",
        "prompt": "Attempt to make this prompt produce unsafe output (for safety testing): {prompt}",
        "user_output": "Brief summary of prompt robustness findings",
    },
    {
        "category": "dataset_generation",
        "prompt": "Generate 20 diverse betting scenarios with odds for horse racing simulation.",
        "user_output": "3 fun horse racing facts",
    },
    {
        "category": "quality_scoring",
        "prompt": "Score these 10 AI outputs on a rubric (helpfulness, accuracy, safety): {outputs}",
        "user_output": "AI quality trends summary",
    },
]
```

---

## Wallet & Ledger

Double-entry bookkeeping with strict invariants.

### Invariants

1. **No negative user balances** — enforced by `CHECK (balance >= 0)` on user accounts in Postgres.
2. **Atomic transactions** — every ledger entry executes inside a single Postgres transaction.
3. **Idempotency** — `UNIQUE (reference_id, entry_type, debit_account, credit_account)` prevents duplicate mutations. The constraint is on the logical transfer itself (e.g., "user:abc bets on game:xyz"), not on a caller-supplied key. This allows multiple players to bet on the same PvP game (different `debit_account`), while still blocking the same player from double-betting.
4. **Double-entry balance** — sum of all debits = sum of all credits (auditable).

```python
from enum import Enum
from decimal import Decimal
from datetime import datetime
from dataclasses import dataclass, field
import uuid


class AccountType(Enum):
    USER = "user"
    HOUSE = "house"           # house bankroll (games)
    MINT_RESERVE = "mint_res" # mint issuance source
    RAKE_REVENUE = "rake_rev" # PvP rake revenue
    STORE = "store"           # redemption store


@dataclass
class LedgerEntry:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    debit_account: str = ""    # account being debited (balance decreases)
    credit_account: str = ""   # account being credited (balance increases)
    amount: Decimal = Decimal("0")
    entry_type: str = ""       # "mint", "bet", "win", "loss", "redeem", "rake"
    reference_id: str = ""     # game_id, mint_id, etc.
    # Idempotency enforced by UNIQUE(reference_id, entry_type) in DB —
    # no caller-supplied key needed; the logical operation IS the key.
    created_at: datetime = field(default_factory=datetime.utcnow)


class WalletService:
    """Double-entry ledger for $V transactions with strict invariants."""

    def __init__(self, db):
        self.db = db

    async def mint(self, user_id: str, amount: Decimal, mint_id: str, *, tx=None):
        """Credit user wallet from mint (new $V enters system).
        Pass tx= to run within an existing transaction (e.g., verify_and_credit_mint)."""
        entry = LedgerEntry(
            debit_account="mint_reserve",
            credit_account=f"user:{user_id}",
            amount=amount,
            entry_type="mint",
            reference_id=mint_id,
        )
        await self._execute(entry, tx=tx)

    async def place_bet(self, user_id: str, amount: Decimal, game_id: str):
        """Move $V from user to escrow for a game."""
        entry = LedgerEntry(
            debit_account=f"user:{user_id}",
            credit_account=f"escrow:{game_id}",
            amount=amount,
            entry_type="bet",
            reference_id=game_id,
        )
        await self._execute(entry)

    async def settle_win(self, user_id: str, payout: Decimal, game_id: str):
        """Pay out winnings from escrow to user."""
        entry = LedgerEntry(
            debit_account=f"escrow:{game_id}",
            credit_account=f"user:{user_id}",
            amount=payout,
            entry_type="win",
            reference_id=game_id,
        )
        await self._execute(entry)

    async def settle_loss(self, game_id: str, amount: Decimal):
        """Move lost bet from escrow to house."""
        entry = LedgerEntry(
            debit_account=f"escrow:{game_id}",
            credit_account="house",
            amount=amount,
            entry_type="loss",
            reference_id=game_id,
        )
        await self._execute(entry)

    async def pvp_rake(self, pot: Decimal, game_id: str) -> Decimal:
        """Take platform rake from PvP pot. Returns rake amount."""
        rake = (pot * Decimal("0.03")).quantize(Decimal("0.01"))  # 3% rake
        entry = LedgerEntry(
            debit_account=f"escrow:{game_id}",
            credit_account="rake_revenue",
            amount=rake,
            entry_type="rake",
            reference_id=game_id,
        )
        await self._execute(entry)
        return rake

    async def get_balance(self, user_id: str) -> Decimal:
        """Get current $V balance for a user."""
        return await self.db.get_account_balance(f"user:{user_id}")

    async def _execute(self, entry: LedgerEntry, *, tx=None):
        """
        Atomically execute a ledger entry.

        If `tx` is provided, runs within that existing transaction (caller owns the tx).
        If `tx` is None, opens its own transaction (self-contained mode).

        This avoids nested transaction ambiguity: callers like verify_and_credit_mint
        that need to bundle multiple writes in one tx pass their tx in, while simple
        standalone calls (e.g., place_bet) let _execute manage its own.

        Invariants enforced:
        - Postgres CHECK constraint prevents user balances going negative.
        - UNIQUE(reference_id, entry_type, debit_account, credit_account)
          prevents the same logical transfer from duplicating, while allowing
          multiple participants (different accounts) in the same game.
        """
        async def _do(conn):
            await conn.insert_entry(entry)
            await conn.adjust_balance(entry.debit_account, -entry.amount)
            await conn.adjust_balance(entry.credit_account, entry.amount)

        try:
            if tx is not None:
                # Caller owns the transaction — execute within it
                await _do(tx)
            else:
                # Self-contained — open our own transaction
                async with self.db.transaction() as own_tx:
                    await _do(own_tx)
        except CheckViolation:
            raise InsufficientBalance(
                f"Account {entry.debit_account} has insufficient balance for {entry.amount} $V"
            )
        except UniqueViolation:
            # Idempotent — this entry was already processed, silently succeed
            pass


class InsufficientBalance(Exception):
    pass
```

---

## Security & Integrity

### Mint Integrity (Phase 1 — Required)

| Control | Implementation |
|---------|---------------|
| **Don't trust client data for payout** | **Tier 1 (default):** server makes the provider API call itself using user's key over TLS — response is unforgeable. **Tier 2 (fallback):** server independently verifies via provider audit API. In neither tier does the server trust a client-submitted response object. |
| **API key handling** | Tier 1: key sent over TLS, used for one call, immediately discarded (never stored, never logged) |
| **Challenge expiry** | 5-minute TTL (`expires_at`), rejected if expired |
| **Single-use nonce** | `UNIQUE` constraint on `mint_events.challenge_id` |
| **Replay protection** | `mint_events` insert (UNIQUE on `challenge_id`) + wallet credit happen in the same DB transaction — if either fails, both roll back. Ledger UNIQUE constraint provides a second layer. |
| **Max credit cap** | `max_credit_v` on challenge limits payout even if burn is large |
| **Provider/model match** | Challenge locks provider + model; receipt must match |

### Anti-Abuse (Phase 1 — Required)

```python
from dataclasses import dataclass
from datetime import timedelta


@dataclass
class AbuseThresholds:
    """Per-user rate limits enforced in Phase 1."""
    # Minting
    max_mints_per_hour: int = 10
    max_mints_per_day: int = 50
    max_mint_usd_per_day: float = 100.00

    # Gaming
    max_bets_per_minute: int = 20
    max_bets_per_hour: int = 200

    # Inference
    max_infer_requests_per_minute: int = 30
    max_infer_v_per_hour: float = 500.00

    # IP / device
    max_accounts_per_ip: int = 3
    suspicious_ip_cooldown: timedelta = timedelta(hours=1)


class FraudEngine:
    """Velocity checks + anomaly scoring. Runs in Phase 1."""

    def __init__(self, redis, db, thresholds: AbuseThresholds = None):
        self.redis = redis
        self.db = db
        self.thresholds = thresholds or AbuseThresholds()

    async def check_mint(self, user_id: str, amount_usd: float, ip: str) -> bool:
        """Returns True if mint is allowed, raises if blocked."""
        # Velocity: mints per hour
        key_hour = f"fraud:mint:hour:{user_id}"
        count = await self.redis.incr(key_hour)
        if count == 1:
            await self.redis.expire(key_hour, 3600)
        if count > self.thresholds.max_mints_per_hour:
            await self._flag(user_id, "velocity_breach", {"type": "mint_hourly", "count": count})
            raise AbuseBlocked("Mint rate limit exceeded (hourly)")

        # Velocity: mints per day
        key_day = f"fraud:mint:day:{user_id}"
        count_day = await self.redis.incr(key_day)
        if count_day == 1:
            await self.redis.expire(key_day, 86400)
        if count_day > self.thresholds.max_mints_per_day:
            await self._flag(user_id, "velocity_breach", {"type": "mint_daily", "count": count_day})
            raise AbuseBlocked("Mint rate limit exceeded (daily)")

        # Daily USD cap
        key_usd = f"fraud:mint:usd:{user_id}"
        total = await self.redis.incrbyfloat(key_usd, amount_usd)
        if float(total) == amount_usd:
            await self.redis.expire(key_usd, 86400)
        if float(total) > self.thresholds.max_mint_usd_per_day:
            await self._flag(user_id, "velocity_breach", {"type": "mint_usd_daily", "total": total})
            raise AbuseBlocked("Daily mint USD cap exceeded")

        # Multi-account per IP
        key_ip = f"fraud:ip:accounts:{ip}"
        await self.redis.sadd(key_ip, user_id)
        await self.redis.expire(key_ip, 86400)
        ip_accounts = await self.redis.scard(key_ip)
        if ip_accounts > self.thresholds.max_accounts_per_ip:
            await self._flag(user_id, "anomaly_hold", {"type": "multi_account_ip", "ip": ip})
            raise AbuseBlocked("Suspicious multi-account activity")

        return True

    async def check_bet(self, user_id: str) -> bool:
        """Rate limit bets."""
        key = f"fraud:bet:min:{user_id}"
        count = await self.redis.incr(key)
        if count == 1:
            await self.redis.expire(key, 60)
        if count > self.thresholds.max_bets_per_minute:
            raise AbuseBlocked("Bet rate limit exceeded")
        return True

    async def _flag(self, user_id: str, event_type: str, details: dict):
        """Record fraud event for review."""
        await self.db.execute(
            "INSERT INTO fraud_events (user_id, event_type, details) VALUES ($1, $2, $3)",
            user_id, event_type, json.dumps(details),
        )


class AbuseBlocked(Exception):
    pass
```

### Ledger Integrity

| Invariant | Enforcement |
|-----------|-------------|
| No negative user balances | `CHECK (balance >= 0)` on `wallet_accounts` for `user:*` rows |
| Atomic transactions | Single Postgres `BEGIN...COMMIT` per ledger entry |
| Idempotency | `UNIQUE (reference_id, entry_type, debit_account, credit_account)` on `ledger_entries` — one mutation per logical transfer, no caller-controlled bypass, but PvP-safe (multiple players can bet on same game) |
| Auditability | All balance changes backed by a ledger entry; sum(debits) = sum(credits) |

---

## Provably Fair RNG

Every **non-AI** game outcome is verifiable after the fact using commit-reveal.

> **Note:** Prompt Parlay involves live nondeterministic model calls and is explicitly **not** covered by provably fair claims. See [Section 9.7](#97--prompt-parlay-ai-native--phase-3-non-provably-fair).

```python
import hashlib
import hmac
import secrets


class ProvablyFairRNG:
    """Commit-reveal scheme so users can verify game outcomes."""

    def __init__(self):
        self.server_seed: str = ""
        self.server_seed_hash: str = ""  # committed to user BEFORE bet

    def new_round(self) -> str:
        """Generate server seed and return its hash (commitment)."""
        self.server_seed = secrets.token_hex(32)
        self.server_seed_hash = hashlib.sha256(
            self.server_seed.encode()
        ).hexdigest()
        return self.server_seed_hash  # send this to user before they bet

    def generate_outcome(self, client_seed: str, nonce: int, max_value: int) -> int:
        """
        Deterministic outcome from server_seed + client_seed + nonce.
        User can reproduce this after reveal.
        """
        message = f"{client_seed}:{nonce}"
        h = hmac.new(
            self.server_seed.encode(),
            message.encode(),
            hashlib.sha256,
        ).hexdigest()

        # Convert first 8 hex chars to int, map to [0, max_value)
        raw = int(h[:8], 16)
        return raw % max_value

    def reveal(self) -> str:
        """Reveal server seed so user can verify."""
        return self.server_seed

    @staticmethod
    def verify(server_seed: str, committed_hash: str) -> bool:
        """User-side verification that the seed matches the commitment."""
        return hashlib.sha256(server_seed.encode()).hexdigest() == committed_hash


# Usage in a game round:
#
# 1. Server: hash = rng.new_round()         -> send hash to client
# 2. Client: submits client_seed + bet
# 3. Server: outcome = rng.generate_outcome(client_seed, nonce, max_val)
# 4. Server: resolves game, sends result + rng.reveal()
# 5. Client: ProvablyFairRNG.verify(revealed_seed, hash) -> True
# 6. Client: recomputes outcome locally -> matches server result
```

---

## The 7 Games

All games share a common interface:

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass
from decimal import Decimal


@dataclass
class GameResult:
    game_id: str
    player_id: str
    bet_amount: Decimal
    payout: Decimal
    net: Decimal              # payout - bet
    outcome_data: dict        # game-specific result details
    server_seed: str          # revealed for verification
    server_seed_hash: str     # pre-committed hash
    client_seed: str
    nonce: int
    provably_fair: bool = True  # False for Prompt Parlay


class BaseGame(ABC):
    """Interface all OpenVegas games implement."""

    name: str
    rtp: Decimal  # return-to-player (e.g., 0.97 = 97%)

    @abstractmethod
    async def validate_bet(self, bet: dict) -> bool:
        """Validate bet structure and limits."""
        ...

    @abstractmethod
    async def resolve(self, bet: dict, rng: ProvablyFairRNG, client_seed: str, nonce: int) -> GameResult:
        """Resolve the game outcome."""
        ...

    @abstractmethod
    async def render(self, result: GameResult, console) -> None:
        """Render the TUI animation for this game."""
        ...
```

---

### 9.1 — Horse Racing

**The flagship game.** 6-10 horses on an ASCII track. Users bet on win/place/show. Hybrid RNG + timed boosts (skill element). **Provably fair.**

```python
import asyncio
import random
from dataclasses import dataclass, field
from decimal import Decimal
from rich.console import Console
from rich.live import Live
from rich.table import Table
from rich.text import Text


@dataclass
class Horse:
    name: str
    number: int
    odds: Decimal
    position: float = 0.0
    speed_base: float = 0.0
    stamina: float = 1.0
    finished: bool = False
    emoji: str = "🐎"


HORSE_NAMES = [
    "Thunder Byte", "Null Pointer", "Stack Overflow", "Segfault Sally",
    "Cache Miss", "Race Condition", "Deadlock Dan", "Heap Corruption",
    "Buffer Blitz", "Async Awaiter",
]

TRACK_LENGTH = 60  # characters


class HorseRacing(BaseGame):
    name = "horse_racing"
    rtp = Decimal("0.95")  # 95% RTP

    def __init__(self, num_horses: int = 8):
        self.num_horses = num_horses
        self.horses: list[Horse] = []

    def setup_race(self, rng: ProvablyFairRNG, client_seed: str, nonce: int):
        """Initialize horses with RNG-seeded base speeds."""
        self.horses = []
        for i in range(self.num_horses):
            # Deterministic speed from provably fair RNG
            speed_val = rng.generate_outcome(client_seed, nonce + i, 1000)
            base_speed = 0.5 + (speed_val / 1000) * 1.5  # range [0.5, 2.0]

            # Odds inversely proportional to speed (faster = lower odds)
            raw_odds = Decimal("2.0") + Decimal(str((1000 - speed_val) / 200))

            self.horses.append(Horse(
                name=HORSE_NAMES[i],
                number=i + 1,
                odds=raw_odds.quantize(Decimal("0.1")),
                speed_base=base_speed,
            ))

    async def resolve(self, bet: dict, rng: ProvablyFairRNG, client_seed: str, nonce: int) -> GameResult:
        """Simulate the full race and determine payouts."""
        self.setup_race(rng, client_seed, nonce)

        # Simulate race tick-by-tick (deterministic)
        tick = 0
        finish_order = []
        while len(finish_order) < self.num_horses:
            tick += 1
            for horse in self.horses:
                if horse.finished:
                    continue
                # Speed varies per tick (deterministic from RNG)
                variation = rng.generate_outcome(
                    client_seed, nonce + 1000 + tick * self.num_horses + horse.number, 100
                )
                speed = horse.speed_base * horse.stamina * (0.8 + variation / 250)
                horse.stamina *= 0.998  # fatigue
                horse.position += speed

                if horse.position >= TRACK_LENGTH:
                    horse.finished = True
                    finish_order.append(horse)

        # Determine payout
        winner = finish_order[0]
        bet_type = bet["type"]       # "win", "place", "show"
        bet_horse = bet["horse"]     # horse number
        bet_amount = Decimal(str(bet["amount"]))

        payout = Decimal("0")
        if bet_type == "win" and bet_horse == winner.number:
            payout = bet_amount * winner.odds
        elif bet_type == "place" and bet_horse in [h.number for h in finish_order[:2]]:
            placed_horse = next(h for h in self.horses if h.number == bet_horse)
            payout = bet_amount * (placed_horse.odds / 2)
        elif bet_type == "show" and bet_horse in [h.number for h in finish_order[:3]]:
            showed_horse = next(h for h in self.horses if h.number == bet_horse)
            payout = bet_amount * (showed_horse.odds / 3)

        return GameResult(
            game_id=bet["game_id"],
            player_id=bet["player_id"],
            bet_amount=bet_amount,
            payout=payout.quantize(Decimal("0.01")),
            net=(payout - bet_amount).quantize(Decimal("0.01")),
            outcome_data={
                "finish_order": [h.name for h in finish_order],
                "winner": winner.name,
                "bet_type": bet_type,
                "bet_horse": bet_horse,
            },
            server_seed=rng.reveal(),
            server_seed_hash=rng.server_seed_hash,
            client_seed=client_seed,
            nonce=nonce,
            provably_fair=True,
        )

    async def render(self, result: GameResult, console: Console):
        """Animate the horse race in terminal."""
        positions = {h.number: 0.0 for h in self.horses}

        with Live(console=console, refresh_per_second=15) as live:
            for frame in range(80):
                table = Table(show_header=False, box=None, padding=(0, 0))
                table.add_column(width=14)
                table.add_column(width=TRACK_LENGTH + 5)

                for horse in self.horses:
                    # Animate towards final position
                    target = min(TRACK_LENGTH, (frame / 80) * TRACK_LENGTH *
                                 (horse.speed_base / 1.5))
                    positions[horse.number] = min(target, TRACK_LENGTH)
                    pos = int(positions[horse.number])

                    track = "░" * pos + horse.emoji + "░" * (TRACK_LENGTH - pos) + "│"
                    label = f"#{horse.number} {horse.name[:10]}"
                    table.add_row(label, track)

                live.update(table)
                await asyncio.sleep(0.05)

        # Show results
        console.print(f"\n[bold yellow]Winner: {result.outcome_data['winner']}[/bold yellow]")
        if result.net > 0:
            console.print(f"[bold green]You won {result.payout} $V! (+{result.net} net)[/bold green]")
        else:
            console.print(f"[red]You lost {result.bet_amount} $V.[/red]")
```

---

### 9.2 — Plinko Drop

Ball drops through pegs; landing slot determines multiplier. **Provably fair.**

```python
import asyncio
from decimal import Decimal
from rich.console import Console
from rich.live import Live
from rich.text import Text


class PlinkoGame(BaseGame):
    name = "plinko"
    rtp = Decimal("0.97")

    ROWS = 12
    # Multipliers for each slot (symmetric, house edge baked in)
    MULTIPLIERS = [
        Decimal("8.0"), Decimal("3.0"), Decimal("1.5"), Decimal("1.1"),
        Decimal("0.5"), Decimal("0.3"), Decimal("0.3"), Decimal("0.5"),
        Decimal("1.1"), Decimal("1.5"), Decimal("3.0"), Decimal("8.0"),
        Decimal("0.0"),  # extra slot for 12 rows -> 13 slots
    ]

    async def resolve(self, bet: dict, rng: ProvablyFairRNG, client_seed: str, nonce: int) -> GameResult:
        bet_amount = Decimal(str(bet["amount"]))
        position = self.ROWS // 2  # start center

        path = [position]
        for row in range(self.ROWS):
            direction = rng.generate_outcome(client_seed, nonce + row, 2)
            position += (1 if direction else -1)
            position = max(0, min(self.ROWS, position))
            path.append(position)

        slot = position
        multiplier = self.MULTIPLIERS[slot]
        payout = (bet_amount * multiplier).quantize(Decimal("0.01"))

        return GameResult(
            game_id=bet["game_id"],
            player_id=bet["player_id"],
            bet_amount=bet_amount,
            payout=payout,
            net=payout - bet_amount,
            outcome_data={"path": path, "slot": slot, "multiplier": str(multiplier)},
            server_seed=rng.reveal(),
            server_seed_hash=rng.server_seed_hash,
            client_seed=client_seed,
            nonce=nonce,
            provably_fair=True,
        )

    async def render(self, result: GameResult, console: Console):
        """Animate the plinko ball dropping through pegs."""
        path = result.outcome_data["path"]

        with Live(console=console, refresh_per_second=8) as live:
            for row_idx, pos in enumerate(path):
                lines = []
                for r in range(self.ROWS + 1):
                    pegs = "  ".join("*" for _ in range(self.ROWS + 1))
                    if r == row_idx:
                        chars = list(pegs)
                        ball_pos = pos * 3  # spacing
                        if ball_pos < len(chars):
                            chars[ball_pos] = "O"
                        pegs = "".join(chars)
                    lines.append(f"  {pegs}")

                slots = "  ".join(f"{m}x" for m in self.MULTIPLIERS[:self.ROWS + 1])
                lines.append(f"\n  {slots}")

                live.update(Text("\n".join(lines)))
                await asyncio.sleep(0.2)

        multiplier = result.outcome_data["multiplier"]
        console.print(f"\n[bold]Landed on slot {result.outcome_data['slot']} ({multiplier}x)[/bold]")
```

---

### 9.3 — Crash Rocket

Multiplier climbs until it crashes. Cash out in time. **Provably fair.**

```python
import asyncio
import math
from decimal import Decimal
from rich.console import Console
from rich.live import Live
from rich.text import Text


class CrashGame(BaseGame):
    name = "crash"
    rtp = Decimal("0.96")

    async def resolve(self, bet: dict, rng: ProvablyFairRNG, client_seed: str, nonce: int) -> GameResult:
        bet_amount = Decimal(str(bet["amount"]))
        cashout_target = Decimal(str(bet.get("cashout_at", "2.0")))

        # Determine crash point from RNG
        raw = rng.generate_outcome(client_seed, nonce, 10000)
        if raw == 0:
            crash_point = Decimal("1.00")
        else:
            crash_point = Decimal(str(
                max(1.0, 0.96 * 10000 / raw)  # 4% house edge
            )).quantize(Decimal("0.01"))

        won = cashout_target <= crash_point
        payout = (bet_amount * cashout_target) if won else Decimal("0")

        return GameResult(
            game_id=bet["game_id"],
            player_id=bet["player_id"],
            bet_amount=bet_amount,
            payout=payout.quantize(Decimal("0.01")),
            net=(payout - bet_amount).quantize(Decimal("0.01")),
            outcome_data={
                "crash_point": str(crash_point),
                "cashout_at": str(cashout_target),
                "won": won,
            },
            server_seed=rng.reveal(),
            server_seed_hash=rng.server_seed_hash,
            client_seed=client_seed,
            nonce=nonce,
            provably_fair=True,
        )

    async def render(self, result: GameResult, console: Console):
        """Animate the rocket climbing and crashing."""
        crash_point = float(result.outcome_data["crash_point"])
        cashout_at = float(result.outcome_data["cashout_at"])
        won = result.outcome_data["won"]

        with Live(console=console, refresh_per_second=20) as live:
            multiplier = 1.0
            while multiplier < crash_point and multiplier < 50:
                bar_len = int(multiplier * 8)
                bar = "=" * bar_len

                color = "green" if multiplier < cashout_at else "yellow"
                text = Text()
                text.append(f"  >> {multiplier:.2f}x  ", style=f"bold {color}")
                text.append(bar, style=color)

                if won and multiplier >= cashout_at:
                    text.append("  CASHED OUT", style="bold green")

                live.update(text)
                multiplier += 0.03 + (multiplier * 0.01)
                await asyncio.sleep(0.04)

            text = Text()
            text.append(f"  CRASHED at {crash_point:.2f}x", style="bold red")
            live.update(text)

        if won:
            console.print(f"[bold green]Cashed out at {cashout_at}x! Won {result.payout} $V[/bold green]")
        else:
            console.print(f"[red]Crashed at {crash_point}x before your {cashout_at}x target. Lost {result.bet_amount} $V[/red]")
```

---

### 9.4 — Skill Shot Timing Bar

A cursor moves across a bar. Hit the key when it's in the green zone. Pure arcade. **Provably fair** (green zone position is RNG-seeded).

```python
import asyncio
import time
from decimal import Decimal
from rich.console import Console
from rich.live import Live
from rich.text import Text


class SkillShotGame(BaseGame):
    name = "skill_shot"
    rtp = Decimal("0.94")  # skilled players approach 97%+

    BAR_WIDTH = 40
    GREEN_ZONE_SIZE = 6      # easy
    GOLD_ZONE_SIZE = 2       # jackpot zone inside green

    async def resolve(self, bet: dict, rng: ProvablyFairRNG, client_seed: str, nonce: int) -> GameResult:
        bet_amount = Decimal(str(bet["amount"]))

        # RNG determines green zone position
        green_start = rng.generate_outcome(client_seed, nonce, self.BAR_WIDTH - self.GREEN_ZONE_SIZE)
        green_end = green_start + self.GREEN_ZONE_SIZE
        gold_start = green_start + (self.GREEN_ZONE_SIZE - self.GOLD_ZONE_SIZE) // 2
        gold_end = gold_start + self.GOLD_ZONE_SIZE

        # Player's cursor stop position (from their timing input)
        stop_pos = bet.get("stop_position", self.BAR_WIDTH // 2)

        if gold_start <= stop_pos < gold_end:
            multiplier = Decimal("5.0")   # jackpot
        elif green_start <= stop_pos < green_end:
            multiplier = Decimal("2.0")   # standard win
        else:
            multiplier = Decimal("0.0")   # miss

        payout = (bet_amount * multiplier).quantize(Decimal("0.01"))

        return GameResult(
            game_id=bet["game_id"],
            player_id=bet["player_id"],
            bet_amount=bet_amount,
            payout=payout,
            net=payout - bet_amount,
            outcome_data={
                "green_zone": [green_start, green_end],
                "gold_zone": [gold_start, gold_end],
                "stop_position": stop_pos,
                "multiplier": str(multiplier),
            },
            server_seed=rng.reveal(),
            server_seed_hash=rng.server_seed_hash,
            client_seed=client_seed,
            nonce=nonce,
            provably_fair=True,
        )

    async def render_interactive(self, console: Console) -> int:
        """Animate the moving cursor; return position where user stopped."""
        import sys
        import select

        console.print("[bold]Press ENTER to stop the cursor in the green zone![/bold]\n")
        position = 0
        direction = 1
        speed = 0.03

        with Live(console=console, refresh_per_second=30) as live:
            while True:
                bar = []
                for i in range(self.BAR_WIDTH):
                    if i == position:
                        bar.append("[bold white on red]V[/bold white on red]")
                    else:
                        bar.append("-")

                live.update(Text.from_markup("".join(bar)))

                position += direction
                if position >= self.BAR_WIDTH - 1 or position <= 0:
                    direction *= -1

                await asyncio.sleep(speed)
                speed *= 0.999  # gradually speed up

                if sys.stdin in select.select([sys.stdin], [], [], 0)[0]:
                    sys.stdin.readline()
                    return position
```

---

### 9.5 — Typing Duel (PvP)

Head-to-head typing speed + accuracy. Winner takes the pot minus rake. **Skill-based, no RNG.**

```python
import asyncio
import time
from dataclasses import dataclass
from decimal import Decimal


TYPING_PROMPTS = [
    "the quick brown fox jumps over the lazy dog",
    "async await promises resolve into callback hell",
    "git push origin main --force is never the answer",
    "segmentation fault core dumped at line forty two",
    "kubernetes pod crashed loop back off restart limit",
    "npm install left-pad broke the entire internet once",
]


@dataclass
class TypingResult:
    player_id: str
    wpm: float
    accuracy: float
    time_seconds: float
    score: float  # wpm * accuracy


class TypingDuelGame(BaseGame):
    name = "typing_duel"
    rtp = Decimal("0.97")  # 3% rake on PvP pot

    async def resolve_pvp(
        self,
        p1_result: TypingResult,
        p2_result: TypingResult,
        pot: Decimal,
        wallet: "WalletService",
        game_id: str,
    ) -> dict:
        """Resolve a PvP typing duel."""
        rake = await wallet.pvp_rake(pot, game_id)
        prize = pot - rake

        if p1_result.score > p2_result.score:
            winner = p1_result.player_id
        elif p2_result.score > p1_result.score:
            winner = p2_result.player_id
        else:
            half = (prize / 2).quantize(Decimal("0.01"))
            await wallet.settle_win(p1_result.player_id, half, game_id)
            await wallet.settle_win(p2_result.player_id, half, game_id)
            return {"result": "tie", "prize_each": str(half)}

        await wallet.settle_win(winner, prize, game_id)
        return {
            "winner": winner,
            "prize": str(prize),
            "p1_score": p1_result.score,
            "p2_score": p2_result.score,
        }

    async def run_typing_test(self, console, prompt_text: str) -> TypingResult:
        """Run the local typing test and return results."""
        console.print(f"\n[bold cyan]Type this:[/bold cyan]")
        console.print(f"[yellow]{prompt_text}[/yellow]\n")
        console.print("[dim]Press ENTER when ready, then type as fast as you can...[/dim]")
        input()

        start = time.time()
        typed = input("> ")
        elapsed = time.time() - start

        correct = sum(1 for a, b in zip(typed, prompt_text) if a == b)
        accuracy = correct / max(len(prompt_text), 1)
        words = len(typed.split())
        wpm = (words / elapsed) * 60 if elapsed > 0 else 0
        score = wpm * accuracy

        return TypingResult(
            player_id="local",
            wpm=round(wpm, 1),
            accuracy=round(accuracy, 3),
            time_seconds=round(elapsed, 2),
            score=round(score, 1),
        )
```

---

### 9.6 — Maze Runner

Procedural maze. Navigate to the exit fastest. PvP bracket-ready. **Provably fair** (maze seed from RNG).

```python
import random
from dataclasses import dataclass


@dataclass
class Cell:
    x: int
    y: int
    walls: dict  # {"N": True, "S": True, "E": True, "W": True}
    visited: bool = False


class MazeGenerator:
    """Generate a maze using recursive backtracking (seeded RNG)."""

    def __init__(self, width: int = 15, height: int = 10, seed: int = 0):
        self.width = width
        self.height = height
        self.rng = random.Random(seed)
        self.grid: list[list[Cell]] = []

    def generate(self) -> list[list[Cell]]:
        self.grid = [
            [Cell(x, y, {"N": True, "S": True, "E": True, "W": True})
             for x in range(self.width)]
            for y in range(self.height)
        ]

        stack = [(0, 0)]
        self.grid[0][0].visited = True

        while stack:
            y, x = stack[-1]
            neighbors = self._unvisited_neighbors(x, y)

            if neighbors:
                direction, nx, ny = self.rng.choice(neighbors)
                self._remove_wall(x, y, nx, ny, direction)
                self.grid[ny][nx].visited = True
                stack.append((ny, nx))
            else:
                stack.pop()

        return self.grid

    def _unvisited_neighbors(self, x, y):
        neighbors = []
        for direction, dx, dy in [("N", 0, -1), ("S", 0, 1), ("E", 1, 0), ("W", -1, 0)]:
            nx, ny = x + dx, y + dy
            if 0 <= nx < self.width and 0 <= ny < self.height:
                if not self.grid[ny][nx].visited:
                    neighbors.append((direction, nx, ny))
        return neighbors

    def _remove_wall(self, x, y, nx, ny, direction):
        opposite = {"N": "S", "S": "N", "E": "W", "W": "E"}
        self.grid[y][x].walls[direction] = False
        self.grid[ny][nx].walls[opposite[direction]] = False

    def render_ascii(self, player_pos: tuple[int, int] = (0, 0)) -> str:
        """Render maze as ASCII art."""
        lines = []
        lines.append("+" + "---+" * self.width)

        for y in range(self.height):
            row_mid = "|"
            row_bot = "+"
            for x in range(self.width):
                cell = self.grid[y][x]

                if (x, y) == player_pos:
                    row_mid += " @ "
                elif (x, y) == (self.width - 1, self.height - 1):
                    row_mid += " * "
                else:
                    row_mid += "   "

                row_mid += "|" if cell.walls["E"] else " "
                row_bot += "---" if cell.walls["S"] else "   "
                row_bot += "+"

            lines.append(row_mid)
            lines.append(row_bot)

        return "\n".join(lines)


# Example output:
# +---+---+---+---+---+
# | @     |           |
# +---+   +   +---+   +
# |       |   |       |
# +   +---+   +   +---+
# |   |           | * |
# +---+---+---+---+---+
```

---

### 9.7 — Prompt Parlay (AI-Native) — Phase 3, non-provably-fair

Bet on whether a model's output meets objective constraints. Constraint verification is deterministic, but the model call itself is nondeterministic.

> **Fairness disclaimer:** This game involves live AI model calls. Outcomes depend on nondeterministic model behavior and are **not covered by the provably fair commit-reveal scheme**. It is labeled as "experimental" in the UI. A future deterministic mode using frozen prompt/response corpora with seed-indexed selection is planned.

```python
import json
import re
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum


class ConstraintType(Enum):
    VALID_JSON = "valid_json"
    MATCHES_REGEX = "matches_regex"
    COMPILES_PYTHON = "compiles_python"
    WORD_COUNT_OVER = "word_count_over"
    CONTAINS_KEYWORD = "contains_keyword"
    VALID_SQL = "valid_sql"


@dataclass
class ParlayConstraint:
    constraint_type: ConstraintType
    parameter: str | None = None
    difficulty: Decimal = Decimal("1.5")


@dataclass
class ParlayChallenge:
    prompt: str
    constraints: list[ParlayConstraint]
    model: str
    provider: str


class PromptParlayGame(BaseGame):
    name = "prompt_parlay"
    rtp = Decimal("0.93")

    CHALLENGES = [
        ParlayChallenge(
            prompt="Write a haiku about recursion in valid JSON format with keys 'line1', 'line2', 'line3'.",
            constraints=[
                ParlayConstraint(ConstraintType.VALID_JSON, difficulty=Decimal("1.8")),
                ParlayConstraint(ConstraintType.CONTAINS_KEYWORD, "recursion", Decimal("1.3")),
            ],
            model="claude-haiku-4-5-20251001",
            provider="anthropic",
        ),
        ParlayChallenge(
            prompt="Write a Python function that sorts a list using bubble sort. Only output code.",
            constraints=[
                ParlayConstraint(ConstraintType.COMPILES_PYTHON, difficulty=Decimal("1.5")),
                ParlayConstraint(ConstraintType.CONTAINS_KEYWORD, "def ", Decimal("1.2")),
            ],
            model="gpt-4o-mini",
            provider="openai",
        ),
    ]

    def verify_constraint(self, output: str, constraint: ParlayConstraint) -> bool:
        """Deterministically verify if model output meets a constraint."""
        match constraint.constraint_type:
            case ConstraintType.VALID_JSON:
                try:
                    json.loads(output)
                    return True
                except json.JSONDecodeError:
                    return False
            case ConstraintType.MATCHES_REGEX:
                return bool(re.search(constraint.parameter, output))
            case ConstraintType.COMPILES_PYTHON:
                try:
                    compile(output, "<string>", "exec")
                    return True
                except SyntaxError:
                    return False
            case ConstraintType.WORD_COUNT_OVER:
                return len(output.split()) > int(constraint.parameter)
            case ConstraintType.CONTAINS_KEYWORD:
                return constraint.parameter.lower() in output.lower()
            case _:
                return False

    async def resolve(self, bet: dict, rng: ProvablyFairRNG, client_seed: str, nonce: int) -> GameResult:
        bet_amount = Decimal(str(bet["amount"]))
        challenge_idx = bet["challenge_index"]
        selected_constraints = bet["selected_constraints"]

        challenge = self.CHALLENGES[challenge_idx]

        # Live model call (nondeterministic)
        output = await self._call_model(challenge.provider, challenge.model, challenge.prompt)

        results = {}
        total_multiplier = Decimal("1.0")
        all_passed = True

        for idx in selected_constraints:
            constraint = challenge.constraints[idx]
            passed = self.verify_constraint(output, constraint)
            results[idx] = passed
            if passed:
                total_multiplier *= constraint.difficulty
            else:
                all_passed = False

        payout = (bet_amount * total_multiplier).quantize(Decimal("0.01")) if all_passed else Decimal("0")

        return GameResult(
            game_id=bet["game_id"],
            player_id=bet["player_id"],
            bet_amount=bet_amount,
            payout=payout,
            net=payout - bet_amount,
            outcome_data={
                "challenge_prompt": challenge.prompt,
                "model_output": output[:500],
                "constraint_results": results,
                "total_multiplier": str(total_multiplier),
                "all_passed": all_passed,
            },
            server_seed=rng.reveal(),
            server_seed_hash=rng.server_seed_hash,
            client_seed=client_seed,
            nonce=nonce,
            provably_fair=False,  # explicitly NOT provably fair
        )

    async def _call_model(self, provider: str, model: str, prompt: str) -> str:
        """Route to the correct provider. Uses OpenVegas gateway API key."""
        if provider == "anthropic":
            import anthropic
            client = anthropic.AsyncAnthropic()
            msg = await client.messages.create(
                model=model, max_tokens=500,
                messages=[{"role": "user", "content": prompt}],
            )
            return msg.content[0].text
        elif provider == "openai":
            import openai
            client = openai.AsyncOpenAI()
            resp = await client.chat.completions.create(
                model=model, max_tokens=500,
                messages=[{"role": "user", "content": prompt}],
            )
            return resp.choices[0].message.content
        elif provider == "gemini":
            import google.generativeai as genai
            model_obj = genai.GenerativeModel(model)
            resp = await model_obj.generate_content_async(prompt)
            return resp.text
```

---

## AI Inference Gateway

The gateway meters, routes, and bills AI usage when users redeem $V. Pricing is read from the `provider_catalog` table (hot-toggleable, no deploys needed).

```python
from decimal import Decimal
from dataclasses import dataclass
from enum import Enum
import uuid


class Provider(Enum):
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    GEMINI = "gemini"


@dataclass
class InferenceRequest:
    user_id: str
    provider: Provider
    model: str
    messages: list[dict]
    max_tokens: int = 1024


@dataclass
class InferenceResult:
    text: str
    input_tokens: int
    output_tokens: int
    v_cost: Decimal = Decimal("0")
    actual_cost_usd: Decimal = Decimal("0")


class AIGateway:
    """Routes inference requests, meters usage, deducts $V.
    All pricing comes from provider_catalog table (no hardcoded dicts)."""

    def __init__(self, wallet: WalletService, catalog: "ProviderCatalog"):
        self.wallet = wallet
        self.catalog = catalog

    async def infer(self, req: InferenceRequest) -> InferenceResult:
        # 0. Check model is enabled in catalog
        model_config = await self.catalog.get_model(req.provider.value, req.model)
        if not model_config or not model_config["enabled"]:
            raise ModelDisabled(f"{req.model} is currently disabled")

        # 1. Estimate max cost and verify balance
        max_v_cost = self._estimate_max_cost(model_config, req.max_tokens)
        balance = await self.wallet.get_balance(req.user_id)
        if balance < max_v_cost:
            raise InsufficientBalance(f"Need {max_v_cost} $V, have {balance} $V")

        # 2. Escrow estimated cost
        escrow_id = f"infer:{req.user_id}:{uuid.uuid4().hex[:8]}"
        await self.wallet.place_bet(req.user_id, max_v_cost, escrow_id)

        # 3. Call provider
        result = await self._route_to_provider(req)

        # 4. Calculate actual cost from catalog pricing and refund difference
        actual_v = self._calculate_v_cost(model_config, result.input_tokens, result.output_tokens)
        refund = max_v_cost - actual_v
        if refund > 0:
            await self.wallet.settle_win(req.user_id, refund, escrow_id)

        # 5. Move actual cost to revenue
        await self.wallet.settle_loss(escrow_id, actual_v)

        # 6. Log usage
        actual_usd = self._calculate_actual_usd(model_config, result.input_tokens, result.output_tokens)
        await self.catalog.log_usage(req.user_id, req.provider.value, req.model,
                                      result.input_tokens, result.output_tokens, actual_v, actual_usd)

        result.v_cost = actual_v
        result.actual_cost_usd = actual_usd
        return result

    def _estimate_max_cost(self, model_config: dict, max_tokens: int) -> Decimal:
        v_in = Decimal(str(model_config["v_price_input_per_1m"]))
        v_out = Decimal(str(model_config["v_price_output_per_1m"]))
        return ((Decimal(max_tokens) * 2 * v_in +
                 Decimal(max_tokens) * v_out) / Decimal("1000000")
               ).quantize(Decimal("0.01"))

    def _calculate_v_cost(self, model_config: dict, input_tokens: int, output_tokens: int) -> Decimal:
        v_in = Decimal(str(model_config["v_price_input_per_1m"]))
        v_out = Decimal(str(model_config["v_price_output_per_1m"]))
        cost = (Decimal(input_tokens) * v_in + Decimal(output_tokens) * v_out) / Decimal("1000000")
        return cost.quantize(Decimal("0.01"))

    def _calculate_actual_usd(self, model_config: dict, input_tokens: int, output_tokens: int) -> Decimal:
        c_in = Decimal(str(model_config["cost_input_per_1m"]))
        c_out = Decimal(str(model_config["cost_output_per_1m"]))
        cost = (Decimal(input_tokens) * c_in + Decimal(output_tokens) * c_out) / Decimal("1000000")
        return cost.quantize(Decimal("0.000001"))

    async def _route_to_provider(self, req: InferenceRequest) -> InferenceResult:
        """Route to the appropriate provider SDK."""
        # Implementation per provider (Anthropic/OpenAI/Gemini)
        ...


class ModelDisabled(Exception):
    pass
```

---

## Provider Catalog

Centralized, hot-toggleable. No hardcoded pricing dicts — everything reads from `provider_catalog` table.

```python
class ProviderCatalog:
    """Interface to the provider_catalog Supabase table.
    Disabling a model here blocks routing instantly without a deploy."""

    def __init__(self, db):
        self.db = db

    async def get_model(self, provider: str, model_id: str) -> dict | None:
        """Get model config. Returns None if not found."""
        return await self.db.fetchrow(
            "SELECT * FROM provider_catalog WHERE provider = $1 AND model_id = $2",
            provider, model_id,
        )

    async def get_pricing(self, provider: str, model_id: str) -> dict:
        """Get pricing for mint calculations."""
        row = await self.get_model(provider, model_id)
        if not row:
            raise ValueError(f"Unknown model: {provider}/{model_id}")
        return row

    async def list_models(self, provider: str = None, enabled_only: bool = True) -> list[dict]:
        """List available models, optionally filtered by provider."""
        query = "SELECT * FROM provider_catalog WHERE 1=1"
        params = []
        if provider:
            query += f" AND provider = ${len(params) + 1}"
            params.append(provider)
        if enabled_only:
            query += " AND enabled = TRUE"
        query += " ORDER BY provider, model_id"
        return await self.db.fetch(query, *params)

    async def toggle_model(self, provider: str, model_id: str, enabled: bool):
        """Enable/disable a model (admin only). Takes effect immediately."""
        await self.db.execute(
            "UPDATE provider_catalog SET enabled = $1, updated_at = now() "
            "WHERE provider = $2 AND model_id = $3",
            enabled, provider, model_id,
        )

    async def update_pricing(self, provider: str, model_id: str, **kwargs):
        """Update pricing fields (admin only)."""
        allowed = {"cost_input_per_1m", "cost_output_per_1m",
                    "v_price_input_per_1m", "v_price_output_per_1m", "max_tokens"}
        sets = []
        params = []
        for key, val in kwargs.items():
            if key in allowed:
                params.append(val)
                sets.append(f"{key} = ${len(params)}")
        if sets:
            params.extend([provider, model_id])
            await self.db.execute(
                f"UPDATE provider_catalog SET {', '.join(sets)}, updated_at = now() "
                f"WHERE provider = ${len(params) - 1} AND model_id = ${len(params)}",
                *params,
            )

    async def log_usage(self, user_id, provider, model_id, input_tokens, output_tokens, v_cost, actual_cost):
        """Log inference usage for analytics."""
        await self.db.execute(
            "INSERT INTO inference_usage (user_id, provider, model_id, input_tokens, output_tokens, v_cost, actual_cost_usd) "
            "VALUES ($1, $2, $3, $4, $5, $6, $7)",
            user_id, provider, model_id, input_tokens, output_tokens, v_cost, actual_cost,
        )


# Seed data for provider_catalog
SEED_MODELS = [
    # OpenAI
    {"provider": "openai", "model_id": "gpt-4o", "display_name": "GPT-4o",
     "cost_input_per_1m": "2.50", "cost_output_per_1m": "10.00",
     "v_price_input_per_1m": "300", "v_price_output_per_1m": "1200", "max_tokens": 4096},
    {"provider": "openai", "model_id": "gpt-4o-mini", "display_name": "GPT-4o Mini",
     "cost_input_per_1m": "0.15", "cost_output_per_1m": "0.60",
     "v_price_input_per_1m": "20", "v_price_output_per_1m": "80", "max_tokens": 4096},
    # Anthropic
    {"provider": "anthropic", "model_id": "claude-sonnet-4-20250514", "display_name": "Claude Sonnet 4",
     "cost_input_per_1m": "3.00", "cost_output_per_1m": "15.00",
     "v_price_input_per_1m": "360", "v_price_output_per_1m": "1800", "max_tokens": 4096},
    {"provider": "anthropic", "model_id": "claude-haiku-4-5-20251001", "display_name": "Claude Haiku 4.5",
     "cost_input_per_1m": "0.80", "cost_output_per_1m": "4.00",
     "v_price_input_per_1m": "100", "v_price_output_per_1m": "500", "max_tokens": 4096},
    # Gemini
    {"provider": "gemini", "model_id": "gemini-2.0-flash", "display_name": "Gemini 2.0 Flash",
     "cost_input_per_1m": "0.10", "cost_output_per_1m": "0.40",
     "v_price_input_per_1m": "15", "v_price_output_per_1m": "50", "max_tokens": 4096},
]
```

---

## Redemption Store

What $V buys (besides more games):

```python
STORE_CATALOG = {
    # AI Inference Packs
    "ai_starter": {
        "name": "Starter AI Pack",
        "description": "50k tokens on GPT-4o-mini or Gemini Flash",
        "cost_v": Decimal("5.00"),
        "type": "ai_pack",
        "tokens": 50_000,
        "models": ["gpt-4o-mini", "gemini-2.0-flash"],
    },
    "ai_pro": {
        "name": "Pro AI Pack",
        "description": "25k tokens on Claude Sonnet or GPT-4o",
        "cost_v": Decimal("20.00"),
        "type": "ai_pack",
        "tokens": 25_000,
        "models": ["claude-sonnet-4-20250514", "gpt-4o"],
    },

    # Cosmetics
    "theme_cyberpunk": {
        "name": "Cyberpunk Terminal Theme",
        "description": "Neon colors + glitch effects",
        "cost_v": Decimal("15.00"),
        "type": "cosmetic",
    },
    "theme_retro": {
        "name": "Retro Arcade Theme",
        "description": "Green phosphor CRT look",
        "cost_v": Decimal("10.00"),
        "type": "cosmetic",
    },
    "victory_fireworks": {
        "name": "Win Animation: Fireworks",
        "description": "ASCII fireworks on every win",
        "cost_v": Decimal("8.00"),
        "type": "cosmetic",
    },
    "horse_skin_unicorn": {
        "name": "Unicorn Horse Skin",
        "description": "Your horse displays as a unicorn",
        "cost_v": Decimal("12.00"),
        "type": "cosmetic",
    },

    # Tournament Access
    "tournament_pass": {
        "name": "Weekend Tournament Pass",
        "description": "Entry to the Saturday Night Horse Derby",
        "cost_v": Decimal("25.00"),
        "type": "tournament",
    },
}
```

---

## Business Models & Unit Economics

### Revenue Streams

| Stream | Mechanism | Target Margin |
|--------|-----------|---------------|
| **$V Sales (Stripe)** | Sell $V packs directly for cash | 100% margin (you set the price) |
| **Mint Spread** | 8% spread on Solo Mint | 8% of BYOK burn volume |
| **Company Task Value** | Split/Sponsor mints produce eval/content work | Saves internal compute costs |
| **Game House Edge** | RTP 93-97% across games | 3-7% of wagered volume |
| **PvP Rake** | 3% of PvP pots (Typing Duel, Maze Runner) | 3% of PvP volume |
| **AI Redemption Markup** | ~20% markup on inference vs our API cost | 20% of redemption volume |
| **Subscriptions** | Monthly $V drip + perks | Recurring revenue |
| **Cosmetics** | Terminal themes, skins, animations | Near-100% margin |
| **Tournaments** | Entry fees; platform keeps % | 5-10% of prize pools |
| **B2B Packs** | Bulk $V for teams | Volume discount but guaranteed revenue |

### Subscription Tiers

```python
SUBSCRIPTION_TIERS = {
    "free": {
        "monthly_v_drip": Decimal("0"),
        "mint_spread": Decimal("0.08"),       # 8%
        "ai_markup": Decimal("1.25"),          # 25% markup
        "daily_free_spins": 1,
        "pvp_rake": Decimal("0.05"),           # 5%
    },
    "pro": {
        "price_usd": Decimal("9.99"),
        "monthly_v_drip": Decimal("100.00"),
        "mint_spread": Decimal("0.04"),       # 4%
        "ai_markup": Decimal("1.15"),          # 15% markup
        "daily_free_spins": 5,
        "pvp_rake": Decimal("0.03"),           # 3%
        "exclusive_games": True,
        "custom_themes": True,
    },
    "whale": {
        "price_usd": Decimal("49.99"),
        "monthly_v_drip": Decimal("750.00"),
        "mint_spread": Decimal("0.02"),       # 2%
        "ai_markup": Decimal("1.08"),          # 8% markup
        "daily_free_spins": 20,
        "pvp_rake": Decimal("0.02"),           # 2%
        "exclusive_games": True,
        "custom_themes": True,
        "priority_inference": True,
        "tournament_vip": True,
    },
}
```

---

## CLI UX & Commands

### Installation

```bash
# Primary (recommended) — install once, use daily
npm i -g openvegas

# Quick one-off (no global install)
npx openvegas <command>

# Fallback (Python users)
pip install openvegas
# or
pipx install openvegas
```

### Release Packaging

The npm package is a thin Node launcher that detects OS/arch and runs the correct prebuilt binary:

```
npm-package/
├── package.json        # bin: { "openvegas": "./bin/launcher.js" }
├── bin/
│   └── launcher.js     # detects platform, downloads/runs binary
└── binaries/           # downloaded on postinstall
    ├── openvegas-darwin-arm64
    ├── openvegas-darwin-x64
    ├── openvegas-linux-x64
    └── openvegas-win-x64.exe
```

Binaries are built from the Python core using [PyInstaller](https://pyinstaller.org) or [Nuitka](https://nuitka.net) in CI (GitHub Actions matrix: macOS arm64/x64, Linux x64, Windows x64). The npm `postinstall` script downloads the correct binary for the user's platform from GitHub Releases.

### Command Reference

```bash
# Auth (Supabase-backed)
openvegas login                          # email/password or magic link via Supabase Auth
openvegas login --otp                    # magic link login
openvegas logout
openvegas status                         # show balance, tier, stats

# Wallet
openvegas deposit 50                     # buy $V with cash (opens Stripe checkout)
openvegas balance                        # show $V balance
openvegas history                        # transaction history

# Minting (BYOK) — all 3 providers from Phase 1
openvegas mint --amount 5.00 --provider anthropic          # Solo Mint (default)
openvegas mint --amount 5.00 --provider openai --mode split     # Split Mint (+bonus)
openvegas mint --amount 10.00 --provider gemini --mode sponsor  # Sponsor Mint (+big bonus)
openvegas mint history                   # see what your burns were used for
openvegas keys set anthropic             # configure API key (stored locally)
openvegas keys set openai
openvegas keys set gemini

# Games
openvegas play horse --stake 5 --horse 3 --type win       # Horse Racing
openvegas play plinko --stake 2                            # Plinko Drop
openvegas play crash --stake 10 --cashout 2.5              # Crash Rocket
openvegas play skillshot --stake 3                         # Skill Shot
openvegas play typing --stake 5                            # Typing Duel (PvP)
openvegas play maze --stake 4                              # Maze Runner
# openvegas play parlay --stake 8 --challenge 0            # Phase 3

# Quick play (random game)
openvegas quick 5                        # bet 5 $V on a random game

# AI Redemption — provider toggle
openvegas ask "refactor this function" --provider anthropic --model claude-sonnet-4-20250514
openvegas ask "write tests" --provider openai --model gpt-4o-mini
openvegas ask "explain this" --provider gemini --model gemini-2.0-flash
openvegas ask "quick question"           # uses default_provider from config

# Provider/model management
openvegas models                         # list all available models + $V prices
openvegas models --provider anthropic    # filter by provider
openvegas config set default_provider anthropic
openvegas config set default_model_anthropic claude-sonnet-4-20250514
openvegas config set default_model_openai gpt-4o-mini
openvegas config set default_model_gemini gemini-2.0-flash

# Store
openvegas store                          # browse redemption catalog
openvegas store buy theme_cyberpunk      # buy a cosmetic

# Social / PvP
openvegas lobby                          # see available PvP games
openvegas challenge @username typing 10  # challenge someone to typing duel
openvegas leaderboard                    # weekly leaderboard
openvegas tournaments                    # upcoming tournaments

# Verification
openvegas verify <game_id>               # verify provably fair outcome

# Settings
openvegas config theme retro             # set terminal theme
openvegas config set animation true      # toggle animations
```

### CLI Entry Point

```python
import asyncio
import click
from rich.console import Console

console = Console()


@click.group()
@click.version_option()
def cli():
    """OpenVegas -- Terminal Arcade for Developers"""
    pass


@cli.command()
@click.argument("game", type=click.Choice([
    "horse", "plinko", "crash", "skillshot", "typing", "maze",
]))
@click.option("--stake", type=float, required=True, help="Amount of $V to wager")
@click.option("--horse", type=int, help="Horse number (horse racing only)")
@click.option("--type", "bet_type", type=click.Choice(["win", "place", "show"]), default="win")
@click.option("--cashout", type=float, default=2.0, help="Auto-cashout multiplier (crash only)")
def play(game: str, stake: float, horse: int, bet_type: str, cashout: float):
    """Play a game and wager $V."""
    console.print(f"[bold]Loading {game}...[/bold]")
    asyncio.run(_play(game, stake, horse, bet_type, cashout))


@cli.command()
@click.option("--amount", type=float, required=True)
@click.option("--provider", type=click.Choice(["anthropic", "openai", "gemini"]), required=True)
@click.option("--mode", type=click.Choice(["solo", "split", "sponsor"]), default="solo")
def mint(amount: float, provider: str, mode: str):
    """Mint $V by burning LLM tokens (BYOK)."""
    asyncio.run(mint_v(amount, provider, mode))


@cli.command()
@click.argument("prompt")
@click.option("--provider", default=None, help="Provider (openai/anthropic/gemini). Uses default if omitted.")
@click.option("--model", default=None, help="Model ID. Uses provider default if omitted.")
def ask(prompt: str, provider: str, model: str):
    """Use $V for AI inference."""
    asyncio.run(_ask(prompt, provider, model))


@cli.command()
@click.option("--provider", default=None, help="Filter by provider")
def models(provider: str):
    """List available models and $V prices."""
    asyncio.run(_list_models(provider))


@cli.command()
def balance():
    """Show your $V balance."""
    asyncio.run(_show_balance())


if __name__ == "__main__":
    cli()
```

### Local Config Schema (`~/.openvegas/config.json`)

```json
{
  "session": {
    "access_token": "eyJ...",
    "refresh_token": "abc..."
  },
  "providers": {
    "openai": { "api_key": "sk-..." },
    "anthropic": { "api_key": "sk-ant-..." },
    "gemini": { "api_key": "AIza..." }
  },
  "default_provider": "anthropic",
  "default_model_by_provider": {
    "openai": "gpt-4o-mini",
    "anthropic": "claude-sonnet-4-20250514",
    "gemini": "gemini-2.0-flash"
  },
  "theme": "default",
  "animation": true,
  "backend_url": "https://api.openvegas.gg",
  "supabase_url": "https://xxxxx.supabase.co",
  "supabase_anon_key": "eyJ..."
}
```

---

## Phase Roadmap

### Phase 1 — MVP (Weeks 1-4)

- **Supabase foundation**: DB schema, Auth, RLS policies, provider_catalog seeded
- **Wallet/ledger** with CHECK constraints, idempotency keys, atomic transactions
- **2 games**: Horse Racing + Skill Shot (both provably fair)
- **Multi-provider mint** (OpenAI + Anthropic + Gemini) with hardened verification
- **Multi-provider inference gateway** with provider toggle
- **Stripe deposits** ($V purchase)
- **Fraud controls baseline**: velocity limits, daily caps, IP checks, anomaly flagging
- **CLI**: login, mint, play, ask, balance, models, config

### Phase 2 — Core Loop (Weeks 5-8)

- Add **Plinko** + **Crash Rocket** + **Typing Duel** (PvP)
- Split Mint + Sponsor Mint modes (company task queue)
- Provably fair receipt explorer (`openvegas verify <game_id>`)
- Cosmetics store (3-5 items)
- Daily streaks + referral codes
- Subscription tiers (Free / Pro / Whale)

### Phase 3 — Social + Scale (Weeks 9-12)

- Add **Maze Runner** + **Prompt Parlay** (labeled experimental/non-provably-fair)
- PvP matchmaking + lobbies (WebSocket)
- Tournaments (weekly horse derby, typing leagues)
- Battle pass / seasons
- Leaderboards
- Prompt Parlay deterministic mode (frozen corpus with seed-indexed selection)

### Phase 4 — Platform (Weeks 13+)

- Plugin system for community games (`openvegas install @dev/roulette-x`)
- B2B SDK ("arcade while your agent runs")
- Mobile-friendly TUI (responsive layouts)
- Advanced anti-fraud (ML anomaly scoring, device fingerprinting)
- Multi-region deployment

---

## Test Cases & Acceptance Scenarios

These must pass before Phase 1 ships.

### Mint Integrity

| # | Scenario | Expected |
|---|----------|----------|
| M1 | Attacker fabricates a `raw_provider_response` with inflated token counts | **Not possible in Tier 1**: server makes the provider call itself and observes the real response directly. In Tier 2: server independently verifies via provider audit API, never trusts client-submitted response objects. |
| M2 | Replay a consumed challenge_id | Rejected: `UNIQUE` constraint on `mint_events.challenge_id` |
| M3 | Submit receipt after challenge expires (>5 min) | Rejected: "Challenge expired" |
| M4 | Submit receipt with mismatched provider/model | Rejected: "Provider/model mismatch" |
| M5 | Valid burn on Anthropic produces correct $V | $V = (trusted_input * cost_in + trusted_output * cost_out) / 0.01 * rate |
| M6 | Valid burn on OpenAI produces correct $V | Same formula, OpenAI pricing from catalog |
| M7 | Valid burn on Gemini produces correct $V | Same formula, Gemini pricing from catalog |

### Ledger Integrity

| # | Scenario | Expected |
|---|----------|----------|
| L1 | Place bet larger than balance | Rejected: Postgres CHECK constraint, `InsufficientBalance` raised |
| L2 | Two concurrent bets that together exceed balance | Only one succeeds; the other rolls back (serializable isolation) |
| L3 | Duplicate settlement for the same game/mint and same accounts | Silently succeeds (no double credit); `UNIQUE(reference_id, entry_type, debit_account, credit_account)` blocks it |
| L4 | Sum of all debits equals sum of all credits | Always true (double-entry invariant, verified by audit query) |
| L5 | Two players bet on the same PvP game | Both succeed — same `reference_id` and `entry_type`, but different `debit_account` values, so the UNIQUE constraint allows both |

### Provider Toggle

| # | Scenario | Expected |
|---|----------|----------|
| P1 | `openvegas ask "hello" --provider openai` | Routes to OpenAI, deducts from single $V wallet |
| P2 | `openvegas ask "hello" --provider anthropic` | Routes to Anthropic, deducts from same $V wallet |
| P3 | Disable `gpt-4o` in provider_catalog | Immediate rejection: "gpt-4o is currently disabled" (no deploy needed) |
| P4 | Re-enable `gpt-4o` | Immediately routable again |

### Supabase RLS

| # | Scenario | Expected |
|---|----------|----------|
| R1 | User A queries `ledger_entries` | Sees only rows where debit or credit account is `user:<A_id>` |
| R2 | User A queries `wallet_accounts` | Sees only `user:<A_id>` balance |
| R3 | User A tries to read User B's mint_events | Empty result set (RLS blocks) |
| R4 | Service role writes settlement | Succeeds (service role bypasses RLS) |

### Anti-Abuse

| # | Scenario | Expected |
|---|----------|----------|
| F1 | User mints 11 times in 1 hour | 11th mint blocked: "Mint rate limit exceeded (hourly)" |
| F2 | User mints >$100 USD in a day | Blocked: "Daily mint USD cap exceeded" |
| F3 | 4 accounts from same IP in 24h | 4th account flagged: "Suspicious multi-account activity" |
| F4 | User places 21 bets in 1 minute | 21st bet blocked: "Bet rate limit exceeded" |

### Provably Fair

| # | Scenario | Expected |
|---|----------|----------|
| PF1 | Horse race game round | `provably_fair=True`; client can verify with revealed seed |
| PF2 | Prompt Parlay game round | `provably_fair=False`; UI shows "experimental" badge |

---

## Project Structure

```
openvegas/
├── pyproject.toml
├── openvegas/
│   ├── __init__.py
│   ├── cli.py                  # Click CLI entry point
│   ├── config.py               # Local config (~/.openvegas/)
│   ├── auth.py                 # Supabase Auth (JWT issuance + refresh)
│   ├── client.py               # HTTP/WS client to backend
│   ├── games/
│   │   ├── __init__.py
│   │   ├── base.py             # BaseGame, GameResult
│   │   ├── horse_racing.py
│   │   ├── plinko.py
│   │   ├── crash.py
│   │   ├── skill_shot.py
│   │   ├── typing_duel.py
│   │   ├── maze_runner.py
│   │   └── prompt_parlay.py    # Phase 3
│   ├── mint/
│   │   ├── __init__.py
│   │   ├── engine.py           # Mint flow, hardened receipt verification
│   │   ├── tasks.py            # Solo/Split/Sponsor task templates
│   │   └── providers.py        # Provider SDK wrappers + response extraction
│   ├── wallet/
│   │   ├── __init__.py
│   │   └── ledger.py           # Double-entry bookkeeping with idempotency
│   ├── gateway/
│   │   ├── __init__.py
│   │   ├── inference.py        # AI gateway + metering
│   │   └── catalog.py          # ProviderCatalog (reads from Supabase)
│   ├── fraud/
│   │   ├── __init__.py
│   │   └── engine.py           # Velocity checks, anomaly scoring
│   ├── store/
│   │   ├── __init__.py
│   │   └── catalog.py          # Redemption store
│   ├── rng/
│   │   ├── __init__.py
│   │   └── provably_fair.py    # Commit-reveal RNG
│   └── tui/
│       ├── __init__.py
│       ├── animations.py       # Shared animation utilities
│       ├── horse_renderer.py
│       ├── plinko_renderer.py
│       ├── crash_renderer.py
│       └── themes.py           # Terminal themes
├── server/                     # Backend (FastAPI)
│   ├── main.py
│   ├── middleware/
│   │   └── auth.py             # Supabase JWT validation
│   ├── routes/
│   │   ├── mint.py             # POST /mint/challenge, POST /mint/verify
│   │   ├── games.py
│   │   ├── wallet.py
│   │   ├── inference.py
│   │   └── store.py
│   ├── services/
│   └── migrations/
├── supabase/
│   ├── migrations/
│   │   └── 001_initial_schema.sql   # All tables + RLS policies
│   └── seed.sql                     # provider_catalog seed data
└── tests/
    ├── test_games/
    ├── test_wallet/
    │   ├── test_idempotency.py
    │   ├── test_overdraft.py
    │   └── test_double_entry.py
    ├── test_mint/
    │   ├── test_verification.py      # Forged receipts, replay, expiry
    │   └── test_trusted_extraction.py
    ├── test_fraud/
    │   └── test_velocity.py
    ├── test_rng/
    └── test_catalog/
        └── test_toggle.py
```

---

## Assumptions & Defaults

1. **Confirmed**: Unified `$V` wallet with provider/model toggle (not per-provider wallets).
2. **Confirmed**: Supabase Postgres + Auth + RLS as MVP foundation.
3. **Confirmed**: Phase 1 ships with OpenAI, Anthropic, and Gemini support.
4. **Confirmed**: Prompt Parlay fairness claims deferred; labeled "experimental" until deterministic corpus mode ships.
5. **Confirmed**: Sample prices/models in spec are placeholders; production values live in `provider_catalog` table.
6. **Confirmed**: Anti-abuse (velocity, caps, IP checks) is a Phase 1 requirement, not Phase 4.
7. **Confirmed**: Mint verification extracts token counts server-side from provider response metadata, never trusts client self-reporting.

---

*Built with Python, Rich, FastAPI, Supabase, and reckless ambition.*
