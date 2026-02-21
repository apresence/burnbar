"""OAuth credential management for Claude.ai (Max plan) authentication."""

import base64
import hashlib
import json
import logging
import os
import secrets
import time
import webbrowser
from pathlib import Path
from urllib.parse import urlencode

import requests

logger = logging.getLogger("burnbar.oauth")

# ------------------------------------------------------------------ #
#  Constants
# ------------------------------------------------------------------ #

CLIENT_ID = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"
AUTH_URL = "https://claude.ai/oauth/authorize"
TOKEN_URL = "https://console.anthropic.com/v1/oauth/token"
REDIRECT_URI = "https://console.anthropic.com/oauth/code/callback"
SCOPES = "user:inference user:profile"

CLAUDE_CODE_CREDS = Path.home() / ".claude" / ".credentials.json"

# Refresh 5 minutes before actual expiry
_EXPIRY_BUFFER_SECONDS = 300


# ------------------------------------------------------------------ #
#  Claude Code credential import
# ------------------------------------------------------------------ #

def load_claude_code_credentials() -> dict | None:
    """Read cached OAuth tokens from Claude Code's credential store.

    Returns dict with 'accessToken', 'refreshToken', 'expiresAt'
    or None if unavailable.
    """
    if not CLAUDE_CODE_CREDS.exists():
        logger.debug("Claude Code credentials file not found: %s", CLAUDE_CODE_CREDS)
        return None

    try:
        with open(CLAUDE_CODE_CREDS, "r") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Failed to read Claude Code credentials: %s", exc)
        return None

    # The file stores credentials keyed by provider or as a flat dict.
    # Claude Code uses a structure like:
    #   {"default": {"accessToken": "...", "refreshToken": "...", "expiresAt": ...}}
    # or it may be a flat dict.
    creds = None
    if isinstance(data, dict):
        # Try "default" key first, then flat structure
        if "default" in data:
            creds = data["default"]
        elif "accessToken" in data:
            creds = data
        else:
            # Try first value if dict of providers
            for key, val in data.items():
                if isinstance(val, dict) and "accessToken" in val:
                    creds = val
                    break

    if not creds or "accessToken" not in creds:
        logger.warning("No accessToken found in Claude Code credentials")
        return None

    logger.info("Loaded Claude Code credentials (expires_at=%s)", creds.get("expiresAt"))
    return creds


# ------------------------------------------------------------------ #
#  PKCE helpers
# ------------------------------------------------------------------ #

def generate_pkce() -> tuple[str, str]:
    """Generate a PKCE code_verifier and code_challenge pair."""
    code_verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    code_challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return code_verifier, code_challenge


def get_authorization_url(code_challenge: str, state: str) -> str:
    """Build the OAuth authorization URL for browser-based login."""
    params = {
        "response_type": "code",
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "scope": SCOPES,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "state": state,
    }
    return f"{AUTH_URL}?{urlencode(params)}"


# ------------------------------------------------------------------ #
#  Token exchange & refresh
# ------------------------------------------------------------------ #

def exchange_code(code: str, code_verifier: str) -> tuple[str, str, int]:
    """Exchange an authorization code for tokens.

    Returns (access_token, refresh_token, expires_at_epoch).
    """
    resp = requests.post(TOKEN_URL, json={
        "grant_type": "authorization_code",
        "client_id": CLIENT_ID,
        "code": code,
        "redirect_uri": REDIRECT_URI,
        "code_verifier": code_verifier,
    }, timeout=15)

    if resp.status_code != 200:
        body = ""
        try:
            body = resp.json().get("error_description", resp.text[:200])
        except Exception:
            body = resp.text[:200]
        raise RuntimeError(f"Token exchange failed ({resp.status_code}): {body}")

    data = resp.json()
    access_token = data["access_token"]
    refresh_token = data.get("refresh_token", "")
    expires_in = data.get("expires_in", 3600)
    expires_at = int(time.time()) + expires_in

    logger.info("Token exchange successful (expires_in=%ds)", expires_in)
    return access_token, refresh_token, expires_at


def refresh_access_token(refresh_token: str) -> tuple[str, str, int]:
    """Refresh an expired access token.

    Returns (new_access_token, new_refresh_token, new_expires_at_epoch).
    """
    resp = requests.post(TOKEN_URL, json={
        "grant_type": "refresh_token",
        "client_id": CLIENT_ID,
        "refresh_token": refresh_token,
    }, timeout=15)

    if resp.status_code != 200:
        body = ""
        try:
            body = resp.json().get("error_description", resp.text[:200])
        except Exception:
            body = resp.text[:200]
        raise RuntimeError(f"Token refresh failed ({resp.status_code}): {body}")

    data = resp.json()
    new_access_token = data["access_token"]
    new_refresh_token = data.get("refresh_token", refresh_token)
    expires_in = data.get("expires_in", 3600)
    new_expires_at = int(time.time()) + expires_in

    logger.info("Token refresh successful (expires_in=%ds)", expires_in)
    return new_access_token, new_refresh_token, new_expires_at


# ------------------------------------------------------------------ #
#  Expiry check
# ------------------------------------------------------------------ #

def is_token_expired(expires_at: int) -> bool:
    """Check if token is expired or will expire within the buffer window."""
    if expires_at <= 0:
        return True
    return time.time() >= (expires_at - _EXPIRY_BUFFER_SECONDS)
