# -*- coding: utf-8 -*-
"""Tests for real escalation delivery (escalation_sender) and its wiring into
the store. Network transports are mocked — nothing is ever actually sent.
اختبارات إرسال التصعيد."""
import pytest

import escalation_sender as sender
import portfolio_store as store


SMTP_KEYS = ["SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_PASSWORD", "SMTP_FROM",
             "SMTP_STARTTLS", "WHATSAPP_TOKEN", "WHATSAPP_PHONE_ID"]


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """Start every test from an unconfigured (dry-run) baseline."""
    for k in SMTP_KEYS:
        monkeypatch.delenv(k, raising=False)
    yield


@pytest.fixture
def st_store(tmp_path):
    orig = store.DB_PATH
    store.reset(tmp_path / "t.db")
    yield store
    store.reset(orig)


def _row(**kw):
    base = {"project_id": "p1", "period_key": "jul", "cause": "gate",
            "owner": "Commercial", "channel": "email", "amount": 28282.0,
            "due": "31 Aug"}
    base.update(kw)
    return base


# --------------------------------------------------------------------------- #
#  Composition
# --------------------------------------------------------------------------- #
def test_compose_has_key_fields():
    subject, body = sender.compose(_row())
    assert "ELEVATE" in subject and "28,282" in subject
    assert "p1" in body and "31 Aug" in body


# --------------------------------------------------------------------------- #
#  Dry-run (default, unconfigured) — never touches the network
# --------------------------------------------------------------------------- #
def test_email_simulated_when_unconfigured():
    assert sender.is_configured("email") is False
    r = sender.send(_row(channel="email"))
    assert r["status"] == "simulated"
    assert r["channel"] == "email"


def test_whatsapp_simulated_when_unconfigured():
    r = sender.send(_row(channel="whatsapp", owner="HSE Manager"))
    assert r["status"] == "simulated"


def test_unknown_channel_is_error():
    r = sender.send(_row(channel="carrier-pigeon"))
    assert r["status"] == "error"


# --------------------------------------------------------------------------- #
#  Email — configured (SMTP mocked)
# --------------------------------------------------------------------------- #
class _FakeSMTP:
    instances = []

    def __init__(self, host, port, timeout=None):
        self.host, self.port = host, port
        self.started_tls = self.logged_in = False
        self.sent = []
        _FakeSMTP.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def starttls(self, context=None):
        self.started_tls = True

    def login(self, user, password):
        self.logged_in = (user, password)

    def send_message(self, msg):
        self.sent.append(msg)


def test_email_sent_when_configured(monkeypatch):
    _FakeSMTP.instances = []
    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("SMTP_USER", "u")
    monkeypatch.setenv("SMTP_PASSWORD", "p")
    monkeypatch.setattr(sender.smtplib, "SMTP", _FakeSMTP)

    assert sender.is_configured("email") is True
    r = sender.send(_row(channel="email", owner="Commercial"))
    assert r["status"] == "sent"
    assert r["to"] == "commercial@unitedbrothers.example"
    srv = _FakeSMTP.instances[-1]
    assert srv.started_tls and srv.logged_in == ("u", "p") and len(srv.sent) == 1


def test_email_skipped_without_recipient(monkeypatch):
    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    monkeypatch.setattr(sender.smtplib, "SMTP", _FakeSMTP)
    # Unknown owner -> no address on file -> skipped, never dials out.
    r = sender.send(_row(channel="email", owner="Nobody"))
    assert r["status"] == "skipped"


def test_email_error_is_captured(monkeypatch):
    def _boom(*a, **k):
        raise OSError("connection refused")

    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    monkeypatch.setattr(sender.smtplib, "SMTP", _boom)
    r = sender.send(_row(channel="email", owner="Commercial"))
    assert r["status"] == "error" and "connection refused" in r["detail"]


# --------------------------------------------------------------------------- #
#  WhatsApp — configured (HTTP mocked)
# --------------------------------------------------------------------------- #
def test_whatsapp_sent_when_configured(monkeypatch):
    monkeypatch.setenv("WHATSAPP_TOKEN", "tok")
    monkeypatch.setenv("WHATSAPP_PHONE_ID", "123")

    class _Resp:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    captured = {}

    def _fake_urlopen(req, timeout=None):
        captured["url"] = req.full_url
        captured["auth"] = req.headers.get("Authorization")
        return _Resp()

    monkeypatch.setattr(sender.urllib.request, "urlopen", _fake_urlopen)
    # HSE Manager has an empty whatsapp number by default -> skipped, no call.
    r = sender.send(_row(channel="whatsapp", owner="HSE Manager"))
    assert r["status"] == "skipped"
    assert "url" not in captured


