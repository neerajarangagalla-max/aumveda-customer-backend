
"""
AUMVEDA Vendor Backend
Owner-Created Employee Account Service

Approved workflow:
1. Vendor Owner signs in.
2. Owner opens Team -> Add Employee.
3. Owner enters name, email and password.
4. Owner assigns one or more active custom roles.
5. FastAPI creates a Supabase Auth identity.
6. PostgreSQL provisions the vendor membership.
7. Employee logs in through the normal Vendor Login.

Employees do not need to:
- Register separately
- Accept an email invitation
- Create their own initial password
- Change their password at first login

Security:
- Endpoint must use get_vendor_owner.
- Vendor ID must come from authenticated context.
- Creator ID must come from authenticated context.
- Employees receive member_role='staff'.
- Employees receive permission_mode='custom'.
- Existing Auth identities cannot be reused.
- Selected roles must belong to the same vendor.
- Passwords are handled only by Supabase Auth.
- No automatic Auth account deletion after uncertainty.
- Detailed provisioning errors stay in backend logs.
"""

import logging
import secrets

from uuid import UUID

from fastapi import HTTPException, status

from app.core.supabase import supabase_admin


# ============================================================
# LOGGER
# ============================================================

logger = logging.getLogger(
    "aumveda.vendor.staff_creation"
)


# ============================================================
# ERROR HELPERS
# ============================================================

def _service_unavailable(
    message: str,
) -> HTTPException:

    return HTTPException(
        status_code=(
            status.HTTP_503_SERVICE_UNAVAILABLE
        ),
        detail=message,
    )


def _validation_error(
    message: str,
) -> HTTPException:

    return HTTPException(
        status_code=(
            status.HTTP_422_UNPROCESSABLE_ENTITY
        ),
        detail=message,
    )


def _conflict(
    message: str,
) -> HTTPException:

    return HTTPException(
        status_code=(
            status.HTTP_409_CONFLICT
        ),
        detail=message,
    )


# ============================================================
# UUID NORMALIZATION
# ============================================================

def _normalize_uuid(
    value,
) -> str:

    try:
        return str(
            UUID(str(value))
        )

    except (
        TypeError,
        ValueError,
        AttributeError,
    ):

        raise _validation_error(
            "Invalid employee provisioning identifier."
        ) from None


# ============================================================
# SAFE DATABASE ERROR DIAGNOSTICS
#
# Record:
# - Exception class
# - PostgreSQL/PostgREST error code
# - SQLSTATE, if available
# - Database error message
# - Database error details
#
# Never log:
# - Passwords
# - Provisioning nonce
# - Auth tokens
# - Service-role credentials
#
# Database error details may still contain sensitive
# information. Logs must be restricted to developers.
# ============================================================

def _log_database_error(
    *,
    operation: str,
    exc: Exception,
    user_id: str = "",
    vendor_id: str = "",
) -> None:

    exception_type = (
        type(exc).__name__
    )

    database_code = getattr(
        exc,
        "code",
        None,
    )

    database_message = getattr(
        exc,
        "message",
        None,
    )

    database_details = getattr(
        exc,
        "details",
        None,
    )

    database_hint = getattr(
        exc,
        "hint",
        None,
    )

    # Some exception implementations expose
    # SQLSTATE directly.

    sqlstate = getattr(
        exc,
        "sqlstate",
        None,
    )

    # Do not serialize the entire exception.
    # It may contain HTTP request data or secrets.

    logger.error(
        "AUMVEDA STAFF DATABASE ERROR | "
        "operation=%s | "
        "user_id=%s | "
        "vendor_id=%s | "
        "exception_type=%s | "
        "database_code=%s | "
        "sqlstate=%s | "
        "database_message=%s | "
        "database_details=%s | "
        "database_hint=%s",
        operation,
        user_id,
        vendor_id,
        exception_type,
        database_code,
        sqlstate,
        database_message,
        database_details,
        database_hint,
    )


# ============================================================
# CHECK EXISTING EMAIL
#
# Uses existing PostgreSQL RPC:
# public.vendor_staff_email_exists
#
# Expected result:
# true  -> Email already exists
# false -> Email not found
#
# Supabase Auth remains authoritative.
#
# This is only a preliminary check and does not
# eliminate concurrent account-creation races.
# ============================================================

