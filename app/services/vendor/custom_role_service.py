
"""
AUMVEDA Vendor Backend
Custom Role Management Service

Features:
- List vendor custom roles
- Get individual custom role
- Create custom role
- Update custom role atomically
- Activate / deactivate custom role
- Aggregate assigned permissions
- Enforce vendor isolation
- Validate operational permissions
- Log database failures safely

All role-management routes must be protected
by the get_vendor_owner dependency.

Supabase service-role credentials must remain
server-side only.
"""

import logging

from fastapi import HTTPException, status

from app.core.supabase import supabase_admin

from app.dependencies.vendor_permissions import (
    OPERATIONAL_PERMISSIONS,
)


logger = logging.getLogger(
    "aumveda.vendor.custom_roles"
)


# ============================================================
# PERMISSION CONFIGURATION
# ============================================================

ALLOWED_PERMISSIONS = frozenset(
    OPERATIONAL_PERMISSIONS
)


# ============================================================
# DATABASE ERROR HELPERS
# ============================================================

def _database_error():
    return HTTPException(
        status_code=(
            status.HTTP_503_SERVICE_UNAVAILABLE
        ),
        detail=(
            "Unable to process vendor custom roles."
        ),
    )


def _role_not_found():
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Custom role not found.",
    )


def _log_database_error(
    operation: str,
    exc: Exception,
):
    """
    Log detailed errors on the backend only.

    Never expose database connection details
    or service credentials to API clients.
    """

    logger.error(
        "Custom role operation failed: %s",
        operation,
        exc_info=(
            type(exc),
            exc,
            exc.__traceback__,
        ),
    )


def _raise_database_exception(
    exc: Exception,
    operation: str = "database operation",
):
    """
    Convert known PostgreSQL errors into
    controlled API responses.
    """

    _log_database_error(
        operation,
        exc,
    )

    code = getattr(
        exc,
        "code",
        None,
    )

    if code is None:
        code = getattr(
            exc,
            "sqlstate",
            None,
        )

    if code == "23505":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "A role with this name already exists."
            ),
        )

    if code == "P0002":
        raise _role_not_found()

    if code == "22023":
        raise HTTPException(
            status_code=(
                status.HTTP_422_UNPROCESSABLE_ENTITY
            ),
            detail="Invalid role update request.",
        )

    raise _database_error()


# ============================================================
# INPUT VALIDATION
# ============================================================

def _normalize_role_name(
    value: str,
) -> str:
    if not isinstance(value, str):
        raise HTTPException(
            status_code=(
                status.HTTP_422_UNPROCESSABLE_ENTITY
            ),
            detail="Role name must be a string.",
        )

    name = " ".join(
        value.strip().split()
    )

    if (
        len(name) < 2
        or len(name) > 80
    ):
        raise HTTPException(
            status_code=(
                status.HTTP_422_UNPROCESSABLE_ENTITY
            ),
            detail=(
                "Role name must contain "
                "2 to 80 characters."
            ),
        )

    return name


def _normalize_description(
    value: str | None,
) -> str | None:
    if value is None:
        return None

    if not isinstance(value, str):
        raise HTTPException(
            status_code=(
                status.HTTP_422_UNPROCESSABLE_ENTITY
            ),
            detail="Invalid role description.",
        )

    description = value.strip()

    if len(description) > 500:
        raise HTTPException(
            status_code=(
                status.HTTP_422_UNPROCESSABLE_ENTITY
            ),
            detail=(
                "Description must not exceed "
                "500 characters."
            ),
        )

    return description or None


def _validate_permissions(
    values: list[str],
) -> list[str]:
    if not isinstance(values, list):
        raise HTTPException(
            status_code=(
                status.HTTP_422_UNPROCESSABLE_ENTITY
            ),
            detail=(
                "Permissions must be provided as a list."
            ),
        )

    if any(
        not isinstance(item, str)
        for item in values
    ):
        raise HTTPException(
            status_code=(
                status.HTTP_422_UNPROCESSABLE_ENTITY
            ),
            detail=(
                "Invalid permission value."
            ),
        )

    permissions = sorted(
        set(values)
    )

    if not permissions:
        raise HTTPException(
            status_code=(
                status.HTTP_422_UNPROCESSABLE_ENTITY
            ),
            detail=(
                "Select at least one permission."
            ),
        )

    invalid = (
        set(permissions)
        - ALLOWED_PERMISSIONS
    )

    if invalid:
        raise HTTPException(
            status_code=(
                status.HTTP_422_UNPROCESSABLE_ENTITY
            ),
            detail=(
                "Invalid role permissions."
            ),
        )

    return permissions


# ============================================================
# PERMISSION AGGREGATION HELPER
# ============================================================

