from __future__ import annotations

from openvegas.compact_uuid import decode_compact_uuid, encode_compact_uuid


def test_compact_uuid_round_trip():
    raw = "123e4567-e89b-12d3-a456-426614174000"
    token = encode_compact_uuid(raw)
    assert token is not None
    assert len(token) <= 22
    assert decode_compact_uuid(token) == raw


def test_compact_uuid_decode_rejects_invalid_token():
    assert decode_compact_uuid("not-valid-@@@") is None

