"""Daily email reports with price trend charts and depart/return date matrices."""

from __future__ import annotations

import io
import logging
import smtplib
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime

import matplotlib
matplotlib.use("Agg")  # non-interactive backend — must be set before importing pyplot
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

from src.config import AppConfig
from src.db import Database

logger = logging.getLogger(__name__)


def send_daily_report(config: AppConfig, db_path: str) -> None:
    """
    Generate and send a daily price report email for every origin/destination
    pair defined in config.search.

    Raises:
        ValueError: if alerts.email is not configured.
    """
    if not config.alerts.email:
        raise ValueError(
            "alerts.email must be configured to send daily reports. "
            "Add smtp_host, smtp_port, sender, password, and recipients to config.yaml."
        )

    db = Database(db_path)
    try:
        for origin in config.search.origins:
            for destination in config.search.destinations:
                _send_route_report(config, db, origin, destination)
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Per-route report
# ---------------------------------------------------------------------------


def _send_route_report(
    config: AppConfig, db: Database, origin: str, destination: str
) -> None:
    days = config.report.days
    trend_rows = db.get_price_trend(origin, destination, days)

    if not trend_rows:
        logger.info(
            "No price data for %s→%s in the last %d days — skipping report.",
            origin,
            destination,
            days,
        )
        return

    matrix = db.get_matrix_latest(origin, destination)
    depart_dates = sorted({k[0] for k in matrix})
    return_dates = sorted({k[1] for k in matrix})

    chart_png = _generate_chart_png(origin, destination, trend_rows, days)
    chart_cid = "price_trend_chart" if chart_png else None

    matrix_html = _build_matrix_html(matrix, depart_dates, return_dates)
    html_body = _build_html_email(
        origin, destination, chart_cid, matrix_html, trend_rows, days
    )
    plain_body = _build_plain_body(origin, destination, trend_rows, matrix)

    subject = f"FlightTracker Daily: {origin} → {destination}"
    _send_email(config, subject, html_body, plain_body, chart_png)
    logger.info("Daily report sent for %s→%s", origin, destination)


# ---------------------------------------------------------------------------
# Chart generation
# ---------------------------------------------------------------------------


def _generate_chart_png(
    origin: str,
    destination: str,
    trend_rows: list[dict],
    days: int,
) -> bytes | None:
    """
    Generate a price trend PNG with a shaded min/max band and an avg price line.
    Returns raw PNG bytes, or None if there are fewer than 2 days of data.
    """
    if len(trend_rows) < 2:
        return None

    dates = [datetime.fromisoformat(row["fetch_date"]) for row in trend_rows]
    avg_prices = [row["avg_price"] for row in trend_rows]
    min_prices = [row["min_price"] for row in trend_rows]
    max_prices = [row["max_price"] for row in trend_rows]

    fig, ax = plt.subplots(figsize=(10, 4))

    # Shaded band between min and max
    ax.fill_between(
        dates, min_prices, max_prices,
        alpha=0.15, color="#1565C0", label="Price range (min–max)"
    )
    # Avg line
    ax.plot(
        dates, avg_prices,
        color="#1565C0", linewidth=2, marker="o", markersize=4, label="Avg price"
    )
    # Min/max dashed lines
    ax.plot(dates, min_prices, color="#2E7D32", linewidth=1, linestyle="--", label="Min price")
    ax.plot(dates, max_prices, color="#C62828", linewidth=1, linestyle="--", label="Max price")

    ax.set_title(
        f"Price Trend: {origin} → {destination}  (last {days} days)",
        fontsize=13, pad=12,
    )
    ax.set_ylabel("Price per person (USD)")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %d"))
    ax.xaxis.set_major_locator(mdates.AutoDateLocator())
    fig.autofmt_xdate(rotation=30)
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f"${x:,.0f}"))
    ax.legend(loc="upper right", fontsize=9)
    ax.grid(True, alpha=0.25)
    fig.tight_layout()

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=130, bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    return buf.read()


# ---------------------------------------------------------------------------
# Price matrix HTML table
# ---------------------------------------------------------------------------


def _price_color(price: float, min_p: float, max_p: float) -> str:
    """HSL color: hue 120 (green) for cheapest → 0 (red) for most expensive."""
    if max_p == min_p:
        hue = 120
    else:
        t = (price - min_p) / (max_p - min_p)
        hue = int(120 * (1.0 - t))
    return f"hsl({hue},65%,88%)"


def _build_matrix_html(
    matrix: dict[tuple[str, str], float],
    depart_dates: list[str],
    return_dates: list[str],
) -> str:
    if not matrix:
        return "<p><em>No price data available for the latest scrape.</em></p>"

    prices = list(matrix.values())
    min_p, max_p = min(prices), max(prices)

    cell_style = "padding:5px 10px;text-align:center;font-size:13px;"
    head_style = "padding:5px 10px;background:#eeeeee;font-size:11px;white-space:nowrap;"
    row_label_style = "padding:5px 10px;background:#eeeeee;font-weight:bold;font-size:11px;white-space:nowrap;"

    # Header row
    header = "<tr><th style='" + head_style + "'></th>"
    for rd in return_dates:
        header += f"<th style='{head_style}'>↩ {rd}</th>"
    header += "</tr>"

    # Data rows
    body_rows = ""
    for dd in depart_dates:
        row = f"<tr><td style='{row_label_style}'>↗ {dd}</td>"
        for rd in return_dates:
            price = matrix.get((dd, rd))
            if price is None:
                row += f"<td style='{cell_style}color:#bbb;'>—</td>"
            else:
                bg = _price_color(price, min_p, max_p)
                row += (
                    f"<td style='{cell_style}background:{bg};'>"
                    f"${price:,.0f}</td>"
                )
        row += "</tr>"
        body_rows += row

    return (
        "<table style='border-collapse:collapse;font-family:monospace;'>"
        f"{header}{body_rows}</table>"
    )


