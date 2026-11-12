import logging
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Depends

from app.core.supabase import supabase
from app.core.security import get_current_user


logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/products",
    tags=["Products"]
)


# Compatibility router for the Customer Web contract.
# It reuses the existing recently-viewed helpers above; no second
# recently-viewed business-logic implementation is introduced.
recently_viewed_router = APIRouter(
    prefix="/recently-viewed",
    tags=["Recently Viewed"],
)


# ============================================================
# RECENTLY VIEWED HELPER FUNCTIONS
# ============================================================

def record_product_view(customer_id: str, product_id: str):
    """
    Insert or update a recently viewed product for a customer.
    """

    viewed_at = datetime.now(timezone.utc).isoformat()

    response = (
        supabase
        .table("recently_viewed_products")
        .upsert(
            {
                "customer_id": customer_id,
                "product_id": product_id,
                "viewed_at": viewed_at,
            },
            on_conflict="customer_id,product_id",
        )
        .execute()
    )

    return response.data[0] if response.data else None


def get_recently_viewed_products(
    customer_id: str,
    limit: int = 10
):
    """
    Retrieve recently viewed active products for a customer.
    """

    response = (
        supabase
        .table("recently_viewed_products")
        .select(
            """
            product_id,
            viewed_at,
            products(
                id,
                vendor_id,
                category_id,
                name,
                slug,
                short_description,
                status,
                is_featured,
                average_rating,
                review_count,
                product_images(
                    image_url,
                    alt_text,
                    sort_order,
                    is_primary
                ),
                product_variants(
                    id,
                    name,
                    price,
                    compare_at_price,
                    stock_quantity,
                    attributes,
                    is_active
                )
            )
            """
        )
        .eq("customer_id", customer_id)
        .order("viewed_at", desc=True)
        .limit(limit)
        .execute()
    )

    recently_viewed = []

    for item in response.data or []:

        product = item.get("products")

        if isinstance(product, list):
            product = product[0] if product else None

        if not product:
            continue

        if product.get("status") != "active":
            continue

        # Get primary product image.
        images = product.get("product_images") or []

        images = sorted(
            images,
            key=lambda image: (
                not image.get("is_primary", False),
                image.get("sort_order") or 9999
            )
        )

        image_url = images[0].get("image_url") if images else None

        # Get active product variants.
        variants = product.get("product_variants") or []

        active_variants = [
            variant
            for variant in variants
            if variant.get("is_active", False)
        ]

        default_variant = next(
            (
                variant
                for variant in active_variants
                if (variant.get("attributes") or {}).get(
                    "is_default"
                ) is True
            ),
            None
        )

        if default_variant is None and active_variants:
            default_variant = active_variants[0]

        price = None
        compare_at_price = None
        stock_quantity = 0
        variant_id = None
        variant_name = None

        if default_variant:

            variant_id = default_variant.get("id")
            variant_name = default_variant.get("name")
            price = default_variant.get("price")

            compare_at_price = default_variant.get(
                "compare_at_price"
            )

            stock_quantity = (
                default_variant.get("stock_quantity") or 0
            )

        recently_viewed.append(
            {
                "id": product.get("id"),
                "vendor_id": product.get("vendor_id"),
                "category_id": product.get("category_id"),
                "name": product.get("name"),
                "slug": product.get("slug"),
                "short_description": product.get(
                    "short_description"
                ),
                "image": image_url,
                "price": price,
                "compare_at_price": compare_at_price,
                "rating": product.get("average_rating"),
                "review_count": product.get("review_count"),
                "is_featured": product.get(
                    "is_featured", False
                ),
                "variant_id": variant_id,
                "variant_name": variant_name,
                "stock_quantity": stock_quantity,
                "in_stock": stock_quantity > 0,
                "viewed_at": item.get("viewed_at"),
            }
        )

    return recently_viewed


# ============================================================
# GET ALL ACTIVE PRODUCTS
# ============================================================

