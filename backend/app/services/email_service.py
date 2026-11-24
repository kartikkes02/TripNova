import smtplib
import asyncio
import httpx
import html as html_lib
import re
from email.message import EmailMessage
from tenacity import retry, stop_after_attempt, wait_exponential

from ..core.config import settings
from datetime import datetime


def get_verification_email_html(full_name: str, code: str) -> str:
    name = full_name if full_name else "Traveler"
    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <style>
            body {{
                font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif;
                background-color: #f4f7f6;
                margin: 0;
                padding: 0;
            }}
            .container {{
                max-width: 600px;
                margin: 40px auto;
                background-color: #ffffff;
                border-radius: 8px;
                overflow: hidden;
                box-shadow: 0 4px 15px rgba(0,0,0,0.05);
            }}
            .header {{
                background-color: #00aa6c; /* TripAdvisor Green */
                padding: 30px;
                text-align: center;
            }}
            .header h1 {{
                color: #ffffff;
                margin: 0;
                font-size: 28px;
                letter-spacing: 1px;
            }}
            .content {{
                padding: 40px 30px;
                color: #333333;
                line-height: 1.6;
            }}
            .content h2 {{
                color: #00aa6c;
                margin-top: 0;
            }}
            .otp-box {{
                background-color: #f0fdf4;
                border: 2px dashed #00aa6c;
                border-radius: 8px;
                padding: 20px;
                text-align: center;
                margin: 30px 0;
            }}
            .otp-code {{
                font-size: 36px;
                font-weight: bold;
                color: #00aa6c;
                letter-spacing: 4px;
                margin: 0;
            }}
            .expiry {{
                color: #666666;
                font-size: 14px;
                text-align: center;
                margin-top: 10px;
            }}
            .footer {{
                background-color: #f4f7f6;
                padding: 20px;
                text-align: center;
                color: #888888;
                font-size: 12px;
                border-top: 1px solid #eeeeee;
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1>TripAdvisor</h1>
            </div>
            <div class="content">
                <h2>Email Verification</h2>
                <p>Hi {name},</p>
                <p>Thank you for signing up! Please verify your email address by entering the code below:</p>
                <div class="otp-box">
                    <p class="otp-code">{code}</p>
                </div>
                <p class="expiry">This code will expire in 10 minutes.</p>
                <p>If you didn't create an account, please ignore this email.</p>
            </div>
            <div class="footer">
                <p>&copy; {datetime.now().year} TripAdvisor by Binod Kapadi. All rights reserved.</p>
            </div>
        </div>
    </body>
    </html>
    """

def get_password_reset_email_html(full_name: str, code: str) -> str:
    name = full_name if full_name else "Traveler"
    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <style>
            body {{
                font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif;
                background-color: #f4f7f6;
                margin: 0;
                padding: 0;
            }}
            .container {{
                max-width: 600px;
                margin: 40px auto;
                background-color: #ffffff;
                border-radius: 8px;
                overflow: hidden;
                box-shadow: 0 4px 15px rgba(0,0,0,0.05);
            }}
            .header {{
                background-color: #00aa6c;
                padding: 30px;
                text-align: center;
            }}
            .header h1 {{
                color: #ffffff;
                margin: 0;
                font-size: 28px;
                letter-spacing: 1px;
            }}
            .content {{
                padding: 40px 30px;
                color: #333333;
                line-height: 1.6;
            }}
            .content h2 {{
                color: #00aa6c;
                margin-top: 0;
            }}
            .otp-box {{
                background-color: #f0fdf4;
                border: 2px dashed #00aa6c;
                border-radius: 8px;
                padding: 20px;
                text-align: center;
                margin: 30px 0;
            }}
            .otp-code {{
                font-size: 36px;
                font-weight: bold;
                color: #00aa6c;
                letter-spacing: 4px;
                margin: 0;
            }}
            .expiry {{
                color: #666666;
                font-size: 14px;
                text-align: center;
                margin-top: 10px;
            }}
            .footer {{
                background-color: #f4f7f6;
                padding: 20px;
                text-align: center;
                color: #888888;
                font-size: 12px;
                border-top: 1px solid #eeeeee;
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1>TripAdvisor</h1>
            </div>
            <div class="content">
                <h2>Password Reset</h2>
                <p>Hi {name},</p>
                <p>Use the verification code below to reset your password:</p>
                <div class="otp-box">
                    <p class="otp-code">{code}</p>
                </div>
                <p class="expiry">This code will expire in 10 minutes.</p>
                <p>If you didn't request a password reset, please ignore this email.</p>
            </div>
            <div class="footer">
                <p>&copy; {datetime.now().year} TripAdvisor by Binod Kapadi. All rights reserved.</p>
            </div>
        </div>
    </body>
    </html>
    """

def get_welcome_email_html(full_name: str) -> str:
    name = full_name if full_name else "Traveler"
    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <style>
            body {{
                font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif;
                background-color: #f4f7f6;
                margin: 0;
                padding: 0;
            }}
            .container {{
                max-width: 600px;
                margin: 40px auto;
                background-color: #ffffff;
                border-radius: 8px;
                overflow: hidden;
                box-shadow: 0 4px 15px rgba(0,0,0,0.05);
            }}
            .header {{
                background-color: #00aa6c;
                padding: 30px;
                text-align: center;
            }}
            .header h1 {{
                color: #ffffff;
                margin: 0;
                font-size: 28px;
                letter-spacing: 1px;
            }}
            .content {{
                padding: 40px 30px;
                color: #333333;
                line-height: 1.6;
            }}
            .content h2 {{
                color: #00aa6c;
                margin-top: 0;
            }}
            .footer {{
                background-color: #f4f7f6;
                padding: 20px;
                text-align: center;
                color: #888888;
                font-size: 12px;
                border-top: 1px solid #eeeeee;
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1>TripAdvisor</h1>
            </div>
            <div class="content">
                <h2>Welcome to TripAdvisor, {name}!</h2>
                <p>We're excited to have you on board. Start planning your next adventure today!</p>
            </div>
            <div class="footer">
                <p>&copy; {datetime.now().year} TripAdvisor by Binod Kapadi. All rights reserved.</p>
            </div>
        </div>
    </body>
    </html>
    """

import re

def _sanitize_itinerary_content(body_text: str) -> str:
    escaped = html_lib.escape(body_text)
    normalized = escaped.replace("\r\n", "\n").replace("\r", "\n")
    lines = normalized.split("\n")
    safe_lines = []

    for line in lines:
        if re.match(r'^Day \d+:', line):
            safe_lines.append(f"<strong>{line}</strong>")
        else:
            safe_lines.append(line)

    return "<br>\n".join(safe_lines)


def get_itinerary_email_html(destination: str, body_text: str) -> str:
    formatted_body = _sanitize_itinerary_content(body_text)

    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <style>
            body {{
                font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif;
                background-color: #f4f7f6;
                margin: 0;
                padding: 0;
            }}
            .container {{
                max-width: 600px;
                margin: 40px auto;
                background-color: #ffffff;
                border-radius: 8px;
                overflow: hidden;
                box-shadow: 0 4px 15px rgba(0,0,0,0.05);
            }}
            .header {{
                background-color: #00aa6c;
                padding: 30px;
                text-align: center;
            }}
            .header h1 {{
                color: #ffffff;
                margin: 0;
                font-size: 28px;
                letter-spacing: 1px;
            }}
            .content {{
                padding: 40px 30px;
                color: #333333;
                line-height: 1.6;
            }}
            .content h2 {{
                color: #00aa6c;
                margin-top: 0;
                margin-bottom: 25px;
            }}
            .itinerary-text {{
                font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif;
                font-size: 15px;
                color: #444444;
                line-height: 1.6;
            }}
            .footer {{
                background-color: #f4f7f6;
                padding: 20px;
                text-align: center;
                color: #888888;
                font-size: 12px;
                border-top: 1px solid #eeeeee;
            }}
            a {{
                color: #00aa6c;
                text-decoration: none;
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1>TripAdvisor</h1>
            </div>
            <div class="content">
                <h2>Your Trip to {destination} is Ready!</h2>
                <div class="itinerary-text">{formatted_body}</div>
            </div>
            <div class="footer">
                <p>&copy; {datetime.now().year} TripAdvisor by Binod Kapadi. All rights reserved.</p>
            </div>
        </div>
    </body>
    </html>
    """


class EmailService:
    @retry(stop=stop_after_attempt(2), wait=wait_exponential(multiplier=1, min=1, max=5))
    async def _send_brevo(self, to_email: str, subject: str, body_text: str, body_html: str = None) -> None:
        if not settings.BREVO_API_KEY:
            raise ValueError("BREVO_API_KEY not configured.")

        clean_brevo_key = settings.BREVO_API_KEY.strip().strip("'\"")
        url = "https://api.brevo.com/v3/smtp/email"
        headers = {
            "accept": "application/json",
            "api-key": clean_brevo_key,
            "content-type": "application/json"
        }
        
        sender_email = getattr(settings, "SENDER_EMAIL", None) or settings.EMAIL_FROM or settings.SMTP_USER
        if not sender_email:
            print("[BREVO] WARNING: SENDER_EMAIL or EMAIL_FROM is not set in environment variables! Brevo requires a verified sender.")
            sender_email = "noreply@tripadvisor.com"

        sender_name = getattr(settings, "SENDER_NAME", "TripAdvisor")
        
        payload = {
            "sender": {"email": sender_email, "name": sender_name},
            "to": [{"email": to_email}],
            "subject": subject,
            "textContent": body_text
        }

        if body_html:
            payload["htmlContent"] = body_html
            payload["headers"] = {"X-Mailin-custom": "itinerary-email"}

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(url, headers=headers, json=payload)
            response_text = response.text
            print(f"[BREVO] API status={response.status_code} to={to_email} sender={sender_email}")

            try:
                response_json = response.json()
            except ValueError:
                response_json = None

            if response.status_code >= 400:
                error_details = response_json or response_text
                print(f"[BREVO] Error ({response.status_code}): {error_details}")
                raise RuntimeError(f"Brevo API Error ({response.status_code}): {error_details}")

            if response_json and isinstance(response_json, dict):
                message_id = response_json.get("messageId") or response_json.get("message_id")
                if message_id:
                    print(f"[BREVO] Email accepted by Brevo! messageId={message_id}")

            response.raise_for_status()

    async def _send_smtp(self, to_email: str, subject: str, body_text: str, body_html: str = None) -> None:
        if not settings.SMTP_HOST or not settings.SMTP_USER or not settings.SMTP_PASSWORD or not settings.EMAIL_FROM:
            # Development fallback
            print(f"\n{'='*50}")
            print(f"EMAIL SERVICE NOT CONFIGURED - DEVELOPMENT MODE")
            print(f"To: {to_email}")
            print(f"Subject: {subject}")
            print(f"Body: {body_text}")
            print(f"{'='*50}\n")
            return

        def _send():
            msg = EmailMessage()
            sender_name = getattr(settings, "SENDER_NAME", "TripAdvisor")
            msg["From"] = f"{sender_name} <{settings.EMAIL_FROM}>"
            msg["To"] = to_email
            msg["Subject"] = subject
            msg.set_content(body_text)
            if body_html:
                msg.add_alternative(body_html, subtype='html')

            with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=10) as server:
                server.starttls()
                server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
                server.send_message(msg)

        try:
            await asyncio.to_thread(_send)
            print(f"Email sent successfully via SMTP to {to_email}")
        except Exception as e:
            print(f"[EMAIL] SMTP delivery failed (outbound SMTP port 587/25 is blocked on cloud host): {e}")

    async def send_email_async(self, to_email: str, subject: str, body_text: str, body_html: str = None) -> None:
        try:
            if settings.BREVO_API_KEY:
                try:
                    await self._send_brevo(to_email, subject, body_text, body_html)
                    print(f"Email sent successfully to {to_email} via Brevo API")
                    return
                except Exception as e:
                    print(f"Brevo API failed, falling back to SMTP: {e}")

            await self._send_smtp(to_email, subject, body_text, body_html)
        except Exception as e:
            print(f"[EMAIL] Background email sending omitted: {e}")

email_service = EmailService()

# Maintain backward-compatibility for non-async calls or simply replace usages if needed.
# Since we will update routes.py to await send_email, we make send_email async.
async def send_email(to_email: str, subject: str, body_text: str, body_html: str = None) -> None:
    await email_service.send_email_async(to_email, subject, body_text, body_html)

async def notify_admin(subject: str, body_text: str) -> None:
    await email_service.send_email_async(settings.NOTIFY_EMAIL, subject, body_text)
