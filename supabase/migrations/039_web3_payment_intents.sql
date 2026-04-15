-- Web3 on-chain payment intents
-- Supports EVM (MetaMask/USDC/ETH) and Solana (Phantom/USDC/SOL) topups.
-- Lifecycle: pending → confirming → confirmed | failed | expired

CREATE TABLE IF NOT EXISTS web3_payment_intents (
  id            UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id       UUID        REFERENCES auth.users(id) ON DELETE CASCADE,
  chain         TEXT        NOT NULL CHECK (chain IN ('evm', 'solana')),
  currency      TEXT        NOT NULL CHECK (currency IN ('USDC', 'ETH', 'SOL')),
  amount_token  NUMERIC(18, 6) NOT NULL CHECK (amount_token > 0),
  amount_usd    NUMERIC(10, 2) NOT NULL CHECK (amount_usd > 0),
  amount_v      NUMERIC(18, 6) NOT NULL CHECK (amount_v > 0),
  platform_addr TEXT        NOT NULL,
  memo          TEXT        NOT NULL UNIQUE,           -- "ov-intent-<uuid[:8]>"
  tx_hash       TEXT        UNIQUE,                   -- set after user submits wallet tx
  status        TEXT        NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending', 'confirming', 'confirmed', 'expired', 'failed')),
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  expires_at    TIMESTAMPTZ NOT NULL,
  confirmed_at  TIMESTAMPTZ
);

-- TTL sweep: mark stale pending intents as expired (run via pg_cron or Railway cron)
-- UPDATE web3_payment_intents SET status = 'expired'
--   WHERE status = 'pending' AND expires_at < now();

CREATE INDEX IF NOT EXISTS web3_payment_intents_user_id_idx
  ON web3_payment_intents (user_id);

CREATE INDEX IF NOT EXISTS web3_payment_intents_status_idx
  ON web3_payment_intents (status)
  WHERE status IN ('pending', 'confirming');
