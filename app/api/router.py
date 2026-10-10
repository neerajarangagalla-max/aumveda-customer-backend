from fastapi import APIRouter

from app.api.routes import (
    auth,
    cart,
    categories,
    database,
    health,
    home,
    products,
    addresses,
    wishlist,
    orders,
    profile,
    recently_viewed,
)

api_router = APIRouter()

api_router.include_router(health.router)
api_router.include_router(database.router)
api_router.include_router(auth.router)
api_router.include_router(home.router)
api_router.include_router(products.router)
api_router.include_router(categories.router)
api_router.include_router(cart.router)
api_router.include_router(wishlist.router)
api_router.include_router(orders.router)
api_router.include_router(profile.router)
api_router.include_router(addresses.router)
api_router.include_router(recently_viewed.router)