def _load_permissions_for_roles(
    vendor_id: str,
    role_ids: list[str],
) -> dict[str, list[str]]:
    """
    Load permission assignments belonging to
    the authenticated vendor.

    Returns:
    {
        "role-uuid": ["products.view", ...]
    }

    The response always contains an entry
    for each requested role.
    """

    role_ids = list(dict.fromkeys(
        str(role_id)
        for role_id in role_ids
    ))

    permissions_by_role = {
        role_id: []
        for role_id in role_ids
    }

    if not role_ids:
        return permissions_by_role

    try:
        response = (
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
                role_ids,
            )
            .execute()
        )

        rows = response.data or []

        if not isinstance(rows, list):
            raise RuntimeError(
                "Invalid permission query response."
            )

        for record in rows:
            role_id = str(
                record.get("role_id") or ""
            )

            permission = record.get(
                "permission_key"
            )

            if (
                role_id in permissions_by_role
                and permission in ALLOWED_PERMISSIONS
            ):
                permissions_by_role[
                    role_id
                ].append(permission)

        for role_id in role_ids:
            permissions_by_role[
                role_id
            ] = sorted(
                set(
                    permissions_by_role[
                        role_id
                    ]
                )
            )

        return permissions_by_role

    except Exception as exc:
        _raise_database_exception(
            exc,
            "load custom role permissions",
        )


# ============================================================
# LIST CUSTOM ROLES
#
# GET /api/v1/vendor/team/roles
#
# FIX:
# Use SELECT * instead of explicitly selecting
# possibly missing columns such as updated_at.
#
# The same selection strategy is already used
# by the working role-detail endpoint.
# ============================================================

def list_vendor_custom_roles(
    vendor_id: str,
) -> dict:
    try:
        roles_response = (
            supabase_admin
            .table(
                "vendor_custom_roles"
            )
            .select("*")
            .eq(
                "vendor_id",
                vendor_id,
            )
            .order(
                "created_at",
                desc=True,
            )
            .execute()
        )

        roles = (
            roles_response.data or []
        )

        if not isinstance(roles, list):
            raise RuntimeError(
                "Invalid custom role list response."
            )

    except Exception as exc:
        _raise_database_exception(
            exc,
            "list vendor custom roles",
        )

    if not roles:
        return {
            "roles": [],
            "total": 0,
        }

    role_ids = [
        str(role["id"])
        for role in roles
    ]

    permissions_by_role = (
        _load_permissions_for_roles(
            vendor_id=vendor_id,
            role_ids=role_ids,
        )
    )

    result = []

    for role in roles:
        role_data = dict(role)

        role_id = str(
            role_data["id"]
        )

        role_data["permissions"] = (
            permissions_by_role.get(
                role_id,
                [],
            )
        )

        result.append(
            role_data
        )

    return {
        "roles": result,
        "total": len(result),
    }


# ============================================================
# GET CUSTOM ROLE DETAIL
#
# GET /api/v1/vendor/team/roles/{role_id}
# ============================================================

def get_vendor_custom_role(
    vendor_id: str,
    role_id: str,
) -> dict:
    try:
        role_response = (
            supabase_admin
            .table(
                "vendor_custom_roles"
            )
            .select("*")
            .eq(
                "vendor_id",
                vendor_id,
            )
            .eq(
                "id",
                role_id,
            )
            .limit(1)
            .execute()
        )

        roles = (
            role_response.data or []
        )

    except Exception as exc:
        _raise_database_exception(
            exc,
            "get vendor custom role",
        )

    if not roles:
        raise _role_not_found()

    role = dict(
        roles[0]
    )

    permission_map = (
        _load_permissions_for_roles(
            vendor_id=vendor_id,
            role_ids=[
                str(role["id"])
            ],
        )
    )

    role["permissions"] = (
        permission_map.get(
            str(role["id"]),
            [],
        )
    )

    return role


# ============================================================
# CREATE CUSTOM ROLE
#
# POST /api/v1/vendor/team/roles
#
# Role starts inactive.
# Permissions are saved.
# Role becomes active after successful setup.
#
# This retains the original provisioning flow.
# ============================================================

