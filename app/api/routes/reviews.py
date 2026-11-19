
import logging
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, Field, ValidationError
from starlette.datastructures import UploadFile as StarletteUploadFile

from app.api.routes.orders import (
    execute_supabase_read,
    get_current_customer_id,
)
from app.core.supabase import supabase, supabase_admin
from app.services.vendor.product_image_service import (
    ALLOWED_IMAGE_TYPES,
    MAX_IMAGE_SIZE_BYTES,
    PRODUCT_IMAGE_BUCKET,
)

router = APIRouter(
    prefix="/reviews",
    tags=["Product Reviews"],
)

logger = logging.getLogger(__name__)

REVIEW_IMAGE_TYPES = {
    "image/jpeg": (".jpg", b"\xff\xd8\xff"),
    "image/jpg": (".jpg", b"\xff\xd8\xff"),
    "image/png": (".png", b"\x89PNG\r\n\x1a\n"),
    "image/webp": (".webp", None),
}


class CreateReviewRequest(BaseModel):
    product_id: UUID
    rating: int = Field(ge=1, le=5)
    title: str | None = Field(default=None, max_length=150)
    review_text: str | None = Field(default=None, max_length=3000)
    order_item_id: UUID | None = None


async def _parse_review_request(
    request: Request,
) -> tuple[CreateReviewRequest, StarletteUploadFile | None]:
    content_type = request.headers.get("content-type", "").lower()
    image_file = None

    if content_type.startswith("multipart/form-data"):
        form = await request.form()
        payload_data = {
            "product_id": form.get("product_id"),
            "rating": form.get("rating"),
            "title": form.get("title"),
            "review_text": form.get("review_text"),
            "order_item_id": form.get("order_item_id"),
        }
        image_file = form.get("image")
        if image_file is not None and not isinstance(
            image_file,
            StarletteUploadFile,
        ):
            raise HTTPException(
                status_code=422,
                detail="The review image upload is invalid.",
            )
    else:
        try:
            payload_data = await request.json()
        except ValueError as exc:
            raise RequestValidationError(
                [
                    {
                        "type": "json_invalid",
                        "loc": ("body",),
                        "msg": "Invalid JSON body.",
                        "input": None,
                    }
                ]
            ) from exc

    try:
        payload = CreateReviewRequest.model_validate(payload_data)
    except ValidationError as exc:
        raise RequestValidationError(exc.errors()) from exc

    return payload, image_file


async def _read_review_image(
    image_file: StarletteUploadFile,
) -> tuple[bytes, str, str]:
    content_type = str(image_file.content_type or "").lower()
    image_type = REVIEW_IMAGE_TYPES.get(content_type)
    if content_type not in ALLOWED_IMAGE_TYPES or image_type is None:
        raise HTTPException(
            status_code=415,
            detail="Choose a JPEG, PNG, or WebP image.",
        )

    image_bytes = await image_file.read(
        MAX_IMAGE_SIZE_BYTES + 1
    )
    if not image_bytes:
        raise HTTPException(
            status_code=400,
            detail="The selected review image is empty.",
        )
    if len(image_bytes) > MAX_IMAGE_SIZE_BYTES:
        raise HTTPException(
            status_code=413,
            detail=(
                "Review images must be no larger than "
                f"{MAX_IMAGE_SIZE_BYTES // (1024 * 1024)} MB."
            ),
        )

    extension, signature = image_type
    if signature is not None and not image_bytes.startswith(signature):
        raise HTTPException(
            status_code=415,
            detail="The selected file is not a valid image.",
        )
    if content_type == "image/webp" and (
        len(image_bytes) < 12
        or image_bytes[:4] != b"RIFF"
        or image_bytes[8:12] != b"WEBP"
    ):
        raise HTTPException(
            status_code=415,
            detail="The selected file is not a valid image.",
        )

    return image_bytes, content_type, extension


def _remove_review_image(storage_path: str) -> None:
    try:
        supabase_admin.storage.from_(
            PRODUCT_IMAGE_BUCKET
        ).remove([storage_path])
    except Exception:
        logger.exception(
            "Could not clean up review image %s",
            storage_path,
        )


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_review(
    request: Request,
    customer_id: str = Depends(get_current_customer_id),
):
    image_storage_path = None
    review_saved = False

    try:
        payload, image_file = await _parse_review_request(request)

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
            .eq("status", "delivered")
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

        image_url = None
        if image_file:
            image_bytes, content_type, extension = (
                await _read_review_image(image_file)
            )
            image_storage_path = (
                f"reviews/{uuid4().hex}{extension}"
            )
            try:
                supabase_admin.storage.from_(
                    PRODUCT_IMAGE_BUCKET
                ).upload(
                    image_storage_path,
                    image_bytes,
                    file_options={
                        "content-type": content_type,
                        "upsert": "false",
                    },
                )
                public_url = supabase_admin.storage.from_(
                    PRODUCT_IMAGE_BUCKET
                ).get_public_url(image_storage_path)
                if isinstance(public_url, dict):
                    image_url = (
                        public_url.get("publicUrl")
                        or public_url.get("public_url")
                    )
                else:
                    image_url = str(public_url)
                if not image_url:
                    raise RuntimeError(
                        "Supabase did not return a public review image URL."
                    )
            except Exception as exc:
                _remove_review_image(image_storage_path)
                image_storage_path = None
                raise HTTPException(
                    status_code=500,
                    detail="Unable to upload the review image.",
                ) from exc

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
            "image_url": image_url,
            "status": "approved",
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

        review_saved = True
        return {
            "status": "success",
            "message": "Your review is published and now visible.",
            "data": result.data[0],
        }

    except HTTPException:
        if image_storage_path and not review_saved:
            _remove_review_image(image_storage_path)
        raise
    except RequestValidationError:
        raise
    except Exception as exc:
        if image_storage_path and not review_saved:
            _remove_review_image(image_storage_path)
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
                "id, product_id, rating, title, review_text, "
                "image_url, created_at"
            )
            .eq("product_id", str(product_id))
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


@router.get("/order/{order_id}")
def get_customer_order_reviews(
    order_id: UUID,
    customer_id: str = Depends(get_current_customer_id),
):
    try:
        order_result = execute_supabase_read(
            supabase.table("orders")
            .select("id")
            .eq("id", str(order_id))
            .eq("customer_id", str(customer_id))
            .limit(1)
        )

        if not order_result.data:
            raise HTTPException(
                status_code=404,
                detail="Order not found.",
            )

        order_items_result = execute_supabase_read(
            supabase.table("order_items")
            .select("id")
            .eq("order_id", str(order_id))
        )
        order_item_ids = [
            str(item["id"])
            for item in order_items_result.data or []
            if item.get("id")
        ]

        reviews = []
        if order_item_ids:
            reviews_result = execute_supabase_read(
                supabase.table("product_reviews")
                .select(
                    "id, order_item_id, product_id, rating, title, "
                    "review_text, image_url, created_at"
                )
                .eq("customer_id", str(customer_id))
                .in_("order_item_id", order_item_ids)
                .order("created_at", desc=True)
            )
            reviews = reviews_result.data or []

        return {
            "status": "success",
            "count": len(reviews),
            "data": reviews,
        }

    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to retrieve customer order reviews")
        raise HTTPException(
            status_code=500,
            detail="Unable to retrieve order reviews.",
        ) from exc
