
"""
AUMVEDA Vendor Backend
Vendor Role-Based Access Control (RBAC)

Supports:
- Vendor Owner permissions
- Legacy vendor membership roles
- Custom staff roles
- Accounts / Earnings permission
- Multiple assigned custom roles
- Vendor-level permission isolation
- Active-role validation
- Fail-closed permission resolution

Security rules:
1. Owner retains all recognized permissions.
2. Custom staff receive only assigned permissions.
3. Legacy staff retain their original permissions.
4. Legacy managers do NOT automatically gain Earnings.
5. Earnings is explicitly assignable through custom roles.
6. Payouts, Team Management and Business Settings
   remain Owner-only.
7. Inactive custom roles grant no permissions.
8. Database failures never grant fallback access.

IMPORTANT:
This module determines effective permissions.

The Earnings API must also enforce
require_vendor_permission("earnings.view").

The database permission constraint must allow
earnings.view before Accounts roles can be saved.
"""

import logging

from collections.abc import Callable
from typing import Any

from fastapi import (
    Depends,
    HTTPException,
    status,
)

from app.core.supabase import supabase_admin

from app.dependencies.vendor import (
    get_approved_vendor,
)


logger = logging.getLogger(
    "aumveda.vendor.permissions"
)


# ============================================================
# 1. ORIGINAL OPERATIONAL PERMISSIONS
# ============================================================

BASE_OPERATIONAL_PERMISSIONS = frozenset({
    "dashboard.view",

    "products.view",
    "products.create",
    "products.update",
    "products.images",

    "inventory.view",
    "inventory.update",

    "orders.view",
    "orders.update",

    "shipping.view",
    "shipping.update",
})


# ============================================================
# 2. ACCOUNTS / FINANCIAL READ PERMISSIONS
#
# These are assignable only through explicit custom
# role membership.
#
# Viewing earnings does not imply:
# - Payout management
# - Bank account changes
# - Financial configuration updates
# - Vendor ownership
# ============================================================

ACCOUNTS_PERMISSIONS = frozenset({
    "earnings.view",
})


# ============================================================
# 3. ALL CUSTOM-ROLE ASSIGNABLE PERMISSIONS
#
# Keep OPERATIONAL_PERMISSIONS as the exported name
# for compatibility with:
#
# custom_role_service.py
# custom role validation
# existing vendor permission dependencies
# ============================================================

OPERATIONAL_PERMISSIONS = (
    BASE_OPERATIONAL_PERMISSIONS
    | ACCOUNTS_PERMISSIONS
)


# ============================================================
# 4. OWNER-ONLY CAPABILITIES
#
# Never grant these through custom roles.
# ============================================================

OWNER_ONLY_CAPABILITIES = frozenset({
    "payouts.view",
    "team.manage",
    "business.manage",
})


# ============================================================
# 5. ALL RECOGNIZED PERMISSIONS
# ============================================================

ALL_PERMISSIONS = (
    OPERATIONAL_PERMISSIONS
    | OWNER_ONLY_CAPABILITIES
)


# ============================================================
# 6. LEGACY ROLE PERMISSIONS
#
# CRITICAL:
# Existing managers must not automatically inherit
# earnings.view when it becomes assignable.
#
# Therefore use BASE_OPERATIONAL_PERMISSIONS
# rather than OPERATIONAL_PERMISSIONS.
#
# Custom role membership is required for staff
# to obtain financial read access.
# ============================================================

LEGACY_ROLE_PERMISSIONS = {
    "manager": BASE_OPERATIONAL_PERMISSIONS,

    "staff": frozenset({
        "dashboard.view",
        "products.view",
        "products.create",
        "products.update",
        "products.images",
    }),

    "inventory": frozenset({
        "dashboard.view",
        "inventory.view",
        "inventory.update",
    }),

    "orders": frozenset({
        "dashboard.view",
        "orders.view",
        "orders.update",
        "shipping.view",
        "shipping.update",
    }),
}


# ============================================================
# 7. DATABASE ERROR HANDLING
# ============================================================

