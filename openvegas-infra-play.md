# OpenVegas Infra Play

## Summary
This document defines the implementation plan for OpenVegas as infrastructure across two tracks:
1. Enterprise-sponsored compute budgets for teams.
2. Autonomous agent integration for fast compute top-ups.
3. Agent-only casino mode with ASCII games for probabilistic compute boosts.

The positioning is infrastructure-first: budget control, policy enforcement, and measurable productivity lift, with deterministic boost mechanics for enterprise-safe incentives.

## Product Defaults
1. Funding mode: Hybrid.
2. Funding priority: Org-sponsored pool first, BYOK fallback only if org policy allows.
3. Agent boosts: Deterministic work-boost only in v1.
4. Mint verification: Tier 1 proxied mint in MVP; Tier 2 disabled until provider audit APIs are integrated.
5. Wallet model: Unified `$V` balance with provider/model routing toggle.
6. Distribution: npm-first (`npm i -g openvegas`), `npx` fallback, PyPI secondary.
7. Casino mode: Agents only (service accounts), never human user accounts.

## Enterprise Play

### Core Product
1. Org admin funds a monthly compute sponsorship budget.
2. Employees consume unified `$V` for provider-routed inference.
3. Admin policies enforce spend and model/provider access constraints.
4. Usage and spend are fully auditable per user, team, and provider.

### Admin Controls
1. Org budget caps (monthly, daily, per-user, per-team).
2. Provider/model allowlist and blocklist.
3. Default provider and model policy.
4. BYOK fallback enable/disable.
5. Real-time budget alerts and anomaly flags.
6. Emergency kill switch for inference and boosts.

### Enterprise Value Proposition
1. Reduce engineering downtime due to credit exhaustion.
2. Centralize spend governance across OpenAI, Anthropic, and Gemini.
3. Improve predictability of AI tooling costs.
4. Keep controls and auditability without blocking developer flow.

## Agent Play

### Agent Runtime Model
1. Org creates service accounts for autonomous agents (for example OpenClaw).
2. Agent requests a short-lived scoped token.
3. Agent starts a session and gets a spend envelope plus policy constraints.
4. Agent calls OpenVegas for routed inference.
5. If near budget limit, agent requests deterministic boost challenge.
6. Agent submits challenge output, gets reward if score threshold is met.
7. All spend and rewards are attributed to org and agent for audit.

### Deterministic Boost Design
1. Server issues an objective challenge with rubric and max reward.
2. Agent submits an artifact and metadata.
3. Verifier computes deterministic score.
4. Reward is capped and policy-bounded.
5. Reward settlement is idempotent.

## Agent-Only Casino Mode

### Scope and Access
1. Casino mode is restricted to service-account agents (for example OpenClaw).
2. Human user accounts cannot call casino endpoints.
3. Org policy controls whether casino mode is enabled per org and per agent.
4. All wagers and payouts use non-withdrawable `$V` and remain inside OpenVegas.

### Initial ASCII Game Set (v1)
1. Poker (five-card draw) with deterministic dealer logic and fixed betting rounds.
2. Blackjack (single-deck ruleset with configurable dealer stand/hit policy).
3. Baccarat (player/banker/tie outcomes and standard commission handling).
4. Roulette (European single-zero wheel).
5. Slots (3-reel ASCII symbols with fixed payout table).

### Casino Session Flow
1. Agent starts a casino session with stake limits from org policy.
2. Agent requests game state and allowed actions.
3. Agent submits move or bet with idempotency key.
4. Server resolves round using provable RNG seed flow and policy checks.
5. Ledger debits wager and credits payout atomically.
6. Session closes on envelope exhaustion, max rounds, or policy stop.

### Payout and Risk Controls
1. Per-round max wager and per-session loss cap enforced server-side.
2. Game RTP bounds are fixed in catalog and versioned.
3. Optional cooldown between rounds to limit abuse loops.
4. House rules and payout tables are immutable per round version.

## API Plan

### Enterprise APIs
1. `POST /v1/orgs` create org.
2. `POST /v1/orgs/{org_id}/sponsorships` create or update funded budget.
3. `POST /v1/orgs/{org_id}/policies` configure caps and model/provider policies.
4. `POST /v1/orgs/{org_id}/members/invite` invite employees.
5. `GET /v1/orgs/{org_id}/usage` usage by provider/model/user/agent.
6. `POST /v1/webhooks/stripe` billing, renewals, top-ups.

### Agent APIs
1. `POST /v1/agents/tokens` issue scoped short-lived token.
2. `POST /v1/agent/sessions/start` create session and spend envelope.
3. `POST /v1/agent/infer` run metered inference.
4. `POST /v1/agent/boost/challenge` request deterministic challenge.
5. `POST /v1/agent/boost/submit` submit artifact for scoring and reward.
6. `GET /v1/agent/budget` current envelope and remaining allowance.

### Agent Casino APIs
1. `POST /v1/agent/casino/sessions/start` create agent-only casino session.
2. `GET /v1/agent/casino/games` list enabled games, rules, and RTP.
3. `POST /v1/agent/casino/rounds/start` place wager and start round.
4. `POST /v1/agent/casino/rounds/{round_id}/action` submit game action (hit/stand/draw/hold).
5. `POST /v1/agent/casino/rounds/{round_id}/resolve` finalize round and payout.
6. `GET /v1/agent/casino/sessions/{session_id}` fetch session PnL and limits.
7. `GET /v1/agent/casino/rounds/{round_id}/verify` fetch proof data for deterministic replay.

## CLI Plan
1. `openvegas org create --name <name>`
2. `openvegas org sponsor set --monthly-usd <amount>`
3. `openvegas org policy set --daily-cap-usd <amount> --allow-openai --allow-anthropic --allow-gemini`
4. `openvegas org member invite <email>`
5. `openvegas org usage --from <date> --to <date>`
6. `openvegas agent token issue --agent <name> --scopes infer,boost,budget.read`
7. `openvegas agent budget`
8. `openvegas agent boost request`
9. `openvegas agent boost submit --challenge <id> --artifact <path>`
10. `openvegas agent casino start --game <poker|blackjack|baccarat|roulette|slots> --stake <v>`
11. `openvegas agent casino action --round <id> --move <value>`
12. `openvegas agent casino resolve --round <id>`
13. `openvegas agent casino status --session <id>`

## Data Model Plan (Supabase)
1. `organizations(id, name, billing_customer_id, status, created_at)`
2. `org_members(org_id, user_id, role, status, created_at)`
3. `org_sponsorships(id, org_id, monthly_budget_usd, refill_rule, status, renewed_at)`
4. `org_policies(id, org_id, allowed_providers, allowed_models, user_daily_cap_usd, byok_fallback_enabled, boost_enabled)`
5. `org_budget_ledger(id, org_id, source, delta_usd, reference_id, created_at)`
6. `agent_accounts(id, org_id, name, status, created_at)`
7. `agent_tokens(id, agent_account_id, scopes, expires_at, revoked_at)`
8. `agent_sessions(id, agent_account_id, org_id, envelope_v, spent_v, status, started_at, ended_at)`
9. `boost_challenges(id, org_id, agent_session_id, rubric_version, max_reward_v, expires_at, status)`
10. `boost_submissions(id, challenge_id, artifact_hash, score, reward_v, status, created_at)`
11. `boost_rewards(id, submission_id, org_id, actor_type, actor_id, reward_v, ledger_ref)`
12. `usage_events(id, org_id, actor_type, actor_id, provider, model, input_tokens, output_tokens, v_cost, usd_cost, created_at)`
13. `casino_game_catalog(id, game_code, version, rtp, rules_json, payout_table_json, enabled)`
14. `casino_sessions(id, org_id, agent_account_id, agent_session_id, max_loss_v, max_rounds, rounds_played, net_pnl_v, status, started_at, ended_at)`
15. `casino_rounds(id, session_id, game_code, wager_v, state_json, rng_commit, rng_reveal, status, started_at, resolved_at)`
16. `casino_moves(id, round_id, move_index, action, payload_json, idempotency_key, created_at, UNIQUE(round_id, idempotency_key))`
17. `casino_payouts(id, round_id, wager_v, payout_v, net_v, ledger_ref, created_at)`
18. `casino_verifications(id, round_id, commit_hash, reveal_seed, client_seed, nonce, created_at)`

## Security and Control Requirements
1. Service-account tokens are short-lived and scoped.
2. All agent calls pass org policy checks.
3. Hard caps are server-enforced.
4. Reward logic is deterministic and bounded.
5. Idempotency keys are required on inference and reward submissions.
6. All debits and credits are ledger-backed and auditable.
7. Keys and sensitive prompts are redacted in logs.
8. No cash-out and no transferable reward value.
9. Casino endpoints require `casino.play` scope and agent account type.
10. Human JWTs are rejected on all casino routes.
11. Casino rounds enforce per-round and per-session loss limits before resolution.

## Implementation Phases

### Phase 0: Wallet API Migration (prerequisite for all phases)
**Must land first — Phases A through D all depend on this interface change.**
1. Refactor `openvegas/wallet/ledger.py`: rename `user_id` params to `account_id`, add `*, tx=None` to `settle_win` and `settle_loss`, add generic `ensure_account(account_id)`.
2. Update all existing consumers to pass prefixed account IDs:
   - `server/routes/games.py` → `f"user:{user_id}"` in `place_bet`, `settle_win`, `settle_loss`
   - `openvegas/mint/engine.py` → `f"user:{challenge.user_id}"` in `ensure_user_account`, `mint`
   - `openvegas/gateway/inference.py` → `f"user:{req.user_id}"` in `get_balance`, `place_bet`, `settle_win`
3. Run existing tests to verify no regressions (9 tests must still pass).

### Phase A: Enterprise Sponsorship Foundation (2-3 weeks)
1. Add org, membership, sponsorship, policy, and budget-ledger schema.
2. Integrate Stripe sponsorship billing and top-up flows.
3. Enforce org policy in inference gateway.
4. Ship org admin API and CLI commands.

