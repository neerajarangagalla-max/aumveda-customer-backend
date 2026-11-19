import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.core.supabase import supabase_admin


router = APIRouter(
    prefix="/admin/faqs",
    tags=["Admin FAQs"],
)

logger = logging.getLogger(__name__)


# ============================================================
# Schemas
# ============================================================

class FAQCategoryCreate(BaseModel):
    name: str
    slug: str
    description: str | None = None
    sort_order: int = 0
    is_active: bool = True


class FAQCategoryUpdate(BaseModel):
    name: str | None = None
    slug: str | None = None
    description: str | None = None
    sort_order: int | None = None
    is_active: bool | None = None


class FAQCreate(BaseModel):
    category_id: str
    question: str
    answer: str
    keywords: list[str] = Field(default_factory=list)
    priority: int = 0
    sort_order: int = 0
    is_active: bool = True


class FAQUpdate(BaseModel):
    category_id: str | None = None
    question: str | None = None
    answer: str | None = None
    keywords: list[str] | None = None
    priority: int | None = None
    sort_order: int | None = None
    is_active: bool | None = None


# ============================================================
# Dashboard / Summary
# ============================================================

@router.get("/summary")
async def faq_summary():
    try:
        categories_response = (
            supabase_admin
            .table("faq_categories")
            .select("id", count="exact")
            .execute()
        )

        faqs_response = (
            supabase_admin
            .table("faqs")
            .select("id", count="exact")
            .execute()
        )

        active_response = (
            supabase_admin
            .table("faqs")
            .select("id", count="exact")
            .eq("is_active", True)
            .execute()
        )

        inactive_response = (
            supabase_admin
            .table("faqs")
            .select("id", count="exact")
            .eq("is_active", False)
            .execute()
        )

        return {
            "status": "success",
            "data": {
                "total_categories": categories_response.count or 0,
                "total_faqs": faqs_response.count or 0,
                "active_faqs": active_response.count or 0,
                "inactive_faqs": inactive_response.count or 0,
            },
        }

    except Exception:
        logger.exception("FAQ summary failed")

        raise HTTPException(
            status_code=500,
            detail="Unable to retrieve FAQ summary.",
        )


# ============================================================
# Categories
# ============================================================

@router.get("/categories")
async def admin_faq_categories():
    try:
        response = (
            supabase_admin
            .table("faq_categories")
            .select(
                """
                id,
                name,
                slug,
                description,
                is_active,
                sort_order,
                created_at,
                updated_at
                """
            )
            .order("sort_order")
            .execute()
        )

        return {
            "status": "success",
            "count": len(response.data or []),
            "data": response.data or [],
        }

    except Exception:
        logger.exception("Admin FAQ category list failed")

        raise HTTPException(
            status_code=500,
            detail="Unable to retrieve FAQ categories.",
        )


@router.post("/categories")
async def create_faq_category(payload: FAQCategoryCreate):
    try:
        response = (
            supabase_admin
            .table("faq_categories")
            .insert(payload.model_dump())
            .execute()
        )

        return {
            "status": "success",
            "message": "FAQ category created successfully.",
            "data": response.data[0] if response.data else None,
        }

    except Exception:
        logger.exception("FAQ category creation failed")

        raise HTTPException(
            status_code=500,
            detail="Unable to create FAQ category.",
        )


@router.put("/categories/{category_id}")
async def update_faq_category(
    category_id: str,
    payload: FAQCategoryUpdate,
):
    try:
        update_data = payload.model_dump(exclude_none=True)

        response = (
            supabase_admin
            .table("faq_categories")
            .update(update_data)
            .eq("id", category_id)
            .execute()
        )

        if not response.data:
            raise HTTPException(
                status_code=404,
                detail="FAQ category not found.",
            )

        return {
            "status": "success",
            "message": "FAQ category updated successfully.",
            "data": response.data[0],
        }

    except HTTPException:
        raise

    except Exception:
        logger.exception("FAQ category update failed")

        raise HTTPException(
            status_code=500,
            detail="Unable to update FAQ category.",
        )


@router.delete("/categories/{category_id}")
async def delete_faq_category(category_id: str):
    try:
        response = (
            supabase_admin
            .table("faq_categories")
            .delete()
            .eq("id", category_id)
            .execute()
        )

        if not response.data:
            raise HTTPException(
                status_code=404,
                detail="FAQ category not found.",
            )

        return {
            "status": "success",
            "message": "FAQ category deleted successfully.",
        }

    except HTTPException:
        raise

    except Exception:
        logger.exception("FAQ category deletion failed")

        raise HTTPException(
            status_code=500,
            detail="Unable to delete FAQ category.",
        )


