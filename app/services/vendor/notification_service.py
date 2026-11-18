"""
AUMVEDA Vendor Backend
Vendor Notification Service

Features:
- Personal notification listing
- Pagination and filtering
- Unread notification count
- Mark individual notification as read
- Mark all notifications as read

Security:
- Recipient-level data isolation
- Vendor role restriction
- Owner-only password assistance notifications
- No customer or admin notification access
"""

import logging

from fastapi import HTTPException, status

from app.core.supabase import supabase_admin


logger = logging.getLogger(
    "aumveda.vendor.notifications"
)

TABLE_NAME = "notifications"

NOTIFICATION_FIELDS = (
    "id,"
    "title,"
    "message,"
    "notification_type,"
    "reference_type,"
    "reference_id,"
    "is_read,"
    "created_at"
)

OWNER_ONLY_NOTIFICATION_TYPE = (
    "employee_password_request"
)


def _recipient_scope(
    query,
    user_id: str,
    is_owner: bool,
):
    """
    Restrict every operation to the
    authenticated vendor recipient.
    """

    query = (
        query
        .eq("recipient_id", user_id)
        .eq("recipient_role", "vendor")
    )

    if not is_owner:
        query = query.neq(
            "notification_type",
            OWNER_ONLY_NOTIFICATION_TYPE,
        )

    return query


def _database_error(
    operation: str,
    exc: Exception,
):
    logger.error(
        "Vendor notification operation failed: %s. "
        "exception_type=%s",
        operation,
        type(exc).__name__,
    )

    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="Notification service temporarily unavailable.",
    )


# ============================================================
# UNREAD NOTIFICATION COUNT
# ============================================================

def get_unread_notification_count(
    user_id: str,
    is_owner: bool,
):
    try:
        query = (
            supabase_admin
            .table(TABLE_NAME)
            .select("id", count="exact")
        )

        query = _recipient_scope(
            query,
            user_id,
            is_owner,
        )

        response = (
            query
            .eq("is_read", False)
            .limit(1)
            .execute()
        )

        return {
            "status": "success",
            "unread_count": int(
                response.count or 0
            ),
        }

    except Exception as exc:
        raise _database_error(
            "unread_count",
            exc,
        ) from exc


# ============================================================
# NOTIFICATION LISTING
# ============================================================

def list_vendor_notifications(
    user_id: str,
    is_owner: bool,
    read_status: str = "all",
    notification_type: str | None = None,
    limit: int = 20,
    offset: int = 0,
):
    try:
        query = (
            supabase_admin
            .table(TABLE_NAME)
            .select(
                NOTIFICATION_FIELDS,
                count="exact",
            )
        )

        query = _recipient_scope(
            query,
            user_id,
            is_owner,
        )

        if read_status == "unread":
            query = query.eq(
                "is_read",
                False,
            )

        elif read_status == "read":
            query = query.eq(
                "is_read",
                True,
            )

        if notification_type:
            query = query.eq(
                "notification_type",
                notification_type,
            )

        response = (
            query
            .order(
                "created_at",
                desc=True,
            )
            .order(
                "id",
                desc=True,
            )
            .range(
                offset,
                offset + limit - 1,
            )
            .execute()
        )

        notifications = response.data or []

        total = int(
            response.count or 0
        )

        unread_result = (
            get_unread_notification_count(
                user_id=user_id,
                is_owner=is_owner,
            )
        )

        return {
            "status": "success",
            "data": notifications,
            "count": len(notifications),
            "total": total,
            "unread_count": unread_result[
                "unread_count"
            ],
            "limit": limit,
            "offset": offset,
            "has_more": (
                offset + len(notifications)
                < total
            ),
        }

    except HTTPException:
        raise

    except Exception as exc:
        raise _database_error(
            "list_notifications",
            exc,
        ) from exc


# ============================================================
# MARK INDIVIDUAL NOTIFICATION AS READ
# ============================================================

def mark_notification_as_read(
    user_id: str,
    is_owner: bool,
    notification_id: str,
):
    try:
        query = (
            supabase_admin
            .table(TABLE_NAME)
            .update({
                "is_read": True,
            })
        )

        query = _recipient_scope(
            query,
            user_id,
            is_owner,
        )

        response = (
            query
            .eq(
                "id",
                notification_id,
            )
            .execute()
        )

        rows = response.data or []

        if not rows:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Notification not found.",
            )

        return {
            "status": "success",
            "message": (
                "Notification marked as read."
            ),
            "notification_id": notification_id,
            "is_read": True,
        }

    except HTTPException:
        raise

    except Exception as exc:
        raise _database_error(
            "mark_notification_read",
            exc,
        ) from exc


# ============================================================
# MARK ALL PERSONAL NOTIFICATIONS AS READ
# ============================================================

def mark_all_notifications_as_read(
    user_id: str,
    is_owner: bool,
):
    try:
        query = (
            supabase_admin
            .table(TABLE_NAME)
            .update({
                "is_read": True,
            })
        )

        query = _recipient_scope(
            query,
            user_id,
            is_owner,
        )

        (
            query
            .eq("is_read", False)
            .execute()
        )

        return {
            "status": "success",
            "message": (
                "All personal notifications "
                "marked as read."
            ),
        }

    except Exception as exc:
        raise _database_error(
            "mark_all_notifications_read",
            exc,
        ) from exc