
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


def database_error(exc: Exception) -> HTTPException:
    message = str(exc).lower()

    if "duplicate key" in message or "unique constraint" in message:
        return HTTPException(
            status_code=409,
            detail="A coupon with this code already exists.",
        )

    return HTTPException(
        status_code=500,
        detail="Coupon operation failed.",
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

    return result.data


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
            "items": result.data or [],
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
        data = payload.model_dump(mode="json")

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

        return {
            "message": "Coupon created successfully.",
            "coupon": result.data[0],
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

        if not changes:
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

        return {
            "message": "Coupon updated successfully.",
            "coupon": result.data[0],
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
