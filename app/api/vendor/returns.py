from typing import Literal
from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    Query,
)

from app.dependencies.vendor_permissions import (
    require_vendor_permission,
)

from app.schemas.vendor.returns import (
    VendorReturnNotesRequest,
    VendorReturnPickupRequest,
    VendorReturnStatusUpdateRequest,
)

from app.services.vendor.returns_service import (
    list_vendor_returns,
    get_vendor_return,
    get_vendor_return_history,
    pack_vendor_replacement,
    schedule_vendor_return_pickup,
    update_vendor_return_status,
    request_vendor_refund,
    complete_vendor_exchange,
)


router = APIRouter(
    prefix="/returns",
    tags=["Vendor Returns & Exchanges"],
)


# ============================================================
# LIST RETURNS AND EXCHANGES
# ============================================================

@router.get("")
def vendor_returns(

    request_type: Literal[
        "return",
        "replacement",
    ] | None = None,

    status: Literal[
        "approved",
        "pickup_scheduled",
        "item_received",
        "replacement_processing",
        "refund_processing",
        "completed",
    ] | None = None,

    limit: int = Query(
        default=50,
        ge=1,
        le=100,
    ),

    offset: int = Query(
        default=0,
        ge=0,
    ),

    vendor_context=Depends(
        require_vendor_permission(
            "shipping.view"
        )
    ),

):

    return list_vendor_returns(

        vendor_id=str(
            vendor_context["vendor_id"]
        ),

        request_type=request_type,

        request_status=status,

        limit=limit,

        offset=offset,

    )


# ============================================================
# RETURN DETAILS
# ============================================================

@router.get("/{return_id}")
def vendor_return_details(

    return_id: UUID,

    vendor_context=Depends(
        require_vendor_permission(
            "shipping.view"
        )
    ),

):

    return get_vendor_return(

        vendor_id=str(
            vendor_context["vendor_id"]
        ),

        return_id=str(return_id),

    )


# ============================================================
# RETURN HISTORY
# ============================================================

@router.get("/{return_id}/history")
def vendor_return_history(

    return_id: UUID,

    vendor_context=Depends(
        require_vendor_permission(
            "shipping.view"
        )
    ),

):

    return get_vendor_return_history(

        vendor_id=str(
            vendor_context["vendor_id"]
        ),

        return_id=str(return_id),

    )


# ============================================================
# PACK REPLACEMENT
# ============================================================

@router.post("/{return_id}/pack")
def vendor_pack_exchange(

    return_id: UUID,

    payload: VendorReturnNotesRequest,

    vendor_context=Depends(
        require_vendor_permission(
            "shipping.update"
        )
    ),

):

    return pack_vendor_replacement(

        vendor_id=str(
            vendor_context["vendor_id"]
        ),

        return_id=str(return_id),

        notes=payload.notes,

    )


# ============================================================
# SCHEDULE PICKUP
# ============================================================

@router.post("/{return_id}/schedule-pickup")
def vendor_schedule_pickup(

    return_id: UUID,

    payload: VendorReturnPickupRequest,

    vendor_context=Depends(
        require_vendor_permission(
            "shipping.update"
        )
    ),

):

    return schedule_vendor_return_pickup(

        vendor_id=str(
            vendor_context["vendor_id"]
        ),

        return_id=str(return_id),

        payload=payload.model_dump(
            mode="json"
        ),

    )


# ============================================================
# UPDATE RETURN FULFILLMENT STATUS
# ============================================================

@router.patch("/{return_id}/status")
def vendor_return_update_status(

    return_id: UUID,

    payload: VendorReturnStatusUpdateRequest,

    vendor_context=Depends(
        require_vendor_permission(
            "shipping.update"
        )
    ),

):

    return update_vendor_return_status(

        vendor_id=str(
            vendor_context["vendor_id"]
        ),

        return_id=str(return_id),

        new_status=payload.status,

        notes=payload.notes,

    )


# ============================================================
# REQUEST REFUND PROCESSING
# ============================================================

@router.post("/{return_id}/request-refund")
def vendor_return_request_refund(

    return_id: UUID,

    payload: VendorReturnNotesRequest,

    vendor_context=Depends(
        require_vendor_permission(
            "shipping.update"
        )
    ),

):

    return request_vendor_refund(

        vendor_id=str(
            vendor_context["vendor_id"]
        ),

        return_id=str(return_id),

        notes=payload.notes,

    )


# ============================================================
# COMPLETE EXCHANGE
# ============================================================

@router.post("/{return_id}/complete-exchange")
def vendor_return_complete_exchange(

    return_id: UUID,

    payload: VendorReturnNotesRequest,

    vendor_context=Depends(
        require_vendor_permission(
            "shipping.update"
        )
    ),

):

    return complete_vendor_exchange(

        vendor_id=str(
            vendor_context["vendor_id"]
        ),

        return_id=str(return_id),

        notes=payload.notes,

    )