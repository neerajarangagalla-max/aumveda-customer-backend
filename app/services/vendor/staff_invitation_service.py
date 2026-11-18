
import secrets
from uuid import UUID
from urllib.parse import urlsplit

from fastapi import HTTPException, status

from app.core.config import settings
from app.core.supabase import supabase_admin


# ============================================================
# AUMVEDA VENDOR — STAFF INVITATION SERVICE
#
# Only called from an Owner-protected FastAPI route.
#
# The Supabase service credential must remain
# exclusively on the backend.
# ============================================================


def _service_unavailable(message: str):
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail=message,
    )


def _get_invitation_redirect() -> str:
    redirect_url = (
        settings.vendor_invite_redirect_url or ""
    ).strip()

    if not redirect_url:
        raise _service_unavailable(
            "Staff invitation redirect is not configured."
        )

    parsed = urlsplit(redirect_url)

    if not parsed.scheme or not parsed.netloc:
        raise _service_unavailable(
            "Invalid staff invitation redirect URL."
        )

    if parsed.scheme not in {"http", "https"}:
        raise _service_unavailable(
            "Invalid invitation redirect protocol."
        )

    # Allow HTTP only for local development.
    if (
        parsed.scheme == "http"
        and parsed.hostname not in {
            "localhost",
            "127.0.0.1",
        }
    ):
        raise _service_unavailable(
            "Production invitation URLs must use HTTPS."
        )

    if (
        parsed.username
        or parsed.password
        or parsed.fragment
    ):
        raise _service_unavailable(
            "Invalid staff invitation redirect configuration."
        )

    return redirect_url


# ============================================================
# CHECK EXISTING EMAIL
# ============================================================

def _check_existing_email(email: str) -> None:
    try:
        response = (
            supabase_admin
            .rpc(
                "vendor_staff_email_exists",
                {
                    "p_email": email,
                },
            )
            .execute()
        )

        result = response.data

    except Exception:
        raise _service_unavailable(
            "Unable to verify staff email availability."
        )

    if result is True:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "This email is already registered. "
                "Use a different employee email."
            ),
        )

    if result is not False:
        raise _service_unavailable(
            "Email availability check returned "
            "an unexpected result."
        )


# ============================================================
# VALIDATE ACTIVE CUSTOM ROLES
# ============================================================

def _validate_custom_roles(
    vendor_id: str,
    role_ids: list[str],
) -> None:
    unique_ids = sorted(set(role_ids))

    if not unique_ids:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Select at least one custom role.",
        )

    try:
        response = (
            supabase_admin
            .table("vendor_custom_roles")
            .select("id")
            .eq("vendor_id", vendor_id)
            .eq("is_active", True)
            .in_("id", unique_ids)
            .execute()
        )

        found_ids = {
            str(row["id"])
            for row in (response.data or [])
        }

    except Exception:
        raise _service_unavailable(
            "Unable to validate the selected custom roles."
        )

    if found_ids != set(unique_ids):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "One or more selected custom roles "
                "are invalid, inactive or belong "
                "to another vendor."
            ),
        )


# ============================================================
# INVITE STAFF MEMBER
# ============================================================

