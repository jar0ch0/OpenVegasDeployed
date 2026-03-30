-- Seed provider catalog with initial models
INSERT INTO provider_catalog (provider, model_id, display_name, cost_input_per_1m, cost_output_per_1m, v_price_input_per_1m, v_price_output_per_1m, max_tokens) VALUES
    ('openai', 'gpt-5.4', 'GPT-5.4', 2.50, 15.00, 300, 1800, 128000),
    ('openai', 'gpt-4o', 'GPT-4o', 2.50, 10.00, 300, 1200, 4096),
    ('openai', 'gpt-4o-mini', 'GPT-4o Mini', 0.15, 0.60, 20, 80, 4096),
    ('anthropic', 'claude-sonnet-4-20250514', 'Claude Sonnet 4', 3.00, 15.00, 360, 1800, 4096),
    ('anthropic', 'claude-haiku-4-5-20251001', 'Claude Haiku 4.5', 0.80, 4.00, 100, 500, 4096),
    ('gemini', 'gemini-2.0-flash', 'Gemini 2.0 Flash', 0.10, 0.40, 15, 50, 4096)
ON CONFLICT (provider, model_id) DO NOTHING;
