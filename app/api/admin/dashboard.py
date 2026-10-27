from fastapi import APIRouter, Depends, HTTPException

from app.core.security import get_current_admin
from app.core.supabase import supabase
import logging

logger = logging.getLogger(__name__)
router = APIRouter(
    prefix="/admin/dashboard",
    tags=["Admin Dashboard"],
    dependencies=[Depends(get_current_admin)],
)


def count_rows(table_name: str, filters: dict | None = None) -> int:
    query = (
        supabase
        .table(table_name)
        .select("id", count="exact", head=True)
    )

    for column, value in (filters or {}).items():
        query = query.eq(column, value)

    return query.execute().count or 0


@router.get("/summary")
def get_dashboard_summary():
    try:
        return {
            "total_customers": count_rows(
                "profiles", {"role": "customer"}
            ),
            "total_vendors": count_rows("vendors"),
            "pending_vendors": count_rows(
                "vendors", {"status": "pending"}
            ),
            "total_products": count_rows("products"),
            "pending_products": count_rows(
                "products", {"status": "pending"}
            ),
            "total_orders": count_rows("orders"),
        }
    except Exception as exc:
        logger.exception("Failed to load dashboard statistics")
        raise HTTPException(
            status_code=500,
            detail="Unable to load dashboard statistics",
        ) from exc
