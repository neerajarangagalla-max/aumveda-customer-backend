import logging
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query, status

from app.core.supabase import supabase


router = APIRouter(
    prefix="/home",
    tags=["Home"],
)

logger = logging.getLogger(__name__)


# ============================================================
# HOMEPAGE CMS CONFIGURATION HELPERS
# ============================================================

PRODUCT_SECTION_TYPES = {
    "product_carousel",
}

CATEGORY_SECTION_TYPES = {
    "category_circles",
    "category_tiles",
}

MAX_SECTION_PRODUCTS = 100


def parse_datetime(value):
    if not value:
        return None

    if isinstance(value, datetime):
        result = value
    else:
        try:
            result = datetime.fromisoformat(
                str(value).replace("Z", "+00:00")
            )
        except (TypeError, ValueError):
            return None

    if result.tzinfo is None:
        result = result.replace(
            tzinfo=timezone.utc
        )

    return result.astimezone(timezone.utc)


def is_published(record, now):
    if record.get("publish_status") != "published":
        return False

    if record.get("is_visible") is not True:
        return False

    start_raw = record.get("starts_at")
    end_raw = record.get("ends_at")

    start = parse_datetime(start_raw)
    end = parse_datetime(end_raw)

    if start_raw and start is None:
        return False

    if end_raw and end is None:
        return False

    if start and now < start:
        return False

    if end and now >= end:
        return False

    return True


def safe_object(value):
    return value if isinstance(value, dict) else {}


def safe_limit(value):
    try:
        return min(
            max(int(value), 1),
            MAX_SECTION_PRODUCTS,
        )
    except (TypeError, ValueError):
        return 12


