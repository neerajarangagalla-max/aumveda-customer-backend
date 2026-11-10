import logging
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query, status

from app.core.supabase import supabase


router = APIRouter(
    prefix="/home",
    tags=["Home"],
)

logger = logging.getLogger(__name__)




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
            .eq("show_on_home", True)
            .eq("is_active", True)
            .order("home_sort_order")
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
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to retrieve homepage categories",
        )
@router.get("/app-banners")
async def get_app_banners():
    try:
        now = datetime.now(timezone.utc).isoformat()

        response = (
            supabase
            .table("homepage_items")
            .select(
                """
                id,
                section_id,
                item_key,
                item_type,
                title,
                subtitle,
                description,
                eyebrow,
                image_url,
                mobile_image_url,
                video_url,
                alt_text,
                badge_text,
                badge_style,
                primary_cta_text,
                primary_cta_url,
                secondary_cta_text,
                secondary_cta_url,
                target_type,
                target_id,
                target_url,
                sort_order,
                is_visible,
                publish_status,
                style_config,
                metadata,
                starts_at,
                ends_at
                """
            )
            .eq("item_type", "app_banner")
            .eq("is_visible", True)
            .eq("publish_status", "published")
            .or_(f"starts_at.is.null,starts_at.lte.{now}")
            .or_(f"ends_at.is.null,ends_at.gt.{now}")
            .order("sort_order")
            .execute()
        )

        return {
            "status": "success",
            "count": len(response.data or []),
            "data": response.data or [],
        }

    except Exception:
        logger.exception("App banners API failed")

        raise HTTPException(
            status_code=500,
            detail="Unable to retrieve app banners",
        )
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
            .eq("is_featured", True)
            .eq("status", "active")
            .order("created_at", desc=False)
            .execute()
        )

        products = []

        for product in response.data or []:
            variants = product.get("product_variants") or []
            images = product.get("product_images") or []

            # Prefer the default variant stored in attributes.
            default_variant = next(
                (
                    variant
                    for variant in variants
                    if (variant.get("attributes") or {}).get(
                        "is_default"
                    ) is True
                ),
                None,
            )

            # Fall back to the first available variant.
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
                "id": product["id"],
                "name": product["name"],
                "slug": product["slug"],
                "description": product.get("short_description"),
                "rating": product.get("average_rating") or 0,
                "review_count": product.get("review_count") or 0,
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
            })

        return {
            "status": "success",
            "count": len(products),
            "data": products,
        }

    except Exception:
        logger.exception("Featured products API failed")
        raise HTTPException(
            status_code=500,
            detail="Unable to retrieve featured products",
        )

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
            .eq("is_active", True)
            .order("created_at", desc=True)
            .execute()
        )

        return {
            "status": "success",
            "count": len(response.data or []),
            "data": response.data or [],
        }

    except Exception:
        logger.exception("Failed to retrieve homepage bundles")
        raise HTTPException(
            status_code=500,
            detail="Unable to retrieve homepage bundles",
        )

@router.get("/shop-by-concern")
async def get_shop_by_concern():
    try:
        # Fetch all active subcategories
        categories_response = (
            supabase
            .table("categories")
            .select("id, name, slug, image_url, parent_id")
            .eq("is_active", True)
            .execute()
        )

        # Prepare all active subcategories, including those with zero sales
        subcategory_sales = {}

        for category in categories_response.data or []:
            if not category.get("parent_id"):
                continue

            category_id = str(category["id"])

            subcategory_sales[category_id] = {
                "id": category_id,
                "name": category.get("name"),
                "slug": category.get("slug"),
                "image_url": category.get("image_url"),
                "units_sold": 0,
                "total_orders": set(),
            }

        # Fetch delivered order items
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
            .eq("status", "delivered")
            .eq("order.status", "delivered")
            .eq("product.category.is_active", True)
            .execute()
        )

        # Calculate sales for each subcategory
        for item in response.data or []:
            product = item.get("product") or {}
            category = product.get("category") or {}

            category_id = str(category.get("id") or "")

            if category_id not in subcategory_sales:
                continue

            subcategory_sales[category_id]["units_sold"] += (
                item.get("quantity") or 0
            )

            order = item.get("order") or {}

            if order.get("id"):
                subcategory_sales[category_id]["total_orders"].add(
                    order["id"]
                )

        # Format and rank results
        results = []

        for category in subcategory_sales.values():
            results.append({
                "id": category["id"],
                "name": category["name"],
                "slug": category["slug"],
                "image_url": category["image_url"],
                "units_sold": category["units_sold"],
                "total_orders": len(category["total_orders"]),
            })

        results.sort(
            key=lambda item: (
                -item["units_sold"],
                -item["total_orders"],
                item["name"] or "",
            )
        )

        # Return top 20 subcategories
        results = results[:20]

        return {
            "status": "success",
            "count": len(results),
            "data": results,
        }

    except Exception:
        logger.exception("Shop by Concern API failed")

        raise HTTPException(
            status_code=500,
            detail="Unable to retrieve popular subcategories",
        )

@router.get("/coupons")
async def get_home_coupons(
    placement: str = Query(
        default="home",
        pattern="^(home|cart|checkout|product_details)$",
    ),
):
    try:
        now = datetime.now(timezone.utc).isoformat()

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
            .eq("is_active", True)
            .contains("display_locations", [placement])
            .lte("starts_at", now)
            .gt("expires_at", now)
            .order("created_at", desc=True)
            .execute()
        )

        coupons = response.data or []

        return {
            "status": "success",
            "count": len(coupons),
            "data": coupons,
        }

    except Exception:
        logger.exception("Failed to retrieve homepage coupons")

        raise HTTPException(
            status_code=500,
            detail="Unable to retrieve homepage coupons",
        )

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
    .eq("status", "active")
    .order("created_at", desc=True)
    .limit(10)
    .execute()
)

        products = []

        for product in response.data or []:
            variants = product.get("product_variants") or []
            images = product.get("product_images") or []

            default_variant = next(
                (
                    variant
                    for variant in variants
                    if (variant.get("attributes") or {}).get(
                        "is_default"
                    ) is True
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
                "id": product["id"],
                "name": product["name"],
                "slug": product["slug"],
                "description": product.get("short_description"),
                "rating": product.get("average_rating") or 0,
                "review_count": product.get("review_count") or 0,
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
                "created_at": product.get("created_at"),
            })

        return {
            "status": "success",
            "count": len(products),
            "data": products,
        }

    except Exception:
        logger.exception("New Arrivals API failed")

        raise HTTPException(
            status_code=500,
            detail="Unable to retrieve new arrivals",
        )
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
            .eq("is_active", True)
            .order("sort_order")
            .execute()
        )

        campaigns = response.data or []

        return {
            "status": "success",
            "count": len(campaigns),
            "data": campaigns,
        }

    except Exception:
        logger.exception("Category campaigns API failed")

        raise HTTPException(
            status_code=500,
            detail="Unable to retrieve category campaigns",
        )