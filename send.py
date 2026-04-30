"""send: deliver the formatted brief over SMTP."""
from __future__ import annotations

import logging
import os
import smtplib
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
BRIEF_PATH = ROOT / "brief.txt"

DEFAULT_HOST = "smtp.gmail.com"
DEFAULT_PORT = 587

logger = logging.getLogger("ramip.send")


def _split_brief(text: str) -> tuple[str, str]:
    """Pull the 'Subject: ...' line out of brief.txt; return (subject, body)."""
    lines = text.splitlines()
    subject = "RAMIP Brief"
    body_start = 0
    for i, line in enumerate(lines):
        if line.startswith("Subject:"):
            subject = line[len("Subject:") :].strip()
            body_start = i + 1
            break
    if body_start < len(lines) and lines[body_start].strip() == "":
        body_start += 1
    body = "\n".join(lines[body_start:])
    return subject, body


def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(levelname)s %(name)s: %(message)s"
    )
    load_dotenv()

    if not BRIEF_PATH.exists():
        print(f"send failed: {BRIEF_PATH.name} not found — run format first")
        return

    subject, body = _split_brief(BRIEF_PATH.read_text())

    host = os.environ.get("SMTP_HOST") or DEFAULT_HOST
    try:
        port = int(os.environ.get("SMTP_PORT") or DEFAULT_PORT)
    except ValueError:
        print(f"send failed: SMTP_PORT must be an integer, got {os.environ.get('SMTP_PORT')!r}")
        return
    user = os.environ.get("SMTP_USER")
    password = os.environ.get("SMTP_PASS")
    to_email = os.environ.get("TO_EMAIL")

    missing = [
        name
        for name, val in (
            ("SMTP_USER", user),
            ("SMTP_PASS", password),
            ("TO_EMAIL", to_email),
        )
        if not val
    ]
    if missing:
        print(f"send failed: missing env vars: {', '.join(missing)} — check .env")
        return

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = user
    msg["To"] = to_email
    msg.set_content(body)

    try:
        with smtplib.SMTP(host, port, timeout=30) as smtp:
            smtp.starttls()
            smtp.login(user, password)
            smtp.send_message(msg)
    except smtplib.SMTPAuthenticationError as exc:
        print(
            f"send failed: SMTP authentication rejected ({exc.smtp_code}). "
            "For Gmail, SMTP_PASS must be an app password "
            "(https://myaccount.google.com/apppasswords), not your account password."
        )
        return
    except smtplib.SMTPException as exc:
        print(f"send failed: SMTP error — {exc}")
        return
    except OSError as exc:
        print(f"send failed: could not reach {host}:{port} — {exc}")
        return

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"brief sent to {to_email} at {timestamp}")


if __name__ == "__main__":
    main()
