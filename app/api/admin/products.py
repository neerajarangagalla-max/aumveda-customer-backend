
from datetime import datetime, timezone
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query

from app.core.security import get_current_admin
from app.core.supabase import supabase
from app.schemas.admin.products import (
    AdminProductCreate,
    AdminProductUpdate,
)

router = APIRouter(
    prefix="/admin/products",
    tags=["Admin Products"],
    dependencies=[Depends(get_current_admin)],
)

ProductStatus = Literal[
    "draft", "pending", "active", "rejected", "archived"
]


def _database_error(exc: Exception) -> HTTPException:
    message = str(exc).lower()

    if "product_not_found" in message:
        return HTTPException(404, "Product not found")

    if "duplicate key" in message or "unique constraint" in message:
        return HTTPException(
            409, "A product slug or variant SKU already exists"
        )

    if (
        "foreign key" in message
        or "invalid input syntax for type uuid" in message
    ):
        return HTTPException(400, "Invalid product, vendor, or category ID")

    if "compare-at price" in message or "primary image" in message:
        return HTTPException(422, str(exc))

    return HTTPException(500, "Product operation failed")


@router.get("")
def list_products(
    status_filter: ProductStatus | None = Query(
        default=None, alias="status"
    ),
    search: str | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    try:
        query = supabase.table("products").select("*", count="exact")

        if status_filter:
            query = query.eq("status", status_filter)

        if search and search.strip():
            query = query.ilike("name", f"%{search.strip()}%")

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
            500, "Unable to retrieve products"
        ) from exc


@router.get("/{product_id}")
def get_product(product_id: UUID):
    try:
        result = (
            supabase.table("products")
            .select("*, product_images(*), product_variants(*)")
            .eq("id", str(product_id))
            .maybe_single()
            .execute()
        )

        if not result.data:
            raise HTTPException(404, "Product not found")

        return result.data
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            500, "Unable to retrieve product"
        ) from exc


@router.post("", status_code=201)
def create_product(payload: AdminProductCreate):
    try:
        result = supabase.rpc(
            "admin_create_product",
            {
                "p_product": payload.model_dump(
                    exclude={"variants", "images"},
                    mode="json",
                ),
                "p_variants": [
                    item.model_dump(mode="json")
                    for item in payload.variants
                ],
                "p_images": [
                    item.model_dump(mode="json")
                    for item in payload.images
                ],
            },
        ).execute()

        if not result.data:
            raise HTTPException(
                500, "Product creation returned no result"
            )

        return {
            "message": "Product created successfully",
            **result.data,
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise _database_error(exc) from exc


@router.patch("/{product_id}")
def update_product(
    product_id: UUID,
    payload: AdminProductUpdate,
):
    try:
        changes = payload.model_dump(
            exclude_unset=True,
            exclude={"variants", "images"},
            mode="json",
        )

        for field in (
            "category_id", "name", "slug", "status", "is_featured"
        ):
            if field in changes and changes[field] is None:
                raise HTTPException(
                    422, f"{field} cannot be null"
                )

        result = supabase.rpc(
            "admin_update_product",
            {
                "p_product_id": str(product_id),
                "p_changes": changes,
                "p_variants": (
                    [
                        item.model_dump(mode="json")
                        for item in payload.variants
                    ]
                    if "variants" in payload.model_fields_set
                    else None
                ),
                "p_images": (
                    [
                        item.model_dump(mode="json")
                        for item in payload.images
                    ]
                    if "images" in payload.model_fields_set
                    else None
                ),
            },
        ).execute()

        if not result.data:
            raise HTTPException(
                500, "Product update returned no result"
            )

        return {
            "message": "Product updated successfully",
            **result.data,
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise _database_error(exc) from exc


@router.patch("/{product_id}/status")
def update_product_status(
    product_id: UUID,
    new_status: ProductStatus,
):
    try:
        result = (
            supabase.table("products")
            .update({
                "status": new_status,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            })
            .eq("id", str(product_id))
            .execute()
        )

        if not result.data:
            raise HTTPException(404, "Product not found")

        return {
            "message": "Product status updated",
            "product": result.data[0],
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            500, "Unable to update product status"
        ) from exc


@router.delete("/{product_id}")
def archive_product(product_id: UUID):
    try:
        result = (
            supabase.table("products")
            .update({
                "status": "archived",
                "updated_at": datetime.now(timezone.utc).isoformat(),
            })
            .eq("id", str(product_id))
            .execute()
        )

        if not result.data:
            raise HTTPException(404, "Product not found")

        return {
            "message": "Product archived successfully",
            "product": result.data[0],
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            500, "Unable to archive product"
        ) from exc
