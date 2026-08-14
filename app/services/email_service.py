"""Utility service for sending emails via SMTP (Gmail App Password)."""

import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import logging

from app.config import (
    MAIL_USERNAME,
    MAIL_PASSWORD,
    MAIL_FROM,
    MAIL_PORT,
    MAIL_SERVER,
    MAIL_FROM_NAME,
)

logger = logging.getLogger(__name__)


def send_email(to_email: str, subject: str, body_html: str, body_text: str | None = None) -> bool:
    """Send an HTML email via SMTP using configured credentials.
    
    Returns True if sent successfully, False otherwise.
    """
    if not MAIL_USERNAME or not MAIL_PASSWORD:
        logger.error("Email credentials are not configured.")
        return False

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"{MAIL_FROM_NAME} <{MAIL_FROM}>"
    msg["To"] = to_email

    if body_text:
        msg.attach(MIMEText(body_text, "plain", "utf-8"))
    
    msg.attach(MIMEText(body_html, "html", "utf-8"))

    try:
        # Clean app password (remove spaces if any)
        clean_password = MAIL_PASSWORD.replace(" ", "")

        with smtplib.SMTP(MAIL_SERVER, MAIL_PORT) as server:
            server.starttls()
            server.login(MAIL_USERNAME, clean_password)
            server.sendmail(MAIL_FROM, [to_email], msg.as_string())
        
        logger.info(f"Email successfully sent to {to_email}")
        return True
    except Exception as e:
        logger.error(f"Failed to send email to {to_email}: {str(e)}")
        return False
