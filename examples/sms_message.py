"""Send a short alert through an email-to-SMS gateway (e.g. Gmail SMTP ->
a carrier's own carrier-to-email SMS address) -- every credential/address
comes from a local ``.env`` file (``SMTP_SERVER``/``SMTP_PORT``/
``SENDER_EMAIL``/``APP_PASSWORD``/``RECIPIENT_SMS``), never committed to
the repo (see ``.gitignore``).

``send_sms(body, subject="")`` is the reusable piece -- import it from
another script to fire an alert from inside your own code (see
``examples/undervolume_error_demo.py``'s own ``except`` block for the
intended use: an SMS the moment a real PyLabRobot volume-tracker error
interrupts a transfer). Running this file directly (``uv run python
examples/sms_message.py``) still sends the exact original test message
this was first written and verified against, unchanged.
"""

import os
import smtplib
from email.mime.text import MIMEText

from dotenv import load_dotenv

# Load variables from the .env file
load_dotenv()

# 1. Configuration Settings from .env
SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.gmail.com")  # Defaults to Gmail if missing
SMTP_PORT = int(os.getenv("SMTP_PORT", 587))
SENDER_EMAIL = os.getenv("SENDER_EMAIL")
APP_PASSWORD = os.getenv("APP_PASSWORD")

# 2. Destination from .env
RECIPIENT_SMS = os.getenv("RECIPIENT_SMS")


def send_sms(body: str, subject: str = "") -> None:
  """Send ``body`` as an SMS via the configured email-to-SMS gateway.

  Synchronous/blocking (plain ``smtplib``, same as this file's own
  original standalone version) -- fine to call directly from an ``async
  def`` protocol script's own ``except`` block (see
  ``undervolume_error_demo.py``); the SMTP round-trip is a one-off, not
  something worth an ``asyncio.to_thread`` wrapper for a demo script.
  """

  msg = MIMEText(body)
  msg["From"] = SENDER_EMAIL
  msg["To"] = RECIPIENT_SMS
  msg["Subject"] = subject

  try:
    with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
      server.starttls()
      server.login(SENDER_EMAIL, APP_PASSWORD)
      server.sendmail(SENDER_EMAIL, RECIPIENT_SMS, msg.as_string())

    print("🚀 SMS successfully routed through Gmail SMTP!")

  except Exception as e:
    print(f"❌ Failed to send message. Error: {e}")


if __name__ == "__main__":
  send_sms("Automated Alert: Your Python script completed successfully!")