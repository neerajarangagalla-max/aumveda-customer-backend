import logging
from datetime import datetime, timezone

from app.core.supabase import supabase_admin


logger = logging.getLogger(__name__)


# ============================================================
# PRODUCT VIEW
# ============================================================

def record_product_view(customer_id: str, product_id: str):
    """
    Create or update a recently viewed product record.

    If the customer has already viewed the product,
    update viewed_at instead of creating a duplicate record.
    """

    viewed_at = datetime.now(timezone.utc).isoformat()

    # --------------------------------------------------------
    # Check whether the product was already viewed
    # --------------------------------------------------------

    existing = (
        supabase_admin
        .table("recently_viewed_products")
        .select("id")
        .eq("customer_id", customer_id)
        .eq("product_id", product_id)
        .limit(1)
        .execute()
    )

    existing_data = existing.data or []

    # --------------------------------------------------------
    # Existing record → update viewed_at
    # --------------------------------------------------------

    if existing_data:

        response = (
            supabase_admin
            .table("recently_viewed_products")
            .update(
                {
                    "viewed_at": viewed_at
                }
            )
            .eq(
                "id",
                existing_data[0]["id"]
            )
            .execute()
        )

        data = response.data or []

        return data[0] if data else None

    # --------------------------------------------------------
    # New record
    # --------------------------------------------------------

    response = (
        supabase_admin
        .table("recently_viewed_products")
        .insert(
            {
                "customer_id": customer_id,
                "product_id": product_id,
                "viewed_at": viewed_at,
            }
        )
        .execute()
    )

    data = response.data or []

    return data[0] if data else None


# ============================================================
# RECENTLY VIEWED PRODUCTS
# ============================================================

def get_recently_viewed_products(
    customer_id: str,
    limit: int = 10,
):
    """
    Return the customer's most recently viewed
    active products.
    """

    response = (
        supabase_admin
        .table("recently_viewed_products")
        .select(
            """
            id,
            customer_id,
            product_id,
            viewed_at,

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
                    is_default
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
        .eq(
            "customer_id",
            customer_id
        )
        .order(
            "viewed_at",
            desc=True
        )
        .limit(limit)
        .execute()
    )

    records = response.data or []

    products = []

    # ========================================================
    # PROCESS PRODUCTS
    # ========================================================

    for record in records:

        product = record.get("products")

        if not product:
            continue

        # ----------------------------------------------------
        # Only active products
        # ----------------------------------------------------

        if product.get("status") != "active":
            continue

        variants = (
            product.get("product_variants")
            or []
        )

        images = (
            product.get("product_images")
            or []
        )

        # ----------------------------------------------------
        # Find default variant
        # ----------------------------------------------------

        default_variant = next(
            (
                variant
                for variant in variants
                if variant.get("is_default") is True
            ),
            None,
        )

        # If no default variant exists,
        # use the first available variant.

        if (
            default_variant is None
            and variants
        ):
            default_variant = variants[0]

        # ----------------------------------------------------
        # Find primary image
        # ----------------------------------------------------

        primary_image = next(
            (
                image
                for image in images
                if image.get("is_primary") is True
            ),
            None,
        )

        # If no primary image exists,
        # use the first image.

        if (
            primary_image is None
            and images
        ):
            primary_image = images[0]

        # ----------------------------------------------------
        # Build product response
        # ----------------------------------------------------

        products.append(
            {
                "id": product.get("id"),

                "name": product.get("name"),

                "slug": product.get("slug"),

                "description": product.get(
                    "short_description"
                ),

                "rating": product.get(
                    "average_rating",
                    0,
                ),

                "review_count": product.get(
                    "review_count",
                    0,
                ),

                "price": (
                    default_variant.get("price")
                    if default_variant
                    else None
                ),

                "compare_at_price": (
                    default_variant.get(
                        "compare_at_price"
                    )
                    if default_variant
                    else None
                ),

                "variant": default_variant,

                "image": (
                    primary_image.get(
                        "image_url"
                    )
                    if primary_image
                    else None
                ),

                "viewed_at": record.get(
                    "viewed_at"
                ),
            }
        )

    return products