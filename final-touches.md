# OpenVegas Final Touches (Revised with Full Dependency and Safety Enhancements)

## Objective
Ship OpenVegas with production-safe correctness for:
1. Human user flow: BYOK mint -> wager -> win/loss -> redeem -> inference.
2. Agent flow (OpenClaw-style): tokenized agent auth -> session envelopes -> infer/boost/casino.
3. Multi-round casino sessions (longer than one round) with server-side enforcement.
4. Auditable company-directed token burn default policy.

## Canonical Accounting Principle (Locked)
To prevent accounting divergence, all new implementation follows this boundary:
1. `wallet/ledger` is the canonical source of `$V` money movement.
2. `inference_token_grants` is inventory entitlement for inference consumption, not money.
3. `session envelopes` are spend limits and reservation controls, not separate balances.

No feature may create an alternative source of truth for `$V`.

## Enhancement-by-Enhancement Incorporation

### 1) `store_orders.status` lifecycle (not default fulfilled)
Implemented in plan:
1. `status` default is `created`.
2. Valid states: `created`, `settled`, `fulfilled`, `failed`, `reversed`.
3. Transition rules are explicit and auditable.

Schema snippet:

```sql
CREATE TYPE store_order_status AS ENUM (
  'created', 'settled', 'fulfilled', 'failed', 'reversed'
);

CREATE TABLE store_orders (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES auth.users(id),
  item_id TEXT NOT NULL,
  cost_v NUMERIC(18,6) NOT NULL,
  status store_order_status NOT NULL DEFAULT 'created',
  idempotency_key TEXT NOT NULL,
  idempotency_payload_hash TEXT NOT NULL,
  failure_reason TEXT,
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now(),
  UNIQUE (user_id, idempotency_key)
);
```

### 2) Transaction boundary safety across wallet + order + grant writes
Implemented in plan:
1. `WalletService.redeem()` gains `tx` parameter.
2. Store service performs all writes using one caller-owned transaction/connection.
3. No cross-connection writes inside store purchase flow.

Code snippet:

```python
# wallet/ledger.py
async def redeem(self, account_id: str, amount: Decimal, reference_id: str, *, tx=None):
    entry = LedgerEntry(
        debit_account=account_id,
        credit_account="store",
        amount=amount,
        entry_type="redeem",
        reference_id=reference_id,
    )
    await self._execute(entry, tx=tx)
```

```python
# store/service.py (v2 canonical flow)
async with self.db.transaction() as tx:
    await tx.execute(
        """
        INSERT INTO store_orders (id, user_id, item_id, cost_v, status, idempotency_key, idempotency_payload_hash)
        VALUES ($1,$2,$3,$4,'created',$5,$6)
        """,
        order_id, user_id, item_id, cost_v, idempotency_key, payload_hash,
    )
    await self.wallet.redeem(
        f"user:{user_id}",
        cost_v,
        reference_id=f"store:{order_id}",
        tx=tx,
    )
    await transition_order(tx, order_id, "created", "settled")
    await issue_grants(tx, ...)
    await transition_order(tx, order_id, "settled", "fulfilled")
```

### 3) Replay and uniqueness protections on business references
Implemented in plan:
1. Keep existing ledger uniqueness invariant.
2. Add `UNIQUE (user_id, idempotency_key)` on `store_orders`.
3. Add `UNIQUE (source_order_id, provider, model_id)` for deterministic grant issuance.
4. Use `reference_id="store:<order_id>"` once only.

Schema snippet:

```sql
ALTER TABLE inference_token_grants
  ADD CONSTRAINT uq_grant_per_order_provider_model
  UNIQUE (source_order_id, provider, model_id);

CREATE TABLE IF NOT EXISTS inference_grant_usages (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  grant_id UUID NOT NULL REFERENCES inference_token_grants(id),
  inference_usage_id UUID,
  request_id TEXT NOT NULL,
  provider TEXT NOT NULL,
  model_id TEXT NOT NULL,
  tokens_used BIGINT NOT NULL CHECK (tokens_used > 0),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

### 4) Startup schema/version compatibility validation
Implemented in plan:
1. Add startup preflight after DB pool init.
2. Validate required tables/columns/indexes for active code paths.
3. Fail startup with actionable error if mismatched.

Code snippet:

```python
REQUIRED_TABLES = {
  "wallet_accounts",
  "ledger_entries",
  "mint_challenges",
  "mint_events",
  "provider_catalog",
  "inference_usage",
}

