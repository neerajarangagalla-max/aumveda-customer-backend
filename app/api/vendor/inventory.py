
from fastapi import APIRouter, Depends

from app.dependencies.vendor_permissions import (
    require_vendor_permission,
)

from app.schemas.vendor.inventory import (
    VendorInventoryUpdateRequest,
)

from app.services.vendor.inventory_service import (
    get_inventory_history,
    get_inventory_item,
    list_low_stock_inventory,
    list_vendor_inventory,
    update_inventory_item,
)


router = APIRouter(
    prefix="/inventory",
    tags=["Vendor Inventory"],
)


# ============================================================
# INVENTORY LIST
# Permission: inventory.view
# ============================================================

@router.get("")
def vendor_inventory(
    vendor_context=Depends(
        require_vendor_permission("inventory.view")
    ),
):
    return list_vendor_inventory(
        vendor_context["vendor_id"]
    )


# ============================================================
# LOW STOCK
# Permission: inventory.view
# ============================================================

@router.get("/low-stock")
def vendor_low_stock_inventory(
    vendor_context=Depends(
        require_vendor_permission("inventory.view")
    ),
):
    return list_low_stock_inventory(
        vendor_context["vendor_id"]
    )


# ============================================================
# INVENTORY HISTORY
# Permission: inventory.view
# ============================================================

@router.get("/{variant_id}/history")
def vendor_inventory_history(
    variant_id: str,
    vendor_context=Depends(
        require_vendor_permission("inventory.view")
    ),
):
    return get_inventory_history(
        vendor_id=vendor_context["vendor_id"],
        variant_id=variant_id,
    )


# ============================================================
# INVENTORY DETAIL
# Permission: inventory.view
# ============================================================

@router.get("/{variant_id}")
def vendor_inventory_detail(
    variant_id: str,
    vendor_context=Depends(
        require_vendor_permission("inventory.view")
    ),
):
    return get_inventory_item(
        vendor_id=vendor_context["vendor_id"],
        variant_id=variant_id,
    )


# ============================================================
# UPDATE INVENTORY
# Permission: inventory.update
# ============================================================

@router.patch("/{variant_id}")
def vendor_update_inventory(
    variant_id: str,
    payload: VendorInventoryUpdateRequest,
    vendor_context=Depends(
        require_vendor_permission("inventory.update")
    ),
):
    return update_inventory_item(
        vendor_id=vendor_context["vendor_id"],
        variant_id=variant_id,
        payload=payload.model_dump(),
    )
