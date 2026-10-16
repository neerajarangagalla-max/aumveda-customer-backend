import logging
from urllib import response

from fastapi import APIRouter, HTTPException, status

from app.core.supabase import supabase


router = APIRouter(
    prefix="/home",
    tags=["Home"],
)

logger = logging.getLogger(__name__)


@router.get("/hero")
async def get_home_hero():
    try:
        hero_check = (
            supabase
            .table("hero_banners")
            .select("id, title_line1, is_active, sort_order")
            .execute()
        )
        print("HERO BANNERS:", hero_check.data)

        response = (
            supabase
            .table("hero_banners")
            .select(
    "id,"
    "eyebrow,"
    "title_line1,"
    "title_line2,"
    "description,"
    "image_url,"
    "video_url,"
    "primary_cta_text,"
    "primary_cta_path,"
    "secondary_cta_text,"
    "secondary_cta_path"
)
            .eq("is_active", True)
            .order("sort_order")
            .limit(1)
            .execute()
        )

        if not response.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Active hero banner not found",
            )

        return {
            "status": "success",
            "data": response.data[0],
        }

    except HTTPException:
        raise

    except Exception:
        logger.exception("Failed to retrieve homepage hero")

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to retrieve homepage hero",
        )

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
@router.get("/featured-products")
async def get_featured_products():

    try:
        all_products = (
            supabase
            .table("products")
            .select("id, name, status, is_featured")
            .execute()
        )
        product_rows = all_products.data or []

        print("ALL PRODUCTS:", len(product_rows))
        print(
            "ACTIVE PRODUCTS:",
            sum(
                1 for product in product_rows
                if product.get("status") == "active"
            )
        )
        print(
            "FEATURED PRODUCTS:",
            sum(
                1 for product in product_rows
                if product.get("is_featured") is True
            )
        )

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
            .eq(
                "is_featured",
                True
            )
            .eq(
                "status",
                "active"
            )
            .order(
                "created_at",
                desc=False
            )
            .execute()
        )

        print(
            "FEATURED PRODUCTS QUERY COUNT:",
            len(response.data or [])
        )

        products = []


        for product in response.data:

            variants = (
                product.get(
                    "product_variants",
                    []
                )
            )


            images = (
                product.get(
                    "product_images",
                    []
                )
            )


            default_variant = None

            for variant in variants:

                if variant.get(
                    "is_default"
                ):
                    default_variant = variant
                    break


            primary_image = None

            for image in images:

                if image.get(
                    "is_primary"
                ):
                    primary_image = image
                    break



            products.append(
                {
                    "id": product["id"],

                    "name": product["name"],

                    "slug": product["slug"],

                    "description":
                        product.get(
                            "short_description"
                        ),

                    "rating":
                        product.get(
                            "average_rating",
                            0
                        ),

                    "review_count":
                        product.get(
                            "review_count",
                            0
                        ),

                    "price":
                        default_variant.get(
                            "price"
                        )
                        if default_variant
                        else None,


                    "compare_at_price":
                        default_variant.get(
                            "compare_at_price"
                        )
                        if default_variant
                        else None,


                    "variant":
                        default_variant,


                    "image":
                        primary_image.get(
                            "image_url"
                        )
                        if primary_image
                        else None
                }
            )



        return {

            "status": "success",

            "count": len(products),

            "data": products

        }


    except Exception as error:

        logger.exception(
            "Featured products API failed"
        )

        raise HTTPException(
            status_code=500,
            detail=str(error)
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

