"""Tests for src/alerts.py — SMTP is fully mocked, no emails are sent."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.alerts import check_and_alert, _build_body
from src.config import AlertsConfig, EmailConfig
from tests.fixtures.sample_results import CHEAP_RESULT, EXPENSIVE_RESULT, MID_RESULT


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_alerts_config(
    enabled: bool = True,
    threshold: float = 1000.0,
    with_email: bool = True,
) -> AlertsConfig:
    email = None
    if with_email:
        email = EmailConfig(
            smtp_host="smtp.gmail.com",
            smtp_port=587,
            sender="test@test.com",
            password="secret",
            recipients=["dest@test.com"],
        )
    return AlertsConfig(enabled=enabled, threshold_usd=threshold, email=email)


# ---------------------------------------------------------------------------
# check_and_alert — no email
# ---------------------------------------------------------------------------


def test_alerts_disabled_returns_empty():
    config = make_alerts_config(enabled=False)
    deals = check_and_alert([CHEAP_RESULT, MID_RESULT], config)
    assert deals == []


def test_no_deals_below_threshold():
    config = make_alerts_config(threshold=500.0)
    deals = check_and_alert([CHEAP_RESULT, MID_RESULT, EXPENSIVE_RESULT], config)
    assert deals == []


def test_deals_filtered_below_threshold():
    config = make_alerts_config(threshold=1000.0, with_email=False)
    deals = check_and_alert([CHEAP_RESULT, MID_RESULT, EXPENSIVE_RESULT], config)
    # CHEAP ($800) and MID ($1050) — only CHEAP is below 1000
    assert len(deals) == 1
    assert deals[0].price_per_person == pytest.approx(800.0)


def test_deals_sorted_cheapest_first():
    from tests.fixtures.sample_results import make_result

    r1 = make_result(price_per_person=900.0)
    r2 = make_result(price_per_person=700.0)
    r3 = make_result(price_per_person=850.0)
    config = make_alerts_config(threshold=1000.0, with_email=False)

    deals = check_and_alert([r1, r2, r3], config)
    assert [d.price_per_person for d in deals] == pytest.approx([700.0, 850.0, 900.0])


def test_empty_results_no_alert():
    config = make_alerts_config()
    deals = check_and_alert([], config)
    assert deals == []


# ---------------------------------------------------------------------------
# check_and_alert — with mocked SMTP
# ---------------------------------------------------------------------------


@patch("src.alerts.smtplib.SMTP")
def test_email_sent_when_deal_found(mock_smtp_cls):
    mock_smtp = MagicMock()
    mock_smtp_cls.return_value.__enter__ = MagicMock(return_value=mock_smtp)
    mock_smtp_cls.return_value.__exit__ = MagicMock(return_value=False)

    config = make_alerts_config(threshold=1000.0)
    deals = check_and_alert([CHEAP_RESULT], config)

    assert len(deals) == 1
    mock_smtp_cls.assert_called_once_with("smtp.gmail.com", 587)
    mock_smtp.login.assert_called_once()
    mock_smtp.sendmail.assert_called_once()


@patch("src.alerts.smtplib.SMTP")
def test_no_email_when_no_deals(mock_smtp_cls):
    config = make_alerts_config(threshold=100.0)  # threshold very low, no deals
    check_and_alert([CHEAP_RESULT], config)

    mock_smtp_cls.assert_not_called()


@patch("src.alerts.smtplib.SMTP")
def test_email_send_failure_does_not_raise(mock_smtp_cls):
    """A failed email should log an error but not crash the program."""
    mock_smtp_cls.side_effect = ConnectionRefusedError("Cannot connect")

    config = make_alerts_config(threshold=1000.0)
    # Should not raise
    deals = check_and_alert([CHEAP_RESULT], config)
    assert len(deals) == 1  # deals are still returned even if email fails


# ---------------------------------------------------------------------------
# _build_body
# ---------------------------------------------------------------------------


def test_build_body_contains_key_info():
    body = _build_body([CHEAP_RESULT], threshold=1000.0)

    assert "DFW" in body
    assert "AMD" in body
    assert "800" in body
    assert "2026-12-15" in body
    assert "2027-01-05" in body


def test_build_body_multiple_deals():
    from tests.fixtures.sample_results import make_result

    deals = [make_result(price_per_person=p) for p in [700.0, 850.0, 950.0]]
    body = _build_body(deals, threshold=1000.0)

    assert "3 flight" in body
    assert "700" in body
    assert "850" in body
    assert "950" in body
