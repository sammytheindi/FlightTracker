"""Email alert system for price drops."""

from __future__ import annotations

import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from src.api.base import FlightResult
from src.config import AlertsConfig

logger = logging.getLogger(__name__)


def check_and_alert(results: list[FlightResult], alerts_config: AlertsConfig) -> list[FlightResult]:
    """
    Filter results below the configured threshold and send an alert email
    if any are found.

    Args:
        results: All flight results from the current search run.
        alerts_config: Alerts section of AppConfig.

    Returns:
        The subset of results that triggered an alert (may be empty).
    """
    if not alerts_config.enabled:
        return []

    deals = [r for r in results if r.price_per_person < alerts_config.threshold_usd]
    if not deals:
        return []

    deals.sort(key=lambda r: r.price_per_person)

    if alerts_config.email:
        try:
            _send_email(deals, alerts_config)
            logger.info("Alert email sent for %d deal(s)", len(deals))
        except Exception as e:
            logger.error("Failed to send alert email: %s", e)

    return deals


def _send_email(deals: list[FlightResult], config: AlertsConfig) -> None:
    """Build and send a consolidated alert email."""
    email_cfg = config.email
    assert email_cfg is not None  # checked by caller

    subject = f"FlightTracker: {len(deals)} deal(s) below ${config.threshold_usd:.0f}/person"
    body = _build_body(deals, config.threshold_usd)

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = email_cfg.sender
    msg["To"] = ", ".join(email_cfg.recipients)
    msg.attach(MIMEText(body, "plain"))

    with smtplib.SMTP(email_cfg.smtp_host, email_cfg.smtp_port) as smtp:
        smtp.ehlo()
        smtp.starttls()
        smtp.login(email_cfg.sender, email_cfg.password)
        smtp.sendmail(
            email_cfg.sender,
            email_cfg.recipients,
            msg.as_string(),
        )


def _build_body(deals: list[FlightResult], threshold: float) -> str:
    """Format the plain-text email body."""
    lines = [
        f"FlightTracker found {len(deals)} flight(s) below ${threshold:.0f}/person:\n",
    ]
    for i, deal in enumerate(deals, 1):
        lines.append(
            f"{i}. {deal.origin} → {deal.destination}\n"
            f"   Depart: {deal.depart_date}  |  Return: {deal.return_date}\n"
            f"   Price:  ${deal.price_per_person:.0f}/person  (${deal.price_usd:.0f} total)\n"
            f"   Airline: {deal.airline}  |  Stops: {deal.stops}  |  Duration: {deal.duration_hrs:.1f}h\n"
        )
    lines.append("\nPrices are subject to change. Verify on the airline or booking site before purchasing.")
    return "\n".join(lines)