def test_whatsapp_sent_with_recipient(monkeypatch):
    monkeypatch.setenv("WHATSAPP_TOKEN", "tok")
    monkeypatch.setenv("WHATSAPP_PHONE_ID", "123")
    monkeypatch.setitem(sender.pdata.ESCALATION_CONTACTS, "HSE Manager",
                        {"email": "hse@x.example", "whatsapp": "+201000000000"})

    class _Resp:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    seen = {}

    def _fake_urlopen(req, timeout=None):
        seen["url"] = req.full_url
        seen["auth"] = req.headers.get("Authorization")
        return _Resp()

    monkeypatch.setattr(sender.urllib.request, "urlopen", _fake_urlopen)
    r = sender.send(_row(channel="whatsapp", owner="HSE Manager"))
    assert r["status"] == "sent"
    assert "/123/messages" in seen["url"] and seen["auth"] == "Bearer tok"


# --------------------------------------------------------------------------- #
#  Store wiring
# --------------------------------------------------------------------------- #
def test_store_send_escalation_simulated_marks_sent(st_store):
    # Build a queued escalation via close_period, then send it (dry-run).
    from gainsharing_calculator import (GainsharingCalculator, ProjectFinancials,
                                         TeamMember)
    from conftest import RATES
    fin = ProjectFinancials("T", 12_000_000, 10_400_000, cash_collected_pct=0.82,
                            quality_factor=0.95, escalation_commodity="steel_rebar",
                            bad_debt_egp=150_000, subcontractor_value_egp=3_000_000,
                            lost_time_injuries=0)
    members = [TeamMember("A", "SM", ld_badge="Level 3", ppc=0.92)]
    gs = GainsharingCalculator(RATES).run(fin, members)
    st_store.close_period("p1", "jul", gs_result=gs,
                          site_agg={"total_lti": 0, "avg_ppc": 0.84})
    q = st_store.escalation_queue("jul")
    assert q and q[0]["status"] == "queued"
    res = st_store.send_escalation(q[0]["id"])
    assert res["status"] == "simulated"
    after = st_store.escalation_queue("jul")[0]
    assert after["status"] == "sent"
    assert "simulated" in (after["send_detail"] or "")


def test_store_send_escalation_error_status(st_store):
    from gainsharing_calculator import (GainsharingCalculator, ProjectFinancials,
                                         TeamMember)
    from conftest import RATES
    fin = ProjectFinancials("T", 12_000_000, 10_400_000, cash_collected_pct=0.60,
                            quality_factor=0.95, escalation_commodity="steel_rebar",
                            bad_debt_egp=150_000, subcontractor_value_egp=3_000_000,
                            lost_time_injuries=0)
    gs = GainsharingCalculator(RATES).run(fin, [TeamMember("A", "SM", ppc=0.9)])
    st_store.close_period("p3", "jul", gs_result=gs, site_agg={"total_lti": 0})
    q = st_store.escalation_queue("jul")
    res = st_store.send_escalation(
        q[0]["id"], sender=lambda row: {"channel": row["channel"], "to": "",
                                        "status": "error", "detail": "boom"})
    assert res["status"] == "error"
    after = st_store.escalation_queue("jul")[0]
    assert after["status"] == "error" and "boom" in (after["send_detail"] or "")


def test_send_queued_processes_all(st_store, monkeypatch):
    from gainsharing_calculator import (GainsharingCalculator, ProjectFinancials,
                                         TeamMember)
    from conftest import RATES
    fin = ProjectFinancials("T", 12_000_000, 10_400_000, cash_collected_pct=0.82,
                            quality_factor=0.95, escalation_commodity="steel_rebar",
                            bad_debt_egp=150_000, subcontractor_value_egp=3_000_000,
                            lost_time_injuries=0)
    gs = GainsharingCalculator(RATES).run(fin, [TeamMember("A", "SM", ppc=0.9)])
    st_store.close_period("p1", "jul", gs_result=gs, site_agg={"total_lti": 0})
    results = st_store.send_queued("jul")
    assert len(results) == 1
    assert all(r["status"] == "simulated" for r in results)
    assert st_store.escalation_queue("jul")[0]["status"] == "sent"
