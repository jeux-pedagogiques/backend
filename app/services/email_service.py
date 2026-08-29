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
        logger.warning("Email credentials are not fully configured. Email simulation mode.")
        print(f"[EMAIL SIMULATION] To: {to_email} | Subject: {subject}")
        return False

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"{MAIL_FROM_NAME} <{MAIL_FROM}>"
    msg["To"] = to_email

    if body_text:
        msg.attach(MIMEText(body_text, "plain", "utf-8"))
    
    msg.attach(MIMEText(body_html, "html", "utf-8"))

    try:
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


def send_verification_email(to_email: str, username: str, code: str) -> bool:
    """Send a stylized 6-digit OTP verification code email for user account registration."""
    subject = f"Votre code de vérification ESPRIT AI : {code}"

    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
      <meta charset="utf-8">
      <style>
        body {{
          font-family: 'Segoe UI', Arial, sans-serif;
          background-color: #f8fafc;
          margin: 0;
          padding: 30px 10px;
          color: #1e293b;
        }}
        .container {{
          max-width: 520px;
          margin: 0 auto;
          background: #ffffff;
          border-radius: 18px;
          overflow: hidden;
          box-shadow: 0 10px 30px rgba(0, 0, 0, 0.08);
          border: 1px solid #e2e8f0;
        }}
        .header {{
          background: linear-gradient(135deg, #c51414 0%, #9e0f0f 100%);
          padding: 36px 24px;
          text-align: center;
          color: #ffffff;
        }}
        .header h1 {{
          margin: 0;
          font-size: 24px;
          font-weight: 800;
          letter-spacing: -0.5px;
        }}
        .content {{
          padding: 36px 30px;
          text-align: center;
        }}
        .greeting {{
          font-size: 18px;
          font-weight: 700;
          color: #0f172a;
          margin-bottom: 12px;
        }}
        .description {{
          font-size: 14px;
          color: #64748b;
          line-height: 1.6;
          margin-bottom: 28px;
        }}
        .otp-box {{
          background: #f1f5f9;
          border: 2px dashed #c51414;
          border-radius: 14px;
          padding: 20px;
          display: inline-block;
          margin-bottom: 28px;
        }}
        .otp-code {{
          font-family: 'Courier New', Courier, monospace;
          font-size: 38px;
          font-weight: 900;
          color: #c51414;
          letter-spacing: 8px;
          margin: 0;
        }}
        .warning {{
          font-size: 12px;
          color: #94a3b8;
          line-height: 1.5;
        }}
        .footer {{
          background: #f8fafc;
          padding: 20px;
          text-align: center;
          font-size: 12px;
          color: #94a3b8;
          border-top: 1px solid #e2e8f0;
        }}
      </style>
    </head>
    <body>
      <div class="container">
        <div class="header">
          <h1>ESPRIT AI</h1>
          <p style="margin: 6px 0 0; opacity: 0.9; font-size: 13px;">Plateforme Pédagogique Intelligente</p>
        </div>
        <div class="content">
          <div class="greeting">Bonjour {username} 👋</div>
          <div class="description">
            Merci de créer votre compte sur <strong>ESPRIT AI</strong>.<br>
            Veuillez saisir le code de vérification ci-dessous pour confirmer votre adresse email et finaliser votre inscription :
          </div>
          <div class="otp-box">
            <div class="otp-code">{code}</div>
          </div>
          <div class="warning">
            ⏳ Ce code est valide pendant <strong>15 minutes</strong>.<br>
            Si vous n'êtes pas à l'origine de cette demande, vous pouvez ignorer cet email en toute sécurité.
          </div>
        </div>
        <div class="footer">
          © {2026} ESPRIT — Tous droits réservés.
        </div>
      </div>
    </body>
    </html>
    """

    plain_text = f"Bonjour {username},\n\nVotre code de vérification pour créer votre compte ESPRIT AI est : {code}\n\nCe code expire dans 15 minutes."

    return send_email(
        to_email=to_email,
        subject=subject,
        body_html=html_content,
        body_text=plain_text
    )