# ---------------------------------------------------------------------------
# Email body builders
# ---------------------------------------------------------------------------


def _build_html_email(
    origin: str,
    destination: str,
    chart_cid: str | None,
    matrix_html: str,
    trend_rows: list[dict],
    days: int,
) -> str:
    all_min = min(r["min_price"] for r in trend_rows)
    latest_avg = trend_rows[-1]["avg_price"]
    latest_min = trend_rows[-1]["min_price"]

    return f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family:Arial,sans-serif;max-width:960px;margin:0 auto;padding:24px;color:#333;">

  <h2 style="color:#1565C0;margin-bottom:4px;">
    FlightTracker Daily Report
  </h2>
  <p style="font-size:18px;margin-top:0;color:#555;">{origin} → {destination}</p>

  <table style="border-collapse:collapse;margin-bottom:24px;">
    <tr>
      <td style="padding:6px 20px 6px 0;color:#666;">Best price in last {days} days</td>
      <td style="padding:6px 0;font-weight:bold;color:#2E7D32;font-size:16px;">${all_min:,.0f}/person</td>
    </tr>
    <tr>
      <td style="padding:6px 20px 6px 0;color:#666;">Latest avg price (all combos)</td>
      <td style="padding:6px 0;">${latest_avg:,.0f}/person</td>
    </tr>
    <tr>
      <td style="padding:6px 20px 6px 0;color:#666;">Latest cheapest combo</td>
      <td style="padding:6px 0;">${latest_min:,.0f}/person</td>
    </tr>
  </table>

  <h3 style="color:#444;">Price Trend — last {days} days</h3>
  <p style="color:#888;font-size:12px;margin-top:-8px;">
    Shaded band = min/max range across all depart×return date combinations per day.
    Solid line = average. Dashed lines = min (green) and max (red).
  </p>
  {f'<img src="cid:{chart_cid}" style="max-width:100%;border:1px solid #e0e0e0;border-radius:4px;" alt="Price trend chart">' if chart_cid else '<p style="color:#888;font-style:italic;">Not enough data yet to show a trend chart (need at least 2 days).</p>'}

  <h3 style="color:#444;margin-top:28px;">Latest Price Matrix</h3>
  <p style="color:#888;font-size:12px;margin-top:-8px;">
    Best price per person for each depart (↗) × return (↩) date combination from the most recent scrape.
    <strong style="color:#2E7D32;">Green</strong> = cheapest &nbsp;|&nbsp;
    <strong style="color:#C62828;">Red</strong> = most expensive.
  </p>
  {matrix_html}

  <p style="color:#bbb;font-size:11px;margin-top:36px;">
    Prices are subject to change. Verify on the airline or booking site before purchasing.<br>
    Generated by FlightTracker.
  </p>
</body>
</html>"""


def _build_plain_body(
    origin: str,
    destination: str,
    trend_rows: list[dict],
    matrix: dict[tuple[str, str], float],
) -> str:
    all_min = min(r["min_price"] for r in trend_rows)
    latest_min = trend_rows[-1]["min_price"]
    latest_date = trend_rows[-1]["fetch_date"]

    lines = [
        f"FlightTracker Daily Report: {origin} → {destination}",
        "=" * 52,
        f"Best price in period:  ${all_min:,.0f}/person",
        f"Latest cheapest combo: ${latest_min:,.0f}/person  (scraped {latest_date})",
        "",
        "Top cheapest date combinations (latest scrape):",
    ]
    for (dep, ret), price in sorted(matrix.items(), key=lambda x: x[1])[:10]:
        lines.append(f"  Depart {dep}  Return {ret}  →  ${price:,.0f}/person")

    lines += ["", "Prices are subject to change. Verify before booking."]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# SMTP send
# ---------------------------------------------------------------------------


def _send_email(
    config: AppConfig,
    subject: str,
    html_body: str,
    plain_body: str,
    chart_png: bytes | None = None,
) -> None:
    email_cfg = config.alerts.email
    assert email_cfg is not None  # guaranteed by send_daily_report caller

    # Build multipart/alternative (text + html)
    alternative = MIMEMultipart("alternative")
    alternative.attach(MIMEText(plain_body, "plain"))
    alternative.attach(MIMEText(html_body, "html"))

    if chart_png:
        # Wrap in multipart/related so the inline CID image is bundled with the HTML
        related = MIMEMultipart("related")
        related.attach(alternative)
        img_part = MIMEImage(chart_png, _subtype="png")
        img_part.add_header("Content-ID", "<price_trend_chart>")
        img_part.add_header("Content-Disposition", "inline", filename="price_trend.png")
        related.attach(img_part)
        payload = related
    else:
        payload = alternative

    msg = MIMEMultipart("mixed")
    msg["Subject"] = subject
    msg["From"] = email_cfg.sender
    msg["To"] = ", ".join(email_cfg.recipients)
    msg.attach(payload)

    with smtplib.SMTP(email_cfg.smtp_host, email_cfg.smtp_port) as smtp:
        smtp.ehlo()
        smtp.starttls()
        smtp.login(email_cfg.sender, email_cfg.password)
        smtp.sendmail(email_cfg.sender, email_cfg.recipients, msg.as_string())
