
from fastapi import (
    APIRouter,
    Depends,
    status,
)

from app.dependencies.vendor import (
    get_vendor_owner,
)

from app.schemas.vendor.custom_roles import (
    VendorCustomRoleCreateRequest,
    VendorCustomRoleUpdateRequest,
    VendorCustomRoleStatusRequest,
)

from app.services.vendor.custom_role_service import (
    create_vendor_custom_role,
    get_vendor_custom_role,
    list_vendor_custom_roles,
    update_vendor_custom_role,
    update_vendor_custom_role_status,
)


router = APIRouter(
    prefix="/team/roles",
    tags=["Vendor Custom Roles"],
)


# ============================================================
# LIST CUSTOM ROLES
# OWNER ONLY
# ============================================================

@router.get("")
def vendor_custom_roles(
    vendor_context=Depends(get_vendor_owner),
):
    return list_vendor_custom_roles(
        vendor_id=vendor_context["vendor_id"],
    )


# ============================================================
# CREATE CUSTOM ROLE
# OWNER ONLY
# ============================================================

@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
)
def vendor_create_custom_role(
    payload: VendorCustomRoleCreateRequest,
    vendor_context=Depends(get_vendor_owner),
):
    return create_vendor_custom_role(
        vendor_id=vendor_context["vendor_id"],
        created_by=vendor_context["user_id"],
        payload=payload.model_dump(),
    )


# ============================================================
# GET CUSTOM ROLE DETAIL
# OWNER ONLY
# ============================================================

@router.get("/{role_id}")
def vendor_custom_role_detail(
    role_id: str,
    vendor_context=Depends(get_vendor_owner),
):
    return get_vendor_custom_role(
        vendor_id=vendor_context["vendor_id"],
        role_id=role_id,
    )


# ============================================================
# EDIT CUSTOM ROLE
# OWNER ONLY
# ATOMIC DATABASE UPDATE
# ============================================================

@router.patch("/{role_id}")
def vendor_edit_custom_role(
    role_id: str,
    payload: VendorCustomRoleUpdateRequest,
    vendor_context=Depends(get_vendor_owner),
):
    return update_vendor_custom_role(
        vendor_id=vendor_context["vendor_id"],
        role_id=role_id,
        payload=payload.model_dump(
            exclude_unset=True,
        ),
    )


# ============================================================
# ACTIVATE / DEACTIVATE ROLE
# OWNER ONLY
# ============================================================

@router.patch("/{role_id}/status")
def vendor_change_custom_role_status(
    role_id: str,
    payload: VendorCustomRoleStatusRequest,
    vendor_context=Depends(get_vendor_owner),
):
    return update_vendor_custom_role_status(
        vendor_id=vendor_context["vendor_id"],
        role_id=role_id,
        is_active=payload.is_active,
    )
