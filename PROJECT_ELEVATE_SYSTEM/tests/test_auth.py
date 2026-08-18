# -*- coding: utf-8 -*-
"""Tests for auth role derivation. Pure logic — no OIDC provider or secrets file
needed. اختبارات المصادقة والأدوار."""
import auth


# --------------------------------------------------------------------------- #
#  Disabled by default (demo mode) — the safe fallback that keeps CI green
# --------------------------------------------------------------------------- #
def test_auth_disabled_without_secrets():
    # No .streamlit/secrets.toml in the test env -> no [auth] section.
    assert auth.enabled() is False
    assert auth.is_logged_in() is False


# --------------------------------------------------------------------------- #
#  Role derivation (pure)
# --------------------------------------------------------------------------- #
def test_role_for_maps_email():
    roles = {"ceo@ubcsis.com": "exec", "pm@ubcsis.com": "mgr"}
    assert auth.role_for("ceo@ubcsis.com", roles=roles, default="member") == "exec"
    assert auth.role_for("pm@ubcsis.com", roles=roles, default="member") == "mgr"


def test_role_for_is_case_insensitive():
    roles = {"ceo@ubcsis.com": "exec"}
    assert auth.role_for("CEO@UBCSIS.com", roles=roles, default="member") == "exec"


def test_role_for_unmapped_falls_back_to_least_privilege():
    roles = {"ceo@ubcsis.com": "exec"}
    # Unknown or blank email must not inherit any elevated role.
    assert auth.role_for("stranger@ubcsis.com", roles=roles, default="member") == "member"
    assert auth.role_for("", roles=roles, default="member") == "member"


def test_default_role_constant_is_member():
    assert auth.DEFAULT_ROLE == "member"
    assert "exec" in auth.ROLE_KEYS and "mgr" in auth.ROLE_KEYS


def test_role_map_ignores_invalid_roles(monkeypatch):
    # A typo'd role in secrets must be dropped, not trusted.
    monkeypatch.setattr(auth, "_section",
                        lambda name: {"a@x.com": "exec", "b@x.com": "superadmin"} if name == "roles" else {})
    m = auth.role_map()
    assert m == {"a@x.com": "exec"}


def test_default_role_reads_auth_section(monkeypatch):
    monkeypatch.setattr(auth, "_section",
                        lambda name: {"default_role": "mgr"} if name == "auth" else {})
    assert auth.default_role() == "mgr"
    # invalid default -> member
    monkeypatch.setattr(auth, "_section",
                        lambda name: {"default_role": "root"} if name == "auth" else {})
    assert auth.default_role() == "member"
