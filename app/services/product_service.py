from app.core.supabase import supabase_admin


def _normalize_product(product):
    variants = product.get("product_variants") or []
    images = product.get("product_images") or []

    default_variant = next(
        (variant for variant in variants if variant.get("is_default")),
        None,
    )
    primary_image = next(
        (image for image in images if image.get("is_primary")),
        None,
    )

    return {
        "id": product.get("id"),
        "name": product.get("name"),
        "slug": product.get("slug"),
        "description": product.get("short_description") or product.get("description"),
        "rating": product.get("average_rating", 0),
        "review_count": product.get("review_count", 0),
        "price": default_variant.get("price") if default_variant else None,
        "compare_at_price": (
            default_variant.get("compare_at_price") if default_variant else None
        ),
        "variant": default_variant,
        "image": primary_image.get("image_url") if primary_image else None,
        "category_id": product.get("category_id"),
        "status": product.get("status"),
        "is_featured": product.get("is_featured"),
    }


def get_products(search=None, category_id=None, limit=20, offset=0):
    query = (
        supabase_admin.table("products")
        .select(
            """
            id,
            name,
            slug,
            short_description,
            description,
            average_rating,
            review_count,
            category_id,
            status,
            is_featured,
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
            """
        )
        .range(offset, offset + limit - 1)
    )

    if search:
        query = query.ilike("name", f"%{search}%")

    if category_id:
        query = query.eq("category_id", category_id)

    response = query.execute()
    return [_normalize_product(item) for item in (response.data or [])]


def get_product_by_slug(slug: str):
    response = (
        supabase_admin.table("products")
        .select(
            """
            id,
            name,
            slug,
            short_description,
            description,
            average_rating,
            review_count,
            category_id,
            status,
            is_featured,
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
            """
        )
        .eq("slug", slug)
        .limit(1)
        .execute()
    )

    data = response.data or []
    if not data:
        return None
    return _normalize_product(data[0])


def get_related_products(product_id: str, limit: int = 6):
    response = (
        supabase_admin.table("products")
        .select(
            """
            id,
            name,
            slug,
            short_description,
            average_rating,
            review_count,
            product_variants(
                id,
                name,
                price,
                compare_at_price,
                is_default
            ),
            product_images(
                id,
                image_url,
                is_primary
            )
            """
        )
        .neq("id", product_id)
        .limit(limit)
        .execute()
    )

    return [_normalize_product(item) for item in (response.data or [])]