def to_number(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def public_item(item):
    fields = (
        "id",
        "item_key",
        "item_type",
        "title",
        "subtitle",
        "description",
        "eyebrow",
        "image_url",
        "mobile_image_url",
        "video_url",
        "alt_text",
        "badge_text",
        "badge_style",
        "primary_cta_text",
        "primary_cta_url",
        "secondary_cta_text",
        "secondary_cta_url",
        "target_type",
        "target_id",
        "target_url",
        "sort_order",
    )

    result = {
        field: item.get(field)
        for field in fields
    }

    result["style_config"] = safe_object(
        item.get("style_config")
    )

    result["metadata"] = safe_object(
        item.get("metadata")
    )

    return result


def selected_target_ids(items, target_type):
    """
    Preserve Admin-defined homepage item order.
    Duplicate selections are ignored.
    """

    seen = set()
    result = []

    for item in items:
        if item.get("target_type") != target_type:
            continue

        target_id = item.get("target_id")

        if not target_id:
            continue

        if target_id in seen:
            continue

        seen.add(target_id)
        result.append(target_id)

    return result


# ============================================================
# CATEGORY RESOLUTION
# ============================================================

def resolve_categories(section, items):
    """
    Only explicitly selected active categories are shown
    for manual category sections.

    This prevents unexpectedly showing every category
    before Admin has configured the homepage.
    """

    category_ids = selected_target_ids(
        items,
        "category",
    )

    if not category_ids:
        return []

    response = (
        supabase
        .table("categories")
        .select(
            "id,name,slug,description,image_url,"
            "parent_id,sort_order"
        )
        .in_("id", category_ids)
        .eq("is_active", True)
        .execute()
    )

    indexed = {
        str(category["id"]): category
        for category in response.data or []
    }

    result = []

    for category_id in category_ids:
        category = indexed.get(
            str(category_id)
        )

        if category:
            result.append(category)

    return result


# ============================================================
# PRODUCT CATALOG HELPERS
# ============================================================

def load_product_variants(product_ids):
    if not product_ids:
        return {}

    response = (
        supabase
        .table("product_variants")
        .select(
            "id,product_id,sku,name,price,"
            "compare_at_price,stock_quantity,"
            "attributes,is_active"
        )
        .in_("product_id", product_ids)
        .eq("is_active", True)
        .execute()
    )

    grouped = {}

    for variant in response.data or []:
        if variant.get("price") is None:
            continue

        if to_number(
            variant["price"]
        ) < 0:
            continue

        grouped.setdefault(
            str(variant["product_id"]),
            [],
        ).append(variant)

    return grouped


def load_product_images(product_ids):
    if not product_ids:
        return {}

    response = (
        supabase
        .table("product_images")
        .select(
            "id,product_id,image_url,alt_text,"
            "is_primary,sort_order"
        )
        .in_("product_id", product_ids)
        .order("sort_order")
        .execute()
    )

    grouped = {}

    for image in response.data or []:
        grouped.setdefault(
            str(image["product_id"]),
            [],
        ).append(image)

    return grouped


def choose_variant(
    variants,
    require_discount=False,
):
    if not variants:
        return None

    eligible = []

    for variant in variants:
        price = to_number(
            variant.get("price")
        )

        compare_price = to_number(
            variant.get("compare_at_price")
        )

        if (
            require_discount
            and compare_price <= price
        ):
            continue

        eligible.append(variant)

    if not eligible:
        return None

    # Prefer the default variant.
    for variant in eligible:
        attributes = safe_object(
            variant.get("attributes")
        )

        if attributes.get(
            "is_default"
        ) is True:
            return variant

    # Deterministic fallback.
    return sorted(
        eligible,
        key=lambda variant: (
            to_number(
                variant.get("price")
            ),
            str(
                variant.get("id", "")
            ),
        ),
    )[0]


def choose_image(images):
    if not images:
        return None

    sorted_images = sorted(
        images,
        key=lambda image: (
            not bool(
                image.get("is_primary")
            ),
            image.get("sort_order")
            if image.get("sort_order")
            is not None
            else 999999,
        ),
    )

    return sorted_images[0]


def serialize_product(
    product,
    variant,
    image,
):
    price = to_number(
        variant.get("price")
    )

    raw_compare_price = variant.get(
        "compare_at_price"
    )

    compare_price = (
        to_number(raw_compare_price)
        if raw_compare_price is not None
        else None
    )

    discount_percentage = 0

    if (
        compare_price
        and compare_price > price
    ):
        discount_percentage = round(
            (
                compare_price - price
            )
            / compare_price
            * 100
        )

    stock_quantity = int(
        to_number(
            variant.get(
                "stock_quantity"
            )
        )
    )

    return {
        "id": product["id"],
        "name": product.get("name"),
        "slug": product.get("slug"),
        "description": product.get(
            "short_description"
        ),
        "category_id": product.get(
            "category_id"
        ),
        "rating": product.get(
            "average_rating"
        ) or 0,
        "review_count": product.get(
            "review_count"
        ) or 0,
        "is_featured": bool(
            product.get(
                "is_featured"
            )
        ),
        "price": price,
        "compare_at_price": compare_price,
        "discount_percentage": (
            discount_percentage
        ),
        "variant": variant,
        "image": (
            image.get("image_url")
            if image
            else None
        ),
        "image_alt": (
            image.get("alt_text")
            if image
            else None
        ),
        "stock_quantity": stock_quantity,
        "in_stock": stock_quantity > 0,
    }


def fetch_product_candidates(
    section,
    items,
):
    """
    Fetch only eligible active products.

    Manual selections preserve Admin item order.
    Automatic selections use existing catalog flags.
    """

    mode = (
        section.get("selection_mode")
        or "manual"
    )

    query = (
        supabase
        .table("products")
        .select(
            "id,name,slug,short_description,"
            "category_id,is_featured,"
            "average_rating,review_count,created_at"
        )
        .eq("status", "active")
    )

    manual_ids = []

    if mode == "manual":
        manual_ids = selected_target_ids(
            items,
            "product",
        )

        if not manual_ids:
            return []

        query = query.in_(
            "id",
            manual_ids,
        )

    elif mode == "featured":
        query = query.eq(
            "is_featured",
            True,
        )

    elif mode == "category":
        category_id = section.get(
            "category_id"
        )

        if not category_id:
            return []

        category_response = (
            supabase
            .table("categories")
            .select("id")
            .eq("id", category_id)
            .eq("is_active", True)
            .limit(1)
            .execute()
        )

        if not category_response.data:
            return []

        query = query.eq(
            "category_id",
            category_id,
        )

    elif mode in (
        "discounted",
        "latest",
    ):
        pass

    else:
        return []

    if mode == "manual":
        response = query.execute()

        indexed = {
            str(product["id"]): product
            for product in response.data or []
        }

        return [
            indexed[str(product_id)]
            for product_id in manual_ids
            if str(product_id)
            in indexed
        ]

    response = (
        query
        .order(
            "created_at",
            desc=True,
        )
        .limit(500)
        .execute()
    )

    return response.data or []


def resolve_products(
    section,
    items,
):
    """
    Resolve active products and their actual
    catalog variants, images, discounts and stock.

    No prices or stock values are copied from CMS items.
    """

    candidates = fetch_product_candidates(
        section,
        items,
    )

    if not candidates:
        return []

    product_ids = [
        product["id"]
        for product in candidates
    ]

    variants_by_product = (
        load_product_variants(
            product_ids
        )
    )

    images_by_product = (
        load_product_images(
            product_ids
        )
    )

    mode = section.get(
        "selection_mode"
    )

    require_discount = (
        mode == "discounted"
    )

    products = []

    for product in candidates:
        product_id = str(
            product["id"]
        )

        variant = choose_variant(
            variants_by_product.get(
                product_id,
                [],
            ),
            require_discount=(
                require_discount
            ),
        )

        if not variant:
            continue

        image = choose_image(
            images_by_product.get(
                product_id,
                [],
            )
        )

        products.append(
            serialize_product(
                product,
                variant,
                image,
            )
        )

    if mode == "discounted":
        products.sort(
            key=lambda product: (
                -product[
                    "discount_percentage"
                ],
                product["name"] or "",
            )
        )

    return products[
        :safe_limit(
            section.get(
                "product_limit"
            )
        )
    ]


# ============================================================
# HOMEPAGE CONFIGURATION
# ============================================================

@router.get("/configuration")
async def get_home_configuration():
    """
    Return the Admin-configured homepage structure.

    This endpoint is used by the Customer Web to determine:
    - which sections are visible
    - section order
    - section content
    - selected categories
    - selected products
    - homepage settings

    Existing App/Admin endpoints are not changed.
    """

    now = datetime.now(timezone.utc)

    try:
        # ------------------------------------------------------
        # Fetch published and visible homepage sections
        # ------------------------------------------------------
        sections_response = (
            supabase
            .table("homepage_sections")
            .select("*")
            .eq(
                "publish_status",
                "published",
            )
            .eq(
                "is_visible",
                True,
            )
            .order("sort_order")
            .execute()
        )

        sections = [
            section
            for section in (
                sections_response.data or []
            )
            if is_published(
                section,
                now,
            )
        ]

        # ------------------------------------------------------
        # Prepare section item mapping
        # ------------------------------------------------------
        section_items = {
            str(section["id"]): []
            for section in sections
        }

        # ------------------------------------------------------
        # Fetch published and visible homepage items
        # ------------------------------------------------------
        if sections:
            section_ids = [
                section["id"]
                for section in sections
            ]

            items_response = (
                supabase
                .table("homepage_items")
                .select("*")
                .in_(
                    "section_id",
                    section_ids,
                )
                .eq(
                    "publish_status",
                    "published",
                )
                .eq(
                    "is_visible",
                    True,
                )
                .order("sort_order")
                .execute()
            )

            for item in (
                items_response.data or []
            ):
                if not is_published(
                    item,
                    now,
                ):
                    continue

                section_id = str(
                    item.get(
                        "section_id"
                    )
                )

                if (
                    section_id
                    in section_items
                ):
                    section_items[
                        section_id
                    ].append(item)

        # ------------------------------------------------------
        # Build public section response
        # ------------------------------------------------------
        public_sections = []

        for section in sections:
            items = section_items.get(
                str(section["id"]),
                [],
            )

            section_type = section.get(
                "section_type"
            )

            result = {
                "id": section.get(
                    "id"
                ),
                "key": section.get(
                    "section_key"
                ),
                "type": section_type,
                "title": section.get(
                    "title"
                ),
                "subtitle": section.get(
                    "subtitle"
                ),
                "eyebrow": section.get(
                    "eyebrow"
                ),
                "sort_order": section.get(
                    "sort_order",
                    0,
                ),
                "selection_mode": section.get(
                    "selection_mode",
                    "manual",
                ),
                "category_id": section.get(
                    "category_id"
                ),
                "product_limit": safe_limit(
                    section.get(
                        "product_limit"
                    )
                ),
                "layout_config": safe_object(
                    section.get(
                        "layout_config"
                    )
                ),
                "content_config": safe_object(
                    section.get(
                        "content_config"
                    )
                ),
                "items": [
                    public_item(item)
                    for item in items
                ],
                "categories": [],
                "products": [],
            }

            # Resolve categories from Admin selections.
            if (
                section_type
                in CATEGORY_SECTION_TYPES
            ):
                result["categories"] = (
                    resolve_categories(
                        section,
                        items,
                    )
                )

            # Resolve products from Admin selections.
            if (
                section_type
                in PRODUCT_SECTION_TYPES
            ):
                result["products"] = (
                    resolve_products(
                        section,
                        items,
                    )
                )

            public_sections.append(
                result
            )

        # ------------------------------------------------------
        # Fetch homepage settings
        # ------------------------------------------------------
        settings_response = (
            supabase
            .table("homepage_settings")
            .select(
                "setting_key,setting_value"
            )
            .eq(
                "is_active",
                True,
            )
            .execute()
        )

        settings = {}

        for setting in (
            settings_response.data or []
        ):
            key = setting.get(
                "setting_key"
            )

            if key:
                settings[key] = safe_object(
                    setting.get(
                        "setting_value"
                    )
                )

        return {
            "status": "success",
            "data": {
                "sections": public_sections,
                "settings": settings,
            },
            "count": len(
                public_sections
            ),
        }

    except Exception:
        logger.exception(
            "Failed to retrieve dynamic homepage configuration"
        )

        raise HTTPException(
            status_code=500,
            detail=(
                "Unable to retrieve "
                "homepage configuration"
            ),
        )


# ============================================================
# EXISTING: HOME CATEGORIES
# ============================================================

@router.get("/categories")
async def get_home_categories():
    try:
        response = (
            supabase
            .table("categories")
            .select(
                "id,"
                "name,"
                "slug,"
                "description,"
                "image_url,"
                "home_sort_order"
            )
            .eq(
                "show_on_home",
                True,
            )
            .eq(
                "is_active",
                True,
            )
            .order(
                "home_sort_order"
            )
            .execute()
        )

        return {
            "status": "success",
            "data": response.data or [],
        }

    except Exception:
        logger.exception(
            "Failed to retrieve homepage categories"
        )

        raise HTTPException(
            status_code=(
                status.HTTP_500_INTERNAL_SERVER_ERROR
            ),
            detail=(
                "Unable to retrieve "
                "homepage categories"
            ),
        )


# ============================================================
# EXISTING: FEATURED PRODUCTS
# ============================================================

@router.get("/featured-products")
async def get_featured_products():
    try:
        response = (
            supabase
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
                    attributes
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
            .eq(
                "is_featured",
                True,
            )
            .eq(
                "status",
                "active",
            )
            .order(
                "created_at",
                desc=False,
            )
            .execute()
        )

        products = []

        for product in (
            response.data or []
        ):
            variants = (
                product.get(
                    "product_variants"
                )
                or []
            )

            images = (
                product.get(
                    "product_images"
                )
                or []
            )

            default_variant = next(
                (
                    variant
                    for variant in variants
                    if (
                        variant.get(
                            "attributes"
                        )
                        or {}
                    ).get(
                        "is_default"
                    )
                    is True
                ),
                None,
            )

            if (
                default_variant is None
                and variants
            ):
                default_variant = variants[0]

            primary_image = next(
                (
                    image
                    for image in images
                    if image.get(
                        "is_primary"
                    )
                    is True
                ),
                None,
            )

            if (
                primary_image is None
                and images
            ):
                primary_image = images[0]

            products.append({
                "id": product["id"],
                "name": product["name"],
                "slug": product["slug"],
                "description": product.get(
                    "short_description"
                ),
                "rating": product.get(
                    "average_rating"
                )
                or 0,
                "review_count": product.get(
                    "review_count"
                )
                or 0,
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
                "variant": default_variant,
                "image": (
                    primary_image.get(
                        "image_url"
                    )
                    if primary_image
                    else None
                ),
            })

        return {
            "status": "success",
            "count": len(products),
            "data": products,
        }

    except Exception:
        logger.exception(
            "Featured products API failed"
        )

        raise HTTPException(
            status_code=500,
            detail=(
                "Unable to retrieve "
                "featured products"
            ),
        )


# ============================================================
# EXISTING: WELLNESS BUNDLES
# ============================================================

@router.get("/bundles")
async def get_home_bundles():
    try:
        response = (
            supabase
            .table("wellness_bundles")
            .select(
                """
                id,
                name,
                description,
                image_url,
                discount_percentage,
                wellness_bundle_items(
                    id,
                    product_id,
                    quantity,
                    sort_order
                )
                """
            )
            .eq(
                "is_active",
                True,
            )
            .order(
                "created_at",
                desc=True,
            )
            .execute()
        )

        return {
            "status": "success",
            "count": len(
                response.data or []
            ),
            "data": response.data or [],
        }

    except Exception:
        logger.exception(
            "Failed to retrieve homepage bundles"
        )

        raise HTTPException(
            status_code=500,
            detail=(
                "Unable to retrieve "
                "homepage bundles"
            ),
        )


# ============================================================
# EXISTING: SHOP BY CONCERN
# ============================================================

@router.get("/shop-by-concern")
async def get_shop_by_concern():
    try:
        categories_response = (
            supabase
            .table("categories")
            .select(
                "id,name,slug,image_url,parent_id"
            )
            .eq(
                "is_active",
                True,
            )
            .execute()
        )

        subcategory_sales = {}

        for category in (
            categories_response.data
            or []
        ):
            if not category.get(
                "parent_id"
            ):
                continue

            category_id = str(
                category["id"]
            )

            subcategory_sales[
                category_id
            ] = {
                "id": category_id,
                "name": category.get(
                    "name"
                ),
                "slug": category.get(
                    "slug"
                ),
                "image_url": category.get(
                    "image_url"
                ),
                "units_sold": 0,
                "total_orders": set(),
            }

        response = (
            supabase
            .table("order_items")
            .select(
                """
                quantity,
                order:orders!inner(
                    id,
                    status
                ),
                product:products!inner(
                    id,
                    category:categories!inner(
                        id,
                        name,
                        slug,
                        image_url,
                        parent_id,
                        is_active
                    )
                )
                """
            )
            .eq(
                "status",
                "delivered",
            )
            .eq(
                "order.status",
                "delivered",
            )
            .eq(
                "product.category.is_active",
                True,
            )
            .execute()
        )

        for item in (
            response.data or []
        ):
            product = (
                item.get("product")
                or {}
            )

            category = (
                product.get("category")
                or {}
            )

            category_id = str(
                category.get("id")
                or ""
            )

            if (
                category_id
                not in subcategory_sales
            ):
                continue

            subcategory_sales[
                category_id
            ]["units_sold"] += (
                item.get("quantity")
                or 0
            )

            order = (
                item.get("order")
                or {}
            )

            if order.get("id"):
                subcategory_sales[
                    category_id
                ]["total_orders"].add(
                    order["id"]
                )

        results = []

        for category in (
            subcategory_sales.values()
        ):
            results.append({
                "id": category["id"],
                "name": category["name"],
                "slug": category["slug"],
                "image_url": category[
                    "image_url"
                ],
                "units_sold": category[
                    "units_sold"
                ],
                "total_orders": len(
                    category[
                        "total_orders"
                    ]
                ),
            })

        results.sort(
            key=lambda item: (
                -item["units_sold"],
                -item["total_orders"],
                item["name"] or "",
            )
        )

        results = results[:20]

        return {
            "status": "success",
            "count": len(results),
            "data": results,
        }

    except Exception:
        logger.exception(
            "Shop by Concern API failed"
        )

        raise HTTPException(
            status_code=500,
            detail=(
                "Unable to retrieve "
                "popular subcategories"
            ),
        )


# ============================================================
# EXISTING: COUPONS
# ============================================================

@router.get("/coupons")
async def get_home_coupons(
    placement: str = Query(
        default="home",
        pattern=(
            "^(home|cart|checkout|"
            "product_details)$"
        ),
    ),
):
    try:
        now = (
            datetime.now(
                timezone.utc
            ).isoformat()
        )

        response = (
            supabase
            .table("coupons")
            .select(
                """
                id,
                code,
                description,
                discount_type,
                discount_value,
                min_order_value,
                max_discount_amount,
                starts_at,
                expires_at,
                first_order_only,
                display_locations
                """
            )
            .eq(
                "is_active",
                True,
            )
            .contains(
                "display_locations",
                [placement],
            )
            .lte(
                "starts_at",
                now,
            )
            .gt(
                "expires_at",
                now,
            )
            .order(
                "created_at",
                desc=True,
            )
            .execute()
        )

        coupons = (
            response.data or []
        )

        return {
            "status": "success",
            "count": len(coupons),
            "data": coupons,
        }

    except Exception:
        logger.exception(
            "Failed to retrieve homepage coupons"
        )

        raise HTTPException(
            status_code=500,
            detail=(
                "Unable to retrieve "
                "homepage coupons"
            ),
        )


# ============================================================
# EXISTING: NEW ARRIVALS
# ============================================================

@router.get("/new-arrivals")
async def get_new_arrivals():
    try:
        response = (
            supabase
            .table("products")
            .select(
                """
                id,
                name,
                slug,
                short_description,
                average_rating,
                review_count,
                created_at,
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
                """
            )
            .eq(
                "status",
                "active",
            )
            .order(
                "created_at",
                desc=True,
            )
            .limit(10)
            .execute()
        )

        products = []

        for product in (
            response.data or []
        ):
            variants = (
                product.get(
                    "product_variants"
                )
                or []
            )

            images = (
                product.get(
                    "product_images"
                )
                or []
            )

            default_variant = next(
                (
                    variant
                    for variant in variants
                    if (
                        variant.get(
                            "attributes"
                        )
                        or {}
                    ).get(
                        "is_default"
                    )
                    is True
                ),
                None,
            )

            if (
                default_variant is None
                and variants
            ):
                default_variant = variants[0]

            primary_image = next(
                (
                    image
                    for image in images
                    if image.get(
                        "is_primary"
                    )
                    is True
                ),
                None,
            )

            if (
                primary_image is None
                and images
            ):
                primary_image = images[0]

            products.append({
                "id": product["id"],
                "name": product["name"],
                "slug": product["slug"],
                "description": product.get(
                    "short_description"
                ),
                "rating": product.get(
                    "average_rating"
                )
                or 0,
                "review_count": product.get(
                    "review_count"
                )
                or 0,
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
                "variant": default_variant,
                "image": (
                    primary_image.get(
                        "image_url"
                    )
                    if primary_image
                    else None
                ),
                "created_at": product.get(
                    "created_at"
                ),
            })

        return {
            "status": "success",
            "count": len(products),
            "data": products,
        }

    except Exception:
        logger.exception(
            "New Arrivals API failed"
        )

        raise HTTPException(
            status_code=500,
            detail=(
                "Unable to retrieve "
                "new arrivals"
            ),
        )


# ============================================================
# EXISTING: APP BANNERS
# ============================================================

@router.get("/app-banners")
async def get_app_banners():
    try:
        response = (
            supabase
            .table("banners")
            .select("*")
            .eq(
                "platform",
                "app",
            )
            .eq(
                "placement",
                "home",
            )
            .eq(
                "is_visible",
                True,
            )
            .eq(
                "publish_status",
                "published",
            )
            .order(
                "sort_order",
                desc=False,
            )
            .execute()
        )

        return {
            "status": "success",
            "count": len(
                response.data or []
            ),
            "data": response.data or [],
        }

    except Exception:
        logger.exception(
            "App banners API failed"
        )

        raise HTTPException(
            status_code=500,
            detail=(
                "Unable to retrieve "
                "app banners"
            ),
        )


# ============================================================
# EXISTING: CATEGORY BANNERS
# ============================================================

@router.get("/category-banners")
async def get_category_banners():
    """
    Get active category banners for the
    customer mobile app.

    Only banners that are:
    - platform = app
    - placement = category
    - visible
    - published
    - within their scheduled publish window

    are returned.
    """

    try:
        now = (
            datetime.now(
                timezone.utc
            ).isoformat()
        )

        response = (
            supabase
            .table("banners")
            .select(
                """
                id,
                category_id,
                title,
                subtitle,
                image_url,
                mobile_image_url,
                target_type,
                target_id,
                target_url,
                sort_order,
                metadata,
                starts_at,
                ends_at,
                categories(
                    id,
                    name,
                    slug
                )
                """
            )
            .eq(
                "platform",
                "app",
            )
            .eq(
                "placement",
                "category",
            )
            .eq(
                "is_visible",
                True,
            )
            .eq(
                "publish_status",
                "published",
            )
            .or_(
                f"starts_at.is.null,"
                f"starts_at.lte.{now}"
            )
            .or_(
                f"ends_at.is.null,"
                f"ends_at.gt.{now}"
            )
            .order(
                "sort_order",
                desc=False,
            )
            .order(
                "created_at",
                desc=False,
            )
            .execute()
        )

        banners = (
            response.data or []
        )

        return {
            "status": "success",
            "count": len(banners),
            "data": banners,
        }

    except Exception:
        logger.exception(
            "Category banners API failed"
        )

        raise HTTPException(
            status_code=500,
            detail=(
                "Unable to retrieve "
                "category banners"
            ),
        )


# ============================================================
# EXISTING: CATEGORY CAMPAIGNS
# ============================================================

@router.get("/category-campaigns")
async def get_category_campaigns():
    try:
        response = (
            supabase
            .table("category_campaigns")
            .select(
                """
                id,
                title,
                image_url,
                category_id,
                sort_order,
                categories(
                    id,
                    name,
                    slug
                )
                """
            )
            .eq(
                "is_active",
                True,
            )
            .order(
                "sort_order"
            )
            .execute()
        )

        campaigns = (
            response.data or []
        )

        return {
            "status": "success",
            "count": len(campaigns),
            "data": campaigns,
        }

    except Exception:
        logger.exception(
            "Category campaigns API failed"
        )

        raise HTTPException(
            status_code=500,
            detail=(
                "Unable to retrieve "
                "category campaigns"
            ),
        )