# ============================================================
# FAQs
# ============================================================

@router.get("")
async def admin_faqs(
    category_id: str | None = None,
    is_active: bool | None = None,
):
    try:
        query = (
            supabase_admin
            .table("faqs")
            .select(
                """
                id,
                category_id,
                question,
                answer,
                keywords,
                priority,
                sort_order,
                is_active,
                created_at,
                updated_at,
                faq_categories (
                    id,
                    name,
                    slug
                )
                """
            )
        )

        if category_id:
            query = query.eq("category_id", category_id)

        if is_active is not None:
            query = query.eq("is_active", is_active)

        response = (
            query
            .order("priority", desc=True)
            .order("sort_order")
            .execute()
        )

        return {
            "status": "success",
            "count": len(response.data or []),
            "data": response.data or [],
        }

    except Exception:
        logger.exception("Admin FAQ list failed")

        raise HTTPException(
            status_code=500,
            detail="Unable to retrieve FAQs.",
        )


@router.get("/{faq_id}")
async def admin_faq(faq_id: str):
    try:
        response = (
            supabase_admin
            .table("faqs")
            .select(
                """
                id,
                category_id,
                question,
                answer,
                keywords,
                priority,
                sort_order,
                is_active,
                created_at,
                updated_at
                """
            )
            .eq("id", faq_id)
            .limit(1)
            .execute()
        )

        if not response.data:
            raise HTTPException(
                status_code=404,
                detail="FAQ not found.",
            )

        return {
            "status": "success",
            "data": response.data[0],
        }

    except HTTPException:
        raise

    except Exception:
        logger.exception("Admin FAQ lookup failed")

        raise HTTPException(
            status_code=500,
            detail="Unable to retrieve FAQ.",
        )


@router.post("")
async def create_faq(payload: FAQCreate):
    try:
        response = (
            supabase_admin
            .table("faqs")
            .insert(payload.model_dump())
            .execute()
        )

        return {
            "status": "success",
            "message": "FAQ created successfully.",
            "data": response.data[0] if response.data else None,
        }

    except Exception:
        logger.exception("FAQ creation failed")

        raise HTTPException(
            status_code=500,
            detail="Unable to create FAQ.",
        )


@router.put("/{faq_id}")
async def update_faq(
    faq_id: str,
    payload: FAQUpdate,
):
    try:
        update_data = payload.model_dump(exclude_none=True)

        response = (
            supabase_admin
            .table("faqs")
            .update(update_data)
            .eq("id", faq_id)
            .execute()
        )

        if not response.data:
            raise HTTPException(
                status_code=404,
                detail="FAQ not found.",
            )

        return {
            "status": "success",
            "message": "FAQ updated successfully.",
            "data": response.data[0],
        }

    except HTTPException:
        raise

    except Exception:
        logger.exception("FAQ update failed")

        raise HTTPException(
            status_code=500,
            detail="Unable to update FAQ.",
        )


@router.patch("/{faq_id}/status")
async def update_faq_status(
    faq_id: str,
    is_active: bool,
):
    try:
        response = (
            supabase_admin
            .table("faqs")
            .update({
                "is_active": is_active
            })
            .eq("id", faq_id)
            .execute()
        )

        if not response.data:
            raise HTTPException(
                status_code=404,
                detail="FAQ not found.",
            )

        return {
            "status": "success",
            "message": "FAQ status updated successfully.",
            "data": response.data[0],
        }

    except HTTPException:
        raise

    except Exception:
        logger.exception(
            "FAQ status update failed"
        )

        raise HTTPException(
            status_code=500,
            detail="Unable to update FAQ status.",
        )

@router.delete("/{faq_id}")
async def delete_faq(faq_id: str):
    try:
        response = (
            supabase_admin
            .table("faqs")
            .delete()
            .eq("id", faq_id)
            .execute()
        )

        if not response.data:
            raise HTTPException(
                status_code=404,
                detail="FAQ not found.",
            )

        return {
            "status": "success",
            "message": "FAQ deleted successfully.",
        }

    except HTTPException:
        raise

    except Exception:
        logger.exception("FAQ deletion failed")

        raise HTTPException(
            status_code=500,
            detail="Unable to delete FAQ.",
        )