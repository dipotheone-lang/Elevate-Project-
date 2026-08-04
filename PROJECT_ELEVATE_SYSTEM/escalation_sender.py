#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
escalation_sender.py
====================
United Brothers Co. / الاخوة المتحدين للمقاولات
PROJECT ELEVATE — real escalation delivery (PORT_GUIDE §5.2)

Turns a queued escalation row into an actual notification:

  * **email**    → SMTP (stdlib ``smtplib`` / ``email``)
  * **whatsapp** → WhatsApp Business Cloud API (Meta Graph API, stdlib ``urllib``)

Design principles
-----------------
* **Credentials never live in the repo.** Every secret is read from an
  environment variable, falling back to ``st.secrets`` when Streamlit is
  running. Nothing is hardcoded.
* **Safe by default.** When a channel is *not* configured the sender runs in
  **simulated** (dry-run) mode: it builds the message and returns success
  *without touching the network*. That keeps CI, offline runs and the public
  demo from ever sending — or crashing — while the exact same code path goes
  live the moment real credentials are present.
* **No new dependencies.** SMTP and the WhatsApp HTTPS call both use the
  standard library.

Each :func:`send` returns a small result dict::

    {"channel": "email", "to": "...", "status": "sent", "detail": "..."}

``status`` is one of ``sent`` · ``simulated`` · ``skipped`` · ``error``.

Configuration (all optional — absence ⇒ simulated)
--------------------------------------------------
SMTP:      ``SMTP_HOST`` ``SMTP_PORT`` (587) ``SMTP_USER`` ``SMTP_PASSWORD``
           ``SMTP_FROM`` ``SMTP_STARTTLS`` (true)
WhatsApp:  ``WHATSAPP_TOKEN`` ``WHATSAPP_PHONE_ID`` ``WHATSAPP_API_VERSION`` (v21.0)

Recipients (owner → address) come from ``portfolio_data.ESCALATION_CONTACTS``.

