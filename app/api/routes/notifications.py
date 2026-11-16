import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.routes.orders import get_current_customer_id
from app.core.supabase import supabase

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/notifications",
    tags=["Customer Notifications"],
)


@router.get("")
def list_customer_notifications(
    limit: int = Query(default=10, ge=1, le=50),
    offset: int = Query(default=0, ge=0),
    customer_id: str = Depends(get_current_customer_id),
):
    try:
        notifications_result = (
            supabase.table("notifications")
            .select(
                "id, title, message, notification_type, reference_type, "
                "reference_id, is_read, created_at",
                count="exact",
            )
            .eq("recipient_id", str(customer_id))
            .eq("recipient_role", "customer")
            .order("created_at", desc=True)
            .range(offset, offset + limit - 1)
            .execute()
        )
        unread_result = (
            supabase.table("notifications")
            .select("id", count="exact")
            .eq("recipient_id", str(customer_id))
            .eq("recipient_role", "customer")
            .eq("is_read", False)
            .limit(1)
            .execute()
        )

        return {
            "items": notifications_result.data or [],
            "total": notifications_result.count or 0,
            "unread_count": unread_result.count or 0,
            "limit": limit,
            "offset": offset,
        }

    except Exception as exc:
        logger.exception(
            "Failed to retrieve customer notifications for %s",
            customer_id,
        )
        raise HTTPException(
            status_code=500,
            detail="Unable to retrieve notifications.",
        ) from exc


@router.patch("/read-all")
def mark_all_customer_notifications_read(
    customer_id: str = Depends(get_current_customer_id),
):
    try:
        result = (
            supabase.table("notifications")
            .update({"is_read": True})
            .eq("recipient_id", str(customer_id))
            .eq("recipient_role", "customer")
            .eq("is_read", False)
            .select("id")
            .execute()
        )

        return {
            "message": "All notifications marked as read.",
            "updated_count": len(result.data or []),
        }

    except Exception as exc:
        logger.exception(
            "Failed to mark customer notifications read for %s",
            customer_id,
        )
        raise HTTPException(
            status_code=500,
            detail="Unable to mark notifications as read.",
        ) from exc


@router.patch("/{notification_id}/read")
def mark_customer_notification_read(
    notification_id: UUID,
    customer_id: str = Depends(get_current_customer_id),
):
    try:
        result = (
            supabase.table("notifications")
            .update({"is_read": True})
            .eq("id", str(notification_id))
            .eq("recipient_id", str(customer_id))
            .eq("recipient_role", "customer")
            .select("id, is_read")
            .execute()
        )

        if not result.data:
            raise HTTPException(
                status_code=404,
                detail="Notification not found.",
            )

        return {
            "message": "Notification marked as read.",
            "notification": result.data[0],
        }

    except HTTPException:
        raise

    except Exception as exc:
        logger.exception(
            "Failed to mark customer notification %s as read",
            notification_id,
        )
        raise HTTPException(
            status_code=500,
            detail="Unable to update notification.",
        ) from exc
