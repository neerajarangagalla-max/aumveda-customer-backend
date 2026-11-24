from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import logging
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, ValidationInfo, field_validator

from app.core.security import get_current_admin
from app.core.supabase import supabase
from app.services.vendor.earnings_service import (
    get_vendor_earnings_summary,
)
from app.services.vendor.payout_service import (
    list_vendor_payouts as list_vendor_payout_records,
)


logger = logging.getLogger(__name__)
FINANCE_READ_PAGE_SIZE = 500
FINANCE_LOOKUP_BATCH_SIZE = 100
router = APIRouter(
    prefix="/admin/finance",
    tags=["Admin Finance"],
    dependencies=[Depends(get_current_admin)],
)


class VendorPayoutCreate(BaseModel):
    vendor_id: UUID
    amount: Decimal = Field(
        gt=0,
        max_digits=14,
        decimal_places=2,
    )
    payment_reference: str = Field(
        min_length=1,
        max_length=255,
    )
    order_item_ids: list[UUID] = Field(
        min_length=1,
        max_length=100,
    )

    @field_validator("payment_reference")
    @classmethod
    def normalize_payment_reference(cls, value: str) -> str:
        reference = value.strip()
        if not reference:
            raise ValueError("A transfer reference is required.")
        return reference

    @field_validator("order_item_ids")
    @classmethod
    def require_unique_order_items(
        cls,
        value: list[UUID],
    ) -> list[UUID]:
        if len(set(value)) != len(value):
            raise ValueError("An order can only be selected once.")
        return value


class VendorBillCreate(BaseModel):
    vendor_id: UUID
    date_from: date
    date_to: date

    @field_validator("date_to")
    @classmethod
    def validate_date_range(
        cls,
        value: date,
        info: ValidationInfo,
    ):
        date_from = info.data.get("date_from")
        if date_from and value < date_from:
            raise ValueError("The start date must be on or before the end date.")
        return value


class VendorBillStatusUpdate(BaseModel):
    status: Literal["paid", "unpaid"]


def get_vendor_payout_balance(vendor_id: str) -> dict:
    summary = get_vendor_earnings_summary(vendor_id)
    payouts = list_vendor_payout_records(vendor_id)

    try:
        confirmed_earnings = Decimal(
            str(summary["confirmed_earnings"])
        )
        reserved_payouts = Decimal("0.00")

        for payout in payouts:
            payout_status = str(
                payout.get("status") or ""
            ).lower()
            if payout_status not in {
                "pending",
                "processing",
                "paid",
                "failed",
            }:
                raise HTTPException(
                    status_code=500,
                    detail="Unknown payout status in financial records.",
                )

            if payout_status in {"pending", "processing", "paid"}:
                payout_amount = Decimal(
                    str(payout["amount"])
                )
                if payout_amount < 0:
                    raise HTTPException(
                        status_code=500,
                        detail="Negative payout amount in financial records.",
                    )
                reserved_payouts += payout_amount

        if (
            not confirmed_earnings.is_finite()
            or not reserved_payouts.is_finite()
        ):
            raise InvalidOperation
    except (KeyError, InvalidOperation, TypeError, ValueError) as exc:
        logger.exception(
            "Unable to calculate available payout balance for vendor %s",
            vendor_id,
        )
        raise HTTPException(
            status_code=500,
            detail="Unable to calculate the vendor payout balance.",
        ) from exc

    available_amount = confirmed_earnings - reserved_payouts
    if available_amount < 0:
        raise HTTPException(
            status_code=409,
            detail=(
                "Recorded payouts exceed confirmed vendor earnings. "
                "Reconcile the vendor balance before adding a payout."
            ),
        )

    allocation_by_item = {
        str(allocation["order_item_id"]): allocation
        for allocation in _get_payout_allocations()
    }
    billed_sale_items = {
        str(line.get("order_item_id"))
        for line in _get_vendor_bill_lines()
        if line.get("source_type") == "sale" and line.get("order_item_id")
    }
    eligible_items = [
        entry
        for entry in _get_completed_finance_entries()
        if (
            str(entry.get("vendor_id")) == vendor_id
            and str(entry.get("id")) not in allocation_by_item
            and str(entry.get("id")) not in billed_sale_items
        )
    ]

    return {
        "vendor_id": vendor_id,
        "currency": "INR",
        "confirmed_earnings": float(confirmed_earnings),
        "reserved_payouts": float(reserved_payouts),
        "available_amount": float(available_amount),
        "eligible_items": eligible_items,
    }


def list_table_records(
    table_name: str,
    limit: int,
    offset: int,
    status: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    vendor_ids: list[str] | None = None,
    order_by: str | None = None,
):
    if date_from and date_to and date_from > date_to:
        raise HTTPException(
            status_code=400,
            detail="The start date must be on or before the end date.",
        )

    if vendor_ids is not None and not vendor_ids:
        return {
            "items": [],
            "total": 0,
            "limit": limit,
            "offset": offset,
        }

    try:
        query = supabase.table(table_name).select("*", count="exact")

        if status:
            query = query.eq("status", status)

        if vendor_ids is not None:
            query = query.in_("vendor_id", vendor_ids)

        if date_from:
            query = query.gte("created_at", date_from.isoformat())

        if date_to:
            query = query.lt(
                "created_at",
                (date_to + timedelta(days=1)).isoformat(),
            )

        if order_by:
            query = query.order(order_by, desc=True)

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


def _read_all_finance_rows(
    table_name: str,
    columns: str,
    date_from: date | None = None,
    date_to: date | None = None,
) -> list[dict]:
    records = []
    offset = 0

    while True:
        query = (
            supabase.table(table_name)
            .select(columns)
            .order("id")
        )
        if date_from:
            query = query.gte("created_at", date_from.isoformat())
        if date_to:
            query = query.lt(
                "created_at",
                (date_to + timedelta(days=1)).isoformat(),
            )

        result = query.range(
            offset,
            offset + FINANCE_READ_PAGE_SIZE - 1,
        ).execute()
        batch = result.data or []
        records.extend(batch)

        if len(batch) < FINANCE_READ_PAGE_SIZE:
            return records

        offset += FINANCE_READ_PAGE_SIZE


def _load_finance_rows_by_ids(
    table_name: str,
    columns: str,
    id_column: str,
    ids: list[str],
) -> list[dict]:
    records = []
    for offset in range(0, len(ids), FINANCE_LOOKUP_BATCH_SIZE):
        batch_ids = ids[
            offset:offset + FINANCE_LOOKUP_BATCH_SIZE
        ]
        result = (
            supabase.table(table_name)
            .select(columns)
            .in_(id_column, batch_ids)
            .execute()
        )
        records.extend(result.data or [])
    return records


