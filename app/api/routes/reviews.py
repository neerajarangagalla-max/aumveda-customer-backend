
import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.api.routes.orders import get_current_customer_id
from app.core.supabase import supabase

router = APIRouter(
    prefix="/reviews",
    tags=["Product Reviews"],
)

logger = logging.getLogger(__name__)


class CreateReviewRequest(BaseModel):
    product_id: UUID
    rating: int = Field(ge=1, le=5)
    title: str | None = Field(default=None, max_length=150)
    review_text: str | None = Field(default=None, max_length=3000)
    order_item_id: UUID | None = None


@router.post("", status_code=status.HTTP_201_CREATED)
def create_review(
    payload: CreateReviewRequest,
    customer_id: str = Depends(get_current_customer_id),
):
    try:
        if not payload.title and not payload.review_text:
            raise HTTPException(
                status_code=400,
                detail="Please provide a review title or written feedback.",
            )

        # Verify that the product exists.
        product_result = (
            supabase.table("products")
            .select("id")
            .eq("id", str(payload.product_id))
            .limit(1)
            .execute()
        )

        if not product_result.data:
            raise HTTPException(
                status_code=404,
                detail="Product not found.",
            )

       
        # Verify the purchase using the customer's orders and order items.
        orders_result = (
            supabase.table("orders")
            .select("id")
            .eq("customer_id", str(customer_id))
            .execute()
        )

        order_ids = [
            order["id"]
            for order in (orders_result.data or [])
        ]

        if not order_ids:
            raise HTTPException(
                status_code=403,
                detail="You must purchase this product before reviewing it.",
            )

        order_items_query = (
            supabase.table("order_items")
            .select("id, product_id, order_id")
            .in_("order_id", order_ids)
            .eq("product_id", str(payload.product_id))
        )

        if payload.order_item_id:
            order_items_query = order_items_query.eq(
                "id", str(payload.order_item_id)
            )

        purchased_items = order_items_query.limit(1).execute()

        if not purchased_items.data:
            logger.warning(
                "Review purchase check failed: customer_id=%s, "
                "product_id=%s, order_ids=%s",
                customer_id,
                payload.product_id,
                order_ids,
            )
            raise HTTPException(
                status_code=403,
                detail="No matching purchase was found for this product.",
            )

        verified_order_item_id = purchased_items.data[0]["id"]


        # Prevent multiple reviews for the same purchased item.
        existing_result = (
            supabase.table("product_reviews")
            .select("id")
            .eq("customer_id", customer_id)
            .eq("order_item_id", verified_order_item_id)
            .limit(1)
            .execute()
        )

        if existing_result.data:
            raise HTTPException(
                status_code=409,
                detail="You have already reviewed this purchased item.",
            )

        review_data = {
            "product_id": str(payload.product_id),
            "customer_id": customer_id,
            "order_item_id": verified_order_item_id,
            "rating": payload.rating,
            "title": payload.title.strip() if payload.title else None,
            "review_text": (
                payload.review_text.strip()
                if payload.review_text
                else None
            ),
            "status": "pending",
        }

        result = (
            supabase.table("product_reviews")
            .insert(review_data)
            .execute()
        )

        if not result.data:
            raise HTTPException(
                status_code=500,
                detail="The review could not be saved.",
            )

        return {
            "status": "success",
            "message": "Review submitted and awaiting approval.",
            "data": result.data[0],
        }

    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to submit product review")
        raise HTTPException(
            status_code=500,
            detail="Unable to submit review. Please try again.",
        ) from exc


@router.get("/product/{product_id}")
def get_product_reviews(product_id: UUID):
    try:
        result = (
            supabase.table("product_reviews")
            .select(
                "id, product_id, customer_id, rating, title, review_text, created_at"
            )
            .eq("product_id", str(product_id))
            .eq("status", "approved")
            .order("created_at", desc=True)
            .execute()
        )

        return {
            "status": "success",
            "count": len(result.data or []),
            "data": result.data or [],
        }

    except Exception as exc:
        logger.exception("Failed to retrieve product reviews")
        raise HTTPException(
            status_code=500,
            detail="Unable to retrieve product reviews.",
        ) from exc
