"""OpenVegas FastAPI backend."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, RedirectResponse
from dotenv import load_dotenv

from server.routes import mint as mint_routes
from server.routes import games as game_routes
from server.routes import wallet as wallet_routes
from server.routes import inference as inference_routes
from server.routes import models as model_routes
from server.routes import ui_auth as ui_auth_routes
from server.routes import casino as casino_routes
from server.routes import casino_human as casino_human_routes
from server.routes import store as store_routes
from server.routes import agent as agent_routes
from server.routes import agent_orchestration as agent_orchestration_routes
from server.routes import ide_bridge as ide_bridge_routes
from server.routes import payments as payment_routes
from server.services.dependencies import (
    assert_db_ready,
    assert_redis_ready,
    assert_schema_compatible,
    close_runtime_deps,
    current_flags,
    get_db,
    init_runtime_deps,
)

ROOT_DIR = Path(__file__).resolve().parents[1]
# Allow `uvicorn server.main:app --reload` to work without manually sourcing env vars.
load_dotenv(ROOT_DIR / ".env", override=False)


@asynccontextmanager
async def lifespan(_: FastAPI):
    await init_runtime_deps()
    try:
        yield
    finally:
        await close_runtime_deps()

app = FastAPI(
    title="OpenVegas API",
    version="0.1.0",
    description="Terminal Arcade for Developers",
    lifespan=lifespan,
)

ROOT_DIR = Path(__file__).resolve().parents[1]
UI_INDEX = ROOT_DIR / "ui" / "index.html"
TOPUP_UI_PAGE = ROOT_DIR / "ui" / "topup.html"
UI_DIR = ROOT_DIR / "ui"
UI_ASSETS_DIR = UI_DIR / "assets"

UI_PAGES = {
    "login": UI_DIR / "login.html",
    "product": UI_DIR / "product.html",
    "how-it-works": UI_DIR / "how-it-works.html",
    "pricing": UI_DIR / "pricing.html",
    "balance": UI_DIR / "balance.html",
    "payments": UI_DIR / "payments.html",
    "transactions": UI_DIR / "transactions.html",
    "security": UI_DIR / "security.html",
    "faq": UI_DIR / "faq.html",
    "docs": UI_DIR / "docs.html",
    "contact": UI_DIR / "contact.html",
}

LEGACY_UI_REDIRECTS = {
}

UI_ASSETS = {
    "theme.css": UI_ASSETS_DIR / "theme.css",
    "layout.css": UI_ASSETS_DIR / "layout.css",
    "site.js": UI_ASSETS_DIR / "site.js",
    "page-auth.js": UI_ASSETS_DIR / "page-auth.js",
    "topup.js": UI_ASSETS_DIR / "topup.js",
    "deck.css": UI_ASSETS_DIR / "deck.css",
    "deck.js": UI_ASSETS_DIR / "deck.js",
    "content-registry.js": UI_ASSETS_DIR / "content-registry.js",
    "market-data.json": UI_ASSETS_DIR / "market-data.json",
}

SLIDES = {
    "01-cover.html": UI_DIR / "slidedeck" / "01-cover.html",
    "02-vibecoding-hook.html": UI_DIR / "slidedeck" / "02-vibecoding-hook.html",
    "03-problem.html": UI_DIR / "slidedeck" / "03-problem.html",
    "04-bad-alternatives.html": UI_DIR / "slidedeck" / "04-bad-alternatives.html",
    "05-solution.html": UI_DIR / "slidedeck" / "05-solution.html",
    "06-product.html": UI_DIR / "slidedeck" / "06-product.html",
    "07-validation.html": UI_DIR / "slidedeck" / "07-validation.html",
    "08-market-size.html": UI_DIR / "slidedeck" / "08-market-size.html",
    "09-business-model.html": UI_DIR / "slidedeck" / "09-business-model.html",
    "10-moat.html": UI_DIR / "slidedeck" / "10-moat.html",
    "11-why-now.html": UI_DIR / "slidedeck" / "11-why-now.html",
    "12-ask.html": UI_DIR / "slidedeck" / "12-ask.html",
}

app.include_router(mint_routes.router, prefix="/mint", tags=["mint"])
app.include_router(game_routes.router, prefix="/games", tags=["games"])
app.include_router(wallet_routes.router, prefix="/wallet", tags=["wallet"])
app.include_router(inference_routes.router, prefix="/inference", tags=["inference"])
app.include_router(ui_auth_routes.router, tags=["ui-auth"])
app.include_router(model_routes.router, tags=["models"])
app.include_router(casino_routes.router, tags=["casino"])
app.include_router(casino_human_routes.router, tags=["casino-human"])
app.include_router(store_routes.router, tags=["store"])
app.include_router(agent_routes.router, tags=["agent"])
app.include_router(agent_orchestration_routes.router, tags=["agent-orchestration"])
app.include_router(ide_bridge_routes.router, tags=["ide-bridge"])
app.include_router(payment_routes.router, tags=["billing"])


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/health/live")
async def health_live():
    return {"status": "up"}


@app.get("/health/ready")
async def health_ready():
    flags = current_flags()
    human_casino_enabled = bool(flags.human_casino_enabled)
    human_casino_schema_ready = bool(flags.human_casino_enabled)

    if os.getenv("OPENVEGAS_TEST_MODE", "0") == "1":
        await assert_db_ready()
        await assert_schema_compatible(get_db(), flags)
        return {
            "status": "ready",
            "mode": "test",
            "redis": "skipped",
            "human_casino_enabled": human_casino_enabled,
            "human_casino_schema_ready": human_casino_schema_ready,
        }

    await assert_db_ready()
    await assert_redis_ready()
    await assert_schema_compatible(get_db(), flags)
    return {
        "status": "ready",
        "mode": "runtime",
        "human_casino_enabled": human_casino_enabled,
        "human_casino_schema_ready": human_casino_schema_ready,
    }


@app.get("/ui")
@app.get("/ui/")
async def ui_page():
    return FileResponse(UI_INDEX)


@app.get("/ui/assets/{asset_name}")
async def ui_asset(asset_name: str):
    asset = UI_ASSETS.get(asset_name)
    if not asset or not asset.exists():
        raise HTTPException(status_code=404, detail="Asset not found")
    return FileResponse(asset)


@app.get("/ui/slidedeck/{slide_name}")
async def ui_slide_page(slide_name: str):
    page = SLIDES.get(slide_name)
    if not page or not page.exists():
        raise HTTPException(status_code=404, detail="Slide not found")
    return FileResponse(page)


@app.get("/ui/topup/{topup_id}")
async def ui_topup_page(topup_id: str):
    if not TOPUP_UI_PAGE.exists():
        raise HTTPException(status_code=404, detail="Page not found")
    return FileResponse(TOPUP_UI_PAGE)


@app.get("/ui/{slug}")
async def ui_page_slug(slug: str):
    redirect_to = LEGACY_UI_REDIRECTS.get(slug)
    if redirect_to:
        return RedirectResponse(url=redirect_to, status_code=307)
    page = UI_PAGES.get(slug)
    if not page or not page.exists():
        raise HTTPException(status_code=404, detail="Page not found")
    return FileResponse(page)