def _get_payout_allocations() -> list[dict]:
    try:
        return _read_all_finance_rows(
            "vendor_payout_allocations",
            "id,payout_id,order_item_id,amount,created_at",
        )
    except Exception as exc:
        logger.exception("Failed to load vendor payout allocations")
        raise HTTPException(
            status_code=500,
            detail=(
                "Vendor payout order allocations are not available. "
                "Run the Supabase payout allocation query."
            ),
        ) from exc


def _get_vendor_bill_lines() -> list[dict]:
    try:
        return _read_all_finance_rows(
            "vendor_bill_lines",
            (
                "id,bill_id,source_type,source_id,order_item_id,"
                "payable_amount,gross_sales,admin_commission,created_at"
            ),
        )
    except Exception as exc:
        logger.exception("Failed to load vendor bill line allocations")
        raise HTTPException(
            status_code=500,
            detail=(
                "Vendor bill records are not available. "
                "Run the Supabase vendor billing query."
            ),
        ) from exc


def _finance_decimal(value, field_name: str) -> Decimal:
    try:
        amount = Decimal(str(value))
        if not amount.is_finite():
            raise InvalidOperation
        return amount.quantize(
            Decimal("0.01"),
            rounding=ROUND_HALF_UP,
        )
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Invalid {field_name} in finance records.",
        ) from exc


def _get_completed_finance_entries(
    date_from: date | None = None,
    date_to: date | None = None,
) -> list[dict]:
    try:
        order_items = _read_all_finance_rows(
            "order_items",
            (
                "id,order_id,vendor_id,product_name,quantity,"
                "unit_price,total_price,status,vendor_net_amount,created_at"
            ),
            date_from,
            date_to,
        )
        order_ids = list({
            str(item["order_id"])
            for item in order_items
            if item.get("order_id")
        })
        if not order_ids:
            return []

        orders = _load_finance_rows_by_ids(
            "orders",
            "id,order_number,status,payment_status,currency",
            "id",
            order_ids,
        )
        orders_by_id = {
            str(order["id"]): order
            for order in orders
        }

        vendor_ids = list({
            str(item["vendor_id"])
            for item in order_items
            if item.get("vendor_id")
        })
        vendors = _load_finance_rows_by_ids(
            "vendors",
            "id,business_name,legal_name",
            "id",
            vendor_ids,
        )
        vendors_by_id = {
            str(vendor["id"]): vendor
            for vendor in vendors
        }

        entries = []
        for item in order_items:
            order_id = str(item.get("order_id") or "")
            order = orders_by_id.get(order_id)
            if not order:
                raise HTTPException(
                    status_code=500,
                    detail="An order required for finance records could not be found.",
                )

            order_status = str(order.get("status") or "").lower()
            item_status = str(item.get("status") or "").lower()
            payment_status = str(
                order.get("payment_status") or ""
            ).lower()
            currency = str(order.get("currency") or "INR").upper()

            if (
                order_status != "delivered"
                or item_status != "delivered"
                or payment_status != "paid"
                or currency != "INR"
            ):
                continue

            vendor_net_amount = item.get("vendor_net_amount")
            if vendor_net_amount is None:
                continue

            vendor_payable = _finance_decimal(
                vendor_net_amount,
                "vendor payable",
            )
            if vendor_payable < 0:
                raise HTTPException(
                    status_code=500,
                    detail="Negative vendor payable found in order records.",
                )

            total_price = _finance_decimal(
                item.get("total_price"),
                "order item total",
            )
            vendor_id = str(item.get("vendor_id") or "")
            vendor = vendors_by_id.get(vendor_id, {})
            vendor_name = (
                vendor.get("business_name")
                or vendor.get("legal_name")
                or vendor_id
            )

            entries.append({
                "id": str(item.get("id") or ""),
                "entry_type": "sale",
                "order_id": order_id,
                "order_number": order.get("order_number"),
                "vendor_id": vendor_id,
                "vendor_name": vendor_name,
                "product_name": item.get("product_name"),
                "quantity": item.get("quantity"),
                "unit_price": float(_finance_decimal(
                    item.get("unit_price"),
                    "order item unit price",
                )),
                "total_price": float(total_price),
                "vendor_payable": float(vendor_payable),
                "admin_commission": float(
                    (total_price - vendor_payable).quantize(
                        Decimal("0.01"),
                        rounding=ROUND_HALF_UP,
                    )
                ),
                "currency": currency,
                "status": "confirmed",
                "created_at": item.get("created_at"),
            })

        entries.sort(
            key=lambda entry: entry.get("created_at") or "",
            reverse=True,
        )
        return entries
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to calculate admin finance entries")
        raise HTTPException(
            status_code=500,
            detail="Unable to calculate admin finance entries.",
        ) from exc


