#!/usr/bin/env python3
"""Provision dummy Supabase auth users for OpenVegas testing.

Usage:
  set -a; source .env; set +a
  python3 scripts/provision_dummy_users.py --env-name prod --count 5
"""

from __future__ import annotations

import argparse
import json
import secrets
import ssl
import string
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import os


def _required_env(name: str) -> str:
    value = str(os.getenv(name, "")).strip()
    if not value:
        raise RuntimeError(f"Missing required env var: {name}")
    return value


def _http_json(
    method: str,
    url: str,
    headers: dict[str, str],
    payload: dict[str, Any] | None = None,
    *,
    insecure_tls: bool = False,
) -> tuple[int, dict[str, Any]]:
    body: bytes | None = None
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url=url, method=method.upper(), headers=headers, data=body)
    ctx = ssl._create_unverified_context() if insecure_tls else None
    try:
        with urllib.request.urlopen(req, timeout=20, context=ctx) as resp:
            status = int(resp.getcode() or 0)
            raw = resp.read().decode("utf-8", errors="replace").strip()
            if not raw:
                return status, {}
            return status, json.loads(raw)
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace").strip()
        try:
            parsed = json.loads(raw) if raw else {}
        except Exception:
            parsed = {"error": raw}
        return int(e.code), parsed


@dataclass
class UserRecord:
    environment: str
    email: str
    password: str
    user_id: str
    status: str
    created_at: str


def _make_password(length: int = 18) -> str:
    if length < 14:
        length = 14
    alphabet = string.ascii_letters + string.digits
    core = "".join(secrets.choice(alphabet) for _ in range(length - 4))
    # Keep deterministic complexity guarantees.
    return "Ov!" + core + "9#"


def _list_users(
    base_url: str,
    headers: dict[str, str],
    *,
    insecure_tls: bool = False,
    max_pages: int = 10,
) -> list[dict[str, Any]]:
    users: list[dict[str, Any]] = []
    for page in range(1, max_pages + 1):
        url = f"{base_url}/auth/v1/admin/users?page={page}&per_page=100"
        status, body = _http_json("GET", url, headers, insecure_tls=insecure_tls)
        if status != 200:
            break
        page_users = list(body.get("users") or [])
        if not page_users:
            break
        users.extend(page_users)
        if len(page_users) < 100:
            break
    return users


def _find_user_by_email(base_url: str, headers: dict[str, str], email: str, *, insecure_tls: bool = False) -> dict[str, Any] | None:
    target = email.strip().lower()
    for user in _list_users(base_url, headers, insecure_tls=insecure_tls):
        if str(user.get("email", "")).strip().lower() == target:
            return user
    return None


def provision_dummy_users(
    *,
    env_name: str,
    count: int,
    email_prefix: str,
    email_domain: str,
    base_url: str,
    service_key: str,
    insecure_tls: bool = False,
) -> list[UserRecord]:
    headers = {
        "apikey": service_key,
        "Authorization": f"Bearer {service_key}",
        "Content-Type": "application/json",
    }
    created: list[UserRecord] = []
    now = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")

    for i in range(1, count + 1):
        email = f"{email_prefix}.{env_name}.{now}.{i}@{email_domain}".lower()
        password = _make_password()
        payload = {
            "email": email,
            "password": password,
            "email_confirm": True,
            "user_metadata": {
                "dummy": True,
                "openvegas_test_account": True,
                "environment": env_name,
                "seed": "scripts/provision_dummy_users.py",
            },
            "app_metadata": {
                "provider": "email",
                "providers": ["email"],
            },
        }
        status, body = _http_json(
            "POST",
            f"{base_url}/auth/v1/admin/users",
            headers,
            payload,
            insecure_tls=insecure_tls,
        )
        if status in {200, 201}:
            user = body.get("user") or body
            created.append(
                UserRecord(
                    environment=env_name,
                    email=email,
                    password=password,
                    user_id=str(user.get("id") or ""),
                    status="created",
                    created_at=datetime.now(timezone.utc).isoformat(),
                )
            )
            continue

        error_text = json.dumps(body, sort_keys=True)
        if "already" in error_text.lower() or "exists" in error_text.lower():
            existing = _find_user_by_email(base_url, headers, email, insecure_tls=insecure_tls)
            created.append(
                UserRecord(
                    environment=env_name,
                    email=email,
                    password=password,
                    user_id=str((existing or {}).get("id") or ""),
                    status="exists",
                    created_at=datetime.now(timezone.utc).isoformat(),
                )
            )
            continue
        raise RuntimeError(f"Failed creating {email}: status={status} body={error_text}")

    return created


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-name", required=True, help="Environment label, e.g. staging or prod")
    parser.add_argument("--count", type=int, default=5, help="How many users to create (max 5)")
    parser.add_argument("--email-prefix", default="ov.dummy", help="Email local-part prefix")
    parser.add_argument("--email-domain", default="openvegas.test", help="Email domain")
    parser.add_argument(
        "--out",
        default="test-accounts.generated.json",
        help="JSON output path (relative to repo root by default)",
    )
    parser.add_argument(
        "--insecure-tls",
        action="store_true",
        help="Disable TLS cert verification for local/dev environments only.",
    )
    args = parser.parse_args()

    if args.count < 1 or args.count > 5:
        raise RuntimeError("--count must be between 1 and 5")

    base_url = _required_env("SUPABASE_URL").rstrip("/")
    # Allow either key name for compatibility with existing env conventions.
    service_key = str(os.getenv("SUPABASE_SECRET_KEY", "")).strip() or str(os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")).strip()
    if not service_key:
        raise RuntimeError("Missing required env var: SUPABASE_SECRET_KEY or SUPABASE_SERVICE_ROLE_KEY")

    records = provision_dummy_users(
        env_name=args.env_name,
        count=args.count,
        email_prefix=args.email_prefix,
        email_domain=args.email_domain,
        base_url=base_url,
        service_key=service_key,
        insecure_tls=args.insecure_tls,
    )
    out_path = Path(args.out)
    if not out_path.is_absolute():
        out_path = Path.cwd() / out_path
    out_path.write_text(json.dumps([r.__dict__ for r in records], indent=2), encoding="utf-8")
    print(str(out_path))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        raise SystemExit(1)
