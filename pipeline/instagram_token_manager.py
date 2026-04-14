"""
instagram_token_manager.py — Access Token Lifecycle Manager
============================================================
Instagram access tokens expire after 60 days.
This module handles:
  - First-time token exchange (short-lived → long-lived)
  - Automatic refresh before expiry
  - Token storage in .env and credentials/instagram_token.json

RUN ONCE to generate your first long-lived token:
    python -m pipeline.instagram_token_manager --exchange --short-token YOUR_SHORT_TOKEN

After that, the pipeline auto-refreshes tokens before each upload.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
from datetime import datetime, timedelta
from pathlib import Path

import requests
from dotenv import load_dotenv, set_key

load_dotenv()
log = logging.getLogger("pipeline.instagram_token_manager")

TOKEN_CACHE_FILE = Path("credentials/instagram_token.json")
ENV_FILE         = Path(".env")
# GRAPH_BASE       = "https://graph.facebook.com/v21.0"
GRAPH_BASE_FB = "https://graph.facebook.com/v21.0"    # for media publish
GRAPH_BASE_IG = "https://graph.instagram.com/v21.0"   # for account queries

# ─────────────────────────────────────────────────────────────────────────────

def exchange_for_long_lived_token(short_lived_token: str) -> dict:
    """
    Exchange a short-lived token (1 hour) for a long-lived token (60 days).

    Args:
        short_lived_token: Token from Meta's token generator / OAuth flow.

    Returns:
        dict with: access_token, token_type, expires_in
    """
    app_id     = os.getenv("META_APP_ID")
    app_secret = os.getenv("META_APP_SECRET")

    if not app_id or not app_secret:
        raise RuntimeError(
            "META_APP_ID and META_APP_SECRET must be set in .env\n"
            "Get them from https://developers.facebook.com/apps/"
        )

    log.info("Exchanging short-lived token for long-lived token...")
    url = f"{GRAPH_BASE_IG}/oauth/access_token"
    params = {
        "grant_type":        "fb_exchange_token",
        "client_id":         app_id,
        "client_secret":     app_secret,
        "fb_exchange_token": short_lived_token,
    }
    resp = requests.get(url, params=params, timeout=30)
    data = resp.json()

    if "error" in data:
        raise RuntimeError(f"Token exchange failed: {data['error']}")

    long_token   = data["access_token"]
    expires_in   = data.get("expires_in", 5183944)   # ~60 days in seconds
    expires_at   = (datetime.utcnow() + timedelta(seconds=expires_in)).isoformat()

    # Save to cache file
    _save_token_cache(long_token, expires_at)

    # Update .env
    if ENV_FILE.exists():
        set_key(str(ENV_FILE), "INSTAGRAM_ACCESS_TOKEN", long_token)
        log.info(f"Updated INSTAGRAM_ACCESS_TOKEN in {ENV_FILE}")

    log.info(f"Long-lived token obtained. Expires: {expires_at}")
    return {"access_token": long_token, "expires_at": expires_at}


def refresh_token_if_needed() -> str:
    """
    Check if the current token expires within 10 days.
    If so, refresh it automatically.

    Returns:
        The current (or newly refreshed) access token string.
    """
    token = os.getenv("INSTAGRAM_ACCESS_TOKEN")
    if not token:
        raise RuntimeError(
            "INSTAGRAM_ACCESS_TOKEN not set. "
            "Run: python -m pipeline.instagram_token_manager --exchange --short-token YOUR_TOKEN"
        )

    # Check expiry from cache
    cache = _load_token_cache()
    if cache:
        expires_at = datetime.fromisoformat(cache.get("expires_at", "2000-01-01"))
        days_left  = (expires_at - datetime.utcnow()).days
        log.info(f"Token expires in {days_left} days ({expires_at.date()})")

        if days_left <= 10:
            log.info("Token expiring soon — refreshing automatically...")
            token = _refresh_long_lived_token(token)
        else:
            log.info("Token is valid. No refresh needed.")

    return token


def _refresh_long_lived_token(current_token: str) -> str:
    """Refresh a long-lived token before it expires."""
    url = f"{GRAPH_BASE_IG}/oauth/access_token"
    params = {
        "grant_type":   "ig_refresh_token",
        "access_token": current_token,
    }
    resp = requests.get(url, params=params, timeout=30)
    data = resp.json()

    if "error" in data:
        raise RuntimeError(f"Token refresh failed: {data['error']}")

    new_token  = data["access_token"]
    expires_in = data.get("expires_in", 5183944)
    expires_at = (datetime.utcnow() + timedelta(seconds=expires_in)).isoformat()

    _save_token_cache(new_token, expires_at)
    if ENV_FILE.exists():
        set_key(str(ENV_FILE), "INSTAGRAM_ACCESS_TOKEN", new_token)

    log.info(f"Token refreshed. New expiry: {expires_at}")
    return new_token


def get_instagram_account_id(access_token: str) -> str:
    """
    Auto-discover your Instagram Account ID from the access token.
    Run this once if you don't know your INSTAGRAM_ACCOUNT_ID.
    """
    url = f"{GRAPH_BASE_IG}/me/accounts"
    params = {"access_token": access_token}
    resp = requests.get(url, params=params, timeout=15)
    pages = resp.json().get("data", [])

    if not pages:
        raise RuntimeError(
            "No Facebook Pages found for this token.\n"
            "Make sure your Instagram account is connected to a Facebook Page."
        )

    # For each page, get connected Instagram account
    for page in pages:
        page_id    = page["id"]
        page_token = page.get("access_token", access_token)

        ig_resp = requests.get(
            f"{GRAPH_BASE_IG}/{page_id}",
            params={"fields": "instagram_business_account", "access_token": page_token},
            timeout=15,
        )
        ig_data = ig_resp.json()
        ig_acct = ig_data.get("instagram_business_account", {})
        ig_id   = ig_acct.get("id")

        if ig_id:
            log.info(f"Found Instagram Account ID: {ig_id} (Page: {page['name']})")
            print(f"\n✓ Your INSTAGRAM_ACCOUNT_ID = {ig_id}")
            print(f"  (Connected to Facebook Page: {page['name']})")
            print(f"\nAdd to your .env file:")
            print(f"  INSTAGRAM_ACCOUNT_ID={ig_id}")
            return ig_id

    raise RuntimeError(
        "No Instagram Professional account found connected to your Facebook Pages.\n"
        "See INSTAGRAM_SETUP_GUIDE.md — Step 3: Connect Instagram to Facebook Page."
    )


def _save_token_cache(token: str, expires_at: str) -> None:
    TOKEN_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    data = {"access_token": token, "expires_at": expires_at}
    TOKEN_CACHE_FILE.write_text(json.dumps(data, indent=2))


def _load_token_cache() -> dict:
    if TOKEN_CACHE_FILE.exists():
        try:
            return json.loads(TOKEN_CACHE_FILE.read_text())
        except Exception:
            return {}
    return {}


# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(description="Instagram Token Manager")
    parser.add_argument(
        "--exchange", action="store_true",
        help="Exchange a short-lived token for a long-lived token"
    )
    parser.add_argument(
        "--short-token", type=str,
        help="The short-lived token from Meta token generator"
    )
    parser.add_argument(
        "--find-account-id", action="store_true",
        help="Auto-discover your INSTAGRAM_ACCOUNT_ID from the current token"
    )
    parser.add_argument(
        "--check", action="store_true",
        help="Check current token status and refresh if needed"
    )
    args = parser.parse_args()

    if args.exchange:
        if not args.short_token:
            print("ERROR: --short-token is required with --exchange")
        else:
            result = exchange_for_long_lived_token(args.short_token)
            print(f"\n✓ Long-lived token saved to .env and credentials/instagram_token.json")
            print(f"  Expires: {result['expires_at']}")

    elif args.find_account_id:
        token = os.getenv("INSTAGRAM_ACCESS_TOKEN")
        if not token:
            print("ERROR: Set INSTAGRAM_ACCESS_TOKEN in .env first")
        else:
            get_instagram_account_id(token)

    elif args.check:
        token = refresh_token_if_needed()
        print(f"✓ Token is valid and active")

    else:
        parser.print_help()