def _permission_database_error(
    operation: str,
    exc: Exception,
) -> HTTPException:
    """
    Log internal failures but never expose
    Supabase or database details to clients.
    """

    logger.error(
        "Vendor permission database failure: %s",
        operation,
        exc_info=(
            type(exc),
            exc,
            exc.__traceback__,
        ),
    )

    return HTTPException(
        status_code=(
            status.HTTP_503_SERVICE_UNAVAILABLE
        ),
        detail=(
            "Unable to verify assigned "
            "vendor permissions."
        ),
    )


# ============================================================
# 8. LOAD CUSTOM ROLE PERMISSIONS
#
# Steps:
# 1. Read member role assignments.
# 2. Restrict to the authenticated vendor.
# 3. Keep only active custom roles.
# 4. Load permissions for those roles.
# 5. Filter against assignable permissions.
#
# No assignments -> empty set.
# Inactive roles -> no permission contribution.
# Database error -> 503, never legacy fallback.
# ============================================================

def _load_custom_permissions(
    vendor_id: str,
    user_id: str,
) -> set[str]:

    # --------------------------------------------------------
    # LOAD ROLE ASSIGNMENTS
    # --------------------------------------------------------

    try:
        assignments_response = (
            supabase_admin
            .table(
                "vendor_member_custom_roles"
            )
            .select("role_id")
            .eq(
                "vendor_id",
                vendor_id,
            )
            .eq(
                "user_id",
                user_id,
            )
            .execute()
        )

        assignments = (
            assignments_response.data or []
        )

        role_ids = sorted({
            str(row["role_id"])
            for row in assignments
            if row.get("role_id")
        })

        if not role_ids:
            return set()

        # ----------------------------------------------------
        # LOAD ACTIVE ROLES
        # ----------------------------------------------------

        roles_response = (
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
                role_ids,
            )
            .execute()
        )

        active_role_ids = {
            str(row["id"])
            for row in (
                roles_response.data or []
            )
            if row.get("id")
        }

        if not active_role_ids:
            return set()

        # ----------------------------------------------------
        # LOAD ROLE PERMISSIONS
        # ----------------------------------------------------

        permissions_response = (
            supabase_admin
            .table(
                "vendor_role_permissions"
            )
            .select(
                "role_id, permission_key"
            )
            .eq(
                "vendor_id",
                vendor_id,
            )
            .in_(
                "role_id",
                sorted(active_role_ids),
            )
            .execute()
        )

        # ----------------------------------------------------
        # COLLECT EFFECTIVE ASSIGNABLE PERMISSIONS
        # ----------------------------------------------------

        permitted = set()

        for record in (
            permissions_response.data or []
        ):
            role_id = str(
                record.get("role_id") or ""
            )

            permission = str(
                record.get("permission_key") or ""
            )

            if (
                role_id in active_role_ids
                and permission in OPERATIONAL_PERMISSIONS
            ):
                permitted.add(
                    permission
                )

        # ----------------------------------------------------
        # DEFENSE IN DEPTH
        # ----------------------------------------------------

        permitted.intersection_update(
            OPERATIONAL_PERMISSIONS
        )

        permitted.difference_update(
            OWNER_ONLY_CAPABILITIES
        )

        return permitted

    except HTTPException:
        raise

    except Exception as exc:
        raise _permission_database_error(
            "load custom role permissions",
            exc,
        ) from exc


# ============================================================
# 9. RESOLVE EFFECTIVE PERMISSIONS
#
# Owner:
#   All recognized permissions.
#
# Custom:
#   Active assigned custom-role permissions only.
#
# Legacy:
#   Original fixed-role permissions only.
#
# Unknown mode:
#   No permissions.
#
# No privilege escalation between modes.
# ============================================================