### Phase B: Agent Runtime API (2 weeks)
1. Add service accounts and scoped token issuance.
2. Implement session envelopes and `agent/infer` metering.
3. Add usage attribution by `agent_account_id`.
4. Add budget introspection endpoint.

### Phase C: Deterministic Boost Engine (2 weeks)
1. Implement challenge issuance and rubric versioning.
2. Implement deterministic verifier.
3. Add reward settlement with idempotency.
4. Add anti-abuse guardrails for challenge and reward rates.

### Phase D: Agent-Only Casino Mode (2-3 weeks)
1. Add casino catalog, session, round, move, payout, and verification schema.
2. Implement five ASCII game engines: poker, blackjack, baccarat, roulette, slots.
3. Add agent-only casino API endpoints with scope and org policy checks.
4. Integrate casino wagers and payouts with ledger transactions.
5. Ship verification endpoint for replay/proof data.

### Phase E: GTM Hardening (1-2 weeks)
1. Add admin usage dashboards and alerts.
2. Add billing statements and export endpoints.
3. Publish OpenClaw integration guide and SDK examples.
4. Finalize enterprise onboarding documentation.

## Acceptance Criteria

### Enterprise
1. User cannot exceed org or personal cap.
2. Disabled provider/model blocks routing immediately.
3. Policy updates apply without deploy.
4. Spend exports reconcile with ledger totals.

### Agent
1. Missing or invalid token scopes are denied.
2. Agent session cannot exceed envelope.
3. Duplicate boost submit cannot double reward.
4. Reward cannot exceed challenge max.
5. Every inference and reward event is attributable to org and agent.

### Agent Casino Mode
1. Human user token calling casino route is rejected.
2. Agent cannot wager above per-round cap.
3. Agent session halts when max loss cap is reached.
4. Duplicate move submission with same idempotency key does not mutate round twice.
5. Round resolution writes exactly one wager debit and one payout credit path.
6. Verification endpoint can replay round outcome from commit/reveal data.

## Risks and Mitigations
1. Compliance risk from gaming framing in enterprise contexts.
Mitigation: agent-only casino access, deterministic boost framing for enterprise flows, and policy-first controls.
2. Fraud risk on boost submissions.
Mitigation: deterministic scoring, tight caps, idempotency, anomaly checks.
3. Provider API volatility.
Mitigation: provider abstraction and centralized provider catalog toggles.
4. Abuse risk from high-frequency casino loops.
Mitigation: round cooldowns, session loss caps, and anomaly-triggered suspension.

## KPI Targets
1. Reduction in blocked-by-credit incidents.
2. Increase in productive agent runtime minutes.
3. Predictable monthly spend variance.
4. Time-to-unblock after cap hits.
5. Agent casino adoption rate among integrated autonomous agents.
6. Net compute uplift per agent session after casino payouts.

---

## Agentic Commerce Context: How Autonomous Agents Like OpenClaw Connect

### The Pattern Driving This Space

What is emerging on X and in production is **agentic commerce** — agents with wallets that discover, pay for, and consume services autonomously. The architecture that works today:

1. **Human funds a wallet** (cash, crypto/USDC, or org-sponsored pool).
2. **Agent gets tool access** via MCP servers, skills, or API plugins.
3. **Agent discovers a paid service** (marketplace, API, or compute provider).
4. **Service returns a price/quote** (or the agent knows the rate table).
5. **Agent signs/submits payment** (or requests approval if policy requires it).
6. **Provider releases output** (inference, task completion, compute credits).
7. **Platform takes a fee** (spread, commission, usage markup, or subscription).

This is exactly the **x402 pattern** (HTTP 402 Payment Required → client pays → server returns resource). OpenVegas slots into step 3-6 as the **paid compute service** that agents call.

### Why OpenClaw Specifically

OpenClaw is a local agent runtime with broad device/tool access. Developers chain it to external skills and marketplaces. What makes it relevant to OpenVegas:

- It can **discover and call paid APIs** (via skill manifests)
- It can **manage wallets and send payments** (USDC/stablecoin integrations exist in the ecosystem)
- It can **make autonomous decisions** about when to spend (e.g., "my budget is low, should I gamble for more?")
- It has an **open skill/plugin system** — OpenVegas publishes a skill manifest, any OpenClaw instance can install it

### How OpenVegas Fits Into an Agent's Workflow

```
Agent is running a multi-step coding task
    │
    ├─ Agent calls OpenVegas /v1/agent/infer for AI inference
    │   └─ $V deducted from session envelope
    │
    ├─ Agent checks /v1/agent/budget → 12 $V remaining, needs ~50 $V to finish
    │
    ├─ DECISION POINT: Agent can either:
    │   ├─ Request a deterministic boost challenge (/v1/agent/boost/challenge)
    │   │   └─ Complete coding task, get scored, earn up to 50 $V
    │   │
    │   └─ Enter casino mode (/v1/agent/casino/sessions/start)
    │       ├─ Play blackjack with 12 $V stake
    │       ├─ Win → now has 24 $V → continue task
    │       └─ Lose → session exhausted → request human approval for top-up
    │
    └─ Agent continues task with replenished budget
```

### OpenVegas as x402-Compatible Service

When an agent calls OpenVegas and has insufficient $V, we can return HTTP 402 with a payment object. The agent's wallet/payment plugin handles the rest:

```
Agent → GET /v1/agent/infer
        ← 402 Payment Required
        ← X-Payment: {"amount": "0.50", "currency": "USDC", "address": "0x..."}

Agent wallet plugin → sends 0.50 USDC on-chain
        → includes tx_hash in retry header

Agent → POST /v1/agent/infer (X-Payment-Proof: tx_hash)
        ← 200 OK (inference result)
```

This is future work (Phase F) but the architecture supports it cleanly because $V is already a metered internal currency.

### Security Considerations for Agent Integrations

1. **Malicious skills/plugins** — OpenVegas validates all agent tokens server-side; a compromised skill cannot escalate scopes
2. **Wallet drain** — Session envelopes + per-round wager caps prevent unbounded loss
3. **Prompt injection** — Agent-submitted prompts for boost challenges are sandboxed; scoring is deterministic (no LLM in the judge loop)
4. **Replay attacks** — Idempotency keys on every casino move and boost submission prevent double-counting

### How OpenVegas Makes Money From Agent Traffic

| Revenue Stream | Mechanism |
|---|---|
| Inference markup | ~20% spread on $V-to-token conversion |
| Casino house edge | 1-5% across game RTPs (97-99% RTP) |
| Boost spread | 8% mint spread on BYOK burns used to fund boosts |
| Session fees | Flat fee per agent session start |
| x402 routing fee | Future: 1-2% on crypto payment routing |
| Enterprise subscription | Org-level monthly fee for admin controls + SLA |

---

## Code Snippets for Implementation

### Existing Code We Reuse (do not rewrite)

- `openvegas/wallet/ledger.py` — `WalletService` with `_execute(entry, *, tx=None)`, `place_bet`, `settle_win`, `settle_loss`, `ensure_escrow_account`
- `openvegas/rng/provably_fair.py` — `ProvablyFairRNG` with `new_round()`, `generate_outcome()`, `reveal()`, `verify()`
- `openvegas/games/base.py` — `BaseGame` ABC, `GameResult` dataclass
- `server/middleware/auth.py` — `get_current_user()` for Supabase JWT validation

---

### Migration: `supabase/migrations/002_enterprise_agent_casino.sql`

