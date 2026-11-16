import logging

from app.core.supabase import supabase

logger = logging.getLogger(__name__)


def create_customer_notification(
    *,
    customer_id: str | None,
    title: str,
    message: str,
    notification_type: str,
    reference_type: str,
    reference_id: str | None,
) -> None:
    if not customer_id or not reference_id:
        logger.error(
            "Skipped customer notification because its recipient or "
            "reference is missing."
        )
        return

    try:
        (
            supabase.table("notifications")
            .insert({
                "recipient_id": str(customer_id),
                "recipient_role": "customer",
                "title": title,
                "message": message,
                "notification_type": notification_type,
                "reference_type": reference_type,
                "reference_id": str(reference_id),
                "is_read": False,
            })
            .execute()
        )
    except Exception:
        logger.exception(
            "Failed to create customer notification %s for %s",
            notification_type,
            customer_id,
        )
