from fastapi import APIRouter, Depends, HTTPException, Query

from app.core.security import get_current_admin
from app.core.supabase import supabase

router = APIRouter(
    prefix="/admin/reports",
    tags=["Admin Reports"],
    dependencies=[Depends(get_current_admin)],
)


def count_rows(table_name: str, filters: dict | None = None) -> int:
    query = supabase.table(table_name).select("id", count="exact", head=True)

    for column, value in (filters or {}).items():
        query = query.eq(column, value)

    result = query.execute()
    return result.count or 0


@router.get("/overview")
def get_reports_overview():
    try:
        return {
            "customers": count_rows("profiles", {"role": "customer"}),
            "vendors": count_rows("vendors"),
            "approved_vendors": count_rows(
                "vendors", {"status": "approved"}
            ),
            "pending_vendors": count_rows(
                "vendors", {"status": "pending"}
            ),
            "products": count_rows("products"),
            "active_products": count_rows(
                "products", {"status": "active"}
            ),
            "pending_products": count_rows(
                "products", {"status": "pending"}
            ),
            "orders": count_rows("orders"),
        }
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=(
                "Unable to generate report overview; "
                "verify the database schema"
            ),
        ) from exc


@router.get("/orders")
def get_orders_report(
    status: str | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    try:
        query = supabase.table("orders").select("*", count="exact")

        if status:
            query = query.eq("status", status)

        result = (
            query.order("created_at", desc=True)
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
            detail="Unable to generate orders report; verify order columns",
        ) from exc


@router.get("/products")
def get_products_report(
    status: str | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    try:
        query = supabase.table("products").select("*", count="exact")

        if status:
            query = query.eq("status", status)

        result = (
            query.order("created_at", desc=True)
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
            detail="Unable to generate products report; verify product columns",
        ) from exc