def resolve_vendor_permissions(
    vendor_context: dict[str, Any],
) -> set[str]:

    membership = (
        vendor_context["membership"]
    )

    member_role = str(
        membership.get(
            "member_role"
        ) or ""
    ).strip().lower()

    permission_mode = str(
        membership.get(
            "permission_mode"
        ) or ""
    ).strip().lower()

    # --------------------------------------------------------
    # INACTIVE MEMBERSHIP
    #
    # Authentication dependency must also reject
    # inactive memberships before allowing access.
    # --------------------------------------------------------

    if membership.get("is_active") is not True:
        return set()

    # --------------------------------------------------------
    # OWNER
    # --------------------------------------------------------

    if member_role == "owner":
        return set(
            ALL_PERMISSIONS
        )

    # --------------------------------------------------------
    # CUSTOM ROLE MEMBERSHIP
    # --------------------------------------------------------

    if permission_mode == "custom":
        permissions = (
            _load_custom_permissions(
                vendor_id=str(
                    vendor_context[
                        "vendor_id"
                    ]
                ),
                user_id=str(
                    vendor_context[
                        "user_id"
                    ]
                ),
            )
        )

    # --------------------------------------------------------
    # LEGACY MEMBERSHIP
    # --------------------------------------------------------

    elif permission_mode == "legacy":
        permissions = set(
            LEGACY_ROLE_PERMISSIONS.get(
                member_role,
                frozenset(),
            )
        )

    # --------------------------------------------------------
    # UNKNOWN PERMISSION MODE
    # --------------------------------------------------------

    else:
        return set()

    # --------------------------------------------------------
    # SECURITY FILTER
    #
    # Staff may receive earnings.view explicitly,
    # but never Owner-only capabilities.
    # --------------------------------------------------------

    permissions.intersection_update(
        OPERATIONAL_PERMISSIONS
    )

    permissions.difference_update(
        OWNER_ONLY_CAPABILITIES
    )

    return permissions


# ============================================================
# 10. REQUIRE A SINGLE PERMISSION
#
# Example:
#
# Depends(
#     require_vendor_permission(
#         "earnings.view"
#     )
# )
# ============================================================

def require_vendor_permission(
    permission: str,
) -> Callable:

    if permission not in ALL_PERMISSIONS:
        raise ValueError(
            "Unknown vendor permission: "
            f"{permission}"
        )

    async def dependency(
        vendor_context: dict[str, Any] = Depends(
            get_approved_vendor
        ),
    ) -> dict[str, Any]:

        permissions = (
            resolve_vendor_permissions(
                vendor_context
            )
        )

        if permission not in permissions:
            raise HTTPException(
                status_code=(
                    status.HTTP_403_FORBIDDEN
                ),
                detail=(
                    "You do not have permission "
                    "to perform this action."
                ),
            )

        return vendor_context

    return dependency


# ============================================================
# 11. REQUIRE MULTIPLE PERMISSIONS
#
# All specified permissions must be granted.
# ============================================================

def require_vendor_permissions(
    *required_permissions: str,
) -> Callable:

    if not required_permissions:
        raise ValueError(
            "At least one permission is required."
        )

    for permission in required_permissions:
        if permission not in ALL_PERMISSIONS:
            raise ValueError(
                "Unknown vendor permission: "
                f"{permission}"
            )

    required = frozenset(
        required_permissions
    )

    async def dependency(
        vendor_context: dict[str, Any] = Depends(
            get_approved_vendor
        ),
    ) -> dict[str, Any]:

        permissions = (
            resolve_vendor_permissions(
                vendor_context
            )
        )

        if not required.issubset(
            permissions
        ):
            raise HTTPException(
                status_code=(
                    status.HTTP_403_FORBIDDEN
                ),
                detail=(
                    "You do not have all required "
                    "permissions for this action."
                ),
            )

        return vendor_context

    return dependency


# ============================================================
# 12. CURRENT USER PERMISSION CONTEXT
#
# Used by Vendor Auth /me endpoint.
#
# Staff frontend can use the permission list to
# show/hide authorized navigation items.
#
# Backend permission checks remain mandatory.
# ============================================================

async def get_vendor_permission_context(
    vendor_context: dict[str, Any] = Depends(
        get_approved_vendor
    ),
) -> dict[str, Any]:

    permissions = (
        resolve_vendor_permissions(
            vendor_context
        )
    )

    membership = (
        vendor_context["membership"]
    )

    return {
        "vendor_id": str(
            vendor_context[
                "vendor_id"
            ]
        ),

        "user_id": str(
            vendor_context[
                "user_id"
            ]
        ),

        "member_role": str(
            membership.get(
                "member_role"
            ) or ""
        ).strip().lower(),

        "permission_mode": str(
            membership.get(
                "permission_mode"
            ) or ""
        ).strip().lower(),

        "permissions": sorted(
            permissions
        ),
    }
