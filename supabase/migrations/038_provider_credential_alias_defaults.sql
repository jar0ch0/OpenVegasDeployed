-- Seed provider credential aliases so production wrapper inference can resolve
-- canonical environment variable names immediately after migrations run.

INSERT INTO provider_credentials (provider, env, key_alias, key_version, status)
SELECT 'openai', 'production', 'OPENAI_API_KEY', '2026-04-05', 'active'
WHERE NOT EXISTS (
  SELECT 1
  FROM provider_credentials
  WHERE provider = 'openai'
    AND env = 'production'
    AND key_alias = 'OPENAI_API_KEY'
);

INSERT INTO provider_credentials (provider, env, key_alias, key_version, status)
SELECT 'anthropic', 'production', 'ANTHROPIC_API_KEY', '2026-04-05', 'active'
WHERE NOT EXISTS (
  SELECT 1
  FROM provider_credentials
  WHERE provider = 'anthropic'
    AND env = 'production'
    AND key_alias = 'ANTHROPIC_API_KEY'
);

INSERT INTO provider_credentials (provider, env, key_alias, key_version, status)
SELECT 'gemini', 'production', 'GEMINI_API_KEY', '2026-04-05', 'active'
WHERE NOT EXISTS (
  SELECT 1
  FROM provider_credentials
  WHERE provider = 'gemini'
    AND env = 'production'
    AND key_alias = 'GEMINI_API_KEY'
);

INSERT INTO schema_migrations(version)
VALUES ('038_provider_credential_alias_defaults')
ON CONFLICT (version) DO NOTHING;
