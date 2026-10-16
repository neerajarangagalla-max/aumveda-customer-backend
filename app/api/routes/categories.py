import logging

from fastapi import APIRouter, HTTPException

from app.services.category_service import get_categories, get_category

router = APIRouter(prefix="/categories", tags=["Categories"])
logger = logging.getLogger(__name__)


@router.get("")
async def categories():
    try:
        data = get_categories()
        return {
            "status": "success",
            "count": len(data),
            "data": data,
        }
    except Exception:
        logger.exception("Category list failed")
        raise HTTPException(
            status_code=500,
            detail="Unable to retrieve categories.",
        )


@router.get("/{slug}")
async def category(slug: str):
    try:
        data = get_category(slug)
        if not data:
            raise HTTPException(
                status_code=404,
                detail="Category not found.",
            )
        return {
            "status": "success",
            "data": data,
        }
    except HTTPException:
        raise
    except Exception:
        logger.exception("Category lookup failed")
        raise HTTPException(
            status_code=500,
            detail="Unable to retrieve category.",
        )