def _get_vendor_ledger_entries(
    date_from: date | None = None,
    date_to: date | None = None,
) -> list[dict]:
    if date_from and date_to and date_from > date_to:
        raise HTTPException(
            status_code=400,
            detail="The start date must be on or before the end date.",
        )

    try:
        order_items = _read_all_finance_rows(
            "order_items",
            (
                "id,order_id,vendor_id,product_name,quantity,"
                "unit_price,total_price,status,vendor_net_amount,created_at"
            ),
            date_from,
            date_to,
        )
        return_requests = _read_all_finance_rows(
            "return_requests",
            (
                "id,order_id,order_item_id,vendor_id,request_type,"
                "requested_quantity,status,created_at"
            ),
            date_from,
            date_to,
        )
        return_requests = [
            request
            for request in return_requests
            if request.get("order_item_id")
        ]
        order_item_ids = sorted({
            str(item["id"])
            for item in order_items
            if item.get("id")
        } | {
            str(request["order_item_id"])
            for request in return_requests
            if request.get("order_item_id")
        })
        if not order_item_ids:
            return []

        related_items = _load_finance_rows_by_ids(
            "order_items",
            (
                "id,order_id,vendor_id,product_name,quantity,"
                "unit_price,total_price,status,vendor_net_amount,created_at"
            ),
            "id",
            order_item_ids,
        )
        items_by_id = {
            str(item["id"]): item
            for item in related_items
            if item.get("id")
        }
        order_ids = sorted({
            str(item["order_id"])
            for item in related_items
            if item.get("order_id")
        })
        orders = _load_finance_rows_by_ids(
            "orders",
            "id,order_number,status,payment_status,currency",
            "id",
            order_ids,
        )
        orders_by_id = {
            str(order["id"]): order
            for order in orders
            if order.get("id")
        }
        vendor_ids = sorted({
            str(item["vendor_id"])
            for item in related_items
            if item.get("vendor_id")
        })
        vendors = _load_finance_rows_by_ids(
            "vendors",
            "id,business_name,legal_name",
            "id",
            vendor_ids,
        )
        vendors_by_id = {
            str(vendor["id"]): vendor
            for vendor in vendors
            if vendor.get("id")
        }

        entries = []
        for item in order_items:
            item_id = str(item.get("id") or "")
            item = items_by_id.get(item_id)
            if not item:
                raise HTTPException(
                    status_code=500,
                    detail="An order item required for vendor billing could not be found.",
                )
            order_id = str(item.get("order_id") or "")
            order = orders_by_id.get(order_id)
            if not order:
                raise HTTPException(
                    status_code=500,
                    detail="An order required for vendor billing could not be found.",
                )

            order_status = str(order.get("status") or "").lower()
            item_status = str(item.get("status") or "").lower()
            payment_status = str(order.get("payment_status") or "").lower()
            currency = str(order.get("currency") or "INR").upper()
            if (
                order_status not in {"delivered", "returned", "refunded"}
                or item_status not in {"delivered", "returned", "refunded"}
                or payment_status not in {
                    "paid",
                    "refunded",
                    "partially_refunded",
                }
                or currency != "INR"
            ):
                continue

            quantity = int(item.get("quantity") or 0)
            if quantity <= 0:
                raise HTTPException(
                    status_code=500,
                    detail="Invalid order item quantity in vendor billing records.",
                )
            vendor_id = str(item.get("vendor_id") or "")
            if not vendor_id:
                raise HTTPException(
                    status_code=500,
                    detail="Missing vendor ID in order item finance records.",
                )
            if item.get("vendor_net_amount") is None:
                continue

            vendor_payable = _finance_decimal(
                item["vendor_net_amount"],
                "vendor payable",
            )
            total_price = _finance_decimal(
                item.get("total_price"),
                "order item total",
            )
            admin_commission = (total_price - vendor_payable).quantize(
                Decimal("0.01"),
                rounding=ROUND_HALF_UP,
            )
            if vendor_payable < 0 or total_price < 0 or admin_commission < 0:
                raise HTTPException(
                    status_code=500,
                    detail="Invalid sales or commission amount in vendor billing records.",
                )

            vendor = vendors_by_id.get(vendor_id, {})
            vendor_name = (
                vendor.get("business_name")
                or vendor.get("legal_name")
                or vendor_id
            )
            entries.append({
                "id": f"sale:{item_id}",
                "source_type": "sale",
                "source_id": item_id,
                "order_item_id": item_id,
                "order_id": order_id,
                "order_number": order.get("order_number"),
                "vendor_id": vendor_id,
                "vendor_name": vendor_name,
                "product_name": item.get("product_name"),
                "entry_type": "sale",
                "quantity": quantity,
                "unit_price": float(_finance_decimal(
                    item.get("unit_price"),
                    "order item unit price",
                )),
                "total_price": float(total_price),
                "gross_sales": float(total_price),
                "vendor_payable": float(vendor_payable),
                "admin_commission": float(admin_commission),
                "adjustment_amount": 0.0,
                "currency": currency,
                "status": item_status,
                "billable": True,
                "created_at": item.get("created_at"),
            })

        for request in return_requests:
            request_id = str(request.get("id") or "")
            item_id = str(request.get("order_item_id") or "")
            item = items_by_id.get(item_id)
            if not item:
                raise HTTPException(
                    status_code=500,
                    detail="A return order item required for vendor billing could not be found.",
                )

            order_id = str(request.get("order_id") or item.get("order_id") or "")
            order = orders_by_id.get(order_id)
            if not order:
                raise HTTPException(
                    status_code=500,
                    detail="A return order required for vendor billing could not be found.",
                )

            request_type = str(request.get("request_type") or "").lower()
            if request_type not in {"return", "replacement"}:
                raise HTTPException(
                    status_code=500,
                    detail="Unknown return request type in vendor billing records.",
                )

            quantity = int(item.get("quantity") or 0)
            requested_quantity = int(request.get("requested_quantity") or 0)
            if (
                quantity <= 0
                or requested_quantity <= 0
                or requested_quantity > quantity
            ):
                raise HTTPException(
                    status_code=500,
                    detail="Invalid returned quantity in vendor billing records.",
                )

            is_completed = str(request.get("status") or "").lower() == "completed"
            is_return = request_type == "return"
            payment_status = str(order.get("payment_status") or "").lower()
            currency = str(order.get("currency") or "INR").upper()
            if currency != "INR":
                continue
            is_paid_order = payment_status in {
                "paid",
                "refunded",
                "partially_refunded",
            }
            adjustment = Decimal("0.00")
            if is_completed and is_return and is_paid_order:
                vendor_net_amount = item.get("vendor_net_amount")
                if vendor_net_amount is None:
                    raise HTTPException(
                        status_code=500,
                        detail=(
                            "A completed return has no saved vendor payable "
                            "amount for adjustment."
                        ),
                    )
                vendor_payable = _finance_decimal(
                    vendor_net_amount,
                    "vendor payable",
                )
                if vendor_payable < 0:
                    raise HTTPException(
                        status_code=500,
                        detail="Negative vendor payable found in return records.",
                    )
                adjustment = (
                    vendor_payable
                    * requested_quantity
                    / quantity
                ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

            original_total = _finance_decimal(
                item.get("total_price"),
                "order item total",
            )
            if original_total < 0:
                raise HTTPException(
                    status_code=500,
                    detail="Negative order item total found in return records.",
                )
            returned_total = (
                original_total * requested_quantity / quantity
            ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            vendor_id = str(item.get("vendor_id") or "")
            if not vendor_id:
                raise HTTPException(
                    status_code=500,
                    detail="Missing vendor ID in return finance records.",
                )
            vendor = vendors_by_id.get(vendor_id, {})
            vendor_name = (
                vendor.get("business_name")
                or vendor.get("legal_name")
                or vendor_id
            )
            entries.append({
                "id": f"{request_type}:{request_id}",
                "source_type": "return" if is_return else "exchange",
                "source_id": request_id,
                "order_item_id": item_id,
                "return_request_id": request_id,
                "order_id": order_id,
                "order_number": order.get("order_number"),
                "vendor_id": vendor_id,
                "vendor_name": vendor_name,
                "product_name": item.get("product_name"),
                "entry_type": "return" if is_return else "exchange",
                "quantity": requested_quantity,
                "unit_price": float(_finance_decimal(
                    item.get("unit_price"),
                    "order item unit price",
                )),
                "total_price": float(returned_total),
                "gross_sales": 0.0,
                "vendor_payable": float(-adjustment),
                "admin_commission": 0.0,
                "adjustment_amount": float(adjustment),
                "currency": currency,
                "status": str(request.get("status") or "unknown").lower(),
                "billable": is_completed and is_paid_order,
                "created_at": request.get("created_at"),
            })

        entries.sort(
            key=lambda entry: str(entry.get("created_at") or ""),
            reverse=True,
        )
        return entries
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to calculate vendor ledger entries")
        raise HTTPException(
            status_code=500,
            detail="Unable to calculate vendor ledger entries.",
        ) from exc


def _calculate_vendor_ledger_totals(entries: list[dict]) -> dict:
    gross_sales = sum(
        (
            _finance_decimal(entry.get("gross_sales"), "gross sales")
            for entry in entries
        ),
        Decimal("0.00"),
    )
    commission = sum(
        (
            _finance_decimal(entry.get("admin_commission"), "admin commission")
            for entry in entries
        ),
        Decimal("0.00"),
    )
    adjustments = sum(
        (
            _finance_decimal(entry.get("adjustment_amount"), "return adjustment")
            for entry in entries
        ),
        Decimal("0.00"),
    )
    payable = sum(
        (
            _finance_decimal(entry.get("vendor_payable"), "vendor payable")
            for entry in entries
        ),
        Decimal("0.00"),
    )
    return {
        "gross_sales": float(gross_sales),
        "admin_commission": float(commission),
        "return_adjustments": float(adjustments),
        "vendor_payable": float(payable),
        "currency": "INR",
    }


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
    vendor_id_filter: UUID | None = Query(default=None, alias="vendor_id"),
    vendor_name: str | None = Query(default=None, max_length=100),
    entry_type: str = Query(default="all"),
    billing_status: str = Query(default="all"),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    if date_from and date_to and date_from > date_to:
        raise HTTPException(
            status_code=400,
            detail="The start date must be on or before the end date.",
        )
    if entry_type not in {"all", "sales", "returns", "exchanges"}:
        raise HTTPException(
            status_code=400,
            detail="Invalid vendor ledger entry filter.",
        )
    if billing_status not in {"all", "billed", "unbilled", "paid"}:
        raise HTTPException(
            status_code=400,
            detail="Invalid vendor ledger bill status filter.",
        )

    entries = _get_vendor_ledger_entries(date_from, date_to)
    if vendor_id_filter:
        entries = [
            entry
            for entry in entries
            if str(entry.get("vendor_id")) == str(vendor_id_filter)
        ]
    if vendor_name and vendor_name.strip():
        search_term = vendor_name.strip().casefold()
        entries = [
            entry
            for entry in entries
            if search_term in str(entry.get("vendor_name") or "").casefold()
        ]
    if entry_type != "all":
        type_map = {
            "sales": {"sale"},
            "returns": {"return"},
            "exchanges": {"exchange"},
        }
        entries = [
            entry
            for entry in entries
            if entry.get("entry_type") in type_map[entry_type]
        ]

    allocations = _get_payout_allocations()
    allocated_items = {
        str(allocation.get("order_item_id"))
        for allocation in allocations
        if allocation.get("order_item_id")
    }
    bill_lines = _get_vendor_bill_lines()
    billed_sources = {
        (
            str(line.get("source_type") or ""),
            str(line.get("source_id") or ""),
        )
        for line in bill_lines
    }
    for entry in entries:
        source_key = (
            str(entry.get("source_type") or ""),
            str(entry.get("source_id") or ""),
        )
        if source_key in billed_sources:
            entry["billing_status"] = "billed"
        elif (
            entry.get("source_type") == "sale"
            and str(entry.get("order_item_id") or "") in allocated_items
        ):
            entry["billing_status"] = "paid"
        else:
            entry["billing_status"] = "unbilled"

    if billing_status != "all":
        entries = [
            entry
            for entry in entries
            if entry.get("billing_status") == billing_status
        ]

    return {
        "items": entries[offset:offset + limit],
        "total": len(entries),
        "totals": _calculate_vendor_ledger_totals(entries),
        "limit": limit,
        "offset": offset,
    }


@router.post("/vendor-bills", status_code=201)
def create_vendor_bill(
    payload: VendorBillCreate,
    current_admin=Depends(get_current_admin),
):
    try:
        vendor_result = (
            supabase.table("vendors")
            .select("id")
            .eq("id", str(payload.vendor_id))
            .maybe_single()
            .execute()
        )
    except Exception as exc:
        logger.exception("Failed to verify vendor %s", payload.vendor_id)
        raise HTTPException(
            status_code=500,
            detail="Unable to verify the selected vendor.",
        ) from exc
    if not vendor_result.data:
        raise HTTPException(
            status_code=404,
            detail="Vendor not found.",
        )

    entries = _get_vendor_ledger_entries(
        payload.date_from,
        payload.date_to,
    )
    vendor_id = str(payload.vendor_id)
    allocations = _get_payout_allocations()
    allocated_items = {
        str(allocation.get("order_item_id"))
        for allocation in allocations
        if allocation.get("order_item_id")
    }
    bill_lines = _get_vendor_bill_lines()
    billed_sources = {
        (
            str(line.get("source_type") or ""),
            str(line.get("source_id") or ""),
        )
        for line in bill_lines
    }
    lines = []
    for entry in entries:
        if (
            str(entry.get("vendor_id")) != vendor_id
            or not entry.get("billable")
        ):
            continue

        source_type = str(entry.get("source_type") or "")
        source_id = str(entry.get("source_id") or "")
        if (source_type, source_id) in billed_sources:
            continue
        if (
            source_type == "sale"
            and str(entry.get("order_item_id") or "") in allocated_items
        ):
            continue

        lines.append({
            "source_type": source_type,
            "source_id": source_id,
            "order_item_id": str(entry.get("order_item_id") or ""),
            "payable_amount": str(
                _finance_decimal(
                    entry.get("vendor_payable"),
                    "vendor payable",
                )
            ),
            "gross_sales": str(
                _finance_decimal(
                    entry.get("gross_sales"),
                    "gross sales",
                )
            ),
            "admin_commission": str(
                _finance_decimal(
                    entry.get("admin_commission"),
                    "admin commission",
                )
            ),
        })

    if not lines:
        raise HTTPException(
            status_code=409,
            detail=(
                "There are no unbilled sales or completed return/exchange "
                "records for this vendor and date range."
            ),
        )

    try:
        result = supabase.rpc(
            "admin_create_vendor_bill",
            {
                "p_vendor_id": vendor_id,
                "p_period_start": payload.date_from.isoformat(),
                "p_period_end": payload.date_to.isoformat(),
                "p_admin_id": str(current_admin.id),
                "p_lines": lines,
            },
        ).execute()
    except Exception as exc:
        logger.exception("Failed to create vendor bill for %s", vendor_id)
        raise HTTPException(
            status_code=500,
            detail=(
                "Unable to generate the vendor bill. "
                "Run the Supabase vendor billing query."
            ),
        ) from exc

    response = result.data
    if not isinstance(response, dict):
        raise HTTPException(
            status_code=500,
            detail="Supabase returned an invalid vendor bill response.",
        )
    error_code = response.get("error")
    if error_code == "vendor_not_found":
        raise HTTPException(
            status_code=404,
            detail="Vendor not found.",
        )
    if error_code == "source_already_billed":
        raise HTTPException(
            status_code=409,
            detail=(
                "One or more records were billed in another request. "
                "Refresh the ledger and try again."
            ),
        )
    if error_code == "invalid_bill_lines":
        raise HTTPException(
            status_code=400,
            detail="The vendor bill contains invalid ledger records.",
        )

    bill = response.get("bill")
    if (
        not isinstance(bill, dict)
        or str(bill.get("vendor_id")) != vendor_id
        or bill.get("status") != "unpaid"
    ):
        raise HTTPException(
            status_code=500,
            detail="Supabase did not confirm the vendor bill.",
        )
    return {
        "message": "Vendor bill generated.",
        "bill": bill,
    }


@router.patch("/vendor-bills/{bill_id}/status")
def update_vendor_bill_status(
    bill_id: UUID,
    payload: VendorBillStatusUpdate,
):
    try:
        result = (
            supabase.table("vendor_bills")
            .update({
                "status": payload.status,
                "paid_at": (
                    datetime.now(timezone.utc).isoformat()
                    if payload.status == "paid"
                    else None
                ),
            })
            .eq("id", str(bill_id))
            .select("*")
            .execute()
        )
    except Exception as exc:
        logger.exception("Failed to update vendor bill %s", bill_id)
        raise HTTPException(
            status_code=500,
            detail="Unable to update vendor bill payment status.",
        ) from exc

    rows = result.data or []
    if not rows:
        raise HTTPException(
            status_code=404,
            detail="Vendor bill not found.",
        )
    return {
        "message": "Vendor bill payment status updated.",
        "bill": rows[0],
    }


@router.get("/vendor-payouts")
def list_vendor_payouts(
    status: str | None = None,
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    vendor_name: str | None = Query(default=None, max_length=100),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    vendor_ids = None
    if vendor_name and vendor_name.strip():
        term = (
            vendor_name.strip()
            .replace("\\", "\\\\")
            .replace("%", "\\%")
            .replace("_", "\\_")
            .replace(",", "")
            .replace("(", "")
            .replace(")", "")
        )
        if not term:
            vendor_ids = []
        else:
            try:
                vendors_result = (
                    supabase.table("vendors")
                    .select("id")
                    .or_(
                        f"business_name.ilike.%{term}%,"
                        f"legal_name.ilike.%{term}%"
                    )
                    .execute()
                )
            except Exception as exc:
                logger.exception("Failed to search payout vendors")
                raise HTTPException(
                    status_code=500,
                    detail="Unable to search payout vendors.",
                ) from exc

            vendor_ids = [
                str(vendor["id"])
                for vendor in vendors_result.data or []
                if vendor.get("id")
            ]

    result = list_table_records(
        "vendor_payouts",
        limit,
        offset,
        status,
        date_from,
        date_to,
        vendor_ids=vendor_ids,
        order_by="created_at",
    )

    vendor_ids = list({
        str(item["vendor_id"])
        for item in result["items"]
        if item.get("vendor_id")
    })
    if not vendor_ids:
        return result

    try:
        vendors_result = (
            supabase.table("vendors")
            .select("id, business_name, legal_name")
            .in_("id", vendor_ids)
            .execute()
        )
    except Exception as exc:
        logger.exception("Failed to load payout vendor names")
        raise HTTPException(
            status_code=500,
            detail="Unable to load payout vendor names.",
        ) from exc

    vendors_by_id = {
        str(vendor["id"]): vendor
        for vendor in vendors_result.data or []
    }
    for item in result["items"]:
        vendor = vendors_by_id.get(str(item.get("vendor_id")))
        if vendor:
            item["vendor_name"] = (
                vendor.get("business_name")
                or vendor.get("legal_name")
                or item.get("vendor_id")
            )

    return result


@router.get("/vendor-payouts/overview")
def get_vendor_payout_overview(
    status: str | None = None,
    vendor_id_filter: UUID | None = Query(default=None, alias="vendor_id"),
    vendor_name: str | None = Query(default=None, max_length=100),
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    if date_from and date_to and date_from > date_to:
        raise HTTPException(
            status_code=400,
            detail="The start date must be on or before the end date.",
        )

    try:
        order_entries = _get_completed_finance_entries()
        allocations = _get_payout_allocations()
        payout_rows = _read_all_finance_rows(
            "vendor_payouts",
            (
                "id,vendor_id,amount,status,payment_reference,"
                "processed_at,created_at"
            ),
        )
        bill_rows = _read_all_finance_rows(
            "vendor_bills",
            (
                "id,vendor_id,period_start,period_end,gross_sales,"
                "admin_commission,return_adjustments,vendor_payable,"
                "order_count,status,created_at,paid_at"
            ),
        )
        bill_lines = _get_vendor_bill_lines()
        vendor_rows = _read_all_finance_rows(
            "vendors",
            "id,business_name,legal_name",
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to load vendor payout settlements")
        raise HTTPException(
            status_code=500,
            detail="Unable to load vendor payout settlements.",
        ) from exc

    vendors_by_id = {
        str(vendor["id"]): vendor
        for vendor in vendor_rows
        if vendor.get("id")
    }
    entries_by_id = {
        str(entry["id"]): entry
        for entry in order_entries
        if entry.get("id")
    }
    allocations_by_payout: dict[str, list[dict]] = {}
    allocated_items = set()
    for allocation in allocations:
        payout_id = str(allocation.get("payout_id") or "")
        order_item_id = str(allocation.get("order_item_id") or "")
        allocated_items.add(order_item_id)
        allocations_by_payout.setdefault(payout_id, []).append(
            allocation
        )
    billed_sale_items = {
        str(line.get("order_item_id"))
        for line in bill_lines
        if line.get("source_type") == "sale" and line.get("order_item_id")
    }

    name_filter = (vendor_name or "").strip().casefold()
    payout_items = []
    for payout in payout_rows:
        payout_id = str(payout.get("id") or "")
        vendor_id = str(payout.get("vendor_id") or "")
        if vendor_id_filter and vendor_id != str(vendor_id_filter):
            continue
        payout_status = str(payout.get("status") or "").lower()
        if payout_status not in {"paid", "pending", "processing", "failed"}:
            raise HTTPException(
                status_code=500,
                detail="Unknown payout status in financial records.",
            )
        if date_from and str(payout.get("created_at") or "")[:10] < date_from.isoformat():
            continue
        if date_to and str(payout.get("created_at") or "")[:10] > date_to.isoformat():
            continue

        vendor = vendors_by_id.get(vendor_id, {})
        vendor_display_name = (
            vendor.get("business_name")
            or vendor.get("legal_name")
            or vendor_id
        )
        if name_filter and name_filter not in str(
            vendor_display_name
        ).casefold():
            continue

        allocated_entries = [
            entries_by_id.get(
                str(allocation.get("order_item_id") or "")
            )
            for allocation in allocations_by_payout.get(payout_id, [])
        ]
        allocated_entries = [
            entry
            for entry in allocated_entries
            if entry is not None
        ]
        if any(
            str(entry.get("vendor_id")) != vendor_id
            for entry in allocated_entries
        ):
            raise HTTPException(
                status_code=500,
                detail="A payout allocation references the wrong vendor.",
            )

        period_values = [
            str(entry.get("created_at") or "")[:10]
            for entry in allocated_entries
            if entry.get("created_at")
        ]
        payout_created = str(payout.get("created_at") or "")
        period_start = min(period_values) if period_values else payout_created[:10]
        period_end = max(period_values) if period_values else payout_created[:10]
        payout_amount = _finance_decimal(
            payout.get("amount"),
            "payout amount",
        )
        gross_sales = sum(
            (
                _finance_decimal(entry["total_price"], "order item total")
                for entry in allocated_entries
            ),
            Decimal("0.00"),
        )
        deductions = sum(
            (
                _finance_decimal(
                    entry["admin_commission"],
                    "admin commission",
                )
                for entry in allocated_entries
            ),
            Decimal("0.00"),
        )
        settlement_status = (
            "paid" if payout_status == "paid" else "unpaid"
        )
        payout_items.append({
            "id": payout_id,
            "record_type": "transfer",
            "payout_id": f"PAY-{payout_id[:8].upper()}",
            "vendor_id": vendor_id,
            "vendor_name": vendor_display_name,
            "settlement_start": period_start,
            "settlement_end": period_end,
            "order_count": len({
                str(entry.get("order_id"))
                for entry in allocated_entries
            }),
            "gross_sales": float(gross_sales),
            "admin_commission": float(deductions),
            "return_adjustments": 0.0,
            "net_payout": float(payout_amount),
            "status": settlement_status,
            "payment_reference": payout.get("payment_reference"),
            "created_at": payout_created,
        })

    for bill in bill_rows:
        bill_id = str(bill.get("id") or "")
        vendor_id = str(bill.get("vendor_id") or "")
        if vendor_id_filter and vendor_id != str(vendor_id_filter):
            continue
        bill_status = str(bill.get("status") or "").lower()
        if bill_status not in {"paid", "unpaid"}:
            raise HTTPException(
                status_code=500,
                detail="Unknown vendor bill status in financial records.",
            )
        period_start = str(bill.get("period_start") or "")[:10]
        period_end = str(bill.get("period_end") or "")[:10]
        if (
            date_from
            and period_end
            and period_end < date_from.isoformat()
        ):
            continue
        if (
            date_to
            and period_start
            and period_start > date_to.isoformat()
        ):
            continue

        vendor = vendors_by_id.get(vendor_id, {})
        vendor_display_name = (
            vendor.get("business_name")
            or vendor.get("legal_name")
            or vendor_id
        )
        if name_filter and name_filter not in str(
            vendor_display_name
        ).casefold():
            continue

        payout_items.append({
            "id": f"bill-{bill_id}",
            "bill_id": bill_id,
            "record_type": "bill",
            "payout_id": f"BILL-{bill_id[:8].upper()}",
            "vendor_id": vendor_id,
            "vendor_name": vendor_display_name,
            "settlement_start": period_start,
            "settlement_end": period_end,
            "order_count": int(bill.get("order_count") or 0),
            "gross_sales": float(_finance_decimal(
                bill.get("gross_sales"),
                "bill gross sales",
            )),
            "admin_commission": None,
            "return_adjustments": float(_finance_decimal(
                bill.get("return_adjustments"),
                "bill return adjustments",
            )),
            "net_payout": float(_finance_decimal(
                bill.get("vendor_payable"),
                "bill vendor payable",
            )),
            "status": bill_status,
            "payment_reference": None,
            "created_at": bill.get("created_at"),
        })

    unpaid_by_vendor: dict[str, list[dict]] = {}
    for entry in order_entries:
        order_item_id = str(entry.get("id") or "")
        if (
            order_item_id in allocated_items
            or order_item_id in billed_sale_items
        ):
            continue
        created_at = str(entry.get("created_at") or "")
        if date_from and created_at[:10] < date_from.isoformat():
            continue
        if date_to and created_at[:10] > date_to.isoformat():
            continue
        vendor_id = str(entry.get("vendor_id") or "")
        if vendor_id_filter and vendor_id != str(vendor_id_filter):
            continue
        vendor = vendors_by_id.get(vendor_id, {})
        vendor_display_name = (
            vendor.get("business_name")
            or vendor.get("legal_name")
            or vendor_id
        )
        if name_filter and name_filter not in str(
            vendor_display_name
        ).casefold():
            continue
        unpaid_by_vendor.setdefault(vendor_id, []).append(entry)

    for vendor_id, entries in unpaid_by_vendor.items():
        vendor = vendors_by_id.get(vendor_id, {})
        vendor_display_name = (
            vendor.get("business_name")
            or vendor.get("legal_name")
            or vendor_id
        )
        period_values = [
            str(entry.get("created_at") or "")[:10]
            for entry in entries
            if entry.get("created_at")
        ]
        total_payable = sum(
            (
                _finance_decimal(
                    entry["vendor_payable"],
                    "vendor payable",
                )
                for entry in entries
            ),
            Decimal("0.00"),
        )
        gross_sales = sum(
            (
                _finance_decimal(entry["total_price"], "order item total")
                for entry in entries
            ),
            Decimal("0.00"),
        )
        deductions = sum(
            (
                _finance_decimal(
                    entry["admin_commission"],
                    "admin commission",
                )
                for entry in entries
            ),
            Decimal("0.00"),
        )
        payout_items.append({
            "id": f"due-{vendor_id}",
            "record_type": "unbilled",
            "payout_id": f"DUE-{vendor_id[:8].upper()}",
            "vendor_id": vendor_id,
            "vendor_name": vendor_display_name,
            "settlement_start": (
                min(period_values) if period_values else None
            ),
            "settlement_end": (
                max(period_values) if period_values else None
            ),
            "order_count": len({
                str(entry.get("order_id"))
                for entry in entries
            }),
            "gross_sales": float(gross_sales),
            "admin_commission": float(deductions),
            "return_adjustments": 0.0,
            "net_payout": float(total_payable),
            "status": "unpaid",
            "payment_reference": None,
            "created_at": max(period_values) if period_values else None,
        })

    if status:
        normalized_status = status.strip().lower()
        if normalized_status not in {"paid", "unpaid"}:
            raise HTTPException(
                status_code=400,
                detail="Payout status must be paid or unpaid.",
            )
        payout_items = [
            item
            for item in payout_items
            if item["status"] == normalized_status
        ]

    payout_items.sort(
        key=lambda item: str(item.get("created_at") or ""),
        reverse=True,
    )
    return {
        "items": payout_items[offset:offset + limit],
        "total": len(payout_items),
        "limit": limit,
        "offset": offset,
    }


@router.get("/vendor-payouts/settlements/{settlement_id}")
def get_vendor_payout_settlement_detail(
    settlement_id: str,
):
    if settlement_id.startswith("bill-"):
        try:
            bill_id = str(UUID(settlement_id[5:]))
        except (TypeError, ValueError, AttributeError) as exc:
            raise HTTPException(
                status_code=404,
                detail="Vendor bill not found.",
            ) from exc

        try:
            bill_result = (
                supabase.table("vendor_bills")
                .select("*")
                .eq("id", bill_id)
                .execute()
            )
            bill_rows = bill_result.data or []
            if not bill_rows:
                raise HTTPException(
                    status_code=404,
                    detail="Vendor bill not found.",
                )
            bill = bill_rows[0]
            bill_lines = [
                line
                for line in _get_vendor_bill_lines()
                if str(line.get("bill_id") or "") == bill_id
            ]
            entries = _get_vendor_ledger_entries()
            entries_by_source = {
                (
                    str(entry.get("source_type") or ""),
                    str(entry.get("source_id") or ""),
                ): entry
                for entry in entries
            }
        except HTTPException:
            raise
        except Exception as exc:
            logger.exception("Failed to load vendor bill detail %s", bill_id)
            raise HTTPException(
                status_code=500,
                detail="Unable to load vendor bill detail.",
            ) from exc

        vendor_id = str(bill.get("vendor_id") or "")
        try:
            vendor_result = (
                supabase.table("vendors")
                .select("id,business_name,legal_name")
                .eq("id", vendor_id)
                .execute()
            )
        except Exception as exc:
            logger.exception(
                "Failed to load vendor %s for bill detail",
                vendor_id,
            )
            raise HTTPException(
                status_code=500,
                detail="Unable to load vendor bill detail.",
            ) from exc
        vendor_rows = vendor_result.data or []
        if not vendor_rows:
            raise HTTPException(
                status_code=404,
                detail="Vendor not found.",
            )
        vendor = vendor_rows[0]
        vendor_name = (
            vendor.get("business_name")
            or vendor.get("legal_name")
            or vendor_id
        )
        bill_status = str(bill.get("status") or "").lower()
        if bill_status not in {"paid", "unpaid"}:
            raise HTTPException(
                status_code=500,
                detail="Unknown vendor bill status in financial records.",
            )

        vendor_entries = []
        for line in bill_lines:
            source_key = (
                str(line.get("source_type") or ""),
                str(line.get("source_id") or ""),
            )
            entry = entries_by_source.get(source_key)
            if not entry:
                raise HTTPException(
                    status_code=500,
                    detail=(
                        "A vendor bill line no longer matches its source "
                        "finance record."
                    ),
                )
            line_payable = _finance_decimal(
                line.get("payable_amount"),
                "bill line payable",
            )
            line_gross_sales = _finance_decimal(
                line.get("gross_sales"),
                "bill line gross sales",
            )
            line_admin_commission = _finance_decimal(
                line.get("admin_commission"),
                "bill line admin commission",
            )
            line_adjustment = (
                -line_payable
                if source_key[0] == "return"
                else Decimal("0.00")
            )
            vendor_entries.append({
                **entry,
                "gross_sales": float(line_gross_sales),
                "admin_commission": float(line_admin_commission),
                "adjustment_amount": float(line_adjustment),
                "vendor_payable": float(line_payable),
                "payout_status": bill_status,
                "payout_id": f"BILL-{bill_id[:8].upper()}",
                "payment_reference": None,
                "payout_created_at": bill.get("created_at"),
            })

        if not vendor_entries:
            raise HTTPException(
                status_code=500,
                detail="The vendor bill has no ledger lines.",
            )
        payable = _finance_decimal(
            bill.get("vendor_payable"),
            "bill vendor payable",
        )
        paid = payable if bill_status == "paid" else Decimal("0.00")
        unpaid = payable if bill_status == "unpaid" else Decimal("0.00")
        return {
            "settlement_id": settlement_id,
            "payout_id": f"BILL-{bill_id[:8].upper()}",
            "vendor_id": vendor_id,
            "vendor_name": vendor_name,
            "period_start": bill.get("period_start"),
            "period_end": bill.get("period_end"),
            "created_at": bill.get("created_at"),
            "transfer_status": bill_status,
            "payment_reference": None,
            "record_type": "bill",
            "gross_sales": float(_finance_decimal(
                bill.get("gross_sales"),
                "bill gross sales",
            )),
            "return_adjustments": float(_finance_decimal(
                bill.get("return_adjustments"),
                "bill return adjustments",
            )),
            "admin_commission": float(_finance_decimal(
                bill.get("admin_commission"),
                "bill admin commission",
            )),
            "items": vendor_entries,
            "totals": {
                "vendor_payable": float(payable),
                "paid": float(paid),
                "unpaid": float(unpaid),
                "currency": "INR",
            },
        }

    try:
        payout_rows = _read_all_finance_rows(
            "vendor_payouts",
            (
                "id,vendor_id,amount,status,payment_reference,"
                "created_at"
            ),
        )
        allocations = _get_payout_allocations()
        entries = _get_completed_finance_entries()
        vendors = _read_all_finance_rows(
            "vendors",
            "id,business_name,legal_name",
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to load vendor payout detail")
        raise HTTPException(
            status_code=500,
            detail="Unable to load vendor payout detail.",
        ) from exc

    payout_by_id = {
        str(payout.get("id")): payout
        for payout in payout_rows
        if payout.get("id")
    }
    if settlement_id.startswith("due-"):
        vendor_id = settlement_id[4:]
        selected_payout = None
    else:
        selected_payout = payout_by_id.get(settlement_id)
        if not selected_payout:
            raise HTTPException(
                status_code=404,
                detail="Payout record not found.",
            )
        vendor_id = str(selected_payout.get("vendor_id") or "")

    vendors_by_id = {
        str(vendor.get("id")): vendor
        for vendor in vendors
        if vendor.get("id")
    }
    vendor = vendors_by_id.get(vendor_id)
    if not vendor:
        raise HTTPException(
            status_code=404,
            detail="Vendor not found.",
        )
    vendor_name = (
        vendor.get("business_name")
        or vendor.get("legal_name")
        or vendor_id
    )
    entries_by_id = {
        str(entry.get("id")): entry
        for entry in entries
        if entry.get("id")
    }
    allocations_by_item = {
        str(allocation.get("order_item_id")): allocation
        for allocation in allocations
        if allocation.get("order_item_id")
    }

    vendor_entries = []
    for entry in entries:
        if str(entry.get("vendor_id")) != vendor_id:
            continue
        order_item_id = str(entry.get("id") or "")
        allocation = allocations_by_item.get(order_item_id)
        allocated_amount = (
            _finance_decimal(allocation["amount"], "payout allocation")
            if allocation
            else Decimal("0.00")
        )
        payable = _finance_decimal(
            entry["vendor_payable"],
            "vendor payable",
        )
        if allocation and allocated_amount != payable:
            raise HTTPException(
                status_code=500,
                detail=(
                    "An order allocation does not match the full vendor payable. "
                    "Reconcile the payout allocation."
                ),
            )
        payout = (
            payout_by_id.get(str(allocation.get("payout_id") or ""))
            if allocation
            else None
        )
        is_paid = bool(
            allocation
            and payout
            and str(payout.get("status") or "").lower() == "paid"
        )
        vendor_entries.append({
            **entry,
            "payout_status": "paid" if is_paid else "unpaid",
            "payout_id": (
                f"PAY-{str(payout['id'])[:8].upper()}"
                if is_paid
                else None
            ),
            "payment_reference": (
                payout.get("payment_reference") if is_paid else None
            ),
            "payout_created_at": (
                payout.get("created_at") if is_paid else None
            ),
        })

    total_payable = sum(
        (
            _finance_decimal(entry["vendor_payable"], "vendor payable")
            for entry in vendor_entries
        ),
        Decimal("0.00"),
    )
    total_paid = sum(
        (
            _finance_decimal(entry["vendor_payable"], "vendor payable")
            for entry in vendor_entries
            if entry["payout_status"] == "paid"
        ),
        Decimal("0.00"),
    )

    return {
        "settlement_id": settlement_id,
        "payout_id": (
            f"PAY-{str(selected_payout['id'])[:8].upper()}"
            if selected_payout
            else f"DUE-{vendor_id[:8].upper()}"
        ),
        "vendor_id": vendor_id,
        "vendor_name": vendor_name,
        "transfer_status": (
            selected_payout.get("status")
            if selected_payout
            else "unpaid"
        ),
        "payment_reference": (
            selected_payout.get("payment_reference")
            if selected_payout
            else None
        ),
        "items": vendor_entries,
        "totals": {
            "vendor_payable": float(total_payable),
            "paid": float(total_paid),
            "unpaid": float(total_payable - total_paid),
            "currency": "INR",
        },
    }


@router.get("/vendor-payouts/eligibility/{vendor_id}")
def get_vendor_payout_eligibility(
    vendor_id: UUID,
):
    vendor_id_value = str(vendor_id)
    try:
        vendor_result = (
            supabase.table("vendors")
            .select("id")
            .eq("id", vendor_id_value)
            .maybe_single()
            .execute()
        )
    except Exception as exc:
        logger.exception(
            "Failed to verify vendor %s for payout eligibility",
            vendor_id_value,
        )
        raise HTTPException(
            status_code=500,
            detail="Unable to verify the selected vendor.",
        ) from exc

    if not vendor_result.data:
        raise HTTPException(
            status_code=404,
            detail="Vendor not found.",
        )

    return get_vendor_payout_balance(vendor_id_value)


@router.post("/vendor-payouts", status_code=201)
def create_vendor_payout(
    payload: VendorPayoutCreate,
    current_admin=Depends(get_current_admin),
):
    billed_sale_items = {
        str(line.get("order_item_id"))
        for line in _get_vendor_bill_lines()
        if line.get("source_type") == "sale" and line.get("order_item_id")
    }
    if any(
        str(order_item_id) in billed_sale_items
        for order_item_id in payload.order_item_ids
    ):
        raise HTTPException(
            status_code=409,
            detail=(
                "One or more selected order items are already in a vendor bill."
            ),
        )

    try:
        result = supabase.rpc(
            "admin_record_vendor_payout_with_allocations",
            {
                "p_vendor_id": str(payload.vendor_id),
                "p_amount": float(payload.amount),
                "p_payment_reference": payload.payment_reference,
                "p_admin_id": str(current_admin.id),
                "p_order_item_ids": [
                    str(order_item_id)
                    for order_item_id in payload.order_item_ids
                ],
            },
        ).execute()
    except Exception as exc:
        logger.exception(
            "Failed to record vendor payout for vendor %s",
            payload.vendor_id,
        )
        raise HTTPException(
            status_code=500,
            detail=(
                "Unable to record the vendor payout. Ensure the "
                "Supabase vendor payout function is installed."
            ),
        ) from exc

    response = result.data
    if not isinstance(response, dict):
        raise HTTPException(
            status_code=500,
            detail="Supabase returned an invalid payout response.",
        )

    error_details = {
        "vendor_not_found": (404, "Vendor not found."),
        "invalid_amount": (
            400,
            "Payout amount must be positive and have at most two decimals.",
        ),
        "invalid_reference": (
            400,
            "A transfer reference is required.",
        ),
        "duplicate_reference": (
            409,
            "This transfer reference is already recorded for the vendor.",
        ),
        "invalid_confirmed_earnings": (
            409,
            "The vendor has invalid confirmed earnings that require reconciliation.",
        ),
        "invalid_existing_payouts": (
            409,
            "The vendor has an invalid existing payout record that requires reconciliation.",
        ),
        "payouts_exceed_balance": (
            409,
            "Recorded payouts exceed confirmed vendor earnings.",
        ),
        "amount_exceeds_balance": (
            409,
            "Payout amount exceeds the vendor's available confirmed earnings.",
        ),
        "invalid_order_selection": (
            400,
            "Select only delivered, paid orders belonging to this vendor.",
        ),
        "order_already_paid": (
            409,
            "One or more selected orders have already been paid.",
        ),
        "amount_must_match_orders": (
            400,
            "Payout amount must equal the payable total of the selected orders.",
        ),
    }
    error = response.get("error")
    if isinstance(error, str) and error in error_details:
        status_code, detail = error_details[error]
        raise HTTPException(
            status_code=status_code,
            detail=detail,
        )

    payout = response.get("payout")
    if (
        not isinstance(payout, dict)
        or payout.get("status") != "paid"
        or str(payout.get("vendor_id")) != str(payload.vendor_id)
    ):
        raise HTTPException(
            status_code=500,
            detail="Supabase did not confirm the vendor payout record.",
        )

    return {
        "message": "Completed vendor payout recorded.",
        "payout": payout,
        "available_amount": response.get("available_amount"),
    }
