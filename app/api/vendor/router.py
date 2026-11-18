"""
AUMVEDA Vendor Backend
Main Vendor API Router

API prefix:
    /api/v1/vendor

Registers all Vendor Backend modules.

Security:
- Existing authentication dependencies remain unchanged.
- Owner-only module restrictions remain unchanged.
- Notifications are restricted to authenticated recipients.
- Public password recovery features remain disabled
  by default.
- Static Team routes are registered before dynamic routes.
- Each router is registered exactly once.
"""

import os

from fastapi import APIRouter

from app.api.vendor import (
    auth,
    branding,
    custom_roles,
    dashboard,
    earnings,
    employee_password_requests,
    inventory,
    notifications,
    orders,
    owner_password_recovery,
    payouts,
    products,
    profile,
    profile_change_requests,
    returns,
    shipping,
    staff_creation,
    team,
    team_invites,
)


vendor_router = APIRouter(
    prefix="/vendor"
)


# ============================================================
# 1. AUTHENTICATION
# ============================================================

vendor_router.include_router(
    auth.router
)


# ============================================================
# 2. BUSINESS PROFILE
# ============================================================

vendor_router.include_router(
    profile.router
)


# ============================================================
# 3. BUSINESS PROFILE CHANGE REQUESTS
# ============================================================

vendor_router.include_router(
    profile_change_requests.router
)


# ============================================================
# 4. BRANDING
# ============================================================

vendor_router.include_router(
    branding.router
)


# ============================================================
# 5. DASHBOARD
# ============================================================

vendor_router.include_router(
    dashboard.router
)


# ============================================================
# 6. PRODUCT MANAGEMENT
# ============================================================

vendor_router.include_router(
    products.router
)


# ============================================================
# 7. INVENTORY MANAGEMENT
# ============================================================

vendor_router.include_router(
    inventory.router
)


# ============================================================
# 8. ORDER MANAGEMENT
# ============================================================

vendor_router.include_router(
    orders.router
)


# ============================================================
# 9. SHIPPING MANAGEMENT
# ============================================================

vendor_router.include_router(
    shipping.router
)


# ============================================================
# 10. RETURNS AND EXCHANGES
# ============================================================

vendor_router.include_router(
    returns.router
)


# ============================================================
# 11. EARNINGS
# ============================================================

vendor_router.include_router(
    earnings.router
)


# ============================================================
# 12. PAYOUTS
# ============================================================

vendor_router.include_router(
    payouts.router
)


# ============================================================
# 13. CUSTOM ROLE MANAGEMENT
# ============================================================

vendor_router.include_router(
    custom_roles.router
)


# ============================================================
# 14. STAFF INVITATION MANAGEMENT
# ============================================================

vendor_router.include_router(
    team_invites.router
)


# ============================================================
# 15. OWNER-CREATED EMPLOYEE ACCOUNTS
# ============================================================

vendor_router.include_router(
    staff_creation.router
)


# ============================================================
# 16. TEAM MANAGEMENT
# ============================================================

vendor_router.include_router(
    team.router
)


# ============================================================
# 17. EMPLOYEE PASSWORD ASSISTANCE
# ============================================================

EMPLOYEE_PASSWORD_REQUESTS_ENABLED = (
    os.getenv(
        "AUMVEDA_ENABLE_EMPLOYEE_PASSWORD_REQUESTS",
        "false",
    ).strip().lower()
    == "true"
)

if EMPLOYEE_PASSWORD_REQUESTS_ENABLED:

    vendor_router.include_router(
        employee_password_requests.router
    )


# ============================================================
# 18. VENDOR OWNER PASSWORD RECOVERY
# ============================================================

OWNER_PASSWORD_RECOVERY_ENABLED = (
    os.getenv(
        "AUMVEDA_ENABLE_OWNER_PASSWORD_RECOVERY",
        "false",
    ).strip().lower()
    == "true"
)

if OWNER_PASSWORD_RECOVERY_ENABLED:

    vendor_router.include_router(
        owner_password_recovery.router
    )


# ============================================================
# 19. VENDOR NOTIFICATIONS
# ============================================================

vendor_router.include_router(
    notifications.router
)