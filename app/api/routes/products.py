from fastapi import APIRouter, HTTPException

from app.core.supabase import supabase
import logging

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/products",
    tags=["Products"]
)


# ============================================================
# GET ALL ACTIVE PRODUCTS
# ============================================================

@router.get("")
def get_products(limit: int = 20, offset: int = 0):

    try:

        # Keep the page size within reasonable limits.
        limit = max(1, min(limit, 50))
        offset = max(0, offset)

        response = (
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
            .order("name")
            .range(offset, offset + limit - 1)
            .execute()
        )

        products = []

        for product in response.data:

            # ------------------------------------------------
            # PRIMARY IMAGE
            # ------------------------------------------------

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


            # ------------------------------------------------
            # DEFAULT ACTIVE VARIANT
            # ------------------------------------------------

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


            # ------------------------------------------------
            # FINAL FRONTEND RESPONSE
            # ------------------------------------------------

            products.append({

                "id": product.get("id"),

                "vendor_id": product.get("vendor_id"),

                "category_id": product.get("category_id"),

                "name": product.get("name"),

                "slug": product.get("slug"),

                "short_description":
                    product.get("short_description"),

                "description":
                    product.get("description"),

                "image": image_url,

                "price": price,

                "compare_at_price":
                    compare_at_price,

                "rating":
                    product.get("average_rating"),

                "review_count":
                    product.get("review_count"),

                "is_featured":
                    product.get("is_featured", False),

                "variant_id":
                    variant_id,

                "variant_name":
                    variant_name,

                "stock_quantity":
                    stock_quantity,

                "in_stock":
                    stock_quantity > 0

            })


        return products


    except Exception:
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
            .select(
                "id,name,parent_id"
            )
            .order(
                "name"
            )
            .execute()
        )

        return response.data


    except Exception:
        raise HTTPException(
            status_code=500,
            detail="Unable to retrieve categories.",
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
            .eq(
                "slug",
                slug
            )
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

        raise HTTPException(
            status_code=404,
            detail="Product not found"
        )