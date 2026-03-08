"""Unit checks for store service helper behavior."""

from openvegas.store.service import StoreService


def test_canonical_payload_hash_is_order_independent():
    a = {"item_id": "ai_starter", "x": 1}
    b = {"x": 1, "item_id": "ai_starter"}
    assert StoreService.canonical_payload_hash(a) == StoreService.canonical_payload_hash(b)


def test_provider_for_model_mapping():
    assert StoreService._provider_for_model("gpt-4o-mini") == "openai"
    assert StoreService._provider_for_model("claude-sonnet-4-20250514") == "anthropic"
    assert StoreService._provider_for_model("gemini-2.0-flash") == "gemini"
