
from datetime import datetime, timezone
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.core.security import get_current_admin
from app.core.supabase import supabase


router = APIRouter(
    prefix="/admin/coupons",
    tags=["Admin Coupons"],
    dependencies=[Depends(get_current_admin)],
)

DiscountType = Literal["percentage", "fixed_amount"]


class CouponCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=3, max_length=40)
    description: str | None = None

    discount_type: DiscountType
    discount_value: float = Field(gt=0)

    min_order_value: float = Field(default=0, ge=0)
    max_discount_amount: float | None = Field(default=None, gt=0)

    starts_at: datetime
    expires_at: datetime

    usage_limit: int | None = Field(default=None, gt=0)
    per_customer_limit: int = Field(default=1, gt=0)

    first_order_only: bool = False
    is_active: bool = True
    product_ids: list[UUID] = Field(default_factory=list)
    category_ids: list[UUID] = Field(default_factory=list)
    display_locations: list[
        Literal["home", "cart", "checkout", "product_details"]
    ] = Field(default_factory=list)

    @field_validator("code")
    @classmethod
    def normalize_code(cls, value: str) -> str:
        value = value.strip().upper()

        if not all(c.isalnum() or c in "_-" for c in value):
            raise ValueError(
                "Coupon code may contain only letters, numbers, "
                "hyphens and underscores."
            )

        return value

    @field_validator("product_ids", "category_ids")
    @classmethod
    def unique_target_ids(cls, value: list[UUID]) -> list[UUID]:
        return list(dict.fromkeys(value))

    @model_validator(mode="after")
    def validate_coupon(self):
        if self.discount_type == "percentage" and self.discount_value > 100:
            raise ValueError("Percentage discount cannot exceed 100.")

        if self.expires_at <= self.starts_at:
            raise ValueError("Expiry must be later than the start date.")

        return self


class CouponUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str | None = Field(default=None, min_length=3, max_length=40)
    description: str | None = None

    discount_type: DiscountType | None = None
    discount_value: float | None = Field(default=None, gt=0)

    min_order_value: float | None = Field(default=None, ge=0)
    max_discount_amount: float | None = Field(default=None, gt=0)

    starts_at: datetime | None = None
    expires_at: datetime | None = None

    usage_limit: int | None = Field(default=None, gt=0)
    per_customer_limit: int | None = Field(default=None, gt=0)

    first_order_only: bool | None = None
    is_active: bool | None = None
    product_ids: list[UUID] | None = None
    category_ids: list[UUID] | None = None
    display_locations: list[
        Literal["home", "cart", "checkout", "product_details"]
    ] | None = None

    @field_validator("code")
    @classmethod
    def normalize_code(cls, value: str | None) -> str | None:
        if value is None:
            return None

        value = value.strip().upper()

        if not all(c.isalnum() or c in "_-" for c in value):
            raise ValueError(
                "Coupon code may contain only letters, numbers, "
                "hyphens and underscores."
            )

        return value

    @field_validator("product_ids", "category_ids")
    @classmethod
    def unique_target_ids(
        cls,
        value: list[UUID] | None,
    ) -> list[UUID] | None:
        return list(dict.fromkeys(value)) if value is not None else None


def database_error(exc: Exception) -> HTTPException:
    message = str(exc).lower()

    if "duplicate key" in message or "unique constraint" in message:
        return HTTPException(
            status_code=409,
            detail="A coupon with this code already exists.",
        )

    if "foreign key" in message or "invalid input syntax for type uuid" in message:
        return HTTPException(
            status_code=422,
            detail="One or more selected products or categories no longer exist.",
        )

    return HTTPException(
        status_code=500,
        detail="Coupon operation failed.",
    )


def load_coupon_targets(coupons: list[dict]) -> list[dict]:
    if not coupons:
        return []

    coupon_ids = [str(coupon["id"]) for coupon in coupons]
    product_rows = (
        supabase
        .table("coupon_products")
        .select("coupon_id,product_id")
        .in_("coupon_id", coupon_ids)
        .execute()
        .data
        or []
    )
    category_rows = (
        supabase
        .table("coupon_categories")
        .select("coupon_id,category_id")
        .in_("coupon_id", coupon_ids)
        .execute()
        .data
        or []
    )

    products_by_coupon: dict[str, list[str]] = {}
    categories_by_coupon: dict[str, list[str]] = {}
    for row in product_rows:
        products_by_coupon.setdefault(row["coupon_id"], []).append(
            row["product_id"]
        )
    for row in category_rows:
        categories_by_coupon.setdefault(row["coupon_id"], []).append(
            row["category_id"]
        )

    return [
        {
            **coupon,
            "product_ids": products_by_coupon.get(str(coupon["id"]), []),
            "category_ids": categories_by_coupon.get(str(coupon["id"]), []),
        }
        for coupon in coupons
    ]