```sql
-- ============================================================
-- ENTERPRISE ORGS
-- ============================================================

CREATE TABLE organizations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    billing_customer_id TEXT,
    status TEXT DEFAULT 'active' CHECK (status IN ('active', 'suspended', 'cancelled')),
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE org_members (
    org_id UUID NOT NULL REFERENCES organizations(id),
    user_id UUID NOT NULL REFERENCES auth.users(id),
    role TEXT NOT NULL DEFAULT 'member' CHECK (role IN ('owner', 'admin', 'member')),
    status TEXT DEFAULT 'active',
    created_at TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (org_id, user_id)
);

CREATE TABLE org_sponsorships (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL REFERENCES organizations(id),
    monthly_budget_usd NUMERIC(12,2) NOT NULL,
    refill_rule TEXT DEFAULT 'manual' CHECK (refill_rule IN ('manual', 'auto_stripe')),
    status TEXT DEFAULT 'active',
    renewed_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE org_policies (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID UNIQUE NOT NULL REFERENCES organizations(id),
    allowed_providers TEXT[] DEFAULT ARRAY['openai','anthropic','gemini'],
    allowed_models TEXT[] DEFAULT ARRAY[]::TEXT[],
    user_daily_cap_usd NUMERIC(10,2) DEFAULT 50.00,
    byok_fallback_enabled BOOLEAN DEFAULT FALSE,
    boost_enabled BOOLEAN DEFAULT TRUE,
    casino_enabled BOOLEAN DEFAULT FALSE,
    casino_agent_max_loss_v NUMERIC(18,2) DEFAULT 100.00,
    casino_round_max_wager_v NUMERIC(18,2) DEFAULT 10.00,
    casino_round_cooldown_ms INT DEFAULT 500,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE org_budget_ledger (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL REFERENCES organizations(id),
    source TEXT NOT NULL,
    delta_usd NUMERIC(12,4) NOT NULL,
    reference_id TEXT,
    created_at TIMESTAMPTZ DEFAULT now()
);

-- ============================================================
-- AGENT SERVICE ACCOUNTS
-- ============================================================

CREATE TABLE agent_accounts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL REFERENCES organizations(id),
    name TEXT NOT NULL,
    status TEXT DEFAULT 'active' CHECK (status IN ('active', 'suspended', 'revoked')),
    created_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE (org_id, name)
);

CREATE TABLE agent_tokens (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_account_id UUID NOT NULL REFERENCES agent_accounts(id),
    scopes TEXT[] NOT NULL,
    token_hash TEXT NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    revoked_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE agent_sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_account_id UUID NOT NULL REFERENCES agent_accounts(id),
    org_id UUID NOT NULL REFERENCES organizations(id),
    envelope_v NUMERIC(18,2) NOT NULL,
    spent_v NUMERIC(18,2) DEFAULT 0,
    status TEXT DEFAULT 'active' CHECK (status IN ('active', 'exhausted', 'closed')),
    started_at TIMESTAMPTZ DEFAULT now(),
    ended_at TIMESTAMPTZ
);

-- ============================================================
-- DETERMINISTIC BOOSTS
-- ============================================================

CREATE TABLE boost_challenges (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL REFERENCES organizations(id),
    agent_session_id UUID NOT NULL REFERENCES agent_sessions(id),
    rubric_version TEXT NOT NULL,
    task_prompt TEXT NOT NULL,
    rubric_json JSONB NOT NULL,
    max_reward_v NUMERIC(18,2) NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    status TEXT DEFAULT 'pending' CHECK (status IN ('pending', 'submitted', 'scored', 'expired')),
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE boost_submissions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    challenge_id UUID UNIQUE NOT NULL REFERENCES boost_challenges(id),
    artifact_hash TEXT NOT NULL,
    artifact_text TEXT NOT NULL,
    score NUMERIC(5,2),
    reward_v NUMERIC(18,2),
    status TEXT DEFAULT 'pending' CHECK (status IN ('pending', 'scored', 'rewarded', 'rejected')),
    created_at TIMESTAMPTZ DEFAULT now()
);

-- ============================================================
-- AGENT-ONLY CASINO
-- ============================================================

CREATE TABLE casino_game_catalog (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    game_code TEXT UNIQUE NOT NULL,
    version INT DEFAULT 1,
    rtp NUMERIC(5,4) NOT NULL,
    rules_json JSONB NOT NULL,
    payout_table_json JSONB NOT NULL,
    enabled BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE casino_sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL REFERENCES organizations(id),
    agent_account_id UUID NOT NULL REFERENCES agent_accounts(id),
    agent_session_id UUID NOT NULL REFERENCES agent_sessions(id),
    max_loss_v NUMERIC(18,2) NOT NULL,
    max_rounds INT DEFAULT 100,
    rounds_played INT DEFAULT 0,
    net_pnl_v NUMERIC(18,2) DEFAULT 0,
    status TEXT DEFAULT 'active' CHECK (status IN ('active', 'loss_capped', 'round_capped', 'closed')),
    started_at TIMESTAMPTZ DEFAULT now(),
    ended_at TIMESTAMPTZ
);

CREATE TABLE casino_rounds (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID NOT NULL REFERENCES casino_sessions(id),
    game_code TEXT NOT NULL,
    wager_v NUMERIC(18,2) NOT NULL,
    state_json JSONB DEFAULT '{}',
    rng_commit TEXT NOT NULL,
    rng_reveal TEXT,
    client_seed TEXT NOT NULL,
    nonce INT NOT NULL,
    status TEXT DEFAULT 'active' CHECK (status IN ('active', 'resolved')),
    started_at TIMESTAMPTZ DEFAULT now(),
    resolved_at TIMESTAMPTZ
);

CREATE TABLE casino_moves (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    round_id UUID NOT NULL REFERENCES casino_rounds(id),
    move_index INT NOT NULL,
    action TEXT NOT NULL,
    payload_json JSONB DEFAULT '{}',
    idempotency_key TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE (round_id, idempotency_key)
);

CREATE TABLE casino_payouts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    round_id UUID UNIQUE NOT NULL REFERENCES casino_rounds(id),
    wager_v NUMERIC(18,2) NOT NULL,
    payout_v NUMERIC(18,2) NOT NULL,
    net_v NUMERIC(18,2) NOT NULL,
    ledger_ref TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE casino_verifications (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    round_id UUID UNIQUE NOT NULL REFERENCES casino_rounds(id),
    commit_hash TEXT NOT NULL,
    reveal_seed TEXT NOT NULL,
    client_seed TEXT NOT NULL,
    nonce INT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT now()
);

-- ============================================================
-- SEED CASINO CATALOG
-- ============================================================

INSERT INTO casino_game_catalog (game_code, rtp, rules_json, payout_table_json) VALUES
('blackjack', 0.9950, '{"decks":1,"dealer_stands_on":17}', '{"blackjack":2.5,"win":2,"push":1}'),
('roulette', 0.9730, '{"type":"european","zeros":1}', '{"straight":36,"red":2,"black":2,"odd":2,"even":2}'),
('slots', 0.9500, '{"reels":3,"symbols":["7","BAR","CHERRY","LEMON","BELL","STAR"]}', '{"777":50,"BAR3":20,"BELL3":10,"STAR3":8,"CHERRY3":5,"CHERRY2":2}'),
('poker', 0.9540, '{"variant":"five_card_draw","draw_count":1}', '{"royal_flush":250,"straight_flush":50,"four_kind":25,"full_house":9,"flush":6,"straight":4,"three_kind":3,"two_pair":2,"jacks_better":1}'),
('baccarat', 0.9862, '{"decks":6,"commission":0.05}', '{"player_wins":2,"banker_wins":1.95,"tie":9}')
ON CONFLICT (game_code) DO NOTHING;

-- ============================================================
-- RLS POLICIES
-- ============================================================

ALTER TABLE organizations ENABLE ROW LEVEL SECURITY;
ALTER TABLE org_members ENABLE ROW LEVEL SECURITY;
ALTER TABLE agent_accounts ENABLE ROW LEVEL SECURITY;
ALTER TABLE agent_sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE casino_sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE casino_rounds ENABLE ROW LEVEL SECURITY;
ALTER TABLE casino_game_catalog ENABLE ROW LEVEL SECURITY;

CREATE POLICY casino_catalog_public ON casino_game_catalog FOR SELECT USING (true);
```

---

### Auth Middleware Extensions: `server/middleware/auth.py`

Adds agent token validation and human-user rejection for casino routes. The existing `get_current_user` for Supabase JWTs is untouched.

```python
import hashlib
from server.services.dependencies import get_db


async def get_current_agent(request: Request) -> dict:
    """Validate agent bearer token (ov_agent_* prefix, not Supabase JWT).
    Looks up token_hash in agent_tokens, checks expiry and revocation."""
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer ov_agent_"):
        raise HTTPException(401, "Invalid agent token format — expected ov_agent_* prefix")

    token = auth.removeprefix("Bearer ")
    token_hash = hashlib.sha256(token.encode()).hexdigest()

    db = get_db()
    row = await db.fetchrow(
        """SELECT at.agent_account_id, at.scopes, at.expires_at,
                  aa.org_id, aa.name AS agent_name, aa.status AS agent_status
           FROM agent_tokens at
           JOIN agent_accounts aa ON at.agent_account_id = aa.id
           WHERE at.token_hash = $1
             AND at.revoked_at IS NULL
             AND at.expires_at > now()
             AND aa.status = 'active'""",
        token_hash,
    )
    if not row:
        raise HTTPException(401, "Agent token invalid, expired, or revoked")

    return {
        "agent_account_id": str(row["agent_account_id"]),
        "org_id": str(row["org_id"]),
        "agent_name": row["agent_name"],
        "scopes": list(row["scopes"]),
        "account_type": "agent",
    }


def require_scope(scope: str):
    """FastAPI Depends wrapper — checks agent token has the required scope."""
    async def _check(agent: dict = Depends(get_current_agent)):
        if scope not in agent["scopes"]:
            raise HTTPException(403, f"Missing required scope: {scope}")
        return agent
    return _check


async def reject_human_users(request: Request):
    """Dependency for casino routes — rejects Supabase human JWTs.
    Agent tokens use ov_agent_* prefix; Supabase JWTs start with ey (base64)."""
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer ey"):
        raise HTTPException(403, "Casino mode is restricted to agent service accounts. Human JWTs are not allowed.")
```

---

### Agent Service: `openvegas/agent/service.py`

Handles service account creation, scoped token issuance, and session envelope management.

```python
"""Agent service — accounts, tokens, and session envelopes."""

from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from openvegas.wallet.ledger import WalletService


class AgentService:
    def __init__(self, db: Any, wallet: WalletService):
        self.db = db
        self.wallet = wallet

    async def create_account(self, org_id: str, name: str) -> dict:
        agent_id = str(uuid.uuid4())
        await self.db.execute(
            "INSERT INTO agent_accounts (id, org_id, name) VALUES ($1, $2, $3)",
            agent_id, org_id, name,
        )
        # Create a wallet account for this agent (prefixed agent: instead of user:)
        await self.db.execute(
            "INSERT INTO wallet_accounts (account_id, balance) VALUES ($1, 0) ON CONFLICT DO NOTHING",
            f"agent:{agent_id}",
        )
        return {"agent_account_id": agent_id, "org_id": org_id, "name": name}

    async def issue_token(
        self, agent_account_id: str, scopes: list[str], ttl_minutes: int = 60
    ) -> str:
        """Generate ov_agent_<random> token, store SHA-256 hash, return plaintext ONCE."""
        token = f"ov_agent_{secrets.token_urlsafe(32)}"
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=ttl_minutes)

        await self.db.execute(
            """INSERT INTO agent_tokens (agent_account_id, scopes, token_hash, expires_at)
               VALUES ($1, $2, $3, $4)""",
            agent_account_id, scopes, token_hash, expires_at,
        )
        return token  # caller stores this; we only keep the hash

    async def start_session(
        self, agent_account_id: str, org_id: str, envelope_v: Decimal
    ) -> dict:
        """Create agent session with a spend envelope (max $V for this session)."""
        session_id = str(uuid.uuid4())
        await self.db.execute(
            """INSERT INTO agent_sessions (id, agent_account_id, org_id, envelope_v)
               VALUES ($1, $2, $3, $4)""",
            session_id, agent_account_id, org_id, float(envelope_v),
        )
        return {
            "session_id": session_id,
            "envelope_v": str(envelope_v),
            "spent_v": "0",
            "remaining_v": str(envelope_v),
            "status": "active",
        }

    async def check_session_budget(self, session_id: str, amount_v: Decimal) -> bool:
        """True if session has enough remaining envelope for this spend."""
        row = await self.db.fetchrow(
            "SELECT envelope_v, spent_v, status FROM agent_sessions WHERE id = $1",
            session_id,
        )
        if not row or row["status"] != "active":
            return False
        remaining = Decimal(str(row["envelope_v"])) - Decimal(str(row["spent_v"]))
        return remaining >= amount_v

    async def record_spend(self, session_id: str, amount_v: Decimal):
        """Increment session spent_v. Auto-close if envelope exhausted."""
        await self.db.execute(
            "UPDATE agent_sessions SET spent_v = spent_v + $1 WHERE id = $2",
            float(amount_v), session_id,
        )
        # Check if exhausted
        row = await self.db.fetchrow(
            "SELECT envelope_v, spent_v FROM agent_sessions WHERE id = $1", session_id
        )
        if row and Decimal(str(row["spent_v"])) >= Decimal(str(row["envelope_v"])):
            await self.db.execute(
                "UPDATE agent_sessions SET status = 'exhausted', ended_at = now() WHERE id = $1",
                session_id,
            )

    async def get_budget(self, session_id: str) -> dict:
        row = await self.db.fetchrow(
            "SELECT * FROM agent_sessions WHERE id = $1", session_id
        )
        if not row:
            return {"error": "Session not found"}
        envelope = Decimal(str(row["envelope_v"]))
        spent = Decimal(str(row["spent_v"]))
        return {
            "session_id": session_id,
            "envelope_v": str(envelope),
            "spent_v": str(spent),
            "remaining_v": str(envelope - spent),
            "status": row["status"],
        }

    async def close_session(self, session_id: str):
        await self.db.execute(
            "UPDATE agent_sessions SET status = 'closed', ended_at = now() WHERE id = $1",
            session_id,
        )
```

