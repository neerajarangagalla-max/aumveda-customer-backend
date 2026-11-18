
"""
AUMVEDA Vendor Backend
Team Management Service

Features:
1. List vendor team members.
2. Retrieve individual member details.
3. Include employee email from Supabase Auth.
4. Include assigned custom roles.
5. Preserve existing member response fields.
6. Update non-owner system roles.
7. Activate and deactivate employees.
8. Protect Vendor Owner privileges.
9. Preserve custom permission mode.

Security:
- Called only by Owner-protected API routes.
- Vendor ID comes from authenticated context.
- Membership queries are vendor-scoped.
- No employee passwords are returned.
- Auth identities are never deleted.
- Vendor Owner memberships cannot be modified.
"""

import logging

from fastapi import HTTPException, status

from app.core.supabase import supabase_admin


logger = logging.getLogger(
    "aumveda.vendor.team_management"
)


ALLOWED_STAFF_ROLES = frozenset({
    "manager",
    "staff",
    "inventory",
    "orders",
})


# ============================================================
# ERROR HELPERS
# ============================================================

def _database_error(message: str):
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail=message,
    )


def _member_not_found():
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Vendor member was not found.",
    )


def _owner_protected():
    return HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=(
            "Vendor Owner privileges cannot be "
            "changed through Team Management."
        ),
    )


def _conflict(message: str):
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail=message,
    )


# ============================================================
# MEMBERSHIP LOOKUP
# ============================================================

def _get_membership(
    vendor_id: str,
    user_id: str,
) -> dict:

    try:
        response = (
            supabase_admin
            .table("vendor_members")
            .select("*")
            .eq("vendor_id", str(vendor_id))
            .eq("user_id", str(user_id))
            .limit(1)
            .execute()
        )

        rows = response.data or []

        if not rows:
            raise _member_not_found()

        return rows[0]

    except HTTPException:
        raise

    except Exception:
        logger.exception(
            "Unable to load vendor membership."
        )

        raise _database_error(
            "Unable to load vendor member."
        ) from None


# ============================================================
# LOAD MEMBER PROFILE
# ============================================================

def _get_member_profile(
    user_id: str,
) -> dict:

    try:
        response = (
            supabase_admin
            .table("profiles")
            .select(
                "id, full_name, phone, avatar_url, "
                "role, is_active, created_at"
            )
            .eq("id", str(user_id))
            .limit(1)
            .execute()
        )

        rows = response.data or []

        return rows[0] if rows else {}

    except Exception:
        logger.exception(
            "Unable to load team member profile."
        )

        raise _database_error(
            "Unable to load team member profile."
        ) from None


# ============================================================
# LOAD EMAIL FROM SUPABASE AUTH
#
# Emails are owned by Supabase Auth.
#
# We do not store password information or expose
# authentication metadata in the Team API.
#
# Called only through Owner-protected operations.
# ============================================================

def _get_member_email(
    user_id: str,
) -> str | None:

    try:
        response = (
            supabase_admin
            .auth
            .admin
            .get_user_by_id(str(user_id))
        )

        auth_user = getattr(
            response,
            "user",
            None,
        )

        if auth_user is None:
            logger.warning(
                "Team member has no Auth identity: %s",
                user_id,
            )

            return None

        email = getattr(
            auth_user,
            "email",
            None,
        )

        if not email:
            return None

        return str(email).strip().lower()

    except Exception:
        logger.exception(
            "Unable to retrieve team member email."
        )

        raise _database_error(
            "Unable to load employee account details."
        ) from None


# ============================================================
# LOAD MEMBER CUSTOM ROLE ASSIGNMENTS
#
# Database:
# public.vendor_member_custom_roles
#
# Return all assigned roles, including inactive roles,
# so the Owner can understand and manage assignments.
#
# Effective permissions remain calculated by the
# existing backend authorization service.
# ============================================================

def _get_member_custom_roles(
    vendor_id: str,
    user_id: str,
) -> list[dict]:

    try:
        response = (
            supabase_admin
            .table("vendor_member_custom_roles")
            .select("role_id")
            .eq("vendor_id", str(vendor_id))
            .eq("user_id", str(user_id))
            .execute()
        )

        assignments = response.data or []

        role_ids = sorted({
            str(row["role_id"])
            for row in assignments
            if row.get("role_id")
        })

        if not role_ids:
            return []

        roles_response = (
            supabase_admin
            .table("vendor_custom_roles")
            .select("*")
            .eq("vendor_id", str(vendor_id))
            .in_("id", role_ids)
            .execute()
        )

        role_rows = roles_response.data or []

        roles_by_id = {
            str(role["id"]): role
            for role in role_rows
            if role.get("id")
        }

        result = []

        for role_id in role_ids:
            role = roles_by_id.get(role_id, {})

            role_name = (
                role.get("name")
                or role.get("role_name")
                or role.get("title")
                or "Custom Role"
            )

            result.append({
                "id": role_id,
                "role_id": role_id,
                "name": str(role_name),
                "is_active": role.get(
                    "is_active",
                    False,
                ),
            })

        return result

    except Exception:
        logger.exception(
            "Unable to load member custom roles."
        )

        raise _database_error(
            "Unable to load employee custom roles."
        ) from None


