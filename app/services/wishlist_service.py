import logging

from app.core.supabase import supabase_admin

logger = logging.getLogger(__name__)


def add_to_wishlist(customer_id: str, product_id: str):
    # Check whether the product is already in the wishlist
    existing = (
        supabase_admin
        .table("wishlist_items")
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
        supabase_admin
        .table("wishlist_items")
        .insert(
            {
                "customer_id": customer_id,
                "product_id": product_id,
            }
        )
        .execute()
    )

    data = response.data or []

    return data[0] if data else None


def remove_from_wishlist(customer_id: str, product_id: str):
    response = (
        supabase_admin
        .table("wishlist_items")
        .delete()
        .eq("customer_id", customer_id)
        .eq("product_id", product_id)
        .execute()
    )

    return bool(response.data)


def is_product_in_wishlist(customer_id: str, product_id: str):
    response = (
        supabase_admin
        .table("wishlist_items")
        .select("id")
        .eq("customer_id", customer_id)
        .eq("product_id", product_id)
        .limit(1)
        .execute()
    )

    return bool(response.data)


def get_customer_wishlist(customer_id: str, limit: int = 50):
    response = (
        supabase_admin
        .table("wishlist_items")
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
        .eq("customer_id", customer_id)
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )

    records = response.data or []
    products = []

    for record in records:
        product = record.get("products")

        if not product:
            continue

        if product.get("status") != "active":
            continue

        variants = product.get("product_variants") or []
        images = product.get("product_images") or []

        default_variant = next(
            (
                variant
                for variant in variants
                if variant.get("is_default") is True
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

        products.append(
            {
                "id": product.get("id"),
                "name": product.get("name"),
                "slug": product.get("slug"),
                "description": product.get("short_description"),
                "rating": product.get("average_rating", 0),
                "review_count": product.get("review_count", 0),
                "price": (
                    default_variant.get("price")
                    if default_variant
                    else None
                ),
                "compare_at_price": (
                    default_variant.get("compare_at_price")
                    if default_variant
                    else None
                ),
                "variant": default_variant,
                "image": (
                    primary_image.get("image_url")
                    if primary_image
                    else None
                ),
                "wishlist_item_id": record.get("id"),
                "created_at": record.get("created_at"),
            }
        )

    return products