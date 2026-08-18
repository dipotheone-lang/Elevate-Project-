#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
auth.py
=======
United Brothers Co. / الاخوة المتحدين للمقاولات
PROJECT ELEVATE — optional login + server-side role derivation (PORT_GUIDE §5.1)

Turns the demo **role selector** into a real identity boundary. When an
OpenID-Connect provider is configured, the dashboard requires sign-in and
derives the viewer's role **from their authenticated email** — the role can no
longer be self-selected, and tab scoping (``portfolio_data.ROLE_TABS``) becomes
a genuine server-side access control rather than a demo convenience.

Uses Streamlit's built-in OIDC auth (``st.login`` / ``st.user`` / ``st.logout``,
Streamlit ≥ 1.42), so it works with any provider — Google Workspace, Microsoft
Entra, Auth0, Okta — configured entirely through **secrets**, never the repo.

Safe by default
---------------
With no ``[auth]`` section configured, :func:`enabled` is ``False`` and the app
falls back to the existing role selector (demo mode). That keeps local runs, the
public demo, and the CI smoke tests working with zero configuration — the exact
same safe-by-default posture used by the escalation sender and the Postgres store.

Configuration (Streamlit secrets — `.streamlit/secrets.toml` or Cloud secrets)
-----------------------------------------------------------------------------
```toml
[auth]
redirect_uri   = "https://your-app.streamlit.app/oauth2callback"
cookie_secret  = "a-long-random-string"
client_id      = "…"
client_secret  = "…"
server_metadata_url = "https://accounts.google.com/.well-known/openid-configuration"
default_role   = "member"   # role for an authenticated but unmapped user

# email -> role (exec | mgr | member). Not in the repo; lives in secrets.
[roles]
"ceo@ubcsis.com"     = "exec"
"pm.sokhna@ubcsis.com" = "mgr"
"foreman@ubcsis.com" = "member"
```

Python: 3.10+  (streamlit only; no new dependency)
"""

from __future__ import annotations

from typing import Optional

import streamlit as st

ROLE_KEYS = ("exec", "mgr", "member")
DEFAULT_ROLE = "member"  # least privilege for an authenticated-but-unmapped user


# --------------------------------------------------------------------------- #
#  Secrets access (never raises when secrets are absent)
# --------------------------------------------------------------------------- #
def _section(name: str) -> dict:
    try:
        if name in st.secrets:  # type: ignore[operator]
            return dict(st.secrets[name])
    except Exception:  # pragma: no cover - no secrets file / not running in app
        pass
    return {}


# --------------------------------------------------------------------------- #
#  State
# --------------------------------------------------------------------------- #
def enabled() -> bool:
    """OIDC login is active only when an ``[auth]`` section is configured."""
    return bool(_section("auth"))


def is_logged_in() -> bool:
    try:
        return bool(st.user.is_logged_in)  # type: ignore[union-attr]
    except Exception:
        return False


def identity() -> dict:
    """The signed-in user's ``{email, name, picture}`` (lowercased email)."""
    def _attr(name: str) -> str:
        try:
            u = st.user
            val = u[name] if hasattr(u, "__getitem__") else None  # Mapping access
        except Exception:
            val = None
        if not val:
            val = getattr(getattr(st, "user", None), name, None)
        return val or ""

    email = str(_attr("email")).lower()
    return {"email": email, "name": str(_attr("name")) or email,
            "picture": str(_attr("picture"))}


# --------------------------------------------------------------------------- #
#  Role derivation (pure + config-backed)
# --------------------------------------------------------------------------- #
def role_map() -> dict:
    """`email(lower) -> role` from the ``[roles]`` secrets section."""
    raw = _section("roles")
    return {str(k).lower(): str(v) for k, v in raw.items() if str(v) in ROLE_KEYS}


def default_role() -> str:
    r = str(_section("auth").get("default_role", "") or DEFAULT_ROLE)
    return r if r in ROLE_KEYS else DEFAULT_ROLE


def role_for(email: str, roles: Optional[dict] = None, default: Optional[str] = None) -> str:
    """Resolve a role from an email. Pure when `roles`/`default` are passed —
    unmapped emails fall back to the least-privilege default role."""
    roles = role_map() if roles is None else roles
    default = default_role() if default is None else default
    return roles.get((email or "").lower(), default)