# ============================================================
# BUILD MEMBER RESPONSE
#
# Existing fields are preserved:
#
# user_id
# full_name
# phone
# avatar_url
# system_role
# profile_active
# member_role
# membership_active
# permission_mode
# joined_at
#
# New fields:
#
# email
# is_active
# invitation_status
# custom_roles
# custom_role_ids
# assigned_custom_role_count
#
# No password or Auth token is returned.
# ============================================================

def _serialize_member(
    membership: dict,
    profile: dict,
    email: str | None,
    custom_roles: list[dict],
) -> dict:

    custom_role_ids = [
        role["id"]
        for role in custom_roles
    ]

    membership_active = membership.get(
        "is_active"
    )

    return {
        "user_id": membership.get("user_id"),

        "full_name": profile.get("full_name"),

        "email": email,

        "phone": profile.get("phone"),

        "avatar_url": profile.get("avatar_url"),

        "system_role": profile.get("role"),

        "profile_active": profile.get(
            "is_active"
        ),

        "member_role": membership.get(
            "member_role"
        ),

        "membership_active": membership_active,

        # Convenient alias for employee UI.
        "is_active": membership_active,

        "permission_mode": membership.get(
            "permission_mode",
            "legacy",
        ),

        "invitation_status": membership.get(
            "invitation_status"
        ),

        "joined_at": membership.get(
            "created_at"
        ),

        "custom_roles": custom_roles,

        "custom_role_ids": custom_role_ids,

        "assigned_custom_role_count": len(
            custom_role_ids
        ),
    }


# ============================================================
# COUNT ACTIVE OWNERS
#
# Retained for compatibility.
# ============================================================

def _count_active_owners(
    vendor_id: str,
) -> int:

    try:
        response = (
            supabase_admin
            .table("vendor_members")
            .select("user_id")
            .eq("vendor_id", str(vendor_id))
            .eq("member_role", "owner")
            .eq("is_active", True)
            .execute()
        )

        return len(response.data or [])

    except Exception:
        logger.exception(
            "Unable to validate active owners."
        )

        raise _database_error(
            "Unable to validate vendor ownership."
        ) from None


# ============================================================
# BUILD COMPLETE MEMBER DETAIL
# ============================================================

def _build_member_detail(
    vendor_id: str,
    membership: dict,
) -> dict:

    user_id = str(
        membership.get("user_id") or ""
    )

    profile = _get_member_profile(
        user_id
    )

    email = _get_member_email(
        user_id
    )

    custom_roles = _get_member_custom_roles(
        vendor_id=vendor_id,
        user_id=user_id,
    )

    return _serialize_member(
        membership=membership,
        profile=profile,
        email=email,
        custom_roles=custom_roles,
    )


# ============================================================
# LIST ALL TEAM MEMBERS
#
# Route:
# GET /api/v1/vendor/team
#
# Preserves the existing LIST response structure.
#
# Existing frontend consumers expecting an array
# will continue receiving an array.
# ============================================================

def list_vendor_members(
    vendor_id: str,
) -> list[dict]:

    try:
        response = (
            supabase_admin
            .table("vendor_members")
            .select(
                "vendor_id, user_id, member_role, "
                "is_active, permission_mode, "
                "invitation_status, created_at"
            )
            .eq("vendor_id", str(vendor_id))
            .order("created_at", desc=False)
            .execute()
        )

        memberships = response.data or []

    except Exception:
        logger.exception(
            "Unable to retrieve vendor team list."
        )

        raise _database_error(
            "Unable to load vendor team."
        ) from None

    result = []

    for membership in memberships:
        member = _build_member_detail(
            vendor_id=str(vendor_id),
            membership=membership,
        )

        result.append(member)

    return result


# ============================================================
# GET INDIVIDUAL TEAM MEMBER
#
# Route:
# GET /api/v1/vendor/team/{user_id}
# ============================================================

def get_vendor_member(
    vendor_id: str,
    user_id: str,
) -> dict:

    membership = _get_membership(
        vendor_id=vendor_id,
        user_id=user_id,
    )

    return _build_member_detail(
        vendor_id=str(vendor_id),
        membership=membership,
    )


