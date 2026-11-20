from datetime import date, timedelta
import logging

from fastapi import APIRouter, Depends, HTTPException, Query

from app.core.security import get_current_admin
from app.core.supabase import supabase


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
    date_from: date | None = None,
    date_to: date | None = None,
):
    if date_from and date_to and date_from > date_to:
        raise HTTPException(
            status_code=400,
            detail="The start date must be on or before the end date.",
        )

    try:
        query = supabase.table(table_name).select("*", count="exact")

        if status:
            query = query.eq("status", status)

        if date_from:
            query = query.gte("created_at", date_from.isoformat())

        if date_to:
            query = query.lt(
                "created_at",
                (date_to + timedelta(days=1)).isoformat(),
            )

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


@router.get("/summary")
def get_finance_summary(
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
):
    if date_from and date_to and date_from > date_to:
        raise HTTPException(
            status_code=400,
            detail="The start date must be on or before the end date.",
        )

    try:
        result = supabase.rpc(
            "admin_finance_summary",
            {
                "p_date_from": (
                    date_from.isoformat()
                    if date_from
                    else None
                ),
                "p_date_to": (
                    date_to.isoformat()
                    if date_to
                    else None
                ),
            },
        ).execute()
    except Exception as exc:
        logger.exception("Failed to retrieve admin finance summary")
        raise HTTPException(
            status_code=500,
            detail=(
                "Unable to retrieve finance summary. "
                "Run the Supabase finance summary function query."
            ),
        ) from exc

    if not isinstance(result.data, dict):
        raise HTTPException(
            status_code=500,
            detail="The Supabase finance summary returned an invalid response.",
        )

    return result.data


@router.get("/payments")
def list_payments(
    status: str | None = None,
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    return list_table_records(
        "payments",
        limit,
        offset,
        status,
        date_from,
        date_to,
    )


@router.get("/refunds")
def list_refunds(
    status: str | None = None,
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    return list_table_records(
        "refunds",
        limit,
        offset,
        status,
        date_from,
        date_to,
    )


@router.get("/vendor-ledger")
def list_vendor_ledger_entries(
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    return list_table_records(
        "vendor_ledger_entries",
        limit,
        offset,
        date_from=date_from,
        date_to=date_to,
    )


@router.get("/vendor-payouts")
def list_vendor_payouts(
    status: str | None = None,
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    return list_table_records(
        "vendor_payouts",
        limit,
        offset,
        status,
        date_from,
        date_to,
    )