REQUIRED_COLUMNS = {
  ("inference_usage", "account_id"),
  ("inference_usage", "actor_type"),
  ("store_orders", "status"),
}

async def assert_schema_compatible(db, flags):
    # query information_schema and raise RuntimeError on missing artifacts
    ...
```

### 5) Company-directed mint as policy-sensitive and auditable
Implemented in plan:
1. Persist `purpose`, `disclosure_version`, `default_policy_version`.
2. Enforce allowed purpose values server-side.
3. Record the default policy active at challenge creation time.
4. Display explicit disclosure in CLI before confirmation.

Schema snippet:

```sql
ALTER TABLE mint_challenges
  ADD COLUMN IF NOT EXISTS purpose TEXT CHECK (purpose IN ('company', 'user')) DEFAULT 'company',
  ADD COLUMN IF NOT EXISTS disclosure_version TEXT NOT NULL DEFAULT 'v1',
  ADD COLUMN IF NOT EXISTS default_policy_version TEXT NOT NULL DEFAULT 'company_default_v1';
```

### 6) Agent parity split into schema/auth/routes/manifest phases
Implemented in plan:
1. Phase 4A: schema + auth foundations.
2. Phase 4B: agent runtime routes.
3. Phase 4C: manifest update and compatibility pin.

### 7) Shared settlement core for human and agent casino
Implemented in plan:
1. One settlement engine (`CasinoService`) for wager validation, RNG commit/reveal, settlement, verification writes.
2. Human and agent routes differ only in principal resolution and policy gates.
3. No duplicate settlement logic in route layers.

### 8) Server-side caps for longer sessions
Implemented in plan:
1. Server-enforced caps:
- max rounds per session
- max wager per round
- max exposure per session
- max unresolved rounds
- session TTL
2. CLI defaults are convenience only, never trust client-provided values.

### 9) Reconciliation jobs added to hardening
Implemented in plan:
1. `reconcile_ledger_orders`
2. `reconcile_grant_invariants`
3. `sweep_abandoned_sessions`
4. `audit_idempotency_collisions`
5. `cleanup_expired_mint_challenges`

### 10) Rollback instructions per migration
Implemented in plan:
1. Added migration compatibility matrix:
- additive vs destructive
- old-code/new-schema compatibility
- new-code/old-schema compatibility
- rollback safety
2. Use forward-fix-only for non-reversible production migrations.

## Revised Rollout Sequence (Dependency-Safe)

### Phase 0: Compatibility hotfixes
1. Fix wallet account prefix use in `server/routes/wallet.py`.
2. Fix inference usage account/user typing mismatch.
3. Enforce mint challenge ownership check.

### Phase 1: Runtime dependency wiring + startup schema checks
1. Replace placeholder DB/Redis in runtime.
2. Add startup preflight schema compatibility checks.
3. Keep placeholder mode only for explicit test mode.

### Phase 2: Store schema + transactional settlement design
1. Add `store_orders` lifecycle statuses.
2. Add `inference_token_grants`.
3. Add transaction-safe wallet redeem path with shared `tx`.
4. Add idempotency and uniqueness guarantees.

### Phase 3: Store buy + grant consumption path
1. Implement backend store routes.
2. Update CLI to backend-backed store operations.
3. Consume grants in inference gateway before `$V` charge path.

### Phase 4A: Agent schema and auth foundation
1. Add missing indexes/constraints for agent sessions, tokens, spend records.
2. Harden scope checks and revocation lookups.

### Phase 4B: Agent runtime parity routes
1. Add `/v1/agent/sessions/start`, `/v1/agent/infer`, `/v1/agent/budget`, `/v1/agent/boost/*`.
2. Enforce session envelope accounting and idempotency.

### Phase 4C: Manifest atomic update
1. Update `openvegas/agent/openclaw_skill.py` to exact shipped endpoints.
2. Bump manifest version and deploy atomically with route availability.

### Phase 5: Human casino route on shared settlement core
1. Add human casino routes with feature flag + policy gate.
2. Reuse existing `CasinoService` internals for settlement and verification.
3. Add server-side abuse caps and TTL.

### Phase 6: Company-directed mint policy and disclosure hardening
1. Default company-purpose mint policy.
2. Persist policy/disclosure metadata for auditability.
3. Add policy-versioned disclosure text.

### Phase 7: Operational hardening + reconciliation + canary
1. Logging and metrics.
2. Reconciliation jobs.
3. Canary scripts for human and agent flows.

## Detailed Non-Breaking Changes

### A) Runtime dependency wiring
File: `server/services/dependencies.py`

```python
_TEST_MODE = os.getenv("OPENVEGAS_TEST_MODE", "0") == "1"

async def init_runtime_deps():
    if _TEST_MODE:
        return
    ...
    await assert_schema_compatible(get_db())
```

### B) Store transaction safety
File: `openvegas/wallet/ledger.py`

```python
async def redeem(self, account_id: str, amount: Decimal, reference_id: str, *, tx=None):
    ...
    await self._execute(entry, tx=tx)
```

File: `openvegas/store/service.py`

```python
# all write operations share one tx
async with self.db.transaction() as tx:
    ...
```

### C) Shared casino settlement core
1. `openvegas/casino/service.py` remains single engine.
2. `server/routes/casino.py` (agent) and `server/routes/human_casino.py` (human) call same service methods.
3. No duplicated payout math or provably-fair writes outside service.

### D) Server-side caps
Schema addition:

```sql
ALTER TABLE casino_sessions
  ADD COLUMN IF NOT EXISTS expires_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS max_exposure_v NUMERIC(18,6) DEFAULT 100.000000;
```

Policy checks in service:
1. reject rounds above round cap.
2. reject sessions above max rounds.
3. reject actions after TTL.
4. reject if unresolved rounds exceed threshold.

## Supabase Setup and Deployment Checks

### Environment
Set:
1. `DATABASE_URL`
2. `REDIS_URL`
3. `SUPABASE_JWT_SECRET`
4. `CASINO_HUMAN_ENABLED` (`false` default)
5. `OPENVEGAS_COMPANY_MINT_DEFAULT` (`true` default)
6. `OPENVEGAS_TEST_MODE` (`0` in runtime, `1` in isolated tests)
7. `STORE_ENABLED` (`true` default)
8. `INFERENCE_ENABLED` (`true` default)
9. `AGENT_RUNTIME_ENABLED` (`true` default)
10. `MINT_AUDIT_ENABLED` (`true` default)

### Migration Order
1. `001_initial_schema.sql`
2. `002_enterprise_agent_casino.sql`
3. `003_inference_usage_accounts.sql`
4. `004_store_fulfillment.sql`
5. `005_agent_api_support.sql`
6. `006_mint_policy_audit.sql`
7. `007_casino_session_caps.sql`
8. `008_schema_migrations_and_readiness.sql`
9. `009_inference_grant_usages_and_preauth.sql`
10. `010_agent_session_events_and_precision.sql`

### Migration Compatibility and Rollback Matrix

1. `003_inference_usage_accounts.sql`
- Type: additive/relaxing
- Old code on new schema: safe
- New code on old schema: unsafe
- Rollback: forward-fix preferred; rollback possible only if new code not deployed

2. `004_store_fulfillment.sql`
- Type: additive
- Old code on new schema: safe
- New code on old schema: unsafe
- Rollback: safe if no dependent data consumed; otherwise forward-fix

3. `005_agent_api_support.sql`
- Type: additive
- Old code on new schema: safe
- New code on old schema: unsafe
- Rollback: forward-fix preferred

4. `006_mint_policy_audit.sql`
- Type: additive
- Old code on new schema: safe
- New code on old schema: unsafe for required audit fields
- Rollback: not recommended after writes begin

5. `007_casino_session_caps.sql`
- Type: additive
- Old code on new schema: safe
- New code on old schema: unsafe
- Rollback: forward-fix preferred

6. `008_schema_migrations_and_readiness.sql`
- Type: additive
- Old code on new schema: safe
- New code on old schema: unsafe when readiness/version checks are enabled
- Rollback: forward-fix preferred

7. `009_inference_grant_usages_and_preauth.sql`
- Type: additive
- Old code on new schema: safe
- New code on old schema: unsafe for grant-usage audit and inference preauth settlement
- Rollback: forward-fix preferred

8. `010_agent_session_events_and_precision.sql`
- Type: additive + precision expansion
- Old code on new schema: safe
- New code on old schema: unsafe for session-event audit and high-precision settlement
- Rollback: forward-fix preferred; precision changes should use forward-only migrations in production

## End-to-End Human User Validation

```bash
openvegas signup
openvegas login
openvegas keys set anthropic
openvegas mint --amount 5 --provider anthropic --mode sponsor
openvegas balance
openvegas history
openvegas play horse --stake 5 --horse 2 --type win
openvegas casino session start --game poker --wager 2 --rounds 8
openvegas casino play --session <session_id>
openvegas store list
openvegas store buy ai_starter --idempotency-key run-001
openvegas store grants
openvegas ask "hello" --provider openai --model gpt-4o-mini
openvegas verify <game_id>
openvegas casino verify --round <round_id>
```

Pass criteria:
1. No split-brain settlement (ledger, order, grant are coherent).
2. Duplicate `store buy` with same idempotency key is no-op.
3. Balance and history reflect prefixed account routing correctly.

## End-to-End Autonomous Agent Validation (OpenClaw Style)

### Admin bootstrap (human JWT)
1. Create org.
2. Create agent account.
3. Issue agent token with scopes `infer,boost,casino.play,budget.read`.

### Agent runtime flow (`Authorization: Bearer ov_agent_*`)

```bash
curl -X POST "$API/v1/agent/sessions/start" \
  -H "Authorization: Bearer $AGENT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"envelope_v": 50}'

curl -X POST "$API/v1/agent/infer" \
  -H "Authorization: Bearer $AGENT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"session_id":"<session_id>","prompt":"health check","provider":"openai","model":"gpt-4o-mini"}'

curl "$API/v1/agent/budget?session_id=<session_id>" \
  -H "Authorization: Bearer $AGENT_TOKEN"

curl -X POST "$API/v1/agent/boost/challenge" \
  -H "Authorization: Bearer $AGENT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"session_id":"<session_id>"}'
```

Pass criteria:
1. Scope enforcement works.
2. Session envelope cannot be exceeded.
3. Casino settlement remains deterministic and auditable.

## Reconciliation Jobs (Required Before Ship)

1. `jobs/reconcile_ledger_orders.py`
- Verify every fulfilled order has exactly one redeem ledger entry and expected grant rows.

2. `jobs/reconcile_grants.py`
- Verify `tokens_remaining <= tokens_total`, no negative grants.

3. `jobs/sweep_sessions.py`
- Expire stale sessions and close unresolved states.

4. `jobs/audit_idempotency.py`
- Report repeated keys and mismatched payload hashes.

5. `jobs/cleanup_mint_challenges.py`
- Mark expired/unused challenges and prune old data.

## Remotion Setup (Skills First)

1. Install skills:

```bash
python3 /Users/stephenekwedike/.codex/skills/.system/skill-installer/scripts/install-skill-from-github.py --repo remotion-dev/skills --path <skill-folder-containing-SKILL.md>
```

2. Restart Codex.
3. Scaffold video app:

```bash
npx create-video@latest
```

4. Open editor:

```bash
npm run dev
```

5. Render:

```bash
npx remotion render
```

Template usage policy:
1. User-supplied demo video/images can be used as style and storyboard templates.
2. Keep imported assets under project `assets/` and render from normalized local copies.

## Final Safety Constraints
1. No route ships before schema compatibility is in place.
2. No mint policy change ships without disclosure metadata persistence.
3. No store purchase flow ships without single-transaction guarantees.
4. Human and agent casino must share one settlement core.
5. Startup must fail fast on schema/version mismatch.

## v2 Enhancement Addendum (Accepted, Additive)

This addendum incorporates the latest tightening requests without removing prior technical detail.

### 1) Explicit store-order write sequence (immediate fulfillment path)
Order lifecycle is now explicit:
1. insert order as `created`
2. redeem ledger -> transition to `settled`
3. issue grants
4. transition to `fulfilled`

```python
async with self.db.transaction() as tx:
    await tx.execute(
        """
        INSERT INTO store_orders (id, user_id, item_id, cost_v, status, idempotency_key, idempotency_payload_hash)
        VALUES ($1,$2,$3,$4,'created',$5,$6)
        """,
        order_id, user_id, item_id, cost_v, idempotency_key, payload_hash,
    )
    await self.wallet.redeem(f"user:{user_id}", cost_v, reference_id=f"store:{order_id}", tx=tx)
    await transition_order(tx, order_id, "created", "settled")
    await issue_grants(tx, ...)
    await transition_order(tx, order_id, "settled", "fulfilled")
```

### 2) DB-enforced legal transition helper

```python
async def transition_order(tx, order_id: str, from_status: str, to_status: str, reason: str | None = None):
    row = await tx.fetchrow(
        """
        UPDATE store_orders
        SET status = $3, failure_reason = COALESCE($4, failure_reason), updated_at = now()
        WHERE id = $1 AND status = $2
        RETURNING id
        """,
        order_id, from_status, to_status, reason,
    )
    if not row:
        raise ValueError(f"Illegal transition {from_status}->{to_status} for {order_id}")
```

### 3) Idempotency lock semantics with conflict handling
Behavior:
1. same key + same payload + completed -> return prior result
2. same key + same payload + in-progress -> return pending
3. same key + different payload -> conflict
4. pending statuses are `created` and `settled`
5. terminal statuses are `fulfilled`, `failed`, `reversed`

```python
async def get_or_lock_order(tx, user_id, idempotency_key, payload_hash):
    row = await tx.fetchrow(
        "SELECT * FROM store_orders WHERE user_id=$1 AND idempotency_key=$2 FOR UPDATE",
        user_id, idempotency_key
    )
    if row:
        if row["idempotency_payload_hash"] != payload_hash:
            raise ValueError("IDEMPOTENCY_PAYLOAD_CONFLICT")
        if row["status"] in {"created", "settled"}:
            return {"state": "pending", "order": row}
        return {"state": "completed", "order": row}
    return None
```

### 4) Deterministic payload canonicalization

```python
import hashlib, json
from decimal import Decimal

def canonical_payload_hash(payload: dict) -> str:
    def norm(v):
        if isinstance(v, Decimal):
            return format(v.normalize(), "f")
        if isinstance(v, dict):
            return {k: norm(v[k]) for k in sorted(v.keys())}
        if isinstance(v, list):
            return [norm(x) for x in v]
        return v
    canonical = json.dumps(norm(payload), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()
```

### 5) Grant consumption atomicity + audit rows

```python
eligible = await tx.fetch(
    """
    SELECT * FROM inference_token_grants
    WHERE user_id=$1 AND provider=$2 AND model_id=$3 AND tokens_remaining > 0
    ORDER BY created_at ASC
    FOR UPDATE
    """,
    user_id, provider, model_id
)
for g in eligible:
    if remaining <= 0:
        break
    use = min(g["tokens_remaining"], remaining)
    ok = await tx.fetchrow(
        """
        UPDATE inference_token_grants
        SET tokens_remaining = tokens_remaining - $2
        WHERE id=$1 AND tokens_remaining >= $2
        RETURNING id
        """,
        g["id"], use
    )
    if not ok:
        continue
    await tx.execute(
        """
        INSERT INTO inference_grant_usages
          (grant_id, inference_usage_id, request_id, provider, model_id, tokens_used)
        VALUES ($1,$2,$3,$4,$5,$6)
        """,
        g["id"], usage_id, request_id, provider, model_id, use
    )
    remaining -= use
```

### 6) Clarified compensation semantics
1. `failed` => no successful redeem captured.
2. `reversed` => redeem captured and compensating ledger entry posted.
3. `settled -> failed` disallowed.

### 7) Feature-aware startup schema checks + migration version gate

```python
async def assert_schema_compatible(db, flags):
    await require_tables(db, {"wallet_accounts", "ledger_entries", "mint_challenges", "mint_events"})
    await require_migration_min(db, "008_schema_migrations_and_readiness")
    if flags.store_enabled:
        await require_migration_min(db, "009_inference_grant_usages_and_preauth")
        await require_tables(db, {"store_orders", "inference_token_grants", "inference_grant_usages"})
    if flags.inference_enabled:
        await require_tables(db, {"inference_preauthorizations"})
    if flags.agent_runtime_enabled:
        await require_migration_min(db, "010_agent_session_events_and_precision")
        await require_tables(db, {"agent_sessions", "agent_session_events", "agent_tokens"})
    if flags.human_casino_enabled:
        await require_tables(db, {"casino_sessions", "casino_rounds"})
    if flags.mint_audit_enabled:
        await require_columns(
            db,
            {
                ("mint_challenges", "purpose"),
                ("mint_challenges", "disclosure_version"),
                ("mint_challenges", "default_policy_version"),
            },
        )
```

Feature mapping used by startup checks:
1. baseline always-on checks: wallet, ledger, mint, `schema_migrations`
2. `STORE_ENABLED` -> store + grant + grant-usage tables
3. `INFERENCE_ENABLED` -> inference preauth + inference usage tables
4. `AGENT_RUNTIME_ENABLED` -> agent auth/session/event tables
5. `CASINO_HUMAN_ENABLED` -> human casino tables and indexes
6. `MINT_AUDIT_ENABLED` -> mint policy audit columns (`purpose`, `disclosure_version`, `default_policy_version`)

```python
def current_flags():
    env = os.getenv
    return SimpleNamespace(
        store_enabled=env("STORE_ENABLED", "1") == "1",
        inference_enabled=env("INFERENCE_ENABLED", "1") == "1",
        agent_runtime_enabled=env("AGENT_RUNTIME_ENABLED", "1") == "1",
        human_casino_enabled=env("CASINO_HUMAN_ENABLED", "0") == "1",
        mint_audit_enabled=env("MINT_AUDIT_ENABLED", "1") == "1",
    )
```

```sql
SELECT version FROM schema_migrations ORDER BY applied_at DESC LIMIT 1;

CREATE TABLE IF NOT EXISTS schema_migrations (
  version TEXT PRIMARY KEY,
  applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

### 8) Liveness/readiness separation

```python
@app.get("/health/live")
async def live():
    return {"status": "up"}

@app.get("/health/ready")
async def ready():
    if os.getenv("OPENVEGAS_TEST_MODE", "0") == "1":
        await assert_db_ready()
        await assert_schema_compatible(get_db(), flags=current_flags())
        return {"status": "ready", "mode": "test", "redis": "skipped"}
    await assert_db_ready()
    await assert_redis_ready()
    await assert_schema_compatible(get_db(), flags=current_flags())
    return {"status": "ready", "mode": "runtime"}
```

### 9) Session envelope schema hardening

```sql
ALTER TABLE agent_sessions
  ADD COLUMN IF NOT EXISTS reserved_v NUMERIC(18,6) NOT NULL DEFAULT 0 CHECK (reserved_v >= 0),
  ADD COLUMN IF NOT EXISTS refunded_v NUMERIC(18,6) NOT NULL DEFAULT 0 CHECK (refunded_v >= 0),
  ADD COLUMN IF NOT EXISTS expires_at TIMESTAMPTZ;

ALTER TABLE agent_sessions
  ADD CONSTRAINT ck_agent_budget CHECK (spent_v >= 0 AND spent_v + reserved_v <= envelope_v);

CREATE TABLE IF NOT EXISTS agent_session_events (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  session_id UUID NOT NULL REFERENCES agent_sessions(id),
  event_type TEXT NOT NULL CHECK (event_type IN ('reserve', 'settle', 'refund', 'expire')),
  amount_v NUMERIC(18,6) NOT NULL CHECK (amount_v >= 0),
  request_id TEXT,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

### 10) Non-negativity constraints

```sql
ALTER TABLE store_orders
  ADD CONSTRAINT ck_store_cost_nonneg CHECK (cost_v >= 0);

ALTER TABLE inference_token_grants
  ADD CONSTRAINT ck_grant_bounds CHECK (
    tokens_total >= 0 AND tokens_remaining >= 0 AND tokens_remaining <= tokens_total
  );
```

### 11) Token hashing at rest (agent auth hardening)

```python
token = f"ov_agent_{secrets.token_urlsafe(32)}"
token_hash = hashlib.sha256(token.encode()).hexdigest()
await db.execute(
    "INSERT INTO agent_tokens (agent_account_id, scopes, token_hash, expires_at) VALUES ($1,$2,$3,$4)",
    agent_account_id, scopes, token_hash, expires_at,
)
```

### 12) Correlation IDs and actor audit identity

```python
@app.middleware("http")
async def request_id_middleware(request, call_next):
    rid = request.headers.get("x-request-id") or f"req_{uuid.uuid4().hex[:12]}"
    request.state.request_id = rid
    response = await call_next(request)
    response.headers["x-request-id"] = rid
    return response
```

Persist per critical event where applicable:
1. `request_id`
2. `actor_type`
3. `actor_id`
4. `org_id`
5. `session_id`
6. `order_id`
7. `challenge_id`
8. `reference_id`
9. `inference_usage_id`

### 13) Inference charging order and two-stage settlement
1. consume eligible grants first (exact provider+model, FIFO).
2. preauthorize remaining `$V`.
3. settle actual usage.
4. refund over-reservation.

Schema and settlement contract:

```sql
CREATE TABLE IF NOT EXISTS inference_preauthorizations (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES auth.users(id),
  request_id TEXT NOT NULL,
  provider TEXT NOT NULL,
  model_id TEXT NOT NULL,
  reserved_v NUMERIC(18,6) NOT NULL CHECK (reserved_v >= 0),
  settled_v NUMERIC(18,6) NOT NULL DEFAULT 0 CHECK (settled_v >= 0),
  status TEXT NOT NULL CHECK (status IN ('reserved', 'settled', 'refunded', 'voided')),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (user_id, request_id)
);
```

```python
async with db.transaction() as tx:
    grants_used = await consume_grants_fifo(tx, user_id, provider, model_id, token_estimate, request_id)
    reserve_v = estimate_v_cost(token_estimate) - grants_used.covered_v
    preauth = await create_preauth(tx, user_id, request_id, provider, model_id, reserve_v)
    await wallet.reserve(account_id=f"user:{user_id}", amount=reserve_v, reference_id=f"infer-preauth:{preauth.id}", tx=tx)

# later, after provider usage is known
async with db.transaction() as tx:
    actual_v = compute_actual_v(usage)
    await settle_preauth(tx, preauth.id, actual_v)
    await wallet.settle_reservation(
        account_id=f"user:{user_id}",
        reservation_ref=f"infer-preauth:{preauth.id}",
        settle_amount=actual_v,
        tx=tx,
    )
```

### 14) Additional required concurrency tests
1. duplicate store-buy race
2. same idempotency key + same payload + in-progress behavior
3. same idempotency key + different payload conflict
4. simultaneous grant consumption race
5. double-settle race on same round
6. session expiration during in-flight action

### 15) Monetary precision policy (explicit)
1. Canonical `$V` storage precision is `NUMERIC(18,6)` across wallet/store/session/preauth paths.
2. Display formatting can round to 2 decimals in CLI/UI, but writes and settlement always use `Decimal`.
3. No `float(...)` conversions are permitted in accounting code paths.

```python
from decimal import Decimal, ROUND_HALF_UP

def as_storage_v(value: str | Decimal) -> Decimal:
    d = value if isinstance(value, Decimal) else Decimal(value)
    return d.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)
```

### 16) Reservation ledger invariants (implementation note, required in code)
`wallet.reserve()` and `wallet.settle_reservation()` must follow the same accounting invariants as `redeem()`:
1. append-only ledger entries only (never mutate prior entries)
2. idempotent `reference_id`/reservation references
3. compensating entries for reversals/refunds
4. no side-channel mutable balance source

```python
async def reserve(self, account_id: str, amount: Decimal, reference_id: str, *, tx=None):
    # one idempotent append-only hold entry keyed by reference_id
    await self._execute(
        LedgerEntry(
            debit_account=account_id,
            credit_account="holds",
            amount=amount,
            entry_type="reserve",
            reference_id=reference_id,
        ),
        tx=tx,
    )

async def settle_reservation(self, account_id: str, reservation_ref: str, settle_amount: Decimal, *, tx=None):
    # settle and refund are both append-only entries derived from reservation_ref
    await self._execute(..., tx=tx)
```

### 17) `updated_at` consistency (implementation note, required in code)
Every state transition must update `updated_at = now()` consistently.
Use explicit SQL in transition helpers and/or triggers for safety.

```sql
CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS trigger AS $$
BEGIN
  NEW.updated_at = now();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_store_orders_updated_at
BEFORE UPDATE ON store_orders
FOR EACH ROW EXECUTE FUNCTION set_updated_at();
```

### 18) Index follow-through for new hot paths (implementation note)
Ensure these indexes exist in migrations:

```sql
CREATE INDEX IF NOT EXISTS idx_inference_grant_usages_grant_created
  ON inference_grant_usages (grant_id, created_at DESC);

CREATE UNIQUE INDEX IF NOT EXISTS idx_inference_preauth_user_request
  ON inference_preauthorizations (user_id, request_id);

CREATE INDEX IF NOT EXISTS idx_agent_session_events_session_created
  ON agent_session_events (session_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_store_orders_user_created
  ON store_orders (user_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_grants_user_provider_model_created
  ON inference_token_grants (user_id, provider, model_id, created_at ASC);
```

### 19) Procedural release gates (must-pass together before broad rollout)
1. human canary flow passes end to end
2. agent canary flow passes end to end
3. reconciliation jobs return clean on fresh data