---

### OpenClaw Skill Manifest: `openvegas/agent/openclaw_skill.py`

This is what an OpenClaw agent installs to discover and call OpenVegas APIs. It follows the standard skill manifest pattern used in the OpenClaw ecosystem.

```python
"""OpenClaw / agent runtime skill manifest.

An agent runtime like OpenClaw loads this manifest to discover
what actions OpenVegas exposes. The agent then calls these as
HTTP tool-use actions with its ov_agent_* bearer token.

The flow mirrors the x402 agentic commerce pattern:
  1. Agent discovers OpenVegas via this skill manifest
  2. Agent authenticates with pre-issued ov_agent_* token (org admin creates it)
  3. Agent starts a session → gets a spend envelope
  4. Agent calls inference → $V deducted from envelope
  5. Budget low? → agent requests boost challenge or enters casino mode
  6. All spend attributed to org + agent for audit
"""

OPENVEGAS_SKILL_MANIFEST = {
    "name": "openvegas",
    "description": "Compute infrastructure for autonomous agents — inference routing, deterministic boosts, and casino games for probabilistic compute top-ups",
    "version": "0.1.0",
    "base_url": "https://api.openvegas.gg",
    "auth": {
        "type": "bearer",
        "token_prefix": "ov_agent_",
        "header": "Authorization",
        "note": "Token issued by org admin via: openvegas agent token issue --agent <name> --scopes infer,boost,casino.play,budget.read",
    },
    "actions": [
        {
            "name": "start_session",
            "description": "Start a metered session. Agent gets a $V spend envelope.",
            "method": "POST",
            "path": "/v1/agent/sessions/start",
            "body": {"envelope_v": "number — max $V for this session"},
            "returns": {"session_id": "string", "envelope_v": "string", "remaining_v": "string"},
            "scope_required": "infer",
        },
        {
            "name": "infer",
            "description": "Run metered AI inference. Deducts from session envelope. Routes to OpenAI, Anthropic, or Gemini based on provider param.",
            "method": "POST",
            "path": "/v1/agent/infer",
            "body": {
                "session_id": "string",
                "prompt": "string",
                "provider": "openai | anthropic | gemini",
                "model": "string — e.g. gpt-4o-mini, claude-sonnet-4-20250514, gemini-2.0-flash",
            },
            "returns": {"text": "string", "v_cost": "string", "input_tokens": "int", "output_tokens": "int"},
            "scope_required": "infer",
        },
        {
            "name": "check_budget",
            "description": "Check how much $V remains in current session envelope.",
            "method": "GET",
            "path": "/v1/agent/budget?session_id={session_id}",
            "returns": {"remaining_v": "string", "spent_v": "string", "status": "string"},
            "scope_required": "budget.read",
        },
        {
            "name": "request_boost_challenge",
            "description": "Request a deterministic coding challenge. Complete it to earn $V. No LLM in the scoring loop — pure code checks (compiles, has docstring, passes lint, etc.).",
            "method": "POST",
            "path": "/v1/agent/boost/challenge",
            "body": {"session_id": "string"},
            "returns": {"challenge_id": "string", "task_prompt": "string", "max_reward_v": "string", "rubric": "object", "expires_at": "string"},
            "scope_required": "boost",
        },
        {
            "name": "submit_boost",
            "description": "Submit code artifact for deterministic scoring. Reward credited if score >= threshold.",
            "method": "POST",
            "path": "/v1/agent/boost/submit",
            "body": {"challenge_id": "string", "artifact_text": "string — the Python code you wrote"},
            "returns": {"score": "number", "reward_v": "string", "details": "object"},
            "scope_required": "boost",
        },
        {
            "name": "casino_start_session",
            "description": "Start an agent-only casino session. Human users cannot use this. Wager $V on games of chance for probabilistic compute top-ups.",
            "method": "POST",
            "path": "/v1/agent/casino/sessions/start",
            "body": {"session_id": "string — parent agent session", "max_loss_v": "number"},
            "returns": {"casino_session_id": "string", "max_loss_v": "string", "max_rounds": "int"},
            "scope_required": "casino.play",
        },
        {
            "name": "casino_list_games",
            "description": "List available casino games with rules and RTP.",
            "method": "GET",
            "path": "/v1/agent/casino/games",
            "returns": [{"game_code": "string", "rtp": "number", "rules": "object"}],
            "scope_required": "casino.play",
        },
        {
            "name": "casino_start_round",
            "description": "Place a wager and start a new game round. Returns initial game state and valid actions.",
            "method": "POST",
            "path": "/v1/agent/casino/rounds/start",
            "body": {
                "casino_session_id": "string",
                "game_code": "poker | blackjack | baccarat | roulette | slots",
                "wager_v": "number",
            },
            "returns": {"round_id": "string", "state": "object", "valid_actions": ["string"]},
            "scope_required": "casino.play",
        },
        {
            "name": "casino_action",
            "description": "Submit a game action (hit, stand, draw, hold, bet_player, bet_banker, spin). Idempotent via idempotency_key.",
            "method": "POST",
            "path": "/v1/agent/casino/rounds/{round_id}/action",
            "body": {
                "action": "string — game-specific",
                "payload": "object — optional (e.g. {positions: [0,2]} for poker hold)",
                "idempotency_key": "string — unique per move, prevents double-apply",
            },
            "returns": {"state": "object", "valid_actions": ["string"]},
            "scope_required": "casino.play",
        },
        {
            "name": "casino_resolve",
            "description": "Finalize the round, reveal RNG seed, settle wager/payout. Returns result and proof data.",
            "method": "POST",
            "path": "/v1/agent/casino/rounds/{round_id}/resolve",
            "returns": {
                "payout_v": "string",
                "net_v": "string",
                "outcome": "object",
                "rng_reveal": "string — server seed for verification",
            },
            "scope_required": "casino.play",
        },
    ],
}
```

---

### Deterministic Boost Engine: `openvegas/agent/boost.py`

Scoring is purely deterministic — `compile()`, string checks, subprocess `ruff` — no LLM in the judge loop.

