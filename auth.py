"""
Intigriti authentication and local credential storage.

Supported modes:
  1. PAT / bearer token storage for the official researcher API.
  2. OIDC password grant, including optional OTP/TOTP fields, when the
     account/client permits direct credential login.

The researcher API documentation recommends Personal Access Tokens. The
credential flow is best-effort because Intigriti may restrict password grant
usage by client.
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
import jwt

SERVER_DIR = Path(__file__).resolve().parent
CONFIG_DIR = SERVER_DIR / "config"
TOKEN_FILE = CONFIG_DIR / "token.json"

IDENTITY_BASE = "https://login.intigriti.com"


class OtpRequired(Exception):
    """Raised when the identity provider asks for a second factor."""


def _ensure_config_dir() -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)


def _decode_exp(token: str) -> float | None:
    try:
        payload = jwt.decode(token, options={"verify_signature": False})
        exp = payload.get("exp")
        return float(exp) if exp else None
    except Exception:
        return None


def _expiry_label(exp: float | None) -> str:
    if not exp:
        return "unknown/non-JWT"
    return datetime.fromtimestamp(exp, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def save_token(token: str, auth_type: str = "bearer", refresh_token: str = "", exp: float | None = None) -> None:
    _ensure_config_dir()
    token = token.strip()
    if not token:
        raise ValueError("Token must not be empty.")
    if exp is None:
        exp = _decode_exp(token)
    TOKEN_FILE.write_text(
        json.dumps(
            {
                "token": token,
                "refresh_token": refresh_token,
                "auth_type": auth_type,
                "exp": exp,
                "stored_at": int(time.time()),
            },
            indent=2,
        )
    )
    try:
        TOKEN_FILE.chmod(0o600)
    except OSError:
        pass


def load_token() -> str | None:
    """
    Return a configured bearer/PAT token.

    Resolution order:
      1. INTIGRITI_PAT
      2. INTIGRITI_TOKEN
      3. ./config/token.json next to this server
    """
    for name in ("INTIGRITI_PAT", "INTIGRITI_TOKEN"):
        value = os.environ.get(name, "").strip()
        if value:
            return value

    if not TOKEN_FILE.exists():
        return None
    try:
        data = json.loads(TOKEN_FILE.read_text())
        exp = data.get("exp")
        if exp and time.time() >= float(exp) - 60:
            return None
        token = str(data.get("token", "")).strip()
        return token or None
    except Exception:
        return None


def store_bearer_token(token: str, auth_type: str = "token") -> str:
    token = token.strip()
    save_token(token, auth_type=auth_type)
    exp = _decode_exp(token)
    return f"Stored Intigriti {auth_type}. Expiry: {_expiry_label(exp)}."


def store_pat(pat: str) -> str:
    return store_bearer_token(pat, "pat")


async def password_login(
    email: str,
    password: str,
    otp: str | None = None,
    client_id: str = "",
    client_secret: str = "",
    scope: str = "researcher_external_api offline_access",
) -> str:
    """
    Authenticate through Intigriti's OIDC password grant.

    The public OpenID configuration advertises the password grant, but not a
    public client id. Provide client_id/client_secret if your Intigriti setup
    requires one. PAT auth is the reliable documented researcher API path.
    """
    if not email or not password:
        raise ValueError("email and password are required for credential authentication.")

    form: dict[str, Any] = {
        "grant_type": "password",
        "username": email,
        "password": password,
        "scope": scope,
    }
    if client_id:
        form["client_id"] = client_id
    if client_secret:
        form["client_secret"] = client_secret
    if otp:
        # Different IdentityServer integrations name this field differently.
        # Sending the common aliases keeps the flow useful across deployments.
        form["otp"] = otp
        form["totp"] = otp
        form["two_factor_code"] = otp

    async with httpx.AsyncClient(base_url=IDENTITY_BASE, timeout=30.0) as http:
        resp = await http.post("/connect/token", data=form)

    try:
        data = resp.json()
    except ValueError:
        data = {"error": resp.text}

    if resp.status_code in (400, 401):
        error = str(data.get("error_description") or data.get("error") or "login failed")
        lowered = error.lower()
        if any(term in lowered for term in ("otp", "totp", "two-factor", "two factor", "mfa", "2fa")):
            raise OtpRequired("OTP required. Call authenticate again with the otp argument.")
        raise ValueError(f"Credential login failed: {error}")
    if resp.status_code >= 400:
        raise ValueError(f"Credential login error {resp.status_code}: {data}")

    token = data.get("access_token")
    if not token:
        raise ValueError(f"No access_token in response. Keys: {list(data.keys())}")

    exp = time.time() + float(data.get("expires_in", 0) or 0) if data.get("expires_in") else _decode_exp(token)
    save_token(token, auth_type="credential", refresh_token=str(data.get("refresh_token", "")), exp=exp)
    return f"Authenticated with credentials. Token expiry: {_expiry_label(exp)}."
