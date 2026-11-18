from fastapi import APIRouter

from app.api.vendor import (
    auth,
    dashboard,
    products,
    profile,
)


vendor_router = APIRouter(
    prefix="/vendor"
)


# ============================================================
# AUTHENTICATION
# ============================================================

vendor_router.include_router(
    auth.router
)


# ============================================================
# PROFILE
# ============================================================

vendor_router.include_router(
    profile.router
)


# ============================================================
# DASHBOARD
# ============================================================

vendor_router.include_router(
    dashboard.router
)


# ============================================================
# PRODUCTS
# ============================================================

vendor_router.include_router(
    products.router
)