def invite_vendor_staff(
    *,
    vendor_id: str,
    invited_by: str,
    full_name: str,
    email: str,
    role_ids: list[UUID],
):
    normalized_email = email.strip().lower()
    normalized_name = " ".join(full_name.split())

    normalized_role_ids = sorted({
        str(role_id)
        for role_id in role_ids
    })

    # --------------------------------------------------------
    # 1. VERIFY CONFIGURATION
    # --------------------------------------------------------

    redirect_url = _get_invitation_redirect()

    # --------------------------------------------------------
    # 2. VERIFY EMAIL IS NOT ALREADY REGISTERED
    # --------------------------------------------------------

    _check_existing_email(normalized_email)

    # --------------------------------------------------------
    # 3. VERIFY ALL CUSTOM ROLES
    # --------------------------------------------------------

    _validate_custom_roles(
        vendor_id=vendor_id,
        role_ids=normalized_role_ids,
    )

    # --------------------------------------------------------
    # 4. GENERATE AN INTERNAL PROVISIONING NONCE
    #
    # This nonce is used only to verify the
    # newly invited Auth account inside PostgreSQL.
    # It is never returned to the frontend.
    # --------------------------------------------------------

    invitation_nonce = secrets.token_urlsafe(48)

    # --------------------------------------------------------
    # 5. SEND SUPABASE AUTH INVITATION
    #
    # The existing on_auth_user_created trigger
    # creates a temporary customer profile.
    #
    # The verified provisioning function converts
    # only the newly invited account into staff.
    # --------------------------------------------------------

    try:
        invitation_response = (
            supabase_admin
            .auth
            .admin
            .invite_user_by_email(
                normalized_email,
                {
                    "data": {
                        "full_name": normalized_name,
                        "aumveda_staff_invitation_nonce": (
                            invitation_nonce
                        ),
                    },
                    "redirect_to": redirect_url,
                },
            )
        )

    except Exception as exc:
        error_code = getattr(exc, "code", None)

        if error_code in {
            "email_exists",
            "user_already_exists",
        }:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This email is already registered.",
            )

        # Do not assume that no account was created
        # if the Auth request failed or timed out.
        # Recheck Auth before attempting to retry.

        raise _service_unavailable(
            "Staff invitation could not be confirmed. "
            "Check Supabase Auth Users before retrying."
        )

    invited_user = getattr(
        invitation_response,
        "user",
        None,
    )

    if not invited_user:
        raise _service_unavailable(
            "Invitation returned no user. "
            "Check Supabase Auth Users before retrying."
        )

    invited_user_id = str(invited_user.id)

    # --------------------------------------------------------
    # 6. BASIC INVITATION RESPONSE VERIFICATION
    #
    # The PostgreSQL verified provisioning function
    # independently checks:
    # - account ID
    # - invitation nonce
    # - invited_at
    # - account creation time
    # - previous sign-in history
    # --------------------------------------------------------

    returned_email = str(
        invited_user.email or ""
    ).strip().lower()

    if returned_email != normalized_email:
        raise _service_unavailable(
            "Invitation identity verification failed. "
            "Manual account review is required."
        )

    # --------------------------------------------------------
    # 7. ATOMIC DATABASE PROVISIONING
    #
    # Requires the existing verified PostgreSQL RPC:
    # provision_vendor_staff_verified_atomic
    # --------------------------------------------------------

    try:
        (
            supabase_admin
            .rpc(
                "provision_vendor_staff_verified_atomic",
                {
                    "p_vendor_id": vendor_id,
                    "p_user_id": invited_user_id,
                    "p_invited_by": invited_by,
                    "p_full_name": normalized_name,
                    "p_role_ids": normalized_role_ids,
                    "p_invitation_nonce": invitation_nonce,
                },
            )
            .execute()
        )

    except Exception:
        # Authentication invitation may already
        # have been delivered.
        #
        # Never delete the user automatically:
        # an existing or reused identity must not
        # be deleted during recovery.
        #
        # The invite remains blocked from Vendor
        # access unless provisioning completed.

        raise _service_unavailable(
            "Invitation was initiated, but staff "
            "provisioning could not be verified. "
            "Manual account review is required "
            "before retrying."
        )

    # --------------------------------------------------------
    # 8. SUCCESS RESPONSE
    #
    # Never return service credentials, nonce,
    # invitation tokens or password information.
    # --------------------------------------------------------

    return {
        "status": "success",
        "message": (
            "Staff invitation initiated and "
            "vendor membership provisioned."
        ),
        "staff": {
            "user_id": invited_user_id,
            "full_name": normalized_name,
            "email": normalized_email,
            "member_role": "staff",
            "permission_mode": "custom",
            "role_ids": normalized_role_ids,
        },
        "invitation_status": "sent",
    }