```python
"""Deterministic boost engine — challenge issuance, scoring, and reward settlement."""

from __future__ import annotations

import hashlib
import subprocess
import tempfile
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from openvegas.wallet.ledger import WalletService


BOOST_RUBRICS = {
    "v1_code_quality": {
        "version": "v1",
        "task_templates": [
            "Write a Python function that reverses a linked list. Include docstring and type hints.",
            "Write a Python function that finds the longest common subsequence of two strings. Include docstring and type hints.",
            "Write a Python function that implements a basic LRU cache. Include docstring and type hints.",
            "Write a Python function that validates an email address using regex. Include docstring and type hints.",
            "Write a Python function that merges two sorted lists into one sorted list. Include docstring and type hints.",
        ],
        "criteria": [
            {"name": "compiles", "weight": 0.30, "check": "compile_check"},
            {"name": "has_docstring", "weight": 0.20, "check": "docstring_check"},
            {"name": "has_type_hints", "weight": 0.20, "check": "type_hint_check"},
            {"name": "passes_lint", "weight": 0.15, "check": "ruff_check"},
            {"name": "length_adequate", "weight": 0.15, "check": "length_check"},
        ],
        "min_score_for_reward": 0.6,
    },
}


class BoostVerifier:
    """Deterministic scoring — no LLM in the loop, pure code checks."""

    def score(self, rubric_version: str, artifact_text: str) -> tuple[float, dict]:
        rubric = BOOST_RUBRICS[rubric_version]
        results = {}
        total = 0.0

        for criterion in rubric["criteria"]:
            check_fn = getattr(self, f"_{criterion['check']}")
            passed = check_fn(artifact_text)
            results[criterion["name"]] = passed
            if passed:
                total += criterion["weight"]

        return round(total, 2), results

    def _compile_check(self, code: str) -> bool:
        try:
            compile(code, "<boost>", "exec")
            return True
        except SyntaxError:
            return False

    def _docstring_check(self, code: str) -> bool:
        return '"""' in code or "'''" in code

    def _type_hint_check(self, code: str) -> bool:
        indicators = ["->", ": str", ": int", ": list", ": dict", ": bool", ": float", ": None"]
        return any(ind in code for ind in indicators)

    def _ruff_check(self, code: str) -> bool:
        try:
            with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False) as f:
                f.write(code)
                f.flush()
                result = subprocess.run(
                    ["ruff", "check", "--select", "E,W", f.name],
                    capture_output=True, timeout=10,
                )
                return result.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return True  # ruff not installed or timeout — pass by default

    def _length_check(self, code: str) -> bool:
        lines = code.strip().split("\n")
        return 5 <= len(lines) <= 200


class BoostService:
    def __init__(self, db: Any, wallet: WalletService, verifier: BoostVerifier | None = None):
        self.db = db
        self.wallet = wallet
        self.verifier = verifier or BoostVerifier()

    async def create_challenge(
        self, org_id: str, session_id: str, max_reward_v: float = 50.0
    ) -> dict:
        import random
        rubric = BOOST_RUBRICS["v1_code_quality"]
        task_prompt = random.choice(rubric["task_templates"])
        challenge_id = str(uuid.uuid4())
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=5)

        await self.db.execute(
            """INSERT INTO boost_challenges
               (id, org_id, agent_session_id, rubric_version, task_prompt, rubric_json,
                max_reward_v, expires_at)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8)""",
            challenge_id, org_id, session_id, "v1_code_quality",
            task_prompt, {"criteria": rubric["criteria"]},
            max_reward_v, expires_at,
        )

        return {
            "challenge_id": challenge_id,
            "task_prompt": task_prompt,
            "max_reward_v": str(max_reward_v),
            "rubric": rubric["criteria"],
            "expires_at": expires_at.isoformat(),
        }

    async def submit_and_score(
        self, challenge_id: str, artifact_text: str, agent_account_id: str
    ) -> dict:
        # Load challenge
        row = await self.db.fetchrow(
            "SELECT * FROM boost_challenges WHERE id = $1", challenge_id
        )
        if not row:
            raise ValueError("Challenge not found")
        if row["status"] != "pending":
            raise ValueError(f"Challenge already {row['status']}")
        if datetime.now(timezone.utc) > row["expires_at"]:
            raise ValueError("Challenge expired")

        # Score deterministically
        score, details = self.verifier.score("v1_code_quality", artifact_text)
        max_reward = Decimal(str(row["max_reward_v"]))
        rubric = BOOST_RUBRICS["v1_code_quality"]
        reward_v = Decimal("0")

        if score >= rubric["min_score_for_reward"]:
            reward_v = (max_reward * Decimal(str(score))).quantize(Decimal("0.01"))

        artifact_hash = hashlib.sha256(artifact_text.encode()).hexdigest()

        # All writes in one transaction: submission + challenge update + wallet credit
        async with self.db.transaction() as tx:
            await tx.execute(
                """INSERT INTO boost_submissions
                   (challenge_id, artifact_hash, artifact_text, score, reward_v, status)
                   VALUES ($1, $2, $3, $4, $5, $6)""",
                challenge_id, artifact_hash, artifact_text,
                float(score), float(reward_v),
                "rewarded" if reward_v > 0 else "scored",
            )
            await tx.execute(
                "UPDATE boost_challenges SET status = 'scored' WHERE id = $1",
                challenge_id,
            )

            if reward_v > 0:
                # Credit the agent's wallet from mint_reserve (new $V enters system).
                # Wallet account_id convention: agents use "agent:<uuid>", humans use "user:<uuid>".
                # ensure_account and mint accept full prefixed account_id strings.
                agent_wallet_id = f"agent:{agent_account_id}"
                await self.wallet.ensure_account(agent_wallet_id)
                await self.wallet.mint(
                    account_id=agent_wallet_id,
                    amount=reward_v,
                    mint_id=f"boost:{challenge_id}",
                    tx=tx,
                )

        return {
            "score": score,
            "reward_v": str(reward_v),
            "details": details,
            "status": "rewarded" if reward_v > 0 else "below_threshold",
        }
```

---

### Casino Base: `openvegas/casino/base.py`

Extends the existing `BaseGame` pattern but for multi-action casino rounds (not single-resolve like horse racing).

```python
"""Casino game interface — multi-action rounds with state machines."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from decimal import Decimal

from openvegas.rng.provably_fair import ProvablyFairRNG


@dataclass
class CasinoRoundState:
    round_id: str
    game_code: str
    wager_v: Decimal
    state: dict = field(default_factory=dict)
    actions_taken: list = field(default_factory=list)
    resolved: bool = False
    payout_multiplier: Decimal = Decimal("0")
    outcome_data: dict = field(default_factory=dict)


class BaseCasinoGame(ABC):
    game_code: str
    rtp: Decimal

    @abstractmethod
    def initial_state(self, rng: ProvablyFairRNG, client_seed: str, nonce: int) -> dict:
        """Set up initial game state (deal cards, etc.)."""
        ...

    @abstractmethod
    def apply_action(
        self, state: dict, action: str, payload: dict,
        rng: ProvablyFairRNG, client_seed: str, nonce: int
    ) -> dict:
        """Apply player action, return updated state. Must be deterministic given same RNG."""
        ...

    @abstractmethod
    def resolve(self, state: dict) -> tuple[Decimal, dict]:
        """Resolve final outcome. Returns (payout_multiplier, outcome_data).
        payout = wager_v * payout_multiplier. 0 = loss, 1 = push, 2 = win, etc."""
        ...

    @abstractmethod
    def valid_actions(self, state: dict) -> list[str]:
        """Return list of valid actions for current state. Empty = must resolve."""
        ...

    @abstractmethod
    def is_resolved(self, state: dict) -> bool:
        """True if the round has concluded and needs resolution."""
        ...
```

---

### Blackjack: `openvegas/casino/blackjack.py`

```python
"""Blackjack — single-deck, dealer stands on 17."""

from decimal import Decimal
from openvegas.casino.base import BaseCasinoGame
from openvegas.rng.provably_fair import ProvablyFairRNG

DECK = [(r, s) for s in ["S","H","D","C"] for r in ["2","3","4","5","6","7","8","9","10","J","Q","K","A"]]


def hand_value(cards: list) -> int:
    total, aces = 0, 0
    for rank, _ in cards:
        if rank in ("J", "Q", "K"):
            total += 10
        elif rank == "A":
            aces += 1
            total += 11
        else:
            total += int(rank)
    while total > 21 and aces > 0:
        total -= 10
        aces -= 1
    return total


def cards_str(cards: list) -> list[str]:
    return [f"{r}{s}" for r, s in cards]


class BlackjackGame(BaseCasinoGame):
    game_code = "blackjack"
    rtp = Decimal("0.9950")

    def initial_state(self, rng: ProvablyFairRNG, client_seed: str, nonce: int) -> dict:
        deck = list(DECK)
        # Fisher-Yates shuffle with provably fair RNG
        for i in range(len(deck) - 1, 0, -1):
            j = rng.generate_outcome(client_seed, nonce + i, i + 1)
            deck[i], deck[j] = deck[j], deck[i]

        player = [deck.pop(), deck.pop()]
        dealer = [deck.pop(), deck.pop()]

        state = {
            "deck": [list(c) for c in deck],
            "player": [list(c) for c in player],
            "dealer": [list(c) for c in dealer],
            "phase": "player_turn",
        }

        # Check for natural blackjack
        if hand_value(player) == 21:
            state["phase"] = "resolved"

        return state

    def apply_action(self, state, action, payload, rng, client_seed, nonce):
        if state["phase"] != "player_turn":
            return state

        if action == "hit":
            state["player"].append(state["deck"].pop())
            if hand_value(state["player"]) > 21:
                state["phase"] = "resolved"  # bust
        elif action == "stand":
            # Dealer plays
            while hand_value(state["dealer"]) < 17:
                state["dealer"].append(state["deck"].pop())
            state["phase"] = "resolved"

        return state

    def resolve(self, state):
        pv = hand_value(state["player"])
        dv = hand_value(state["dealer"])

        # Natural blackjack
        if pv == 21 and len(state["player"]) == 2:
            if dv == 21 and len(state["dealer"]) == 2:
                return Decimal("1"), {"result": "push", "player": pv, "dealer": dv, "player_cards": cards_str(state["player"]), "dealer_cards": cards_str(state["dealer"])}
            return Decimal("2.5"), {"result": "blackjack", "player": pv, "dealer": dv, "player_cards": cards_str(state["player"]), "dealer_cards": cards_str(state["dealer"])}

        if pv > 21:
            return Decimal("0"), {"result": "bust", "player": pv, "dealer": dv, "player_cards": cards_str(state["player"]), "dealer_cards": cards_str(state["dealer"])}
        if dv > 21:
            return Decimal("2"), {"result": "dealer_bust", "player": pv, "dealer": dv, "player_cards": cards_str(state["player"]), "dealer_cards": cards_str(state["dealer"])}
        if pv > dv:
            return Decimal("2"), {"result": "win", "player": pv, "dealer": dv, "player_cards": cards_str(state["player"]), "dealer_cards": cards_str(state["dealer"])}
        if pv == dv:
            return Decimal("1"), {"result": "push", "player": pv, "dealer": dv, "player_cards": cards_str(state["player"]), "dealer_cards": cards_str(state["dealer"])}
        return Decimal("0"), {"result": "loss", "player": pv, "dealer": dv, "player_cards": cards_str(state["player"]), "dealer_cards": cards_str(state["dealer"])}

    def valid_actions(self, state):
        if state["phase"] == "player_turn":
            return ["hit", "stand"]
        return []

    def is_resolved(self, state):
        return state["phase"] == "resolved"
```

---

### Roulette: `openvegas/casino/roulette.py`

