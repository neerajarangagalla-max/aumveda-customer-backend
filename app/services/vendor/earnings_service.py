
import logging

from decimal import (
    Decimal,
    InvalidOperation,
    ROUND_HALF_UP,
)

from uuid import UUID

from fastapi import HTTPException, status

from app.core.supabase import supabase_admin


logger = logging.getLogger(__name__)

CENT = Decimal("0.01")
PAGE_SIZE = 500
LOOKUP_BATCH_SIZE = 100

EXCLUDED_ORDER_STATUSES = {
    "cancelled",
    "returned",
}

EXCLUDED_ITEM_STATUSES = {
    "cancelled",
    "returned",
    "refunded",
}

EXCLUDED_PAYMENT_STATUSES = {
    "failed",
    "refunded",
    "partially_refunded",
}


# ============================================================
# VALIDATION AND MONEY HELPERS
# ============================================================

def _validate_uuid(value):
    try:
        return str(UUID(str(value)))

    except (TypeError, ValueError, AttributeError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid vendor ID.",
        )


def _decimal(value):
    try:
        amount = Decimal(str(value))

        if not amount.is_finite():
            raise ValueError(
                "Non-finite financial amount."
            )

        return amount

    except (
        TypeError,
        ValueError,
        InvalidOperation,
    ):
        raise HTTPException(
            status_code=500,
            detail="Invalid financial amount.",
        )


def _round_money(value):
    return value.quantize(
        CENT,
        rounding=ROUND_HALF_UP,
    )


def _money(value):
    return float(
        _round_money(value)
    )


# ============================================================
# PAGINATED DATABASE READ
# ============================================================

def _read_all(query_factory):
    """
    Load all matching records using pagination.

    Avoid silently calculating financial totals
    from only the first Supabase response page.
    """

    records = []
    offset = 0

    while True:
        result = (
            query_factory()
            .range(
                offset,
                offset + PAGE_SIZE - 1,
            )
            .execute()
        )

        batch = result.data or []

        records.extend(batch)

        if len(batch) < PAGE_SIZE:
            break

        offset += PAGE_SIZE

    return records


# ============================================================
# LOAD VENDOR ORDER ITEMS
# ============================================================

def _load_order_items(vendor_id):
    return _read_all(
        lambda: (
            supabase_admin
            .table("order_items")
            .select(
                "id,"
                "order_id,"
                "vendor_id,"
                "product_name,"
                "quantity,"
                "status,"
                "vendor_net_amount,"
                "created_at"
            )
            .eq("vendor_id", vendor_id)
            .order("id")
        )
    )


# ============================================================
# LOAD PARENT ORDERS
# ============================================================

def _load_orders(order_ids):
    orders = {}

    for offset in range(
        0,
        len(order_ids),
        LOOKUP_BATCH_SIZE,
    ):
        batch = order_ids[
            offset:offset + LOOKUP_BATCH_SIZE
        ]

        response = (
            supabase_admin
            .table("orders")
            .select(
                "id,"
                "order_number,"
                "status,"
                "payment_status,"
                "currency,"
                "created_at"
            )
            .in_("id", batch)
            .execute()
        )

        for order in response.data or []:
            orders[str(order["id"])] = order

    return orders


# ============================================================
# EARNINGS CALCULATION
# ============================================================