@router.get("")
def get_products(
    limit: int = 20,
    offset: int = 0,
    category_id: str | None = None,
    subcategory_id: str | None = None,
):

    try:

        # Validate subcategory if supplied.
        if subcategory_id:

            subcategory_response = (
                supabase
                .table("categories")
                .select("id, parent_id, is_active")
                .eq("id", subcategory_id)
                .eq("is_active", True)
                .limit(1)
                .execute()
            )

            subcategories = subcategory_response.data or []

            if not subcategories:
                raise HTTPException(
                    status_code=404,
                    detail="Subcategory not found.",
                )

            selected_subcategory = subcategories[0]

            if not selected_subcategory.get("parent_id"):
                raise HTTPException(
                    status_code=400,
                    detail="The selected category is not a subcategory.",
                )

            if (
                category_id
                and selected_subcategory["parent_id"] != category_id
            ):
                raise HTTPException(
                    status_code=400,
                    detail="Subcategory does not belong to this category.",
                )

        # Keep the page size within reasonable limits.
        limit = max(1, min(limit, 50))
        offset = max(0, offset)

        query = (
            supabase
            .table("products")
            .select(
                """
                id,
                vendor_id,
                category_id,
                name,
                slug,
                short_description,
                status,
                is_featured,
                average_rating,
                review_count,
                product_images(
                    image_url,
                    alt_text,
                    sort_order,
                    is_primary
                ),
                product_variants(
                    id,
                    name,
                    price,
                    compare_at_price,
                    stock_quantity,
                    attributes,
                    is_active
                )
                """,
                count="none",
            )
            .eq("status", "active")
        )

        if subcategory_id:

            query = query.eq("category_id", subcategory_id)

        elif category_id:

            category_response = (
                supabase
                .table("categories")
                .select("id,is_active")
                .eq("id", category_id)
                .eq("is_active", True)
                .limit(1)
                .execute()
            )

            if not category_response.data:
                raise HTTPException(
                    status_code=404,
                    detail="Category not found.",
                )

            subcategory_response = (
                supabase
                .table("categories")
                .select("id")
                .eq("parent_id", category_id)
                .eq("is_active", True)
                .execute()
            )

            category_ids = [category_id] + [
                category["id"]
                for category in subcategory_response.data or []
            ]

            query = query.in_("category_id", category_ids)

        response = (
            query
            .order("name")
            .range(offset, offset + limit - 1)
            .execute()
        )

        products = []

        for product in response.data or []:

            # PRIMARY IMAGE

            images = product.get("product_images") or []

            images = sorted(
                images,
                key=lambda image: (
                    not image.get("is_primary", False),
                    image.get("sort_order") or 9999
                )
            )

            image_url = None

            if images:
                image_url = images[0].get("image_url")

            # DEFAULT ACTIVE VARIANT

            variants = product.get("product_variants") or []

            active_variants = [
                variant
                for variant in variants
                if variant.get("is_active", False)
            ]

            default_variant = next(
                (
                    variant
                    for variant in active_variants
                    if (variant.get("attributes") or {}).get(
                        "is_default"
                    ) is True
                ),
                None
            )

            if default_variant is None and active_variants:
                default_variant = active_variants[0]

            price = None
            compare_at_price = None
            stock_quantity = 0
            variant_id = None
            variant_name = None

            if default_variant:

                variant_id = default_variant.get("id")
                variant_name = default_variant.get("name")
                price = default_variant.get("price")

                compare_at_price = default_variant.get(
                    "compare_at_price"
                )

                stock_quantity = (
                    default_variant.get("stock_quantity") or 0
                )

            # FINAL FRONTEND RESPONSE

            products.append(
                {
                    "id": product.get("id"),
                    "vendor_id": product.get("vendor_id"),
                    "category_id": product.get("category_id"),
                    "name": product.get("name"),
                    "slug": product.get("slug"),
                    "short_description": product.get(
                        "short_description"
                    ),
                    "description": product.get("description"),
                    "image": image_url,
                    "price": price,
                    "compare_at_price": compare_at_price,
                    "rating": product.get("average_rating"),
                    "review_count": product.get("review_count"),
                    "is_featured": product.get(
                        "is_featured", False
                    ),
                    "variant_id": variant_id,
                    "variant_name": variant_name,
                    "stock_quantity": stock_quantity,
                    "in_stock": stock_quantity > 0
                }
            )

        return products

    except HTTPException:
        raise

    except Exception:
        logger.exception("Products API failed")

        raise HTTPException(
            status_code=500,
            detail="Unable to retrieve products.",
        )