```python
"""European Roulette — single-zero wheel."""

from decimal import Decimal
from openvegas.casino.base import BaseCasinoGame
from openvegas.rng.provably_fair import ProvablyFairRNG

RED_NUMBERS = {1,3,5,7,9,12,14,16,18,19,21,23,25,27,30,32,34,36}


class RouletteGame(BaseCasinoGame):
    game_code = "roulette"
    rtp = Decimal("0.9730")

    def initial_state(self, rng, client_seed, nonce):
        return {"bet_type": None, "bet_value": None, "result": None, "phase": "betting"}

    def apply_action(self, state, action, payload, rng, client_seed, nonce):
        if action in ("bet_red", "bet_black", "bet_odd", "bet_even", "bet_number"):
            state["bet_type"] = action
            state["bet_value"] = payload.get("number")
            return state

        if action == "spin":
            state["result"] = rng.generate_outcome(client_seed, nonce, 37)  # 0-36
            state["phase"] = "resolved"
        return state

    def resolve(self, state):
        r = state["result"]
        bt = state["bet_type"]
        bv = state.get("bet_value")
        data = {"result": r, "bet_type": bt}

        if bt == "bet_number" and r == bv:
            return Decimal("36"), {**data, "hit": True}
        if bt == "bet_red" and r in RED_NUMBERS:
            return Decimal("2"), {**data, "hit": True}
        if bt == "bet_black" and r not in RED_NUMBERS and r != 0:
            return Decimal("2"), {**data, "hit": True}
        if bt == "bet_odd" and r != 0 and r % 2 == 1:
            return Decimal("2"), {**data, "hit": True}
        if bt == "bet_even" and r != 0 and r % 2 == 0:
            return Decimal("2"), {**data, "hit": True}
        return Decimal("0"), {**data, "hit": False}

    def valid_actions(self, state):
        if state["phase"] == "resolved":
            return []
        if state["bet_type"] is None:
            return ["bet_red", "bet_black", "bet_odd", "bet_even", "bet_number"]
        return ["spin"]

    def is_resolved(self, state):
        return state["phase"] == "resolved"
```

---

### Slots: `openvegas/casino/slots.py`

```python
"""3-Reel ASCII Slots."""

from decimal import Decimal
from openvegas.casino.base import BaseCasinoGame
from openvegas.rng.provably_fair import ProvablyFairRNG

SYMBOLS = ["7", "BAR", "CHERRY", "LEMON", "BELL", "STAR"]

PAYOUT_TABLE = {
    ("7","7","7"): Decimal("50"),
    ("BAR","BAR","BAR"): Decimal("20"),
    ("BELL","BELL","BELL"): Decimal("10"),
    ("STAR","STAR","STAR"): Decimal("8"),
    ("CHERRY","CHERRY","CHERRY"): Decimal("5"),
}


class SlotsGame(BaseCasinoGame):
    game_code = "slots"
    rtp = Decimal("0.9500")

    def initial_state(self, rng, client_seed, nonce):
        return {"reels": None, "phase": "ready"}

    def apply_action(self, state, action, payload, rng, client_seed, nonce):
        if action == "spin":
            reels = [
                SYMBOLS[rng.generate_outcome(client_seed, nonce + i, len(SYMBOLS))]
                for i in range(3)
            ]
            state["reels"] = reels
            state["phase"] = "resolved"
        return state

    def resolve(self, state):
        reels = tuple(state["reels"])
        data = {"reels": list(reels)}

        if reels in PAYOUT_TABLE:
            return PAYOUT_TABLE[reels], {**data, "hit": True}
        if reels[0] == "CHERRY" and reels[1] == "CHERRY":
            return Decimal("2"), {**data, "hit": True, "partial": "two_cherries"}
        return Decimal("0"), {**data, "hit": False}

    def valid_actions(self, state):
        return ["spin"] if state["phase"] == "ready" else []

    def is_resolved(self, state):
        return state["phase"] == "resolved"
```

---

### Poker: `openvegas/casino/poker.py`

```python
"""Five-Card Draw Poker (Jacks or Better)."""

from collections import Counter
from decimal import Decimal
from openvegas.casino.base import BaseCasinoGame
from openvegas.rng.provably_fair import ProvablyFairRNG

DECK = [(r, s) for s in ["S","H","D","C"] for r in ["2","3","4","5","6","7","8","9","10","J","Q","K","A"]]
RANK_ORDER = {"2":2,"3":3,"4":4,"5":5,"6":6,"7":7,"8":8,"9":9,"10":10,"J":11,"Q":12,"K":13,"A":14}

HAND_PAYOUTS = {
    "royal_flush": Decimal("250"),
    "straight_flush": Decimal("50"),
    "four_of_a_kind": Decimal("25"),
    "full_house": Decimal("9"),
    "flush": Decimal("6"),
    "straight": Decimal("4"),
    "three_of_a_kind": Decimal("3"),
    "two_pair": Decimal("2"),
    "jacks_or_better": Decimal("1"),
}


def evaluate_hand(cards: list) -> str:
    ranks = [c[0] for c in cards]
    suits = [c[1] for c in cards]
    values = sorted([RANK_ORDER[r] for r in ranks])
    counts = Counter(ranks)
    freq = sorted(counts.values(), reverse=True)
    is_flush = len(set(suits)) == 1
    is_straight = (values[-1] - values[0] == 4 and len(set(values)) == 5) or values == [2,3,4,5,14]

    if is_flush and is_straight:
        if values == [10,11,12,13,14]:
            return "royal_flush"
        return "straight_flush"
    if freq == [4, 1]:
        return "four_of_a_kind"
    if freq == [3, 2]:
        return "full_house"
    if is_flush:
        return "flush"
    if is_straight:
        return "straight"
    if freq == [3, 1, 1]:
        return "three_of_a_kind"
    if freq == [2, 2, 1]:
        return "two_pair"
    if freq == [2, 1, 1, 1]:
        pair_rank = [r for r, c in counts.items() if c == 2][0]
        if RANK_ORDER[pair_rank] >= 11:  # J, Q, K, A
            return "jacks_or_better"
    return "nothing"


class PokerGame(BaseCasinoGame):
    game_code = "poker"
    rtp = Decimal("0.9540")

    def initial_state(self, rng, client_seed, nonce):
        deck = list(DECK)
        for i in range(len(deck) - 1, 0, -1):
            j = rng.generate_outcome(client_seed, nonce + i, i + 1)
            deck[i], deck[j] = deck[j], deck[i]
        hand = [list(deck.pop()) for _ in range(5)]
        remaining = [list(c) for c in deck]
        return {"deck": remaining, "hand": hand, "phase": "draw"}

    def apply_action(self, state, action, payload, rng, client_seed, nonce):
        if action == "hold":
            keep_positions = set(payload.get("positions", []))
            new_hand = []
            for i, card in enumerate(state["hand"]):
                if i in keep_positions:
                    new_hand.append(card)
                else:
                    new_hand.append(state["deck"].pop())
            state["hand"] = new_hand
            state["phase"] = "resolved"
        elif action == "stand":
            state["phase"] = "resolved"
        return state

    def resolve(self, state):
        cards = [tuple(c) for c in state["hand"]]
        hand_rank = evaluate_hand(cards)
        multiplier = HAND_PAYOUTS.get(hand_rank, Decimal("0"))
        display = [f"{r}{s}" for r, s in cards]
        return multiplier, {"hand": display, "rank": hand_rank}

    def valid_actions(self, state):
        if state["phase"] == "draw":
            return ["hold", "stand"]
        return []

    def is_resolved(self, state):
        return state["phase"] == "resolved"
```

---

### Baccarat: `openvegas/casino/baccarat.py`

```python
"""Baccarat — player/banker/tie with standard third-card rules."""

from decimal import Decimal
from openvegas.casino.base import BaseCasinoGame
from openvegas.rng.provably_fair import ProvablyFairRNG

DECK = [(r, s) for s in ["S","H","D","C"] for r in ["A","2","3","4","5","6","7","8","9","10","J","Q","K"]]
CARD_VALUES = {"A":1,"2":2,"3":3,"4":4,"5":5,"6":6,"7":7,"8":8,"9":9,"10":0,"J":0,"Q":0,"K":0}


def hand_total(cards: list) -> int:
    return sum(CARD_VALUES[c[0]] for c in cards) % 10


class BaccaratGame(BaseCasinoGame):
    game_code = "baccarat"
    rtp = Decimal("0.9862")

    def initial_state(self, rng, client_seed, nonce):
        # 6-deck shoe shuffle
        shoe = list(DECK) * 6
        for i in range(len(shoe) - 1, 0, -1):
            j = rng.generate_outcome(client_seed, nonce + (i % 10000), i + 1)
            shoe[i], shoe[j] = shoe[j], shoe[i]
        return {"shoe": [list(c) for c in shoe], "bet_type": None, "player": [], "banker": [], "phase": "betting"}

    def apply_action(self, state, action, payload, rng, client_seed, nonce):
        if action in ("bet_player", "bet_banker", "bet_tie"):
            state["bet_type"] = action
            shoe = state["shoe"]
            state["player"] = [shoe.pop(), shoe.pop()]
            state["banker"] = [shoe.pop(), shoe.pop()]

            pt = hand_total(state["player"])
            bt = hand_total(state["banker"])

            # Natural — no third card
            if pt >= 8 or bt >= 8:
                state["phase"] = "resolved"
                return state

            # Player third card rule
            if pt <= 5:
                state["player"].append(shoe.pop())
                p3 = CARD_VALUES[state["player"][2][0]]
                # Banker third card rule (depends on player's third card)
                if bt <= 2:
                    state["banker"].append(shoe.pop())
                elif bt == 3 and p3 != 8:
                    state["banker"].append(shoe.pop())
                elif bt == 4 and p3 in (2,3,4,5,6,7):
                    state["banker"].append(shoe.pop())
                elif bt == 5 and p3 in (4,5,6,7):
                    state["banker"].append(shoe.pop())
                elif bt == 6 and p3 in (6,7):
                    state["banker"].append(shoe.pop())
            else:
                # Player stood — banker draws on 0-5
                if bt <= 5:
                    state["banker"].append(shoe.pop())

            state["phase"] = "resolved"
        return state

    def resolve(self, state):
        pt = hand_total(state["player"])
        bt = hand_total(state["banker"])
        bet = state["bet_type"]
        pc = [f"{r}{s}" for r, s in state["player"]]
        bc = [f"{r}{s}" for r, s in state["banker"]]
        data = {"player_total": pt, "banker_total": bt, "player_cards": pc, "banker_cards": bc}

        if pt == bt:
            if bet == "bet_tie":
                return Decimal("9"), {**data, "result": "tie_win"}
            return Decimal("1"), {**data, "result": "tie_push"}
        if pt > bt:
            if bet == "bet_player":
                return Decimal("2"), {**data, "result": "player_wins"}
            return Decimal("0"), {**data, "result": "player_wins"}
        # banker wins
        if bet == "bet_banker":
            return Decimal("1.95"), {**data, "result": "banker_wins"}  # 5% commission
        return Decimal("0"), {**data, "result": "banker_wins"}

    def valid_actions(self, state):
        if state["phase"] == "betting":
            return ["bet_player", "bet_banker", "bet_tie"]
        return []

    def is_resolved(self, state):
        return state["phase"] == "resolved"
```