# ============================================================
# UPDATE MEMBER SYSTEM ROLE
#
# Preserved security behavior:
#
# 1. Cannot assign owner.
# 2. Cannot change existing owner.
# 3. Cannot change own role.
# 4. Only permitted legacy roles accepted.
# 5. Existing permission_mode preserved.
#
# Custom-role permissions are not changed by
# updating member_role.
# ============================================================

def update_vendor_member_role(
    vendor_id: str,
    user_id: str,
    member_role: str,
    current_user_id: str,
) -> dict:

    requested_role = str(
        member_role or ""
    ).strip().lower()

    if requested_role not in ALLOWED_STAFF_ROLES:
        raise HTTPException(
            status_code=(
                status.HTTP_422_UNPROCESSABLE_ENTITY
            ),
            detail=(
                "Only manager, staff, inventory and "
                "orders roles can be assigned."
            ),
        )

    membership = _get_membership(
        vendor_id=vendor_id,
        user_id=user_id,
    )

    current_role = str(
        membership.get("member_role") or ""
    ).strip().lower()

    if current_role == "owner":
        raise _owner_protected()

    if str(user_id) == str(current_user_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "You cannot change your own "
                "membership role."
            ),
        )

    if current_role == requested_role:
        return {
            "message": (
                "Vendor member already has "
                "the requested role."
            ),
            "member": membership,
        }

    try:
        response = (
            supabase_admin
            .table("vendor_members")
            .update({
                "member_role": requested_role,
            })
            .eq("vendor_id", str(vendor_id))
            .eq("user_id", str(user_id))
            .neq("member_role", "owner")
            .select("*")
            .execute()
        )

        rows = response.data or []

        if not rows:
            raise _conflict(
                "Member role could not be updated. "
                "Refresh the team and try again."
            )

        return {
            "message": (
                "Vendor member role updated successfully."
            ),
            "member": rows[0],
        }

    except HTTPException:
        raise

    except Exception:
        logger.exception(
            "Unable to update member role."
        )

        raise _database_error(
            "Unable to update vendor member role."
        ) from None


# ============================================================
# ACTIVATE / DEACTIVATE EMPLOYEE
#
# Route:
# PATCH /api/v1/vendor/team/{user_id}/status
#
# Security:
# - Owner membership cannot be modified.
# - The acting Owner cannot modify their own status.
# - Membership is limited to the current vendor.
# - Custom permission_mode is preserved.
# - Existing FastAPI membership checks deny
#   access to inactive employees.
# ============================================================

def update_vendor_member_status(
    vendor_id: str,
    user_id: str,
    is_active: bool,
    current_user_id: str,
) -> dict:

    membership = _get_membership(
        vendor_id=vendor_id,
        user_id=user_id,
    )

    current_role = str(
        membership.get("member_role") or ""
    ).strip().lower()

    if current_role == "owner":
        raise _owner_protected()

    if str(user_id) == str(current_user_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "You cannot change your own "
                "membership status."
            ),
        )

    # ========================================================
    # ACTIVATION VALIDATION
    # ========================================================

    if is_active:
        profile = _get_member_profile(user_id)

        if not profile:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Member profile was not found.",
            )

        if profile.get("role") != "vendor":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    "Only Vendor accounts can be "
                    "activated as staff."
                ),
            )

        if profile.get("is_active") is not True:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    "Member profile is inactive. "
                    "Activation is not permitted."
                ),
            )

        permission_mode = str(
            membership.get(
                "permission_mode"
            ) or ""
        ).strip().lower()

        if permission_mode not in {
            "legacy",
            "custom",
        }:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    "Invalid member permission mode."
                ),
            )

        
        # Custom permissions are evaluated separately
        # by the existing vendor authorization service.
        

    # ========================================================
    # NO CHANGE REQUIRED
    # ========================================================

    if membership.get("is_active") is is_active:
        return {
            "message": (
                "Vendor member already has "
                "the requested status."
            ),
            "member": membership,
        }

    # ========================================================
    # UPDATE ONLY NON-OWNER MEMBER
    # ========================================================

    try:
        response = (
            supabase_admin
            .table("vendor_members")
            .update({
                "is_active": is_active,
            })
            .eq("vendor_id", str(vendor_id))
            .eq("user_id", str(user_id))
            .neq("member_role", "owner")
            .select("*")
            .execute()
        )

        rows = response.data or []

        if not rows:
            raise _conflict(
                "Member status could not be updated. "
                "Refresh the team and try again."
            )

        return {
            "message": (
                "Vendor member status updated successfully."
            ),
            "member": rows[0],
        }

    except HTTPException:
        raise

    except Exception:
        logger.exception(
            "Unable to update member status."
        )

        raise _database_error(
            "Unable to update vendor member status."
        ) from None
