import logging

from fastapi import APIRouter, HTTPException, status

from app.core.supabase import supabase


router = APIRouter(
    tags=["Database"],
)

logger = logging.getLogger(__name__)


@router.get("/database-test")
async def database_test():
    try:
        response = (
            supabase
            .table("categories")
            .select("id")
            .limit(1)
            .execute()
        )

        return {
            "status": "ok",
            "database": "connected",
            "provider": "Supabase PostgreSQL",
            "test_table": "categories",
            "records_returned": len(response.data or []),
        }

    except Exception:
        logger.exception("Supabase database connectivity test failed")

    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail="Database connectivity test failed.",
    )