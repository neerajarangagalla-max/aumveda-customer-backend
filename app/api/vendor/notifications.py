"""
AUMVEDA Vendor Backend
Vendor Notifications API

API endpoints:
GET    /api/v1/vendor/notifications
GET    /api/v1/vendor/notifications/unread-count
PATCH  /api/v1/vendor/notifications/read-all
PATCH  /api/v1/vendor/notifications/{notification_id}/read

Access:
- Approved Vendor Owners
- Active authorized vendor employees
- Personal notifications only
"""

from typing import Literal
from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    Query,
)

from app.dependencies.vendor import (
    get_approved_vendor,
)

from app.services.vendor.notification_service import (
    list_vendor_notifications,
    get_unread_notification_count,
    mark_notification_as_read,
    mark_all_notifications_as_read,
)


router = APIRouter(
    prefix="/notifications",
    tags=["Vendor Notifications"],
)


# ============================================================
# AUTHENTICATED RECIPIENT
# ============================================================

def _get_recipient_context(
    vendor_context: dict,
):
    membership = vendor_context["membership"]

    member_role = str(
        membership.get("member_role") or ""
    ).strip().lower()

    return {
        "user_id": str(
            vendor_context["user_id"]
        ),
        "is_owner": (
            member_role == "owner"
        ),
    }


# ============================================================
# LIST NOTIFICATIONS
# ============================================================

@router.get("")
def vendor_notifications(
    read_status: Literal[
        "all",
        "read",
        "unread",
    ] = Query("all"),

    notification_type: str | None = Query(
        None,
        min_length=1,
        max_length=100,
    ),

    limit: int = Query(
        20,
        ge=1,
        le=100,
    ),

    offset: int = Query(
        0,
        ge=0,
    ),

    vendor_context=Depends(
        get_approved_vendor
    ),
):
    recipient = _get_recipient_context(
        vendor_context
    )

    return list_vendor_notifications(
        **recipient,
        read_status=read_status,
        notification_type=notification_type,
        limit=limit,
        offset=offset,
    )


# ============================================================
# UNREAD COUNT
# ============================================================

@router.get("/unread-count")
def vendor_notification_unread_count(
    vendor_context=Depends(
        get_approved_vendor
    ),
):
    recipient = _get_recipient_context(
        vendor_context
    )

    return get_unread_notification_count(
        **recipient,
    )


# ============================================================
# MARK ALL AS READ
# ============================================================

@router.patch("/read-all")
def vendor_notifications_read_all(
    vendor_context=Depends(
        get_approved_vendor
    ),
):
    recipient = _get_recipient_context(
        vendor_context
    )

    return mark_all_notifications_as_read(
        **recipient,
    )


# ============================================================
# MARK SINGLE NOTIFICATION AS READ
# ============================================================

@router.patch("/{notification_id}/read")
def vendor_notification_read(
    notification_id: UUID,

    vendor_context=Depends(
        get_approved_vendor
    ),
):
    recipient = _get_recipient_context(
        vendor_context
    )

    return mark_notification_as_read(
        **recipient,
        notification_id=str(
            notification_id
        ),
    )