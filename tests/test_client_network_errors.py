from __future__ import annotations

import httpx
import pytest

from openvegas.client import APIError, OpenVegasClient


@pytest.mark.asyncio
async def test_request_network_error_maps_to_api_error(monkeypatch):
    client = OpenVegasClient()

    async def _boom(*_args, **_kwargs):
        raise httpx.ReadError("boom")

    monkeypatch.setattr(httpx.AsyncClient, "request", _boom)

    with pytest.raises(APIError) as e:
        await client._request("GET", "/health/ready")
    assert e.value.status == 503
    assert "Backend request failed" in e.value.detail
