from fastapi import APIRouter

from app.services.site_settings_service import (
    get_branding_settings,
    get_public_site_settings,
)


router = APIRouter(
    prefix="/site-settings",
    tags=["Site Settings"],
)


@router.get("/public")
def public_site_settings():
    return get_public_site_settings()


@router.get("/branding")
def branding_settings():
    return {
        "branding": get_branding_settings()
    }