---

### Casino Service: `openvegas/casino/service.py`

Orchestrates sessions, rounds, and ledger settlement. Uses the existing `WalletService._execute(tx=)` pattern for atomic wager+payout.

```python
"""Casino service — session management, round lifecycle, and ledger settlement."""

from __future__ import annotations

import json
import secrets
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from openvegas.casino.base import BaseCasinoGame
from openvegas.casino.blackjack import BlackjackGame
from openvegas.casino.roulette import RouletteGame
from openvegas.casino.slots import SlotsGame
from openvegas.casino.poker import PokerGame
from openvegas.casino.baccarat import BaccaratGame
from openvegas.rng.provably_fair import ProvablyFairRNG
from openvegas.wallet.ledger import WalletService, InsufficientBalance


CASINO_GAMES: dict[str, BaseCasinoGame] = {
    "blackjack": BlackjackGame(),
    "roulette": RouletteGame(),
    "slots": SlotsGame(),
    "poker": PokerGame(),
    "baccarat": BaccaratGame(),
}


class CasinoService:
    def __init__(self, db: Any, wallet: WalletService):
        self.db = db
        self.wallet = wallet

    async def start_session(
        self, org_id: str, agent_account_id: str,
        agent_session_id: str, max_loss_v: Decimal, max_rounds: int = 100,
    ) -> dict:
        """Start a casino session linked to a parent agent session.
        agent_session_id ties casino activity back to the agent's spend envelope."""
        # Validate parent agent session: must exist, belong to same agent+org, and be active
        parent = await self.db.fetchrow(
            """SELECT id, status FROM agent_sessions
               WHERE id = $1 AND agent_account_id = $2 AND org_id = $3""",
            agent_session_id, agent_account_id, org_id,
        )
        if not parent:
            raise ValueError("Parent agent session not found or does not belong to this agent/org")
        if parent["status"] != "active":
            raise ValueError(f"Parent agent session is '{parent['status']}', must be 'active'")

        # Check org policy
        policy = await self.db.fetchrow(
            "SELECT * FROM org_policies WHERE org_id = $1", org_id
        )
        if policy and not policy["casino_enabled"]:
            raise ValueError("Casino mode is disabled for this org")
        if policy:
            cap = Decimal(str(policy["casino_agent_max_loss_v"]))
            max_loss_v = min(max_loss_v, cap)

        session_id = str(uuid.uuid4())
        await self.db.execute(
            """INSERT INTO casino_sessions
               (id, org_id, agent_account_id, agent_session_id, max_loss_v, max_rounds)
               VALUES ($1, $2, $3, $4, $5, $6)""",
            session_id, org_id, agent_account_id, agent_session_id,
            float(max_loss_v), max_rounds,
        )
        return {
            "casino_session_id": session_id,
            "agent_session_id": agent_session_id,
            "max_loss_v": str(max_loss_v),
            "max_rounds": max_rounds,
            "status": "active",
        }

    async def start_round(
        self, session_id: str, game_code: str,
        wager_v: Decimal, agent_account_id: str,
    ) -> dict:
        # Validate session AND ownership — agent can only start rounds in their own session
        session = await self.db.fetchrow(
            "SELECT * FROM casino_sessions WHERE id = $1 AND agent_account_id = $2",
            session_id, agent_account_id,
        )
        if not session or session["status"] != "active":
            raise ValueError("Casino session is not active or does not belong to this agent")
        if session["rounds_played"] >= session["max_rounds"]:
            raise ValueError("Max rounds reached for this session")

        # Check loss cap: if net PnL is already at -max_loss_v, block new rounds
        current_loss = Decimal(str(session["net_pnl_v"]))
        max_loss = Decimal(str(session["max_loss_v"]))
        if current_loss <= -max_loss:
            await self.db.execute(
                "UPDATE casino_sessions SET status = 'loss_capped', ended_at = now() WHERE id = $1",
                session_id,
            )
            raise ValueError("Session loss cap reached")

        # Check per-round wager cap from org policy
        policy = await self.db.fetchrow(
            "SELECT casino_round_max_wager_v FROM org_policies WHERE org_id = $1",
            str(session["org_id"]),
        )
        if policy:
            round_cap = Decimal(str(policy["casino_round_max_wager_v"]))
            if wager_v > round_cap:
                raise ValueError(f"Wager {wager_v} exceeds round cap {round_cap}")

        # Get game engine
        game = CASINO_GAMES.get(game_code)
        if not game:
            raise ValueError(f"Unknown game: {game_code}")

        # Init RNG and game state
        rng = ProvablyFairRNG()
        commitment = rng.new_round()
        client_seed = secrets.token_hex(16)
        nonce = 0
        state = game.initial_state(rng, client_seed, nonce)

        round_id = str(uuid.uuid4())
        agent_wallet_id = f"agent:{agent_account_id}"

        # Atomic: escrow + round insert + session update in one transaction.
        # If any step fails, all roll back — no orphaned escrows or phantom rounds.
        await self.wallet.ensure_escrow_account(round_id)
        async with self.db.transaction() as tx:
            await self.wallet.place_bet(agent_wallet_id, wager_v, round_id, tx=tx)

            await tx.execute(
                """INSERT INTO casino_rounds
                   (id, session_id, game_code, wager_v, state_json, rng_commit, client_seed, nonce)
                   VALUES ($1, $2, $3, $4, $5, $6, $7, $8)""",
                round_id, session_id, game_code, float(wager_v),
                json.dumps({**state, "_server_seed": rng.server_seed}),
                commitment, client_seed, nonce,
            )

            await tx.execute(
                "UPDATE casino_sessions SET rounds_played = rounds_played + 1 WHERE id = $1",
                session_id,
            )

        # Strip internal seed from state shown to agent
        visible_state = {k: v for k, v in state.items() if not k.startswith("_")}

        return {
            "round_id": round_id,
            "rng_commit": commitment,
            "state": visible_state,
            "valid_actions": game.valid_actions(state),
        }

    async def apply_action(
        self, round_id: str, action: str, payload: dict,
        idempotency_key: str, agent_account_id: str,
    ) -> dict:
        # Ownership check: join through session to verify this agent owns the round
        row = await self.db.fetchrow(
            """SELECT cr.* FROM casino_rounds cr
               JOIN casino_sessions cs ON cr.session_id = cs.id
               WHERE cr.id = $1 AND cs.agent_account_id = $2""",
            round_id, agent_account_id,
        )
        if not row or row["status"] != "active":
            raise ValueError("Round is not active or does not belong to this agent")

        state = json.loads(row["state_json"]) if isinstance(row["state_json"], str) else row["state_json"]
        game = CASINO_GAMES[row["game_code"]]

        if action not in game.valid_actions(state):
            raise ValueError(f"Invalid action '{action}'. Valid: {game.valid_actions(state)}")

        # Reconstruct RNG from stored seed
        rng = ProvablyFairRNG()
        rng.server_seed = state.pop("_server_seed", "")
        rng.server_seed_hash = row["rng_commit"]

        # Get actual move count from DB (not from state dict) for deterministic nonce progression
        move_count_row = await self.db.fetchrow(
            "SELECT COUNT(*) AS cnt FROM casino_moves WHERE round_id = $1", round_id
        )
        move_count = move_count_row["cnt"] if move_count_row else 0

        # Nonce = base nonce + 100 (offset from initial_state nonces) + move_count
        action_nonce = row["nonce"] + 100 + move_count
        state = game.apply_action(state, action, payload, rng, row["client_seed"], action_nonce)

        # Atomic: move insert + state update in one transaction.
        # If either fails, both roll back — no desync between move log and round state.
        state["_server_seed"] = rng.server_seed  # put it back for next action
        async with self.db.transaction() as tx:
            await tx.execute(
                """INSERT INTO casino_moves (round_id, move_index, action, payload_json, idempotency_key)
                   VALUES ($1, $2, $3, $4, $5)""",
                round_id, move_count, action, json.dumps(payload), idempotency_key,
            )
            await tx.execute(
                "UPDATE casino_rounds SET state_json = $1 WHERE id = $2",
                json.dumps(state), round_id,
            )

        visible_state = {k: v for k, v in state.items() if not k.startswith("_")}
        return {
            "state": visible_state,
            "valid_actions": game.valid_actions(state),
            "is_resolved": game.is_resolved(state),
        }

    async def resolve_round(self, round_id: str, agent_account_id: str) -> dict:
        # Ownership check: join through session to verify this agent owns the round.
        # Payout goes to the session's agent_account_id (from DB), NOT the caller param,
        # as a defense-in-depth measure against round takeover.
        row = await self.db.fetchrow(
            """SELECT cr.*, cs.agent_account_id AS owner_agent_id, cs.id AS session_id_val
               FROM casino_rounds cr
               JOIN casino_sessions cs ON cr.session_id = cs.id
               WHERE cr.id = $1 AND cs.agent_account_id = $2""",
            round_id, agent_account_id,
        )
        if not row or row["status"] != "active":
            raise ValueError("Round is not active, already resolved, or does not belong to this agent")

        # Use the DB-verified owner, not the caller param, for payout.
        # Prefix with "agent:" to match the wallet account_id convention.
        verified_owner = f"agent:{row['owner_agent_id']}"

        state = json.loads(row["state_json"]) if isinstance(row["state_json"], str) else row["state_json"]
        game = CASINO_GAMES[row["game_code"]]
        server_seed = state.pop("_server_seed", "")

        if not game.is_resolved(state):
            raise ValueError("Round is not in a resolved state — submit remaining actions first")

        payout_multiplier, outcome_data = game.resolve(state)
        wager_v = Decimal(str(row["wager_v"]))
        payout_v = (wager_v * payout_multiplier).quantize(Decimal("0.01"))
        net_v = payout_v - wager_v

        # Atomic ledger settlement — ALL writes (wallet + payout record + round status
        # + session PnL) go through the same tx so they commit or rollback together.
        async with self.db.transaction() as tx:
            if payout_v > 0:
                await self.wallet.settle_win(verified_owner, payout_v, round_id, tx=tx)
                leftover = wager_v - payout_v
                if leftover > 0:
                    await self.wallet.settle_loss(round_id, leftover, tx=tx)
            else:
                await self.wallet.settle_loss(round_id, wager_v, tx=tx)

            ledger_ref = f"casino_payout:{round_id}"
            await tx.execute(
                """INSERT INTO casino_payouts (round_id, wager_v, payout_v, net_v, ledger_ref)
                   VALUES ($1, $2, $3, $4, $5)""",
                round_id, float(wager_v), float(payout_v), float(net_v), ledger_ref,
            )

            await tx.execute(
                "UPDATE casino_rounds SET status = 'resolved', rng_reveal = $1, resolved_at = now() WHERE id = $2",
                server_seed, round_id,
            )

            # Write verification record (dedicated table for clean verify endpoint reads)
            await tx.execute(
                """INSERT INTO casino_verifications
                   (round_id, commit_hash, reveal_seed, client_seed, nonce)
                   VALUES ($1, $2, $3, $4, $5)""",
                round_id, row["rng_commit"], server_seed, row["client_seed"], row["nonce"],
            )

            # Update session PnL
            session_id = str(row["session_id_val"])
            await tx.execute(
                "UPDATE casino_sessions SET net_pnl_v = net_pnl_v + $1 WHERE id = $2",
                float(net_v), session_id,
            )

        return {
            "round_id": round_id,
            "wager_v": str(wager_v),
            "payout_v": str(payout_v),
            "net_v": str(net_v),
            "outcome": outcome_data,
            "rng_reveal": server_seed,
            "rng_commit": row["rng_commit"],
        }

    async def get_session(self, session_id: str, agent_account_id: str) -> dict:
        """Ownership-enforced session read."""
        row = await self.db.fetchrow(
            "SELECT * FROM casino_sessions WHERE id = $1 AND agent_account_id = $2",
            session_id, agent_account_id,
        )
        if not row:
            raise ValueError("Session not found or does not belong to this agent")
        return {
            "casino_session_id": str(row["id"]),
            "max_loss_v": str(row["max_loss_v"]),
            "max_rounds": row["max_rounds"],
            "rounds_played": row["rounds_played"],
            "net_pnl_v": str(row["net_pnl_v"]),
            "status": row["status"],
        }
```

