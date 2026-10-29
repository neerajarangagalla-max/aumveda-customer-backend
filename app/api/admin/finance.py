from fastapi import APIRouter, Depends, HTTPException, Query

from app.core.security import get_current_admin
from app.core.supabase import supabase
import logging
logger = logging.getLogger(__name__)
router = APIRouter(
    prefix="/admin/finance",
    tags=["Admin Finance"],
    dependencies=[Depends(get_current_admin)],
)


def list_table_records(
    table_name: str,
    limit: int,
    offset: int,
    status: str | None = None,
):
    try:
        query = supabase.table(table_name).select("*", count="exact")

        if status:
            query = query.eq("status", status)

        result = query.range(offset, offset + limit - 1).execute()

        return {
            "items": result.data or [],
            "total": result.count or 0,
            "limit": limit,
            "offset": offset,
        }
    except Exception as exc:
        logger.exception("Failed to retrieve finance records from %s", table_name)
    raise HTTPException(
        status_code=500,
        detail=f"Unable to retrieve {table_name} records",
    ) from exc


@router.get("/payments")
def list_payments(
    status: str | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    return list_table_records("payments", limit, offset, status)


@router.get("/refunds")
def list_refunds(
    status: str | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    return list_table_records("refunds", limit, offset, status)


@router.get("/vendor-ledger")
def list_vendor_ledger_entries(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    return list_table_records("vendor_ledger_entries", limit, offset)


@router.get("/vendor-payouts")
def list_vendor_payouts(
    status: str | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    return list_table_records("vendor_payouts", limit, offset, status)
