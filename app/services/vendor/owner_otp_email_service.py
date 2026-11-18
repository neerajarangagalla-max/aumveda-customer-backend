
"""
AUMVEDA Vendor Backend
M12.6.9D - Vendor Owner OTP Email Sender

Purpose:
Send password recovery OTP emails to verified
Vendor Owners.

Security:
- SMTP credentials are environment-configured.
- No passwords or OTPs are logged.
- No SMTP credentials are returned to clients.
- TLS is required.
- No fallback to unencrypted SMTP.
- No database or Supabase Auth changes.

This service is not connected to public routes yet.
"""

import os
import smtplib
import ssl

from email.message import EmailMessage


class OTPEmailConfigurationError(Exception):
    """SMTP configuration is missing or invalid."""


class OTPEmailDeliveryError(Exception):
    """The OTP email could not be delivered."""


def _smtp_config():
    host = os.getenv(
        "AUMVEDA_SMTP_HOST", ""
    ).strip()

    port_value = os.getenv(
        "AUMVEDA_SMTP_PORT", "465"
    ).strip()

    username = os.getenv(
        "AUMVEDA_SMTP_USERNAME", ""
    ).strip()

    password = os.getenv(
        "AUMVEDA_SMTP_PASSWORD", ""
    )

    sender = os.getenv(
        "AUMVEDA_SMTP_FROM_EMAIL", ""
    ).strip()

    security = os.getenv(
        "AUMVEDA_SMTP_SECURITY", "ssl"
    ).strip().lower()

    if not all([
        host,
        username,
        password,
        sender,
    ]):
        raise OTPEmailConfigurationError(
            "Vendor OTP email service is not configured."
        )

    try:
        port = int(port_value)
    except ValueError:
        raise OTPEmailConfigurationError(
            "Invalid SMTP port configuration."
        ) from None

    if not 1 <= port <= 65535:
        raise OTPEmailConfigurationError(
            "Invalid SMTP port configuration."
        )

    if security not in {"ssl", "starttls"}:
        raise OTPEmailConfigurationError(
            "SMTP must use SSL or STARTTLS."
        )

    return {
        "host": host,
        "port": port,
        "username": username,
        "password": password,
        "sender": sender,
        "security": security,
    }


def send_vendor_owner_otp_email(
    *,
    recipient_email: str,
    otp: str,
    expiry_minutes: int = 10,
) -> None:
    """
    Sends the supplied OTP.

    IMPORTANT:
    This function does not generate or verify OTPs.
    The caller must:
    - Verify the recipient is a Vendor Owner.
    - Generate a cryptographically secure OTP.
    - Store only a protected OTP verifier.
    - Enforce expiration and attempt limits.
    - Prevent OTP reuse.
    """

    if (
        not isinstance(recipient_email, str)
        or not recipient_email.strip()
        or "\n" in recipient_email
        or "\r" in recipient_email
        or "@" not in recipient_email
    ):
        raise ValueError(
            "A valid recipient email is required."
        )

    if (
        not isinstance(otp, str)
        or len(otp) != 6
        or not otp.isascii()
        or not otp.isdigit()
    ):
        raise ValueError(
            "A valid six-digit OTP is required."
        )

    if (
        not isinstance(expiry_minutes, int)
        or not 1 <= expiry_minutes <= 30
    ):
        raise ValueError(
            "Invalid OTP expiry configuration."
        )

    config = _smtp_config()

    message = EmailMessage()

    message["Subject"] = (
        "AUMVEDA Vendor - Password Reset OTP"
    )

    message["From"] = config["sender"]

    message["To"] = recipient_email.strip()

    message.set_content(
        f"""
AUMVEDA VENDOR ACCOUNT

Password Reset Verification

Your one-time password (OTP) is:

{otp}

This OTP expires in {expiry_minutes} minutes.

If you did not request a password reset,
you can ignore this email.

Never share your OTP with anyone.

AUMVEDA Vendor Security
""".strip()
    )

    tls_context = ssl.create_default_context()

    try:
        if config["security"] == "ssl":
            with smtplib.SMTP_SSL(
                config["host"],
                config["port"],
                timeout=15,
                context=tls_context,
            ) as smtp:
                smtp.login(
                    config["username"],
                    config["password"],
                )

                smtp.send_message(message)

        else:
            with smtplib.SMTP(
                config["host"],
                config["port"],
                timeout=15,
            ) as smtp:
                smtp.ehlo()

                smtp.starttls(
                    context=tls_context
                )

                smtp.ehlo()

                smtp.login(
                    config["username"],
                    config["password"],
                )

                smtp.send_message(message)

    except (
        smtplib.SMTPException,
        OSError,
        TimeoutError,
    ) as exc:
        raise OTPEmailDeliveryError(
            "Unable to deliver Vendor Owner OTP email."
        ) from exc
