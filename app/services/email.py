"""
ScholarBot — Email service (Blocker 3).
SendGrid integration for verification, password reset, deadline reminders.

To enable: add SENDGRID_API_KEY and FROM_EMAIL to Render environment variables.
SendGrid free tier: 100 emails/day — sufficient for early launch.
"""
import os
import logging

logger = logging.getLogger(__name__)

SENDGRID_API_KEY = os.environ.get("SENDGRID_API_KEY", "")
FROM_EMAIL = os.environ.get("FROM_EMAIL", "noreply@scholarbot.app")
BASE_URL = os.environ.get("BASE_URL", "https://scholarbot-web.onrender.com")


def _send(to: str, subject: str, html: str) -> bool:
    """Send one email via SendGrid. Returns True on success."""
    if not SENDGRID_API_KEY:
        logger.warning("SENDGRID_API_KEY not set — email not sent to %s", to)
        return False
    try:
        from sendgrid import SendGridAPIClient
        from sendgrid.helpers.mail import Mail
        msg = Mail(from_email=FROM_EMAIL, to_emails=to,
                   subject=subject, html_content=html)
        sg = SendGridAPIClient(SENDGRID_API_KEY)
        resp = sg.send(msg)
        ok = resp.status_code in (200, 202)
        if not ok:
            logger.error("SendGrid error %s for %s", resp.status_code, to)
        return ok
    except Exception as e:
        logger.error("Email send failed: %s", e)
        return False


def _wrap(title: str, body: str) -> str:
    """Minimal HTML wrapper consistent with ScholarBot branding."""
    return f"""
<html><body style="font-family:Arial,sans-serif;color:#333;margin:0;padding:0;background:#f5f5f0">
<div style="max-width:600px;margin:0 auto;padding:32px 16px">
  <div style="background:#1a1a2e;padding:20px 24px;border-radius:8px 8px 0 0">
    <span style="color:#fff;font-size:20px;font-weight:700">🎓 ScholarBot</span>
  </div>
  <div style="background:#fff;padding:28px 24px;border-radius:0 0 8px 8px;border:1px solid #e8e8e0">
    <h2 style="color:#1a1a2e;margin-top:0">{title}</h2>
    {body}
    <hr style="border:none;border-top:1px solid #e8e8e0;margin:24px 0">
    <p style="font-size:12px;color:#888">
      ScholarBot · AI-Powered Scholarship Assistant<br>
      <a href="{BASE_URL}" style="color:#2563eb">{BASE_URL}</a>
    </p>
  </div>
</div></body></html>"""


def send_verification_email(to: str, name: str, token: str) -> bool:
    link = f"{BASE_URL}/verify?token={token}"
    body = f"""
    <p>Hi {name},</p>
    <p>Thanks for joining ScholarBot. Click the button below to verify your email:</p>
    <div style="text-align:center;margin:24px 0">
      <a href="{link}" style="background:#2563eb;color:#fff;padding:12px 28px;
         text-decoration:none;border-radius:6px;font-size:15px;font-weight:600">
        Verify my email
      </a>
    </div>
    <p style="font-size:13px;color:#666">
      Link expires in 24 hours. If you didn't sign up, ignore this email.
    </p>"""
    return _send(to, "Verify your ScholarBot email", _wrap("Email Verification", body))


def send_password_reset_email(to: str, name: str, token: str) -> bool:
    link = f"{BASE_URL}/?reset_token={token}"
    body = f"""
    <p>Hi {name},</p>
    <p>We received a request to reset your ScholarBot password.</p>
    <div style="text-align:center;margin:24px 0">
      <a href="{link}" style="background:#2563eb;color:#fff;padding:12px 28px;
         text-decoration:none;border-radius:6px;font-size:15px;font-weight:600">
        Reset my password
      </a>
    </div>
    <p style="font-size:13px;color:#666">
      Link expires in 24 hours. If you didn't request this, you can safely ignore it —
      your password has not been changed.
    </p>"""
    return _send(to, "Reset your ScholarBot password", _wrap("Password Reset", body))


def send_deadline_reminder(to: str, name: str, scholarships: list) -> bool:
    """
    scholarships: list of {name, deadline, days_left, amount_usd, url}
    """
    rows = "".join(
        f"""<tr style="border-bottom:1px solid #e8e8e0">
          <td style="padding:10px 8px">
            <a href="{s.get('url','#')}" style="color:#2563eb;text-decoration:none">
              {s['name'][:50]}
            </a>
          </td>
          <td style="padding:10px 8px;text-align:center;color:
            {'#dc2626' if s['days_left']<=7 else '#d97706' if s['days_left']<=30 else '#059669'}">
            {s['days_left']} days
          </td>
          <td style="padding:10px 8px;text-align:right;font-weight:600">
            ${s.get('amount_usd',0):,.0f}
          </td>
        </tr>"""
        for s in scholarships[:5]
    )
    body = f"""
    <p>Hi {name},</p>
    <p>You have upcoming scholarship deadlines. Don't miss them:</p>
    <table style="width:100%;border-collapse:collapse;font-size:14px">
      <thead>
        <tr style="background:#f5f5f0">
          <th style="padding:8px;text-align:left">Scholarship</th>
          <th style="padding:8px;text-align:center">Days Left</th>
          <th style="padding:8px;text-align:right">Award</th>
        </tr>
      </thead>
      <tbody>{rows}</tbody>
    </table>
    <div style="text-align:center;margin:24px 0">
      <a href="{BASE_URL}/?page=pipeline" style="background:#059669;color:#fff;padding:12px 28px;
         text-decoration:none;border-radius:6px;font-size:15px;font-weight:600">
        View my pipeline
      </a>
    </div>"""
    return _send(to, f"⏰ {len(scholarships)} scholarship deadline{'s' if len(scholarships)>1 else ''} approaching",
                 _wrap("Upcoming Deadlines", body))


def email_configured() -> bool:
    return bool(SENDGRID_API_KEY)