def _calculate_vendor_earnings(vendor_id):
    vendor_id = _validate_uuid(vendor_id)

    try:
        items = _load_order_items(
            vendor_id
        )

        if not items:
            return {
                "entries": [],
                "projected": Decimal("0.00"),
                "confirmed": Decimal("0.00"),
                "projected_count": 0,
                "confirmed_count": 0,
                "legacy_count": 0,
            }

        order_ids = list({
            str(item["order_id"])
            for item in items
        })

        orders = _load_orders(
            order_ids
        )

        projected = Decimal("0.00")
        confirmed = Decimal("0.00")

        projected_count = 0
        confirmed_count = 0
        legacy_count = 0

        entries = []

        for item in items:
            order = orders.get(
                str(item["order_id"])
            )

            if not order:
                # Avoid calculating earnings from
                # an order that cannot be verified.
                raise HTTPException(
                    status_code=500,
                    detail=(
                        "An order required for earnings "
                        "calculation could not be found."
                    ),
                )

            order_status = str(
                order.get("status") or ""
            ).lower()

            item_status = str(
                item.get("status") or ""
            ).lower()

            payment_status = str(
                order.get("payment_status") or ""
            ).lower()

            currency = str(
                order.get("currency") or "INR"
            ).upper()

            # Exclude cancelled, returned,
            # refunded and failed payments.
            if (
                order_status
                in EXCLUDED_ORDER_STATUSES
                or item_status
                in EXCLUDED_ITEM_STATUSES
                or payment_status
                in EXCLUDED_PAYMENT_STATUSES
            ):
                continue

            # Do not mix different currencies
            # in an INR financial summary.
            if currency != "INR":
                continue

            saved_net = item.get(
                "vendor_net_amount"
            )

            # Older orders did not have commission
            # snapshots. Never silently assign
            # today's commission to those orders.
            if saved_net is None:
                legacy_count += 1
                continue

            vendor_amount = _round_money(
                _decimal(saved_net)
            )

            if vendor_amount < 0:
                raise HTTPException(
                    status_code=500,
                    detail=(
                        "Negative vendor entitlement "
                        "found in order records."
                    ),
                )

            # Confirmed earnings require both:
            # 1. Item delivered
            # 2. Customer payment confirmed
            is_confirmed = (
                item_status == "delivered"
                and order_status == "delivered"
                and payment_status == "paid"
            )

            if is_confirmed:
                earning_status = "confirmed"
                confirmed += vendor_amount
                confirmed_count += 1

            else:
                earning_status = "projected"
                projected += vendor_amount
                projected_count += 1

            entries.append({
                "id": str(item["id"]),
                "order_item_id": str(item["id"]),
                "order_id": str(item["order_id"]),
                "order_number": order.get(
                    "order_number"
                ),
                "product_name": item.get(
                    "product_name"
                ),
                "quantity": item.get(
                    "quantity"
                ),
                "entry_type": "earning",
                "amount": _money(vendor_amount),
                "currency": "INR",
                "status": earning_status,
                "order_status": order_status,
                "item_status": item_status,
                "payment_status": payment_status,
                "created_at": item.get(
                    "created_at"
                ),
            })

        entries.sort(
            key=lambda entry:
                entry.get("created_at") or "",
            reverse=True,
        )

        return {
            "entries": entries,
            "projected": _round_money(
                projected
            ),
            "confirmed": _round_money(
                confirmed
            ),
            "projected_count": projected_count,
            "confirmed_count": confirmed_count,
            "legacy_count": legacy_count,
        }

    except HTTPException:
        raise

    except Exception as exc:
        logger.exception(
            "Vendor earnings calculation failed"
        )

        raise HTTPException(
            status_code=500,
            detail=(
                "Unable to calculate vendor earnings."
            ),
        ) from exc


# ============================================================
# VENDOR EARNINGS HISTORY
# ============================================================

def list_vendor_ledger_entries(
    vendor_id: str,
) -> list[dict]:
    """
    Read-only, calculated financial history.

    Uses immutable order-item net entitlements.

    Does not expose:
      - Admin commission revenue
      - Admin commission rates
      - Platform gross sales
      - Other vendors' earnings

    Note: These are calculated earning records,
    not entries persisted in vendor_ledger_entries.
    """

    result = _calculate_vendor_earnings(
        vendor_id
    )

    return result["entries"]


# ============================================================
# VENDOR EARNINGS SUMMARY
# ============================================================

def get_vendor_earnings_summary(
    vendor_id: str,
) -> dict:
    result = _calculate_vendor_earnings(
        vendor_id
    )

    confirmed = _money(
        result["confirmed"]
    )

    projected = _money(
        result["projected"]
    )

    return {
        # Existing API compatibility.
        # This represents confirmed calculated
        # earnings, not the actual ledger balance.
        "ledger_entry_count": (
            result["confirmed_count"]
        ),

        "net_ledger_amount": confirmed,

        "entry_type_totals": {
            "earning": confirmed,
        },

        # New vendor-facing fields.
        "confirmed_earnings": confirmed,

        "projected_earnings": projected,

        "confirmed_order_items": (
            result["confirmed_count"]
        ),

        "projected_order_items": (
            result["projected_count"]
        ),

        "unreconciled_legacy_items": (
            result["legacy_count"]
        ),

        "currency": "INR",

        "calculation_basis": (
            "order_item_commission_snapshots"
        ),

        "settlement_balance_verified": False,
    }