---

### Casino API Routes: `server/routes/casino.py`

All routes require `casino.play` scope and reject human JWTs.

```python
"""Agent-only casino API routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from server.middleware.auth import require_scope, reject_human_users
from server.services.dependencies import get_casino_service
from openvegas.wallet.ledger import InsufficientBalance

router = APIRouter(prefix="/v1/agent/casino")


class StartSessionRequest(BaseModel):
    agent_session_id: str  # parent agent session — links casino activity to spend envelope
    max_loss_v: float


class StartRoundRequest(BaseModel):
    casino_session_id: str
    game_code: str
    wager_v: float


class ActionRequest(BaseModel):
    action: str
    payload: dict = {}
    idempotency_key: str


@router.post("/sessions/start")
async def start_casino_session(
    req: StartSessionRequest,
    agent: dict = Depends(require_scope("casino.play")),
    _=Depends(reject_human_users),
):
    svc = get_casino_service()
    from decimal import Decimal
    try:
        return await svc.start_session(
            org_id=agent["org_id"],
            agent_account_id=agent["agent_account_id"],
            agent_session_id=req.agent_session_id,
            max_loss_v=Decimal(str(req.max_loss_v)),
        )
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/games")
async def list_games(
    agent: dict = Depends(require_scope("casino.play")),
    _=Depends(reject_human_users),
):
    from server.services.dependencies import get_db
    db = get_db()
    rows = await db.fetch("SELECT * FROM casino_game_catalog WHERE enabled = TRUE")
    return {"games": [dict(r) for r in rows]}


@router.post("/rounds/start")
async def start_round(
    req: StartRoundRequest,
    agent: dict = Depends(require_scope("casino.play")),
    _=Depends(reject_human_users),
):
    svc = get_casino_service()
    from decimal import Decimal
    try:
        return await svc.start_round(
            session_id=req.casino_session_id,
            game_code=req.game_code,
            wager_v=Decimal(str(req.wager_v)),
            agent_account_id=agent["agent_account_id"],
        )
    except (ValueError, InsufficientBalance) as e:
        raise HTTPException(400, str(e))


@router.post("/rounds/{round_id}/action")
async def submit_action(
    round_id: str,
    req: ActionRequest,
    agent: dict = Depends(require_scope("casino.play")),
    _=Depends(reject_human_users),
):
    svc = get_casino_service()
    try:
        return await svc.apply_action(
            round_id, req.action, req.payload,
            req.idempotency_key, agent["agent_account_id"],
        )
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/rounds/{round_id}/resolve")
async def resolve_round(
    round_id: str,
    agent: dict = Depends(require_scope("casino.play")),
    _=Depends(reject_human_users),
):
    svc = get_casino_service()
    try:
        return await svc.resolve_round(round_id, agent["agent_account_id"])
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/rounds/{round_id}/verify")
async def verify_round(
    round_id: str,
    agent: dict = Depends(require_scope("casino.play")),
):
    from server.services.dependencies import get_db
    db = get_db()
    # Read from casino_verifications (written atomically during resolve).
    # Ownership check via round -> session join.
    row = await db.fetchrow(
        """SELECT cv.*, cr.game_code FROM casino_verifications cv
           JOIN casino_rounds cr ON cv.round_id = cr.id
           JOIN casino_sessions cs ON cr.session_id = cs.id
           WHERE cv.round_id = $1 AND cs.agent_account_id = $2""",
        round_id, agent["agent_account_id"],
    )
    if not row:
        raise HTTPException(404, "Verification data not found — round may not be resolved yet, or does not belong to this agent")
    return {
        "round_id": round_id,
        "rng_commit": row["commit_hash"],
        "rng_reveal": row["reveal_seed"],
        "client_seed": row["client_seed"],
        "nonce": row["nonce"],
        "game_code": row["game_code"],
    }


@router.get("/sessions/{session_id}")
async def get_session(
    session_id: str,
    agent: dict = Depends(require_scope("casino.play")),
):
    svc = get_casino_service()
    try:
        return await svc.get_session(session_id, agent["agent_account_id"])
    except ValueError as e:
        raise HTTPException(404, str(e))
```

---

### Files to Create Summary

| File | Phase | Purpose |
|------|-------|---------|
| `supabase/migrations/002_enterprise_agent_casino.sql` | A | All new tables + RLS + casino seed data |
| `openvegas/enterprise/__init__.py` | A | Package init |
| `openvegas/enterprise/org_service.py` | A | Org CRUD, policy, sponsorship |
| `openvegas/agent/__init__.py` | B | Package init |
| `openvegas/agent/service.py` | B | Agent accounts, tokens, sessions |
| `openvegas/agent/openclaw_skill.py` | B | Skill manifest for agent runtimes |
| `openvegas/agent/boost.py` | C | Deterministic boost engine |
| `openvegas/casino/__init__.py` | D | Package init |
| `openvegas/casino/base.py` | D | BaseCasinoGame ABC |
| `openvegas/casino/blackjack.py` | D | Blackjack engine |
| `openvegas/casino/roulette.py` | D | Roulette engine |
| `openvegas/casino/slots.py` | D | Slots engine |
| `openvegas/casino/poker.py` | D | Poker engine |
| `openvegas/casino/baccarat.py` | D | Baccarat engine |
| `openvegas/casino/service.py` | D | Session/round/settle orchestrator |
| `server/routes/casino.py` | D | Agent-only casino API |
| `server/routes/agent.py` | B | Agent session/infer/budget API |
| `server/routes/boost.py` | C | Boost challenge/submit API |
| `server/routes/org.py` | A | Enterprise org admin API |

### Files to Modify

| File | Changes |
|------|---------|
| `server/middleware/auth.py` | Add `get_current_agent`, `require_scope`, `reject_human_users` |
| `server/main.py` | Register org, agent, boost, casino routers |
| `server/services/dependencies.py` | Add `get_agent_service`, `get_boost_service`, `get_casino_service`, `get_org_service` |
| `openvegas/cli.py` | Add `org` and `agent` command groups |
| `openvegas/wallet/ledger.py` | **Four changes:** (1) Add `*, tx=None` param to `place_bet`, `settle_win`, and `settle_loss` (same pattern as `mint`) — needed for atomic `start_round` and `resolve_round`. (2) Rename `user_id` params to `account_id` across `mint`, `place_bet`, `settle_win`, `get_balance`, `ensure_user_account`. Callers pass full prefixed strings (`user:<uuid>` or `agent:<uuid>`). (3) Add generic `ensure_account(account_id)` that accepts any prefix. (4) Update all existing consumers (`server/routes/games.py`, `openvegas/mint/engine.py`, `openvegas/gateway/inference.py`) to pass `f"user:{user_id}"` instead of bare `user_id`. |
| `openvegas/fraud/engine.py` | Add `check_casino_round` rate limiter |
