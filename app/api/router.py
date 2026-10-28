from fastapi import APIRouter

from app.api.admin import (
    categories as admin_categories,
    customers as admin_customers,
    dashboard as admin_dashboard,
    finance as admin_finance,
    inventory as admin_inventory,
    orders as admin_orders,
    products as admin_products,
    reports as admin_reports,
    reviews as admin_reviews,
    settings as admin_settings,
    vendors as admin_vendors,
    returns as admin_returns,

)
from app.api.routes import (
    addresses,
    auth,
    cart,
    categories,
    database,
    health,
    home,
    orders,
    products,
    profile,
    wishlist,
    reviews,
    returns,
)


api_router = APIRouter()


# ------------------------------------------------------------
# HEALTH
# ------------------------------------------------------------

api_router.include_router(
    health.router
)
api_router.include_router(
    returns.router
)
api_router.include_router(
    reviews.router
)
# ------------------------------------------------------------
# DATABASE
# ------------------------------------------------------------

api_router.include_router(
    database.router
)


# ------------------------------------------------------------
# AUTH
# ------------------------------------------------------------

api_router.include_router(
    auth.router
)


# ------------------------------------------------------------
# HOME
# ------------------------------------------------------------

api_router.include_router(
    home.router
)


# ------------------------------------------------------------
# PRODUCTS
# ------------------------------------------------------------

api_router.include_router(
    products.router
)


# ------------------------------------------------------------
# CATEGORIES
# ------------------------------------------------------------

api_router.include_router(
    categories.router
)


# ------------------------------------------------------------
# PROFILE
# ------------------------------------------------------------

api_router.include_router(
    profile.router
)


# ------------------------------------------------------------
# ADDRESSES
# ------------------------------------------------------------

api_router.include_router(
    addresses.router
)


# ------------------------------------------------------------
# WISHLIST
# ------------------------------------------------------------

api_router.include_router(
    wishlist.router
)


# ------------------------------------------------------------
# RECENTLY VIEWED
# ------------------------------------------------------------




# ------------------------------------------------------------
# CART
# ------------------------------------------------------------

api_router.include_router(
    cart.router
)


# ------------------------------------------------------------
# ORDERS
# ------------------------------------------------------------

api_router.include_router(
    orders.router
)


# ------------------------------------------------------------
# ADMIN DASHBOARD
# ------------------------------------------------------------

api_router.include_router(
    admin_dashboard.router
)

api_router.include_router(
    admin_vendors.router
)

api_router.include_router(
    admin_products.router
)

api_router.include_router(
    admin_categories.router
)

api_router.include_router(
    admin_customers.router
)

api_router.include_router(
    admin_orders.router
)

api_router.include_router(
    admin_inventory.router
)

api_router.include_router(
    admin_reviews.router
)

api_router.include_router(
    admin_finance.router
)

api_router.include_router(
    admin_reports.router
)

api_router.include_router(
    admin_settings.router
)
api_router.include_router(
    admin_returns.router
)