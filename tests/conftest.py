from __future__ import annotations

import asyncio

import pytest

import openvegas.agent.local_tools as local_tools


@pytest.fixture(autouse=True)
def _cleanup_background_shell_jobs():
    yield
    jobs = list(local_tools._BACKGROUND_JOBS.values())
    if not jobs:
        return

    async def _drain() -> None:
        for job in jobs:
            proc = job.process
            try:
                if proc.returncode is None:
                    proc.kill()
                await proc.wait()
            except Exception:
                # Best-effort test cleanup only.
                pass

    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(_drain())
    finally:
        loop.close()
        local_tools._BACKGROUND_JOBS.clear()