# ============================================================
# GET CATEGORIES
# ============================================================

@router.get("/categories")
def get_categories():

    try:

        response = (
            supabase
            .table("categories")
            .select("id,name,parent_id")
            .eq("is_active", True)
            .order("name")
            .execute()
        )

        return response.data

    except Exception:

        logger.exception("Categories API failed")

        raise HTTPException(
            status_code=500,
            detail="Unable to retrieve categories.",
        )


# ============================================================
# GET RECENTLY VIEWED PRODUCTS
# IMPORTANT: Keep this BEFORE /{slug}
# ============================================================

@router.get("/recently-viewed")
def recently_viewed_products(
    limit: int = 10,
    user=Depends(get_current_user),
):

    try:

        limit = max(1, min(limit, 20))

        products = get_recently_viewed_products(
            customer_id=str(user.id),
            limit=limit,
        )

        return {
            "status": "success",
            "data": products,
        }

    except HTTPException:
        raise

    except Exception:

        logger.exception(
            "Unable to retrieve recently viewed products"
        )

        raise HTTPException(
            status_code=500,
            detail="Unable to retrieve recently viewed products.",
        )


# ============================================================
# CUSTOMER WEB COMPATIBILITY: RECENTLY VIEWED
# ============================================================

@recently_viewed_router.get("")
def get_recently_viewed_compat(
    limit: int = 10,
    user=Depends(get_current_user),
):
    try:
        limit = max(1, min(limit, 20))
        products = get_recently_viewed_products(
            customer_id=str(user.id),
            limit=limit,
        )
        return {
            "status": "success",
            "count": len(products),
            "data": products,
        }
    except HTTPException:
        raise
    except Exception:
        logger.exception("Unable to retrieve recently viewed products")
        raise HTTPException(
            status_code=500,
            detail="Unable to retrieve recently viewed products.",
        )


@recently_viewed_router.post("/{product_id}")
def record_recently_viewed_compat(
    product_id: str,
    user=Depends(get_current_user),
):
    try:
        product_response = (
            supabase
            .table("products")
            .select("id")
            .eq("id", product_id)
            .eq("status", "active")
            .limit(1)
            .execute()
        )

        if not product_response.data:
            raise HTTPException(
                status_code=404,
                detail="Product not found.",
            )

        result = record_product_view(
            customer_id=str(user.id),
            product_id=product_id,
        )

        return {
            "status": "success",
            "message": "Product view recorded.",
            "data": result,
        }
    except HTTPException:
        raise
    except Exception:
        logger.exception("Unable to record recently viewed product")
        raise HTTPException(
            status_code=500,
            detail="Unable to record product view.",
        )


# ============================================================
# GET PRODUCT BY SLUG
# ============================================================

@router.get("/{slug}")
def get_product_by_slug(slug: str):

    try:

        response = (
            supabase
            .table("products")
            .select(
                """
                *,
                product_images(*),
                product_variants(*)
                """
            )
            .eq("slug", slug)
            .eq("status", "active")
            .single()
            .execute()
        )

        if not response.data:

            raise HTTPException(
                status_code=404,
                detail="Product not found"
            )

        return response.data

    except HTTPException:
        raise

    except Exception:

        logger.exception("Unable to retrieve product by slug")

        raise HTTPException(
            status_code=404,
            detail="Product not found"
        )


# ============================================================
# RECORD RECENTLY VIEWED PRODUCT
# ============================================================

@router.post("/{product_id}/view")
def track_product_view(
    product_id: str,
    user=Depends(get_current_user),
):

    try:

        # Check whether the product exists and is active.
        product_response = (
            supabase
            .table("products")
            .select("id")
            .eq("id", product_id)
            .eq("status", "active")
            .limit(1)
            .execute()
        )

        if not product_response.data:

            raise HTTPException(
                status_code=404,
                detail="Product not found.",
            )

        # Record the product view.
        result = record_product_view(
            customer_id=str(user.id),
            product_id=product_id,
        )

        return {
            "status": "success",
            "message": "Product view recorded.",
            "data": result,
        }

    except HTTPException:
        raise

    except Exception:

        logger.exception("Unable to record product view")

        raise HTTPException(
            status_code=500,
            detail="Unable to record product view.",
        )