def replace_coupon_targets(
    coupon_id: UUID | str,
    product_ids: list[UUID] | None,
    category_ids: list[UUID] | None,
):
    (
        supabase
        .rpc(
            "set_coupon_targets",
            {
                "p_coupon_id": str(coupon_id),
                "p_product_ids": [str(value) for value in product_ids or []],
                "p_category_ids": [
                    str(value) for value in category_ids or []
                ],
            },
        )
        .execute()
    )


def get_coupon(coupon_id: UUID):
    result = (
        supabase.table("coupons")
        .select("*")
        .eq("id", str(coupon_id))
        .maybe_single()
        .execute()
    )

    if not result.data:
        raise HTTPException(404, "Coupon not found.")

    return load_coupon_targets([result.data])[0]


def validate_dates(starts_at, expires_at):
    if starts_at and expires_at and expires_at <= starts_at:
        raise HTTPException(
            422,
            "Expiry date must be later than the start date.",
        )


@router.get("")
def list_coupons(
    search: str | None = None,
    is_active: bool | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    try:
        query = supabase.table("coupons").select("*", count="exact")

        if is_active is not None:
            query = query.eq("is_active", is_active)

        if search and search.strip():
            term = search.strip()
            query = query.ilike("code", f"%{term}%")

        result = (
            query.order("created_at", desc=True)
            .range(offset, offset + limit - 1)
            .execute()
        )

        return {
            "items": load_coupon_targets(result.data or []),
            "total": result.count or 0,
            "limit": limit,
            "offset": offset,
        }

    except Exception as exc:
        raise HTTPException(
            500,
            "Unable to retrieve coupons.",
        ) from exc


@router.get("/{coupon_id}")
def get_coupon_details(coupon_id: UUID):
    try:
        return get_coupon(coupon_id)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            500,
            "Unable to retrieve coupon.",
        ) from exc


@router.post("", status_code=201)
def create_coupon(payload: CouponCreate):
    try:
        data = payload.model_dump(
            mode="json",
            exclude={"product_ids", "category_ids"},
        )

        result = (
            supabase.table("coupons")
            .insert(data)
            .execute()
        )

        if not result.data:
            raise HTTPException(
                500,
                "Coupon was not created.",
            )

        coupon = result.data[0]
        try:
            replace_coupon_targets(
                coupon["id"],
                payload.product_ids,
                payload.category_ids,
            )
        except Exception:
            (
                supabase
                .table("coupons")
                .delete()
                .eq("id", coupon["id"])
                .execute()
            )
            raise

        return {
            "message": "Coupon created successfully.",
            "coupon": get_coupon(UUID(coupon["id"])),
        }

    except HTTPException:
        raise
    except Exception as exc:
        raise database_error(exc) from exc


@router.patch("/{coupon_id}")
def update_coupon(
    coupon_id: UUID,
    payload: CouponUpdate,
):
    try:
        existing = get_coupon(coupon_id)

        changes = payload.model_dump(
            mode="json",
            exclude_unset=True,
        )
        product_ids = changes.pop(
            "product_ids",
            existing.get("product_ids", []),
        )
        category_ids = changes.pop(
            "category_ids",
            existing.get("category_ids", []),
        )
        targets_changed = (
            "product_ids" in payload.model_fields_set
            or "category_ids" in payload.model_fields_set
        )

        if not changes and not targets_changed:
            raise HTTPException(
                422,
                "No coupon changes were provided.",
            )

        merged = {**existing, **changes}

        if (
            merged["discount_type"] == "percentage"
            and float(merged["discount_value"]) > 100
        ):
            raise HTTPException(
                422,
                "Percentage discount cannot exceed 100.",
            )

        validate_dates(
            merged["starts_at"],
            merged["expires_at"],
        )

        if changes:
            changes["updated_at"] = datetime.now(
                timezone.utc
            ).isoformat()

            result = (
                supabase.table("coupons")
                .update(changes)
                .eq("id", str(coupon_id))
                .select("*")
                .execute()
            )

            if not result.data:
                raise HTTPException(
                    404,
                    "Coupon not found or not updated.",
                )

        if targets_changed:
            replace_coupon_targets(
                coupon_id,
                product_ids,
                category_ids,
            )

        return {
            "message": "Coupon updated successfully.",
            "coupon": get_coupon(coupon_id),
        }

    except HTTPException:
        raise
    except Exception as exc:
        raise database_error(exc) from exc


@router.patch("/{coupon_id}/active")
def update_coupon_active_status(
    coupon_id: UUID,
    is_active: bool,
):
    try:
        get_coupon(coupon_id)

        result = (
            supabase.table("coupons")
            .update({
                "is_active": is_active,
                "updated_at": datetime.now(
                    timezone.utc
                ).isoformat(),
            })
            .eq("id", str(coupon_id))
            .select("*")
            .execute()
        )

        if not result.data:
            raise HTTPException(
                404,
                "Coupon not found or not updated.",
            )

        return {
            "message": "Coupon status updated successfully.",
            "coupon": result.data[0],
        }

    except HTTPException:
        raise
    except Exception as exc:
        raise database_error(exc) from exc
