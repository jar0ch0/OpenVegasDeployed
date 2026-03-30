"""Dummy fixture for multi-hunk patch testing."""


def normalize_name(value: str) -> str:
    return " ".join(value.split()).strip().lower()


def display_name(value: str) -> str:
    cleaned = normalize_name(value)
    return " ".join(part.capitalize() for part in cleaned.split())


def safe_slug(value: str) -> str:
    return normalize_name(display_name(value)).replace(" ", "-")

