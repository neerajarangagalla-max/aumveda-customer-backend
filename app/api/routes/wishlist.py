
import logging

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.supabase import supabase

router = APIRouter(
    prefix="/wishlist",
    tags=["Wishlist"],
)

logger = logging.getLogger(__name__)

security = HTTPBearer(
    auto_error=False,
)

WISHLIST_TABLE = "wishlist_items"


def get_current_customer_id(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
) -> str:
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication scheme.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    access_token = credentials.credentials

    try:
        auth_response = supabase.auth.get_user(access_token)
        user = getattr(auth_response, "user", None)
        user_id = getattr(user, "id", None)
    except Exception:
        logger.exception("Supabase access token validation failed")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired authentication token.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token.",
        )

    try:
        profile_response = (
            supabase
            .table("profiles")
            .select("id,role,is_active")
            .eq("id", user_id)
            .limit(1)
            .execute()
        )
    except Exception:
        logger.exception("Failed to load customer profile")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to verify customer profile.",
        )

    profiles = profile_response.data or []

    if not profiles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Customer profile not found. Please sign in again.",
        )

    profile = profiles[0]

    if profile.get("role") != "customer":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This account is not a customer account.",
        )

    if profile.get("is_active") is False:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Customer account is inactive.",
        )

    return user_id


def _add_to_wishlist(customer_id: str, product_id: str):
    existing = (
        supabase
        .table(WISHLIST_TABLE)
        .select("id, customer_id, product_id, created_at")
        .eq("customer_id", customer_id)
        .eq("product_id", product_id)
        .limit(1)
        .execute()
    )

    existing_data = existing.data or []

    if existing_data:
        return existing_data[0]

    response = (
        supabase
        .table(WISHLIST_TABLE)
        .insert({
            "customer_id": customer_id,
            "product_id": product_id,
        })
        .execute()
    )

    data = response.data or []
    return data[0] if data else None


def _remove_from_wishlist(customer_id: str, product_id: str):
    response = (
        supabase
        .table(WISHLIST_TABLE)
        .delete()
        .eq("customer_id", customer_id)
        .eq("product_id", product_id)
        .execute()
    )

    return bool(response.data)


def _is_product_in_wishlist(customer_id: str, product_id: str):
    response = (
        supabase
        .table(WISHLIST_TABLE)
        .select("id")
        .eq("customer_id", customer_id)
        .eq("product_id", product_id)
        .limit(1)
        .execute()
    )

    return bool(response.data)


def _get_customer_wishlist(customer_id: str, limit: int = 50):
    response = (
        supabase
        .table(WISHLIST_TABLE)
        .select(
            """
            id,
            customer_id,
            product_id,
            created_at,
            products(
                id,
                name,
                slug,
                short_description,
                average_rating,
                review_count,
                status,
                product_variants(
                    id,
                    name,
                    price,
                    compare_at_price,
                    stock_quantity,
                    attributes
                ),
                product_images(
                    id,
                    image_url,
                    alt_text,
                    is_primary,
                    sort_order
                )
            )
            """
        )
        .eq("customer_id", customer_id)
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )

    records = response.data or []
    products = []

    for record in records:
        product = record.get("products")

        if not product or product.get("status") != "active":
            continue

        variants = product.get("product_variants") or []
        images = product.get("product_images") or []

        default_variant = next(
            (
                variant
                for variant in variants
                if (variant.get("attributes") or {}).get("is_default") is True
            ),
            None,
        )

        if default_variant is None and variants:
            default_variant = variants[0]

        primary_image = next(
            (
                image
                for image in images
                if image.get("is_primary") is True
            ),
            None,
        )

        if primary_image is None and images:
            primary_image = images[0]

        products.append({
            "id": product.get("id"),
            "name": product.get("name"),
            "slug": product.get("slug"),
            "description": product.get("short_description"),
            "rating": product.get("average_rating", 0),
            "review_count": product.get("review_count", 0),
            "price": (
                default_variant.get("price")
                if default_variant else None
            ),
            "compare_at_price": (
                default_variant.get("compare_at_price")
                if default_variant else None
            ),
            "variant": default_variant,
            "image": (
                primary_image.get("image_url")
                if primary_image else None
            ),
            "wishlist_item_id": record.get("id"),
            "created_at": record.get("created_at"),
        })

    return products


@router.get("")
async def get_wishlist(
    customer_id: str = Depends(get_current_customer_id),
):
    try:
        products = _get_customer_wishlist(customer_id)

        return {
            "status": "success",
            "count": len(products),
            "data": products,
        }

    except Exception:
        logger.exception("Wishlist retrieval failed")
        raise HTTPException(
            status_code=500,
            detail="Unable to retrieve wishlist.",
        )


@router.post("/{product_id}")
async def add_product_to_wishlist(
    product_id: str,
    customer_id: str = Depends(get_current_customer_id),
):
    try:
        item = _add_to_wishlist(customer_id, product_id)

        if item is None:
            raise HTTPException(
                status_code=500,
                detail="Unable to add product to wishlist.",
            )

        return {
            "status": "success",
            "message": "Product added to wishlist",
            "data": item,
        }

    except HTTPException:
        raise
    except Exception:
        logger.exception("Adding wishlist item failed")
        raise HTTPException(
            status_code=500,
            detail="Unable to add product to wishlist.",
        )


@router.delete("/{product_id}")
async def delete_product_from_wishlist(
    product_id: str,
    customer_id: str = Depends(get_current_customer_id),
):
    try:
        removed = _remove_from_wishlist(customer_id, product_id)

        return {
            "status": "success",
            "message": (
                "Product removed from wishlist"
                if removed
                else "Product was not in wishlist"
            ),
            "data": {
                "removed": removed,
                "product_id": product_id,
            },
        }

    except Exception:
        logger.exception("Removing wishlist item failed")
        raise HTTPException(
            status_code=500,
            detail="Unable to remove product from wishlist.",
        )


@router.get("/{product_id}/status")
async def get_wishlist_status(
    product_id: str,
    customer_id: str = Depends(get_current_customer_id),
):
    try:
        wishlisted = _is_product_in_wishlist(
            customer_id,
            product_id,
        )

        return {
            "status": "success",
            "data": {
                "product_id": product_id,
                "wishlisted": wishlisted,
            },
        }

    except Exception:
        logger.exception("Wishlist status lookup failed")
        raise HTTPException(
            status_code=500,
            detail="Unable to retrieve wishlist status.",
        )