def _check_existing_email(
    email: str,
) -> None:

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

        exists = response.data

    except Exception as exc:

        _log_database_error(
            operation="check_existing_email",
            exc=exc,
        )

        raise _service_unavailable(
            "Unable to verify employee email "
            "availability. Check backend logs."
        ) from None

    if exists is True:

        raise _conflict(
            "This email address is already "
            "registered. Please use a different "
            "employee email."
        )

    if exists is not False:

        logger.error(
            "Employee email RPC returned "
            "an unexpected result type: %s",
            type(exists).__name__,
        )

        raise _service_unavailable(
            "Employee email availability "
            "could not be confirmed."
        )


# ============================================================
# VERIFY CUSTOM ROLES
#
# Requirements:
# - At least one custom role
# - Maximum 100 unique custom roles
# - Every role belongs to authenticated vendor
# - Every selected role is active
#
# PostgreSQL provisioning independently repeats
# these checks for authorization.
# ============================================================

def _validate_custom_roles(
    vendor_id: str,
    role_ids: list[str],
) -> list[str]:

    normalized_ids = sorted(
        set(role_ids)
    )

    if not normalized_ids:

        raise _validation_error(
            "Select at least one custom role."
        )

    if len(normalized_ids) > 100:

        raise _validation_error(
            "A maximum of 100 custom roles "
            "can be assigned."
        )

    try:

        response = (
            supabase_admin
            .table(
                "vendor_custom_roles"
            )
            .select("id")
            .eq(
                "vendor_id",
                vendor_id,
            )
            .eq(
                "is_active",
                True,
            )
            .in_(
                "id",
                normalized_ids,
            )
            .execute()
        )

        rows = response.data or []

        found_ids = {
            str(UUID(str(row["id"])))
            for row in rows
            if row.get("id")
        }

    except Exception as exc:

        _log_database_error(
            operation="validate_custom_roles",
            exc=exc,
            vendor_id=vendor_id,
        )

        raise _service_unavailable(
            "Unable to verify the selected "
            "custom roles. Check backend logs."
        ) from None

    if found_ids != set(normalized_ids):

        raise _validation_error(
            "One or more selected roles "
            "are invalid, inactive, or belong "
            "to another vendor."
        )

    return normalized_ids


# ============================================================
# CREATE VENDOR STAFF
#
# IMPORTANT:
#
# This service must only be called by an endpoint
# protected with:
#
# Depends(get_vendor_owner)
#
# Both vendor_id and created_by must be read from
# the authenticated Owner context, never from
# the browser payload.
# ============================================================

