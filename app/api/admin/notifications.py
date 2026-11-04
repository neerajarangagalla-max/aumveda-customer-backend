
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query

from app.core.security import get_current_admin
from app.core.supabase import supabase


router = APIRouter(
    prefix="/admin/notifications",
    tags=["Admin Notifications"],
    dependencies=[Depends(get_current_admin)],
)


def get_admin_id(current_admin):
    return str(current_admin.id)


@router.get("")
def list_notifications(
    current_admin=Depends(get_current_admin),
    is_read: bool | None = Query(default=None),
    notification_type: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    try:
        admin_id = get_admin_id(current_admin)

        query = (
            supabase.table("notifications")
            .select("*", count="exact")
            .eq("recipient_id", admin_id)
            .eq("recipient_role", "admin")
        )

        if is_read is not None:
            query = query.eq("is_read", is_read)

        if notification_type:
            query = query.eq("notification_type", notification_type)

        result = (
            query
            .order("created_at", desc=True)
            .range(offset, offset + limit - 1)
            .execute()
        )

        return {
            "items": result.data or [],
            "total": result.count or 0,
            "limit": limit,
            "offset": offset,
        }

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="Unable to retrieve notifications",
        ) from exc


@router.get("/unread-count")
def get_unread_count(
    current_admin=Depends(get_current_admin),
):
    try:
        admin_id = get_admin_id(current_admin)

        result = (
            supabase.table("notifications")
            .select("id", count="exact")
            .eq("recipient_id", admin_id)
            .eq("recipient_role", "admin")
            .eq("is_read", False)
            .execute()
        )

        return {
            "unread_count": result.count or 0
        }

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="Unable to retrieve unread notification count",
        ) from exc


@router.patch("/{notification_id}/read")
def mark_notification_read(
    notification_id: UUID,
    current_admin=Depends(get_current_admin),
):
    try:
        admin_id = get_admin_id(current_admin)

        result = (
            supabase.table("notifications")
            .update({"is_read": True})
            .eq("id", str(notification_id))
            .eq("recipient_id", admin_id)
            .eq("recipient_role", "admin")
            .select("id, is_read")
            .execute()
        )

        if not result.data:
            raise HTTPException(
                status_code=404,
                detail="Notification not found",
            )

        return {
            "message": "Notification marked as read",
            "notification": result.data[0],
        }

    except HTTPException:
        raise

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="Unable to update notification",
        ) from exc


@router.patch("/read-all")
def mark_all_notifications_read(
    current_admin=Depends(get_current_admin),
):
    try:
        admin_id = get_admin_id(current_admin)

        result = (
            supabase.table("notifications")
            .update({"is_read": True})
            .eq("recipient_id", admin_id)
            .eq("recipient_role", "admin")
            .eq("is_read", False)
            .execute()
        )

        return {
            "message": "All notifications marked as read",
            "updated_count": len(result.data or []),
        }

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="Unable to mark all notifications as read",
        ) from exc
