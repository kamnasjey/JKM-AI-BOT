from __future__ import annotations

import os
import smtplib
from email.mime.text import MIMEText
from email.utils import formataddr


def send_email(*, to_email: str, subject: str, text_body: str) -> None:
    """Send a plain-text email via SMTP.

    Configure via env:
      SMTP_HOST (default: smtp.gmail.com)
      SMTP_PORT (default: 587)
      SMTP_USERNAME
      SMTP_PASSWORD
      SMTP_FROM (optional, default: SMTP_USERNAME)
      SMTP_FROM_NAME (optional)

    For Gmail, use an App Password (2FA enabled) as SMTP_PASSWORD.
    """

    host = os.getenv("SMTP_HOST", "smtp.gmail.com").strip()
    port = int(os.getenv("SMTP_PORT", "587").strip() or "587")
    username = os.getenv("SMTP_USERNAME", "").strip()
    password = os.getenv("SMTP_PASSWORD", "").strip()
    from_email = os.getenv("SMTP_FROM", "").strip() or username
    from_name = os.getenv("SMTP_FROM_NAME", "JKM Trading AI").strip() or "JKM Trading AI"

    if not username or not password or not from_email:
        raise RuntimeError(
            "SMTP is not configured (SMTP_USERNAME/SMTP_PASSWORD required)."
        )

    msg = MIMEText(text_body, _charset="utf-8")
    msg["Subject"] = subject
    msg["From"] = formataddr((from_name, from_email))
    msg["To"] = to_email

    with smtplib.SMTP(host, port, timeout=20) as smtp:
        smtp.ehlo()
        if port == 587:
            smtp.starttls()
            smtp.ehlo()
        smtp.login(username, password)
        smtp.sendmail(from_email, [to_email], msg.as_string())


def send_verification_email(*, to_email: str, code: str, verify_url: str | None = None) -> None:
    subject = "Verify your email – JKM Trading AI"
    body = (
        "Welcome to JKM Trading AI!\n\n"
        "Use this verification code to confirm your email:\n\n"
        f"{code}\n\n"
        "This code expires in 24 hours.\n\n"
    )
    if verify_url:
        body += (
            "Optional link (if your browser is already open):\n"
            f"{verify_url}\n\n"
        )
    body += "If you didn't request this, you can ignore this email.\n"
    send_email(to_email=to_email, subject=subject, text_body=body)
