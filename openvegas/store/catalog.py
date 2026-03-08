"""Redemption store catalog."""

from decimal import Decimal

STORE_CATALOG = {
    "ai_starter": {
        "name": "Starter AI Pack",
        "description": "50k tokens on GPT-4o-mini or Gemini Flash",
        "cost_v": Decimal("5.00"),
        "type": "ai_pack",
        "tokens": 50_000,
        "models": ["gpt-4o-mini", "gemini-2.0-flash"],
    },
    "ai_pro": {
        "name": "Pro AI Pack",
        "description": "25k tokens on Claude Sonnet or GPT-4o",
        "cost_v": Decimal("20.00"),
        "type": "ai_pack",
        "tokens": 25_000,
        "models": ["claude-sonnet-4-20250514", "gpt-4o"],
    },
    "theme_cyberpunk": {
        "name": "Cyberpunk Terminal Theme",
        "description": "Neon colors + glitch effects",
        "cost_v": Decimal("15.00"),
        "type": "cosmetic",
    },
    "theme_retro": {
        "name": "Retro Arcade Theme",
        "description": "Green phosphor CRT look",
        "cost_v": Decimal("10.00"),
        "type": "cosmetic",
    },
    "victory_fireworks": {
        "name": "Win Animation: Fireworks",
        "description": "ASCII fireworks on every win",
        "cost_v": Decimal("8.00"),
        "type": "cosmetic",
    },
    "horse_skin_unicorn": {
        "name": "Unicorn Horse Skin",
        "description": "Your horse displays as a unicorn",
        "cost_v": Decimal("12.00"),
        "type": "cosmetic",
    },
    "tournament_pass": {
        "name": "Weekend Tournament Pass",
        "description": "Entry to the Saturday Night Horse Derby",
        "cost_v": Decimal("25.00"),
        "type": "tournament",
    },
}
