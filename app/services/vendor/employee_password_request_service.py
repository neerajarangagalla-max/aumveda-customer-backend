
"""
AUMVEDA Vendor Backend
M12.6.8G - Employee Password Assistance Service

Workflow:
Employee submits email.
Backend identifies eligible employee and owner.
Vendor Owner receives a notification.
Owner resets password via existing Team Management.

Security:
- No employee OTP.
- No password updates.
- Generic public response.
- Restricted PostgreSQL RPC lookup.
- Existing notification table reused.
- Duplicate notification cooldown.
"""

import logging
from datetime import datetime, timedelta, timezone

from app.core.supabase import supabase_admin


logger = logging.getLogger(
    "aumveda.vendor.employee_password_request"
)

SUCCESS_MESSAGE = (
    "If this email belongs to an eligible employee, "
    "a password assistance request will be sent "
    "to the Vendor Owner."
)

REQUEST_COOLDOWN_MINUTES = 15

NOTIFICATION_TYPE = "employee_password_request"

REFERENCE_TYPE = "vendor_employee"


def _success():
    return {
        "status": "success",
        "message": SUCCESS_MESSAGE,
    }


def _normalize_email(email):
    if not isinstance(email, str):
        return ""

    return email.strip().lower()


def _lookup_employee(email):
    """
    Restricted service-role PostgreSQL function.

    Returns:
        employee_user_id
        vendor_id
        owner_user_id

    The database function verifies:
    - Supabase Auth email identity.
    - Active Vendor profile.
    - Active accepted employee membership.
    - Non-owner employee role.
    - Exactly one active accepted Vendor Owner.
    - Unambiguous employee membership.
    """

    response = (
        supabase_admin
        .rpc(
            "lookup_vendor_employee_for_password_request",
            {
                "p_email": email,
            },
        )
        .execute()
    )

    rows = response.data or []

    if len(rows) != 1:
        return None

    row = rows[0]

    employee_id = row.get(
        "employee_user_id"
    )

    vendor_id = row.get(
        "vendor_id"
    )

    owner_id = row.get(
        "owner_user_id"
    )

    if not all([
        employee_id,
        vendor_id,
        owner_id,
    ]):
        return None

    if str(employee_id) == str(owner_id):
        return None

    return {
        "employee_user_id": str(employee_id),
        "vendor_id": str(vendor_id),
        "owner_user_id": str(owner_id),
    }


def _recent_request_exists(
    owner_id,
    employee_id,
):
    cutoff = (
        datetime.now(timezone.utc)
        - timedelta(
            minutes=REQUEST_COOLDOWN_MINUTES
        )
    ).isoformat()

    response = (
        supabase_admin
        .table("notifications")
        .select("id")
        .eq(
            "recipient_id",
            owner_id
        )
        .eq(
            "recipient_role",
            "vendor"
        )
        .eq(
            "notification_type",
            NOTIFICATION_TYPE
        )
        .eq(
            "reference_type",
            REFERENCE_TYPE
        )
        .eq(
            "reference_id",
            employee_id
        )
        .gte(
            "created_at",
            cutoff
        )
        .limit(1)
        .execute()
    )

    return bool(response.data)


def _create_notification(
    owner_id,
    employee_id,
):
    """
    Create a Vendor Owner notification.

    Does not contain passwords, OTPs,
    access tokens or employee email.
    """

    payload = {
        "recipient_id": owner_id,
        "recipient_role": "vendor",
        "title": "Employee Password Assistance",
        "message": (
            "A team member has requested help "
            "with a forgotten password. "
            "Open Team Management to review "
            "the employee account."
        ),
        "notification_type": NOTIFICATION_TYPE,
        "reference_type": REFERENCE_TYPE,
        "reference_id": employee_id,
        "is_read": False,
    }

    (
        supabase_admin
        .table("notifications")
        .insert(payload)
        .execute()
    )


def request_employee_password_assistance(
    email,
):
    """
    Public employee password assistance workflow.

    The response is intentionally identical
    for known and unknown email addresses.

    This function never changes a password.
    """

    normalized_email = _normalize_email(
        email
    )

    if not normalized_email:
        return _success()

    try:
        employee = _lookup_employee(
            normalized_email
        )

        if employee is None:
            return _success()

        employee_id = employee[
            "employee_user_id"
        ]

        owner_id = employee[
            "owner_user_id"
        ]

        if _recent_request_exists(
            owner_id,
            employee_id,
        ):
            return _success()

        _create_notification(
            owner_id,
            employee_id,
        )

        logger.info(
            "Employee password assistance "
            "notification created."
        )

    except Exception as exc:
        logger.error(
            "Employee password assistance failed. "
            "exception_type=%s",
            type(exc).__name__,
        )

    return _success()
