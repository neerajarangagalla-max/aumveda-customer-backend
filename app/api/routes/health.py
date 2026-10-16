from fastapi import APIRouter


router = APIRouter(
    tags=["Health"],
)


@router.get("/health")
async def health_check():
    return {
        "status": "ok",
        "service": "customer-backend",
        "message": "AUMVEDA Customer Backend is running",
    }