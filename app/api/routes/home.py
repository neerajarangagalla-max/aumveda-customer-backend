import logging

from fastapi import APIRouter, HTTPException, status

from app.services.home_service import (
    get_categories as fetch_categories,
    get_decorations as fetch_decorations,
    get_featured_products as fetch_featured_products,
    get_hero as fetch_hero,
    get_wellness_bundles as fetch_wellness_bundles,
)


router = APIRouter(
    prefix="/home",
    tags=["Home"],
)

logger = logging.getLogger(__name__)


@router.get("/hero")
def get_home_hero():
    try:
        hero = fetch_hero()

        if not hero:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Active hero banner not found",
            )

        return {
            "status": "success",
            "data": hero,
        }

    except HTTPException:
        raise

    except Exception:
        logger.exception(
            "Failed to retrieve homepage hero"
        )

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to retrieve homepage hero",
        )


@router.get("/categories")
def get_home_categories():
    try:
        categories = fetch_categories()

        return {
            "status": "success",
            "data": categories,
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
def get_home_featured_products():
    try:
        products = fetch_featured_products()

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
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to retrieve featured products",
        )


@router.get("/decorations")
def get_home_decorations():
    try:
        decorations = fetch_decorations()

        return {
            "status": "success",
            "count": len(decorations),
            "data": decorations,
        }

    except Exception:
        logger.exception(
            "Failed to retrieve homepage decorations"
        )

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to retrieve homepage decorations",
        )
# ============================================================
# WELLNESS BUNDLES
# ============================================================

@router.get("/bundles")
def get_home_bundles():

    try:

        bundles = fetch_wellness_bundles()

        return {
            "status": "success",
            "count": len(bundles),
            "data": bundles,
        }

    except Exception:

        logger.exception(
            "Failed to retrieve wellness bundles"
        )

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to retrieve wellness bundles",
        )