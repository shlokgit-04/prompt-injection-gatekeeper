"""send_email tool. Demo mode (SMTP_HOST unset) writes to DATA_DIR/outbox;
with SMTP_* env vars set it sends real mail through SMTP. The security gate,
not this tool, decides whether a call is allowed to run."""
from __future__ import annotations

import os
import smtplib
import time
from email.message import EmailMessage


def send_email(to: str, subject: str, body: str) -> dict:
    host = os.environ.get("SMTP_HOST", "").strip()
    if not host:
        outbox = os.path.join(os.environ.get("DATA_DIR", "./data"), "outbox")
        os.makedirs(outbox, exist_ok=True)
        path = os.path.join(outbox, f"{int(time.time() * 1000)}_to_{to.replace('@', '_at_')}.txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write(f"TO: {to}\nSUBJECT: {subject}\n\n{body}\n")
        return {"status": "written_to_outbox", "path": path, "to": to, "subject": subject}
    msg = EmailMessage()
    msg["To"], msg["Subject"] = to, subject
    msg.set_content(body)
    msg["From"] = os.environ.get("SMTP_USER", "")
    with smtplib.SMTP(host, int(os.environ.get("SMTP_PORT", "587"))) as s:
        s.starttls()
        if os.environ.get("SMTP_USER"):
            s.login(os.environ["SMTP_USER"], os.environ["SMTP_PASSWORD"])
        s.send_message(msg)
    return {"status": "sent", "to": to, "subject": subject}