def create_vendor_staff(
    *,
    vendor_id: str,
    created_by: str,
    full_name: str,
    email: str,
    password: str,
    role_ids: list[UUID],
) -> dict:

    # ========================================================
    # 1. NORMALIZE VENDOR AND OWNER IDS
    # ========================================================

    normalized_vendor_id = (
        _normalize_uuid(
            vendor_id
        )
    )

    normalized_creator_id = (
        _normalize_uuid(
            created_by
        )
    )

    # ========================================================
    # 2. VALIDATE EMPLOYEE NAME
    # ========================================================

    if not isinstance(
        full_name,
        str,
    ):

        raise _validation_error(
            "Employee full name is required."
        )

    normalized_name = " ".join(
        full_name.split()
    )

    if not (
        2 <= len(normalized_name) <= 150
    ):

        raise _validation_error(
            "Employee name must contain "
            "2 to 150 characters."
        )

    # ========================================================
    # 3. VALIDATE EMAIL
    #
    # The Pydantic request schema also validates
    # the email using EmailStr.
    # ========================================================

    if not isinstance(
        email,
        str,
    ):

        raise _validation_error(
            "Employee email is required."
        )

    normalized_email = (
        email.strip().lower()
    )

    if not normalized_email:

        raise _validation_error(
            "Employee email is required."
        )

    # ========================================================
    # 4. VALIDATE PASSWORD
    #
    # Owner chooses the initial password.
    #
    # No fixed application-level password length
    # is imposed by this service.
    #
    # Supabase Auth applies its own configured
    # password policy.
    #
    # Passwords are never trimmed or logged.
    # ========================================================

    if not isinstance(
        password,
        str,
    ):

        raise _validation_error(
            "Employee password must be a string."
        )

    if not password:

        raise _validation_error(
            "Employee password cannot be empty."
        )

    # ========================================================
    # 5. NORMALIZE CUSTOM ROLE IDS
    # ========================================================

    if not isinstance(
        role_ids,
        list,
    ):

        raise _validation_error(
            "Custom roles must be provided as a list."
        )

    normalized_role_ids = sorted({
        _normalize_uuid(role_id)
        for role_id in role_ids
    })

    if not normalized_role_ids:

        raise _validation_error(
            "Select at least one custom role."
        )

    # ========================================================
    # 6. CHECK EMAIL AVAILABILITY
    # ========================================================

    _check_existing_email(
        normalized_email
    )

    # ========================================================
    # 7. VALIDATE ACTIVE CUSTOM ROLES
    # ========================================================

    normalized_role_ids = (
        _validate_custom_roles(
            vendor_id=(
                normalized_vendor_id
            ),
            role_ids=(
                normalized_role_ids
            ),
        )
    )

    # ========================================================
    # 8. GENERATE PRIVATE PROVISIONING NONCE
    #
    # Stored temporarily in Supabase Auth metadata.
    # The PostgreSQL wrapper verifies and removes it.
    #
    # Do not return or log this value.
    # ========================================================

    creation_nonce = (
        secrets.token_urlsafe(48)
    )

    # ========================================================
    # 9. CREATE SUPABASE AUTH ACCOUNT
    #
    # Owner-selected password is passed directly to
    # Supabase Auth Admin create_user.
    #
    # email_confirm=True permits immediate login
    # without an email-verification step.
    #
    # IMPORTANT:
    # This is administrative confirmation, not
    # proof that the employee owns the mailbox.
    # ========================================================

    logger.info(
        "Starting Owner-created employee account "
        "creation for vendor_id=%s",
        normalized_vendor_id,
    )

    try:

        auth_response = (
            supabase_admin
            .auth
            .admin
            .create_user(
                {
                    "email": (
                        normalized_email
                    ),
                    "password": password,
                    "email_confirm": True,
                    "user_metadata": {
                        "full_name": (
                            normalized_name
                        ),
                        "aumveda_staff_creation_nonce": (
                            creation_nonce
                        ),
                    },
                }
            )
        )

    except Exception as exc:

        error_code = str(
            getattr(
                exc,
                "code",
                "",
            ) or ""
        ).lower()

        if error_code in {
            "email_exists",
            "user_already_exists",
        }:

            raise _conflict(
                "This employee email is "
                "already registered."
            ) from None

        logger.error(
            "Supabase Auth employee creation "
            "failed or could not be confirmed. "
            "vendor_id=%s exception_type=%s "
            "auth_error_code=%s",
            normalized_vendor_id,
            type(exc).__name__,
            error_code,
        )

        # Auth account creation may succeed before
        # an HTTP timeout or network failure.
        #
        # Do not automatically retry or delete.

        raise _service_unavailable(
            "Employee Auth account creation "
            "could not be confirmed. Review "
            "Supabase Auth Users before retrying."
        ) from None

    # ========================================================
    # 10. CHECK SUPABASE AUTH RESPONSE
    # ========================================================

    employee_user = getattr(
        auth_response,
        "user",
        None,
    )

    if employee_user is None:

        logger.error(
            "Supabase Auth returned no employee "
            "identity after account creation."
        )

        raise _service_unavailable(
            "Supabase Auth did not return "
            "the employee identity. Review "
            "Auth Users before retrying."
        )

    # ========================================================
    # 11. VERIFY EMPLOYEE AUTH USER ID
    # ========================================================

    try:

        employee_user_id = str(
            UUID(
                str(employee_user.id)
            )
        )

    except (
        TypeError,
        ValueError,
        AttributeError,
    ):

        logger.error(
            "Supabase Auth returned invalid "
            "employee user ID."
        )

        raise _service_unavailable(
            "Employee Auth identity verification "
            "failed. Manual review is required."
        )

    # ========================================================
    # 12. VERIFY EMPLOYEE EMAIL
    # ========================================================

    returned_email = (
        str(
            employee_user.email or ""
        )
        .strip()
        .lower()
    )

    if (
        returned_email
        != normalized_email
    ):

        logger.error(
            "Employee Auth email mismatch "
            "for user_id=%s",
            employee_user_id,
        )

        raise _service_unavailable(
            "Employee Auth email verification "
            "failed. Manual review is required."
        )

    logger.info(
        "Supabase Auth identity created. "
        "user_id=%s vendor_id=%s",
        employee_user_id,
        normalized_vendor_id,
    )

    # ========================================================
    # 13. CALL VERIFIED POSTGRESQL PROVISIONING
    #
    # RPC:
    # public.provision_vendor_staff_password_verified_atomic
    #
    # The database verifies:
    # - Freshly created Auth user
    # - Private provisioning nonce
    # - Password-based Auth identity
    # - No previous employee sign-in
    # - Active and approved Vendor Owner
    # - Valid vendor-specific custom roles
    # - Eligible employee profile
    # - No existing vendor membership
    #
    # On success:
    # - Profile role becomes vendor
    # - Staff membership is created
    # - Custom roles are assigned
    # - Staff membership is activated
    # - Provisioning nonce is removed
    #
    # The database transaction is atomic.
    # ========================================================

    try:

        (
            supabase_admin
            .rpc(
                "provision_vendor_staff_password_verified_atomic",
                {
                    "p_vendor_id": (
                        normalized_vendor_id
                    ),
                    "p_user_id": (
                        employee_user_id
                    ),
                    "p_created_by": (
                        normalized_creator_id
                    ),
                    "p_full_name": (
                        normalized_name
                    ),
                    "p_role_ids": (
                        normalized_role_ids
                    ),
                    "p_creation_nonce": (
                        creation_nonce
                    ),
                },
            )
            .execute()
        )

    # ========================================================
    # 14. CAPTURE EXACT DATABASE ERROR
    #
    # This is the main diagnostic improvement.
    #
    # PostgreSQL/PostgREST error details are
    # available in the FastAPI terminal.
    #
    # They are never returned to Vendor Web.
    # ========================================================

    except Exception as exc:

        _log_database_error(
            operation=(
                "provision_vendor_staff_password_verified_atomic"
            ),
            exc=exc,
            user_id=employee_user_id,
            vendor_id=normalized_vendor_id,
        )

        # Do not automatically delete the Auth user.
        #
        # A database transaction may have committed
        # even when the HTTP request fails.
        #
        # The account must be reconciled before
        # another employee creation attempt.

        raise _service_unavailable(
            "Employee Auth account was created, "
            "but vendor membership provisioning "
            "could not be confirmed. "
            "Review the Vendor Backend logs "
            "before retrying."
        ) from None

    # ========================================================
    # 15. LOG SUCCESS
    #
    # No password or nonce is logged.
    # ========================================================

    logger.info(
        "Employee account provisioning completed. "
        "user_id=%s vendor_id=%s "
        "assigned_role_count=%s",
        employee_user_id,
        normalized_vendor_id,
        len(normalized_role_ids),
    )

    # ========================================================
    # 16. RETURN SAFE RESPONSE
    #
    # Never return:
    # - Initial password
    # - Password hash
    # - Internal nonce
    # - Service-role credentials
    # - Auth access token
    # - Auth refresh token
    # ========================================================

    return {
        "status": "success",

        "message": (
            "Employee account created successfully. "
            "The employee can log in through the "
            "Vendor Login page using the credentials "
            "provided by the Vendor Owner."
        ),

        "staff": {
            "user_id": (
                employee_user_id
            ),
            "full_name": (
                normalized_name
            ),
            "email": (
                normalized_email
            ),
            "member_role": "staff",
            "permission_mode": "custom",
            "role_ids": (
                normalized_role_ids
            ),
        },

        "account_status": "active",
    }
