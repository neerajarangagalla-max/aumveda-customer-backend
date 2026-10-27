
import logging
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.core.security import get_current_admin
from app.core.supabase import supabase


logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/admin/inventory",
    tags=["Admin Inventory"],
    dependencies=[Depends(get_current_admin)],
)


class InventoryAdjustmentRequest(BaseModel):
    variant_id: str
    action: Literal["add", "remove"]
    quantity: int = Field(gt=0)
    notes: str | None = Field(default=None, max_length=500)


def enrich_transaction_items(items: list[dict]) -> list[dict]:
    """Attach product and variant details to inventory transactions."""
    if not items:
        return items

    variant_ids = list({
        item["variant_id"]
        for item in items
        if item.get("variant_id")
    })

    variants_by_id = {}

    if variant_ids:
        variants_result = (
            supabase.table("product_variants")
            .select("id, product_id, sku, name")
            .in_("id", variant_ids)
            .execute()
        )

        variants_by_id = {
            variant["id"]: variant
            for variant in (variants_result.data or [])
        }

    product_ids = list({
        variant["product_id"]
        for variant in variants_by_id.values()
        if variant.get("product_id")
    })

    products_by_id = {}

    if product_ids:
        products_result = (
            supabase.table("products")
            .select("id, name")
            .in_("id", product_ids)
            .execute()
        )

        products_by_id = {
            product["id"]: product
            for product in (products_result.data or [])
        }

    enriched_items = []

    for item in items:
        transaction = dict(item)
        variant = variants_by_id.get(item.get("variant_id"), {})
        product = products_by_id.get(variant.get("product_id"), {})

        transaction["product_name"] = (
            product.get("name") or "Unknown product"
        )
        transaction["variant_name"] = (
            variant.get("name") or "Unknown variant"
        )
        transaction["sku"] = variant.get("sku")

        enriched_items.append(transaction)

    return enriched_items


@router.get("/transactions")
def list_inventory_transactions(
    variant_id: str | None = None,
    vendor_id: str | None = None,
    transaction_type: str | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    try:
        query = supabase.table("inventory_transactions").select(
            "*", count="exact"
        )

        if variant_id:
            query = query.eq("variant_id", variant_id)

        if vendor_id:
            query = query.eq("vendor_id", vendor_id)

        if transaction_type:
            query = query.eq("transaction_type", transaction_type)

        result = (
            query.order("created_at", desc=True)
            .range(offset, offset + limit - 1)
            .execute()
        )

        items = enrich_transaction_items(result.data or [])

        return {
            "items": items,
            "total": result.count or 0,
            "limit": limit,
            "offset": offset,
        }

    except Exception as exc:
        logger.exception("Unable to retrieve inventory transactions")
        raise HTTPException(
            status_code=500,
            detail="Unable to retrieve inventory transactions",
        ) from exc


@router.get("/transactions/{transaction_id}")
def get_inventory_transaction(transaction_id: str):
    try:
        result = (
            supabase.table("inventory_transactions")
            .select("*")
            .eq("id", transaction_id)
            .maybe_single()
            .execute()
        )

        if not result.data:
            raise HTTPException(
                status_code=404,
                detail="Inventory transaction not found",
            )

        enriched = enrich_transaction_items([result.data])
        return enriched[0]

    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Unable to retrieve inventory transaction")
        raise HTTPException(
            status_code=500,
            detail="Unable to retrieve inventory transaction",
        ) from exc


@router.get("/stock")
def list_inventory_stock(
    search: str | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    try:
        query = supabase.table("product_variants").select(
            "id, product_id, sku, name, price, "
            "stock_quantity, is_active, attributes",
            count="exact",
        )

        if search and search.strip():
            term = search.strip()
            query = query.or_(
                f"sku.ilike.%{term}%,name.ilike.%{term}%"
            )

        result = (
            query.order("name")
            .range(offset, offset + limit - 1)
            .execute()
        )

        items = result.data or []

        product_ids = list({
            item["product_id"]
            for item in items
            if item.get("product_id")
        })

        product_names = {}

        if product_ids:
            products_result = (
                supabase.table("products")
                .select("id, name")
                .in_("id", product_ids)
                .execute()
            )

            product_names = {
                product["id"]: product.get("name", "Unnamed product")
                for product in (products_result.data or [])
            }

        for item in items:
            item["product_name"] = product_names.get(
                item.get("product_id"),
                "Unknown product",
            )

        return {
            "items": items,
            "total": result.count or 0,
            "limit": limit,
            "offset": offset,
        }

    except Exception as exc:
        logger.exception("Unable to retrieve inventory stock")
        raise HTTPException(
            status_code=500,
            detail="Unable to retrieve inventory stock",
        ) from exc


@router.post("/stock/adjust")
def adjust_inventory_stock(payload: InventoryAdjustmentRequest):
    try:
        result = supabase.rpc(
            "adjust_inventory_stock",
            {
                "p_variant_id": payload.variant_id,
                "p_action": payload.action,
                "p_quantity": payload.quantity,
                "p_notes": payload.notes,
            },
        ).execute()

        return result.data

    except Exception as exc:
        logger.exception("Inventory stock adjustment failed")
        message = str(exc)

        if "Insufficient stock" in message:
            raise HTTPException(status_code=400, detail=message)

        if "Product variant not found" in message:
            raise HTTPException(status_code=404, detail=message)

        if (
            "Action must be" in message
            or "Quantity must be" in message
        ):
            raise HTTPException(status_code=400, detail=message)

        if "no vendor assigned" in message:
            raise HTTPException(status_code=400, detail=message)

        raise HTTPException(
            status_code=500,
            detail="Unable to adjust inventory stock",
        ) from exc
