
"""
AUMVEDA Vendor Backend
M12.6.9F.1 - Owner Password OTP Security

Purpose:
- Generate cryptographically secure six-digit OTPs.
- Create HMAC-SHA256 OTP verifiers.
- Verify OTPs without storing plaintext codes.
- Bind each verifier to an Owner and a challenge ID.

IMPORTANT:
- Does not send emails.
- Does not access the database.
- Does not update passwords.
- Does not register any API endpoints.
- Expiration, attempt limits and atomic consumption
  must be enforced by the database service.
"""

import hashlib
import hmac
import os
import secrets
import uuid


OTP_LENGTH = 6
OTP_EXPIRY_MINUTES = 10
OTP_MAX_ATTEMPTS = 5

OTP_SECRET_ENV = "AUMVEDA_OWNER_OTP_HMAC_SECRET"


class OTPConfigurationError(RuntimeError):
    """The server-side OTP secret is not configured."""


def _get_secret() -> bytes:
    """
    Load the backend-only HMAC secret.

    Configure with at least 32 random bytes,
    represented as 64 hexadecimal characters.
    """

    value = os.getenv(OTP_SECRET_ENV, "").strip()

    if not value:
        raise OTPConfigurationError(
            "Vendor Owner OTP HMAC secret is not configured."
        )

    try:
        secret = bytes.fromhex(value)
    except ValueError:
        raise OTPConfigurationError(
            "Vendor Owner OTP HMAC secret is invalid."
        ) from None

    if len(secret) < 32:
        raise OTPConfigurationError(
            "Vendor Owner OTP HMAC secret must be "
            "at least 32 bytes."
        )

    return secret


def _validate_uuid(value: str, field_name: str) -> str:
    try:
        return str(uuid.UUID(str(value)))
    except (ValueError, TypeError, AttributeError):
        raise ValueError(
            f"Invalid {field_name}."
        ) from None


def _validate_otp(otp: str) -> None:
    if (
        not isinstance(otp, str)
        or len(otp) != OTP_LENGTH
        or not otp.isascii()
        or not otp.isdigit()
    ):
        raise ValueError(
            "OTP must contain exactly six ASCII digits."
        )


def generate_owner_otp() -> str:
    """
    Generate a cryptographically secure
    six-digit numerical OTP.

    Leading zeros are preserved.
    """

    return f"{secrets.randbelow(1_000_000):06d}"


def create_owner_otp_hmac(
    *,
    owner_user_id: str,
    challenge_id: str,
    otp: str,
) -> str:
    """
    Create a keyed verifier for an OTP challenge.

    The verifier is bound to:
    - Vendor Owner user ID
    - Unique challenge ID
    - OTP value
    """

    _validate_otp(otp)

    owner_id = _validate_uuid(
        owner_user_id,
        "Owner user ID",
    )

    challenge = _validate_uuid(
        challenge_id,
        "OTP challenge ID",
    )

    secret = _get_secret()

    message = (
        f"aumveda:vendor-owner-password-reset:v1:"
        f"{owner_id}:{challenge}:{otp}"
    ).encode("utf-8")

    return hmac.new(
        secret,
        message,
        hashlib.sha256,
    ).hexdigest()


def verify_owner_otp_hmac(
    *,
    owner_user_id: str,
    challenge_id: str,
    otp: str,
    expected_hmac: str,
) -> bool:
    """
    Check the supplied OTP against its stored verifier.

    Returns False for incorrectly formatted OTPs
    or invalid stored verifier formats.

    A missing or invalid server secret remains
    a configuration error.
    """

    secret = _get_secret()

    if (
        not isinstance(expected_hmac, str)
        or len(expected_hmac) != 64
    ):
        return False

    try:
        bytes.fromhex(expected_hmac)
    except ValueError:
        return False

    try:
        candidate_hmac = create_owner_otp_hmac(
            owner_user_id=owner_user_id,
            challenge_id=challenge_id,
            otp=otp,
        )
    except ValueError:
        return False

    return hmac.compare_digest(
        candidate_hmac,
        expected_hmac.lower(),
    )