Python: 3.10+  (stdlib only)
"""

from __future__ import annotations

import json
import os
import smtplib
import ssl
import urllib.error
import urllib.request
from email.message import EmailMessage
from typing import Any, Callable, Optional

import portfolio_data as pdata

WHATSAPP_GRAPH_HOST = "https://graph.facebook.com"


# --------------------------------------------------------------------------- #
#  Configuration helpers
# --------------------------------------------------------------------------- #
def _secret(name: str) -> Optional[str]:
    """Read a secret from the environment, then Streamlit secrets. Never raises."""
    val = os.environ.get(name)
    if val not in (None, ""):
        return val
    try:  # Streamlit is an app dependency but must be optional for CI/offline.
        import streamlit as st  # noqa: WPS433 (local import on purpose)

        if name in st.secrets:  # type: ignore[operator]
            sv = st.secrets[name]
            return str(sv) if sv not in (None, "") else None
    except Exception:  # pragma: no cover - streamlit absent / no secrets file
        pass
    return None


def _flag(name: str, default: bool) -> bool:
    raw = _secret(name)
    if raw is None:
        return default
    return raw.strip().lower() not in ("0", "false", "no", "off")


def smtp_configured() -> bool:
    return bool(_secret("SMTP_HOST"))


def whatsapp_configured() -> bool:
    return bool(_secret("WHATSAPP_TOKEN") and _secret("WHATSAPP_PHONE_ID"))


def is_configured(channel: str | None = None) -> bool:
    """True if the given channel (or any channel) can really send."""
    if channel == "email":
        return smtp_configured()
    if channel == "whatsapp":
        return whatsapp_configured()
    return smtp_configured() or whatsapp_configured()


def _recipient(owner: str, channel: str) -> str:
    contact = pdata.ESCALATION_CONTACTS.get(owner, {})
    return str(contact.get(channel, "") or "")


# --------------------------------------------------------------------------- #
#  Message composition
# --------------------------------------------------------------------------- #
def _cause_label(cause: str) -> str:
    return pdata.CAUSE.get(cause, {}).get("en", cause)


def compose(row: dict) -> tuple[str, str]:
    """Return (subject, body) for an escalation row. Kept pure for testing."""
    cause = row.get("cause", "")
    label = _cause_label(cause)
    project = row.get("project_id", "—")
    period = row.get("period_key", "—")
    amount = row.get("amount") or 0
    due = row.get("due", "")
    sla = pdata.ESCALATION_OWNERS.get(cause, {}).get("sla_days", "")
    subject = f"[ELEVATE] {label} — {project} / {period} (EGP {amount:,.0f} blocked)"
    body = (
        "PROJECT ELEVATE — escalation\n"
        "United Brothers Co. / الاخوة المتحدين للمقاولات\n"
        "----------------------------------------------\n"
        f"Cause      : {label} ({cause})\n"
        f"Project    : {project}\n"
        f"Period     : {period}\n"
        f"Owner      : {row.get('owner', '—')}\n"
        f"Amount held: EGP {amount:,.0f}\n"
        f"Action due : {due}"
        + (f"  (SLA {sla} days)" if sla else "")
        + "\n----------------------------------------------\n"
        "This is an automated notification fired on period close. "
        "Please action the item before the due date.\n"
    )
    return subject, body


# --------------------------------------------------------------------------- #
#  Channel senders
# --------------------------------------------------------------------------- #
def _send_email(row: dict) -> dict:
    to = _recipient(row.get("owner", ""), "email")
    subject, body = compose(row)
    result = {"channel": "email", "to": to, "status": "simulated", "detail": ""}

    if not smtp_configured():
        result["detail"] = "SMTP not configured — simulated (dry-run)"
        return result
    if not to:
        result["status"] = "skipped"
        result["detail"] = f"no email on file for owner '{row.get('owner')}'"
        return result

    host = _secret("SMTP_HOST")
    port = int(_secret("SMTP_PORT") or 587)
    user = _secret("SMTP_USER")
    password = _secret("SMTP_PASSWORD")
    sender = _secret("SMTP_FROM") or user or "elevate@unitedbrothers.example"

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = to
    msg.set_content(body)

    try:
        with smtplib.SMTP(host, port, timeout=20) as srv:
            if _flag("SMTP_STARTTLS", True):
                srv.starttls(context=ssl.create_default_context())
            if user and password:
                srv.login(user, password)
            srv.send_message(msg)
        result["status"] = "sent"
        result["detail"] = f"SMTP {host}:{port}"
    except Exception as exc:  # smtplib / ssl / socket errors
        result["status"] = "error"
        result["detail"] = f"{type(exc).__name__}: {exc}"
    return result


def _send_whatsapp(row: dict) -> dict:
    to = _recipient(row.get("owner", ""), "whatsapp")
    _, body = compose(row)
    result = {"channel": "whatsapp", "to": to, "status": "simulated", "detail": ""}

    if not whatsapp_configured():
        result["detail"] = "WhatsApp not configured — simulated (dry-run)"
        return result
    if not to:
        result["status"] = "skipped"
        result["detail"] = f"no WhatsApp number on file for owner '{row.get('owner')}'"
        return result

    token = _secret("WHATSAPP_TOKEN")
    phone_id = _secret("WHATSAPP_PHONE_ID")
    version = _secret("WHATSAPP_API_VERSION") or "v21.0"
    url = f"{WHATSAPP_GRAPH_HOST}/{version}/{phone_id}/messages"
    payload = json.dumps({
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": body},
    }).encode("utf-8")
    req = urllib.request.Request(
        url, data=payload, method="POST",
        headers={"Authorization": f"Bearer {token}",
                 "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:  # noqa: S310 (trusted host)
            result["status"] = "sent"
            result["detail"] = f"HTTP {resp.status}"
    except urllib.error.HTTPError as exc:
        result["status"] = "error"
        detail = exc.read().decode("utf-8", "replace")[:300] if hasattr(exc, "read") else str(exc)
        result["detail"] = f"HTTP {exc.code}: {detail}"
    except Exception as exc:
        result["status"] = "error"
        result["detail"] = f"{type(exc).__name__}: {exc}"
    return result


_DISPATCH: dict[str, Callable[[dict], dict]] = {
    "email": _send_email,
    "whatsapp": _send_whatsapp,
}


# --------------------------------------------------------------------------- #
#  Public entry point
# --------------------------------------------------------------------------- #
def send(row: dict) -> dict:
    """Deliver one escalation row on its ``channel``. Never raises — any failure
    comes back as ``status="error"`` with a ``detail`` message."""
    channel = str(row.get("channel", "email"))
    handler = _DISPATCH.get(channel)
    if handler is None:
        return {"channel": channel, "to": "", "status": "error",
                "detail": f"unknown channel '{channel}'"}
    return handler(row)
