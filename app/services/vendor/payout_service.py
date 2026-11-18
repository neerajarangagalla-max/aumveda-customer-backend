
from decimal import Decimal, InvalidOperation
from uuid import UUID
import logging

from fastapi import HTTPException, status

from app.core.supabase import supabase_admin


logger = logging.getLogger(__name__)


PAYOUT_STATUSES = {
    "pending",
    "processing",
    "paid",
    "failed",
}


# ============================================================
# INTERNAL HELPERS
# ============================================================

def _validate_uuid(value: str, field: str) -> str:
    try:
        return str(UUID(str(value)))
    except (TypeError, ValueError, AttributeError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid {field}.",
        )


def _money(value) -> Decimal:
    try:
        amount = Decimal(str(value if value is not None else 0))

        if not amount.is_finite():
            raise ValueError("Invalid monetary amount")

        return amount.quantize(Decimal("0.01"))

    except (InvalidOperation, ValueError, TypeError):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Invalid financial amount in payout records.",
        )


def _amount(value: Decimal) -> float:
    return float(value.quantize(Decimal("0.01")))


def _safe_payout(row: dict) -> dict:
    """
    Return vendor-facing payout fields only.

    Do not expose:
      - platform commission revenue
      - other vendors' payouts
      - internal administration notes
      - platform gross-sales calculations
    """

    return {
        "id": row.get("id"),
        "vendor_id": row.get("vendor_id"),
        "amount": _amount(_money(row.get("amount"))),
        "status": row.get("status"),
        "payment_reference": row.get("payment_reference"),
        "processed_at": row.get("processed_at"),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
    }


# ============================================================
# PAYOUT LIST
# ============================================================

def list_vendor_payouts(
    vendor_id: str,
) -> list[dict]:

    vendor_id = _validate_uuid(
        vendor_id,
        "vendor ID",
    )

    try:
        response = (
            supabase_admin
            .table("vendor_payouts")
            .select(
                "id,"
                "vendor_id,"
                "amount,"
                "status,"
                "payment_reference,"
                "processed_at,"
                "created_at,"
                "updated_at"
            )
            .eq("vendor_id", vendor_id)
            .order(
                "created_at",
                desc=True,
            )
            .execute()
        )

        return [
            _safe_payout(row)
            for row in (response.data or [])
        ]

    except HTTPException:
        raise

    except Exception as exc:
        logger.exception(
            "Unable to load vendor payouts"
        )

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to load vendor payouts.",
        ) from exc


# ============================================================
# PAYOUT DETAIL
# ============================================================

def get_vendor_payout(
    vendor_id: str,
    payout_id: str,
) -> dict:

    vendor_id = _validate_uuid(
        vendor_id,
        "vendor ID",
    )

    payout_id = _validate_uuid(
        payout_id,
        "payout ID",
    )

    try:
        response = (
            supabase_admin
            .table("vendor_payouts")
            .select(
                "id,"
                "vendor_id,"
                "amount,"
                "status,"
                "payment_reference,"
                "processed_at,"
                "created_at,"
                "updated_at"
            )
            .eq("id", payout_id)
            .eq("vendor_id", vendor_id)
            .limit(1)
            .execute()
        )

        rows = response.data or []

        if not rows:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Payout was not found.",
            )

        return _safe_payout(rows[0])

    except HTTPException:
        raise

    except Exception as exc:
        logger.exception(
            "Unable to load vendor payout details"
        )

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to load payout details.",
        ) from exc


# ============================================================
# PAYOUT SUMMARY
# ============================================================

def get_vendor_payout_summary(
    vendor_id: str,
) -> dict:
    """
    Reports only payout records.

    This is NOT the vendor earnings balance.

    pending_amount:
        Scheduled but not yet processed.

    processing_amount:
        Transfer in progress.

    paid_amount:
        Recorded as transferred by Admin.

    failed_amount:
        Failed payout attempts.
        Excluded from amounts due/paid.
    """

    payouts = list_vendor_payouts(vendor_id)

    amounts = {
        key: Decimal("0.00")
        for key in PAYOUT_STATUSES
    }

    counts = {
        key: 0
        for key in PAYOUT_STATUSES
    }

    for payout in payouts:
        payout_status = str(
            payout.get("status") or ""
        ).strip().lower()

        if payout_status not in PAYOUT_STATUSES:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Unknown payout status in financial records.",
            )

        payout_amount = _money(
            payout.get("amount")
        )

        if payout_amount < 0:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Invalid negative payout amount.",
            )

        amounts[payout_status] += payout_amount
        counts[payout_status] += 1

    pending_amount = amounts["pending"]
    processing_amount = amounts["processing"]
    paid_amount = amounts["paid"]
    failed_amount = amounts["failed"]

    scheduled_amount = (
        pending_amount + processing_amount
    )

    recorded_total = sum(
        amounts.values(),
        Decimal("0.00"),
    )

    return {
        "total_payouts": len(payouts),

        # Amount recorded as transferred by Admin.
        "paid_payouts": counts["paid"],
        "paid_amount": _amount(paid_amount),

        # Scheduled, not yet transferred.
        "pending_payouts": counts["pending"],
        "pending_amount": _amount(pending_amount),

        # In-progress transfers.
        "processing_payouts": counts["processing"],
        "processing_amount": _amount(processing_amount),

        # Failed transfers, reported separately.
        "failed_payouts": counts["failed"],
        "failed_amount": _amount(failed_amount),

        # Pending + processing only.
        "scheduled_amount": _amount(scheduled_amount),

        # All recorded payout attempts, including failed.
        # Not equivalent to total earnings.
        "total_recorded_amount": _amount(recorded_total),

        # Compatibility with the previous API shape.
        # This is NOT the earnings balance.
        "total_net_amount": _amount(recorded_total),
    }
