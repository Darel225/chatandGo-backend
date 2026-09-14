import aiosmtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from app.core.config import settings


def _build_otp_email_html(otp_code: str) -> str:
    """Construit le template HTML de l'email OTP."""
    return f"""
<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
</head>
<body style="margin:0; padding:0; background-color:#f0f4ff; font-family: 'Segoe UI', Arial, sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background-color:#f0f4ff; padding: 40px 0;">
    <tr>
      <td align="center">
        <table width="520" cellpadding="0" cellspacing="0" style="background:#ffffff; border-radius:16px; box-shadow: 0 8px 30px rgba(37,99,235,0.12); overflow:hidden;">
          
          <!-- Header -->
          <tr>
            <td style="background: linear-gradient(135deg, #1d4ed8, #2563eb); padding: 32px; text-align:center;">
              <h1 style="color:#ffffff; font-size:28px; margin:0; letter-spacing:1px;">Chat<span style="color:#93c5fd;">&</span>Go</h1>
              <p style="color:#bfdbfe; font-size:12px; letter-spacing:3px; margin-top:6px; margin-bottom:0;">COMMERCE FLUIDITÉ</p>
            </td>
          </tr>

          <!-- Body -->
          <tr>
            <td style="padding: 40px 48px;">
              <p style="color:#1e293b; font-size:16px; margin-top:0;">Bonjour,</p>
              <p style="color:#475569; font-size:15px; line-height:1.6;">
                Vous avez demandé un code de vérification pour accéder à votre compte <strong>Chat&amp;Go</strong>. Voici votre code à usage unique :
              </p>
              
              <!-- OTP Code -->
              <div style="text-align:center; margin: 32px 0; background:#f0f4ff; border-radius:12px; padding: 28px;">
                <span style="font-size:52px; font-weight:800; letter-spacing:14px; color:#1d4ed8; font-family: 'Courier New', monospace;">{otp_code}</span>
              </div>

              <p style="color:#64748b; font-size:14px; text-align:center; margin-bottom:0;">
                ⏱️ Ce code est valable <strong style="color:#1d4ed8;">5 minutes</strong> uniquement.
              </p>
            </td>
          </tr>

          <!-- Footer -->
          <tr>
            <td style="background:#f8fafc; padding: 20px 48px; border-top: 1px solid #e2e8f0;">
              <p style="color:#94a3b8; font-size:12px; text-align:center; margin:0;">
                Si vous n'avez pas demandé ce code, ignorez cet email. Votre compte reste sécurisé.
              </p>
            </td>
          </tr>

        </table>
      </td>
    </tr>
  </table>
</body>
</html>
"""


async def send_otp_email(to_email: str, otp_code: str) -> None:
    """Envoie l'email OTP de manière asynchrone via SMTP."""
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"🔐 {otp_code} — Votre code de vérification Chat&Go"
    msg["From"] = f"Chat&Go <{settings.EMAIL_FROM}>"
    msg["To"] = to_email

    html_content = _build_otp_email_html(otp_code)
    msg.attach(MIMEText(html_content, "html", "utf-8"))

    await aiosmtplib.send(
        msg,
        hostname=settings.SMTP_HOST,
        port=465,
        username=settings.SMTP_USER,
        password=settings.SMTP_PASSWORD,
        use_tls=True,
    )
