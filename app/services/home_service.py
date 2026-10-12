import logging

from app.core.supabase import supabase_admin


logger = logging.getLogger(__name__)


AUMVEDA_LOGO_URL = (
    "https://zgohazzneofbxnmqnhcl.supabase.co/storage/v1/object/public/site_assets/branding/logo%20without%20bg.webp"
)


def get_hero():
    response = (
        supabase_admin
        .table("hero_banners")
        .select(
            """
            id,
            eyebrow,
            title_line1,
            title_line2,
            description,
            image_url,
            mobile_image_url,
            video_url,
            primary_cta_text,
            primary_cta_path,
            secondary_cta_text,
            secondary_cta_path
            """
        )
        .eq("is_active", True)
        .order("sort_order")
        .limit(1)
        .execute()
    )

    if not response.data:
        return None

    hero = response.data[0]

    hero["logo_url"] = AUMVEDA_LOGO_URL

    return hero

def get_categories():
    response = (
        supabase_admin
        .table("categories")
        .select(
            """
            id,
            name,
            slug,
            description,
            image_url,
            home_sort_order
            """
        )
        .eq("show_on_home", True)
        .eq("is_active", True)
        .order("home_sort_order")
        .execute()
    )

    return response.data or []


def get_featured_products():
    response = (
        supabase_admin
        .table("products")
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
        .eq("is_featured", True)
        .eq("status", "active")
        .order("created_at", desc=False)
        .execute()
    )

    products = []

    for product in response.data or []:

        variants = product.get("product_variants") or []
        images = product.get("product_images") or []

        # --------------------------------------------------
        # Default variant
        # --------------------------------------------------

        default_variant = next(
            (
                variant
                for variant in variants
                if variant.get("is_default") is True
            ),
            None,
        )

        # Fallback to first variant
        if default_variant is None and variants:
            default_variant = variants[0]

        # --------------------------------------------------
        # Primary image
        # --------------------------------------------------

        primary_image = next(
            (
                image
                for image in images
                if image.get("is_primary") is True
            ),
            None,
        )

        # Fallback to first image
        if primary_image is None and images:
            primary_image = images[0]

        # --------------------------------------------------
        # Product response
        # --------------------------------------------------

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
                    primary_image.get("image_url")
                    if primary_image
                    else None
                ),
            }
        )

    return products


def get_decorations():

    try:
        response = (
            supabase_admin
            .storage
            .from_("decorations")
            .list()
        )

        decorations = []

        # Safety check
        if not response:
            return []

        for file in response:

            if not isinstance(file, dict):
                continue

            file_name = file.get("name")

            if not file_name:
                continue

            # Skip folders
            if file.get("id") is None:
                continue

            public_url = (
                supabase_admin
                .storage
                .from_("decorations")
                .get_public_url(file_name)
            )

            decorations.append(
                {
                    "name": file_name,
                    "url": public_url,
                }
            )

        return decorations

    except Exception:
        logger.exception(
            "Failed to retrieve decorations from Supabase"
        )

        return []
# ============================================================
# WELLNESS BUNDLES
# ============================================================

def get_wellness_bundles():
    """
    Return active wellness bundles with their products.
    """

    response = (
        supabase_admin
        .table("wellness_bundles")
        .select(
            """
            id,
            name,
            description,
            image_url,
            discount_percentage,
            is_active,
            wellness_bundle_items(
                id,
                product_id,
                quantity,

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
            )
            """
        )
        .eq("is_active", True)
        .order("created_at", desc=False)
        .execute()
    )

    bundles = []

    for bundle in response.data or []:

        items = bundle.get(
            "wellness_bundle_items"
        ) or []

        products = []

        for item in items:

            product = item.get("products")

            if not product:
                continue

            # ----------------------------------------------
            # Only active products
            # ----------------------------------------------

            if product.get("status") != "active":
                continue

            variants = (
                product.get(
                    "product_variants"
                ) or []
            )

            images = (
                product.get(
                    "product_images"
                ) or []
            )

            # ----------------------------------------------
            # Default variant
            # ----------------------------------------------

            default_variant = next(
                (
                    variant
                    for variant in variants
                    if variant.get(
                        "is_default"
                    ) is True
                ),
                None,
            )

            if (
                default_variant is None
                and variants
            ):
                default_variant = variants[0]

            # ----------------------------------------------
            # Primary image
            # ----------------------------------------------

            primary_image = next(
                (
                    image
                    for image in images
                    if image.get(
                        "is_primary"
                    ) is True
                ),
                None,
            )

            if (
                primary_image is None
                and images
            ):
                primary_image = images[0]

            # ----------------------------------------------
            # Product data
            # ----------------------------------------------

            products.append(
                {
                    "id": product.get(
                        "id"
                    ),

                    "name": product.get(
                        "name"
                    ),

                    "slug": product.get(
                        "slug"
                    ),

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
                        default_variant.get(
                            "price"
                        )
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

                    "variant": (
                        default_variant
                    ),

                    "image": (
                        primary_image.get(
                            "image_url"
                        )
                        if primary_image
                        else None
                    ),

                    "quantity": item.get(
                        "quantity",
                        1,
                    ),
                }
            )

        # ----------------------------------------------
        # Skip empty bundles
        # ----------------------------------------------

        if not products:
            continue

        bundles.append(
            {
                "id": bundle.get(
                    "id"
                ),

                "name": bundle.get(
                    "name"
                ),

                "description": bundle.get(
                    "description"
                ),

                "image": bundle.get(
                    "image_url"
                ),

                "discount_percentage": bundle.get(
                    "discount_percentage",
                    0,
                ),

                "products": products,
            }
        )

    return bundles