"""
email_alert.py
--------------
Sends a single digest email summarizing favorite-ticker signals via SMTP.

Configure via environment variables (see ALERTS_SETUP.md):
  SMTP_HOST     e.g. smtp.gmail.com
  SMTP_PORT     e.g. 465 (SSL) or 587 (STARTTLS) - defaults to 465
  SMTP_USER     the sending mailbox login (e.g. your Gmail address)
  SMTP_PASS     app password / SMTP password (for Gmail this MUST be an
                App Password, not your normal account password)
  ALERT_FROM    optional "From" display address, defaults to SMTP_USER
  ALERT_TO      comma-separated recipient list, e.g. "me@x.com,me@y.com"
"""

import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart


def _env(name, default=None):
    v = os.environ.get(name, default)
    return v.strip() if isinstance(v, str) else v


def send_alert_email(subject: str, html_body: str, text_body: str = None):
    """
    Sends one email. Raises on failure so the caller (and the GitHub Actions
    log) can see clearly that delivery failed, rather than silently no-op'ing.
    """
    host = _env("SMTP_HOST")
    port = int(_env("SMTP_PORT", "465"))
    user = _env("SMTP_USER")
    password = _env("SMTP_PASS")
    to_raw = _env("ALERT_TO")
    from_addr = _env("ALERT_FROM", user)

    if not all([host, user, password, to_raw]):
        raise ValueError(
            "Missing email config. Required env vars: SMTP_HOST, SMTP_USER, "
            "SMTP_PASS, ALERT_TO (SMTP_PORT is optional, defaults to 465)."
        )

    to_list = [addr.strip() for addr in to_raw.split(",") if addr.strip()]

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = ", ".join(to_list)

    msg.attach(MIMEText(text_body or html_body, "plain"))
    msg.attach(MIMEText(html_body, "html"))

    if port == 465:
        with smtplib.SMTP_SSL(host, port, timeout=30) as server:
            server.login(user, password)
            server.sendmail(from_addr, to_list, msg.as_string())
    else:
        with smtplib.SMTP(host, port, timeout=30) as server:
            server.starttls()
            server.login(user, password)
            server.sendmail(from_addr, to_list, msg.as_string())