def create_vendor_custom_role(
    vendor_id: str,
    created_by: str,
    payload: dict,
) -> dict:
    role_name = (
        _normalize_role_name(
            payload["role_name"]
        )
    )

    description = (
        _normalize_description(
            payload.get(
                "description"
            )
        )
    )

    permissions = (
        _validate_permissions(
            payload["permissions"]
        )
    )

    role_id = None

    try:
        role_response = (
            supabase_admin
            .table(
                "vendor_custom_roles"
            )
            .insert({
                "vendor_id": vendor_id,
                "role_name": role_name,
                "description": description,
                "is_active": False,
                "created_by": created_by,
            })
            .execute()
        )

        rows = (
            role_response.data or []
        )

        if not rows:
            raise RuntimeError(
                "Role creation returned no record."
            )

        role_id = str(
            rows[0]["id"]
        )

        permission_rows = [
            {
                "vendor_id": vendor_id,
                "role_id": role_id,
                "permission_key": permission,
            }
            for permission in permissions
        ]

        (
            supabase_admin
            .table(
                "vendor_role_permissions"
            )
            .insert(
                permission_rows
            )
            .execute()
        )

        activation_response = (
            supabase_admin
            .table(
                "vendor_custom_roles"
            )
            .update({
                "is_active": True,
            })
            .eq(
                "vendor_id",
                vendor_id,
            )
            .eq(
                "id",
                role_id,
            )
            .eq(
                "is_active",
                False,
            )
            .execute()
        )

        if not (
            activation_response.data or []
        ):
            raise RuntimeError(
                "Role activation failed."
            )

    except Exception as exc:
        _log_database_error(
            "create vendor custom role",
            exc,
        )

        # Clean up an incomplete inactive role.
        # Never delete an active role.

        if role_id is not None:
            try:
                (
                    supabase_admin
                    .table(
                        "vendor_custom_roles"
                    )
                    .delete()
                    .eq(
                        "vendor_id",
                        vendor_id,
                    )
                    .eq(
                        "id",
                        role_id,
                    )
                    .eq(
                        "is_active",
                        False,
                    )
                    .execute()
                )

            except Exception:
                logger.exception(
                    "Failed to clean up incomplete "
                    "custom role."
                )

        _raise_database_exception(
            exc,
            "create vendor custom role",
        )

    # Return the created role only after
    # successful provisioning.
    return get_vendor_custom_role(
        vendor_id=vendor_id,
        role_id=role_id,
    )


# ============================================================
# UPDATE CUSTOM ROLE
#
# PATCH /api/v1/vendor/team/roles/{role_id}
#
# Uses PostgreSQL RPC:
# update_vendor_custom_role_atomic
#
# Role details and permission changes happen
# inside one PostgreSQL transaction.
# ============================================================

def update_vendor_custom_role(
    vendor_id: str,
    role_id: str,
    payload: dict,
) -> dict:
    existing_role = (
        get_vendor_custom_role(
            vendor_id=vendor_id,
            role_id=role_id,
        )
    )

    if (
        "role_name" in payload
        and payload["role_name"] is None
    ):
        raise HTTPException(
            status_code=(
                status.HTTP_422_UNPROCESSABLE_ENTITY
            ),
            detail=(
                "Role name cannot be null."
            ),
        )

    if (
        "permissions" in payload
        and payload["permissions"] is None
    ):
        raise HTTPException(
            status_code=(
                status.HTTP_422_UNPROCESSABLE_ENTITY
            ),
            detail=(
                "Permissions cannot be null."
            ),
        )

    role_name = (
        _normalize_role_name(
            payload.get(
                "role_name",
                existing_role["role_name"],
            )
        )
    )

    description = (
        _normalize_description(
            payload.get(
                "description",
                existing_role.get(
                    "description"
                ),
            )
        )
    )

    permissions = (
        _validate_permissions(
            payload.get(
                "permissions",
                existing_role["permissions"],
            )
        )
    )

    try:
        (
            supabase_admin
            .rpc(
                "update_vendor_custom_role_atomic",
                {
                    "p_vendor_id": vendor_id,
                    "p_role_id": role_id,
                    "p_role_name": role_name,
                    "p_description": description,
                    "p_permissions": permissions,
                },
            )
            .execute()
        )

    except Exception as exc:
        _raise_database_exception(
            exc,
            "update vendor custom role",
        )

    return get_vendor_custom_role(
        vendor_id=vendor_id,
        role_id=role_id,
    )


# ============================================================
# ACTIVATE / DEACTIVATE ROLE
#
# PATCH /api/v1/vendor/team/roles/{role_id}/status
# ============================================================

def update_vendor_custom_role_status(
    vendor_id: str,
    role_id: str,
    is_active: bool,
) -> dict:
    existing_role = (
        get_vendor_custom_role(
            vendor_id=vendor_id,
            role_id=role_id,
        )
    )

    if (
        existing_role.get("is_active")
        == is_active
    ):
        return existing_role

    if (
        is_active
        and not existing_role.get(
            "permissions"
        )
    ):
        raise HTTPException(
            status_code=(
                status.HTTP_422_UNPROCESSABLE_ENTITY
            ),
            detail=(
                "A role must have at least one "
                "permission before activation."
            ),
        )

    try:
        response = (
            supabase_admin
            .table(
                "vendor_custom_roles"
            )
            .update({
                "is_active": is_active,
            })
            .eq(
                "vendor_id",
                vendor_id,
            )
            .eq(
                "id",
                role_id,
            )
            .execute()
        )

        rows = (
            response.data or []
        )

    except Exception as exc:
        _raise_database_exception(
            exc,
            "update custom role status",
        )

    if not rows:
        raise _role_not_found()

    return get_vendor_custom_role(
        vendor_id=vendor_id,
        role_id=role_id,
    )
