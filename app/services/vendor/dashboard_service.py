
from fastapi import HTTPException, status

from app.core.supabase import supabase_admin


def get_vendor_dashboard(vendor_id: str) -> dict:
    try:
        # -----------------------------------------------------
        # PRODUCTS
        # -----------------------------------------------------
        products_response = (
            supabase_admin
            .table("products")
            .select("id, status")
            .eq("vendor_id", vendor_id)
            .execute()
        )

        products = products_response.data or []

        total_products = len(products)

        active_products = sum(
            1
            for item in products
            if item.get("status") == "active"
        )

        draft_products = sum(
            1
            for item in products
            if item.get("status") == "draft"
        )

        # -----------------------------------------------------
        # ORDER ITEMS
        # -----------------------------------------------------
        # The actual database column is total_price,
        # not line_total.
        order_items_response = (
            supabase_admin
            .table("order_items")
            .select(
                "id, order_id, quantity, total_price, status, created_at"
            )
            .eq("vendor_id", vendor_id)
            .execute()
        )

        order_items = order_items_response.data or []

        total_order_items = len(order_items)

        pending_order_items = sum(
            1
            for item in order_items
            if item.get("status") == "pending"
        )

        unique_order_ids = {
            item.get("order_id")
            for item in order_items
            if item.get("order_id")
        }

        total_orders = len(unique_order_ids)

        # -----------------------------------------------------
        # LEDGER / EARNINGS
        # -----------------------------------------------------
        ledger_response = (
            supabase_admin
            .table("vendor_ledger_entries")
            .select("entry_type, amount")
            .eq("vendor_id", vendor_id)
            .execute()
        )

        ledger_entries = ledger_response.data or []

        # Preserves the existing dashboard calculation.
        # We will verify ledger entry semantics separately.
        ledger_total = sum(
            float(item.get("amount") or 0)
            for item in ledger_entries
        )

        # -----------------------------------------------------
        # PAYOUTS
        # -----------------------------------------------------
        # The actual database column is amount,
        # not net_amount.
        payouts_response = (
            supabase_admin
            .table("vendor_payouts")
            .select("id, amount, status")
            .eq("vendor_id", vendor_id)
            .execute()
        )

        payouts = payouts_response.data or []

        pending_payout_amount = sum(
            float(item.get("amount") or 0)
            for item in payouts
            if item.get("status") == "pending"
        )

        paid_payout_amount = sum(
            float(item.get("amount") or 0)
            for item in payouts
            if item.get("status") == "paid"
        )

        # -----------------------------------------------------
        # RESPONSE
        # -----------------------------------------------------
        # Keep the existing response structure unchanged
        # so Vendor Web remains compatible.
        return {
            "products": {
                "total": total_products,
                "active": active_products,
                "draft": draft_products,
            },
            "orders": {
                "total_orders": total_orders,
                "total_order_items": total_order_items,
                "pending_order_items": pending_order_items,
            },
            "earnings": {
                "ledger_total": ledger_total,
                "pending_payout": pending_payout_amount,
                "paid_payout": paid_payout_amount,
            },
        }

    except HTTPException:
        raise

    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Unable to load vendor dashboard: {str(exc)}",
        ) from exc
