import logging

from fastapi import APIRouter, HTTPException, Query

from app.core.supabase import supabase_admin

router = APIRouter(
    prefix="/chatbot",
    tags=["Chatbot"],
)

logger = logging.getLogger(__name__)


# ============================================================
# FAQ Categories
# ============================================================

@router.get("/categories")
async def chatbot_categories():
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
                sort_order
                """
            )
            .eq("is_active", True)
            .order("sort_order")
            .execute()
        )

        return {
            "status": "success",
            "count": len(response.data or []),
            "data": response.data or [],
        }

    except Exception:
        logger.exception("FAQ category list failed")

        raise HTTPException(
            status_code=500,
            detail="Unable to retrieve FAQ categories.",
        )


# ============================================================
# FAQs
# ============================================================

@router.get("/faqs")
async def chatbot_faqs(
    category_id: str | None = Query(default=None),
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
                sort_order
                """
            )
            .eq("is_active", True)
        )

        if category_id:
            query = query.eq("category_id", category_id)

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
        logger.exception("FAQ list failed")

        raise HTTPException(
            status_code=500,
            detail="Unable to retrieve FAQs.",
        )


# ============================================================
# FAQ Search
# ============================================================

@router.get("/search")
async def search_faqs(
    q: str = Query(..., min_length=1),
):
    try:
        search_text = q.strip().lower()

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
                sort_order
                """
            )
            .eq("is_active", True)
            .order("priority", desc=True)
            .order("sort_order")
            .execute()
        )

        faqs = response.data or []

        matches = []

        for faq in faqs:
            question = (faq.get("question") or "").lower()
            keywords = faq.get("keywords") or []

            if isinstance(keywords, str):
                keywords = [
                    keyword.strip().lower()
                    for keyword in keywords.split(",")
                ]
            else:
                keywords = [
                    str(keyword).lower()
                    for keyword in keywords
                ]

            # Direct question match
            if search_text in question:
                matches.append(faq)
                continue

            # Keyword match
            if any(search_text in keyword for keyword in keywords):
                matches.append(faq)
                continue

            # Word-level matching
            search_words = set(search_text.split())
            question_words = set(question.split())

            if search_words.intersection(question_words):
                matches.append(faq)

        return {
            "status": "success",
            "query": q,
            "count": len(matches),
            "data": matches[:10],
        }

    except Exception:
        logger.exception("FAQ search failed")

        raise HTTPException(
            status_code=500,
            detail="Unable to search FAQs.",
        )


# ============================================================
# Single FAQ
# ============================================================

@router.get("/faqs/{faq_id}")
async def chatbot_faq(faq_id: str):
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
                sort_order
                """
            )
            .eq("id", faq_id)
            .eq("is_active", True)
            .limit(1)
            .execute()
        )

        data = response.data or []

        if not data:
            raise HTTPException(
                status_code=404,
                detail="FAQ not found.",
            )

        return {
            "status": "success",
            "data": data[0],
        }

    except HTTPException:
        raise

    except Exception:
        logger.exception("FAQ lookup failed")

        raise HTTPException(
            status_code=500,
            detail="Unable to retrieve FAQ.",
        )