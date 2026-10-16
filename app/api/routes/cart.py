import logging
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

from app.core.supabase import supabase


router = APIRouter(
    prefix="/cart",
    tags=["Cart"],
)

logger = logging.getLogger(__name__)

security = HTTPBearer(
    auto_error=False
)


# ============================================================
# REQUEST MODELS
# ============================================================


class AddCartItemRequest(BaseModel):

    variant_id: UUID

    quantity: int = Field(
        default=1,
        ge=1,
    )


class UpdateCartItemRequest(BaseModel):

    quantity: int = Field(
        ge=1,
    )


# ============================================================
# AUTHENTICATION
# ============================================================


def get_current_customer_id(
    credentials: HTTPAuthorizationCredentials | None =
        Depends(security),
) -> str:

    # --------------------------------------------------------
    # Authorization header
    # --------------------------------------------------------

    if credentials is None:

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required.",
            headers={
                "WWW-Authenticate": "Bearer"
            },
        )


    if credentials.scheme.lower() != "bearer":

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication scheme.",
            headers={
                "WWW-Authenticate": "Bearer"
            },
        )


    access_token = credentials.credentials


    # --------------------------------------------------------
    # Validate token with Supabase Auth
    # --------------------------------------------------------

    try:

        auth_response = (
            supabase
            .auth
            .get_user(access_token)
        )

        user = getattr(
            auth_response,
            "user",
            None,
        )

        user_id = getattr(
            user,
            "id",
            None,
        )

    except Exception:

        logger.exception(
            "Supabase access token validation failed"
        )

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired authentication token.",
            headers={
                "WWW-Authenticate": "Bearer"
            },
        )


    if not user_id:

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token.",
            headers={
                "WWW-Authenticate": "Bearer"
            },
        )


    # --------------------------------------------------------
    # Verify AUMVEDA profile
    # --------------------------------------------------------

    try:

        profile_response = (
            supabase
            .table("profiles")
            .select(
                "id,role,is_active"
            )
            .eq(
                "id",
                user_id,
            )
            .limit(1)
            .execute()
        )

    except Exception:

        logger.exception(
            "Failed to load customer profile"
        )

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to verify customer profile.",
        )


    profiles = (
        profile_response.data
        or []
    )


    if not profiles:

        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "Customer profile not found. "
                "Please sign in again."
            ),
        )


    profile = profiles[0]


    if profile.get("role") != "customer":

        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This account is not a customer account.",
        )


    if profile.get("is_active") is False:

        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Customer account is inactive.",
        )


    return user_id


# ============================================================
# CART HELPERS
# ============================================================


def get_or_create_cart(
    customer_id: str,
) -> dict[str, Any]:

    # --------------------------------------------------------
    # Find existing cart
    # --------------------------------------------------------

    response = (
        supabase
        .table("carts")
        .select(
            "id,customer_id,created_at,updated_at"
        )
        .eq(
            "customer_id",
            customer_id,
        )
        .limit(1)
        .execute()
    )


    carts = response.data or []


    if carts:

        return carts[0]


    # --------------------------------------------------------
    # Create cart
    # --------------------------------------------------------

    try:

        insert_response = (
            supabase
            .table("carts")
            .insert(
                {
                    "customer_id": customer_id
                }
            )
            .select(
                "id,customer_id,created_at,updated_at"
            )
            .execute()
        )

        created_carts = (
            insert_response.data
            or []
        )

        if created_carts:

            return created_carts[0]

    except Exception:

        # ----------------------------------------------------
        # Another request may have created the cart
        # at exactly the same time.
        #
        # The database UNIQUE constraint on customer_id
        # protects us from duplicate carts.
        # ----------------------------------------------------

        logger.info(
            "Cart creation raced with another request; "
            "retrying cart lookup."
        )


    # --------------------------------------------------------
    # Re-fetch after possible concurrent creation
    # --------------------------------------------------------

    retry_response = (
        supabase
        .table("carts")
        .select(
            "id,customer_id,created_at,updated_at"
        )
        .eq(
            "customer_id",
            customer_id,
        )
        .limit(1)
        .execute()
    )


    retry_carts = (
        retry_response.data
        or []
    )


    if retry_carts:

        return retry_carts[0]


    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail="Unable to create customer cart.",
    )


# ============================================================
# GET CART ITEMS
# ============================================================


def get_cart_items(
    cart_id: str,
) -> list[dict[str, Any]]:

    response = (
        supabase
        .table("cart_items")
        .select(
            """
            id,
            cart_id,
            variant_id,
            quantity,
            created_at,
            updated_at,
            product_variants(
                id,
                product_id,
                name,
                price,
                compare_at_price,
                stock_quantity,
                is_active,
                products(
                    id,
                    name,
                    slug,
                    short_description,
                    status,
                    average_rating,
                    review_count,
                    product_images(
                        id,
                        image_url,
                        alt_text,
                        sort_order,
                        is_primary
                    )
                )
            )
            """
        )
        .eq(
            "cart_id",
            cart_id,
        )
        .order(
            "created_at"
        )
        .execute()
    )

    return response.data or []


# ============================================================
# IMAGE HELPER
# ============================================================


def get_primary_image(
    product: dict[str, Any] | None,
) -> str | None:

    if not product:

        return None


    images = (
        product.get("product_images")
        or []
    )


    if not images:

        return None


    sorted_images = sorted(
        images,
        key=lambda image: (
            not image.get(
                "is_primary",
                False,
            ),
            image.get(
                "sort_order"
            ) or 9999,
        ),
    )


    return sorted_images[0].get(
        "image_url"
    )


# ============================================================
# FORMAT CART RESPONSE
# ============================================================


def build_cart_response(
    cart: dict[str, Any],
) -> dict[str, Any]:

    items = get_cart_items(
        cart["id"]
    )


    formatted_items = []

    subtotal = 0.0
    total_quantity = 0


    for item in items:

        variant = (
            item.get(
                "product_variants"
            )
            or {}
        )


        product = (
            variant.get(
                "products"
            )
            or {}
        )


        quantity = int(
            item.get(
                "quantity"
            )
            or 0
        )


        price = float(
            variant.get(
                "price"
            )
            or 0
        )


        compare_at_price = (
            variant.get(
                "compare_at_price"
            )
        )


        if compare_at_price is not None:

            compare_at_price = float(
                compare_at_price
            )


        line_total = (
            price * quantity
        )


        subtotal += line_total

        total_quantity += quantity


        formatted_items.append(
            {
                "id": item.get("id"),

                "cart_id":
                    item.get("cart_id"),

                "variant_id":
                    item.get("variant_id"),

                "quantity":
                    quantity,

                "product": {
                    "id":
                        product.get("id"),

                    "name":
                        product.get("name"),

                    "slug":
                        product.get("slug"),

                    "short_description":
                        product.get(
                            "short_description"
                        ),

                    "image":
                        get_primary_image(
                            product
                        ),

                    "rating":
                        product.get(
                            "average_rating"
                        ),

                    "review_count":
                        product.get(
                            "review_count"
                        ),
                },

                "variant": {
                    "id":
                        variant.get("id"),

                    "name":
                        variant.get("name"),

                    "price":
                        price,

                    "compare_at_price":
                        compare_at_price,

                    "stock_quantity":
                        int(
                            variant.get(
                                "stock_quantity"
                            )
                            or 0
                        ),

                    "is_active":
                        variant.get(
                            "is_active",
                            False,
                        ),
                },

                "line_total":
                    line_total,

            }
        )


    return {
        "id":
            cart.get("id"),

        "customer_id":
            cart.get("customer_id"),

        "items":
            formatted_items,

        "item_count":
            len(formatted_items),

        "total_quantity":
            total_quantity,

        "subtotal":
            subtotal,

        "created_at":
            cart.get("created_at"),

        "updated_at":
            cart.get("updated_at"),
    }


# ============================================================
# GET VARIANT
# ============================================================


def get_active_variant(
    variant_id: str,
) -> dict[str, Any]:

    response = (
        supabase
        .table("product_variants")
        .select(
            """
            id,
            product_id,
            name,
            price,
            compare_at_price,
            stock_quantity,
            is_active,
            products(
                id,
                name,
                slug,
                status
            )
            """
        )
        .eq(
            "id",
            variant_id,
        )
        .limit(1)
        .execute()
    )


    variants = (
        response.data
        or []
    )


    if not variants:

        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product variant not found.",
        )


    variant = variants[0]


    if not variant.get(
        "is_active",
        False,
    ):

        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This product variant is no longer available.",
        )


    product = (
        variant.get(
            "products"
        )
        or {}
    )


    if product.get(
        "status"
    ) != "active":

        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This product is no longer available.",
        )


    return variant


# ============================================================
# GET CART
# ============================================================


@router.get("")
def get_cart(
    customer_id: str = Depends(
        get_current_customer_id
    ),
):

    try:

        cart = get_or_create_cart(
            customer_id
        )

        return {
            "status": "success",
            "data":
                build_cart_response(
                    cart
                ),
        }

    except HTTPException:

        raise

    except Exception as error:

        logger.exception(
            "Failed to load cart"
        )

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to load cart: {str(error)}",
        )


# ============================================================
# GET CART COUNT
# ============================================================


@router.get("/count")
def get_cart_count(
    customer_id: str = Depends(
        get_current_customer_id
    ),
):

    try:

        cart_response = (
            supabase
            .table("carts")
            .select("id")
            .eq(
                "customer_id",
                customer_id,
            )
            .limit(1)
            .execute()
        )


        carts = (
            cart_response.data
            or []
        )


        if not carts:

            return {
                "status": "success",
                "data": {
                    "item_count": 0,
                    "total_quantity": 0,
                },
            }


        cart_id = carts[0]["id"]


        items_response = (
            supabase
            .table("cart_items")
            .select(
                "quantity"
            )
            .eq(
                "cart_id",
                cart_id,
            )
            .execute()
        )


        items = (
            items_response.data
            or []
        )


        total_quantity = sum(
            int(
                item.get(
                    "quantity"
                )
                or 0
            )
            for item in items
        )


        return {
            "status": "success",
            "data": {
                "item_count":
                    len(items),

                "total_quantity":
                    total_quantity,
            },
        }

    except HTTPException:

        raise

    except Exception as error:

        logger.exception(
            "Failed to load cart count"
        )

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to load cart count: {str(error)}",
        )


# ============================================================
# ADD ITEM TO CART
# ============================================================


@router.post("/items")
def add_cart_item(
    payload: AddCartItemRequest,
    customer_id: str = Depends(
        get_current_customer_id
    ),
):

    try:

        variant_id = str(
            payload.variant_id
        )


        variant = get_active_variant(
            variant_id
        )


        stock_quantity = int(
            variant.get(
                "stock_quantity"
            )
            or 0
        )


        if stock_quantity <= 0:

            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This product is out of stock.",
            )


        cart = get_or_create_cart(
            customer_id
        )


        cart_id = cart["id"]


        # ----------------------------------------------------
        # Check existing cart item
        # ----------------------------------------------------

        existing_response = (
            supabase
            .table("cart_items")
            .select(
                "id,quantity"
            )
            .eq(
                "cart_id",
                cart_id,
            )
            .eq(
                "variant_id",
                variant_id,
            )
            .limit(1)
            .execute()
        )


        existing_items = (
            existing_response.data
            or []
        )


        if existing_items:

            existing_item = (
                existing_items[0]
            )


            new_quantity = (
                int(
                    existing_item.get(
                        "quantity"
                    )
                    or 0
                )
                +
                payload.quantity
            )


            if new_quantity > stock_quantity:

                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=(
                        f"Only {stock_quantity} "
                        "unit(s) are currently available."
                    ),
                )


            (
                supabase
                .table("cart_items")
                .update(
                    {
                        "quantity":
                            new_quantity
                    }
                )
                .eq(
                    "id",
                    existing_item["id"],
                )
                .eq(
                    "cart_id",
                    cart_id,
                )
                .execute()
            )

        else:

            if payload.quantity > stock_quantity:

                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=(
                        f"Only {stock_quantity} "
                        "unit(s) are currently available."
                    ),
                )


            try:

                (
                    supabase
                    .table("cart_items")
                    .insert(
                        {
                            "cart_id":
                                cart_id,

                            "variant_id":
                                variant_id,

                            "quantity":
                                payload.quantity,
                        }
                    )
                    .execute()
                )

            except Exception:

                # ------------------------------------------------
                # Another request may have inserted the same
                # cart/variant pair simultaneously.
                # Re-read and increase the quantity safely.
                # ------------------------------------------------

                retry_response = (
                    supabase
                    .table("cart_items")
                    .select(
                        "id,quantity"
                    )
                    .eq(
                        "cart_id",
                        cart_id,
                    )
                    .eq(
                        "variant_id",
                        variant_id,
                    )
                    .limit(1)
                    .execute()
                )


                retry_items = (
                    retry_response.data
                    or []
                )


                if not retry_items:

                    raise


                retry_item = (
                    retry_items[0]
                )


                new_quantity = (
                    int(
                        retry_item.get(
                            "quantity"
                        )
                        or 0
                    )
                    +
                    payload.quantity
                )


                if new_quantity > stock_quantity:

                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail=(
                            f"Only {stock_quantity} "
                            "unit(s) are currently available."
                        ),
                    )


                (
                    supabase
                    .table("cart_items")
                    .update(
                        {
                            "quantity":
                                new_quantity
                        }
                    )
                    .eq(
                        "id",
                        retry_item["id"],
                    )
                    .eq(
                        "cart_id",
                        cart_id,
                    )
                    .execute()
                )


        return {
            "status": "success",
            "message": "Product added to cart.",
            "data":
                build_cart_response(
                    cart
                ),
        }


    except HTTPException:

        raise

    except Exception as error:

        logger.exception(
            "Failed to add item to cart"
        )

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to add item to cart: {str(error)}",
        )


# ============================================================
# UPDATE CART ITEM
# ============================================================


@router.patch("/items/{item_id}")
def update_cart_item(
    item_id: UUID,
    payload: UpdateCartItemRequest,
    customer_id: str = Depends(
        get_current_customer_id
    ),
):

    try:

        cart = get_or_create_cart(
            customer_id
        )


        cart_id = cart["id"]


        item_response = (
            supabase
            .table("cart_items")
            .select(
                "id,cart_id,variant_id,quantity"
            )
            .eq(
                "id",
                str(item_id),
            )
            .eq(
                "cart_id",
                cart_id,
            )
            .limit(1)
            .execute()
        )


        items = (
            item_response.data
            or []
        )


        if not items:

            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Cart item not found.",
            )


        item = items[0]


        variant = get_active_variant(
            item["variant_id"]
        )


        stock_quantity = int(
            variant.get(
                "stock_quantity"
            )
            or 0
        )


        if payload.quantity > stock_quantity:

            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"Only {stock_quantity} "
                    "unit(s) are currently available."
                ),
            )


        (
            supabase
            .table("cart_items")
            .update(
                {
                    "quantity":
                        payload.quantity
                }
            )
            .eq(
                "id",
                str(item_id),
            )
            .eq(
                "cart_id",
                cart_id,
            )
            .execute()
        )


        return {
            "status": "success",
            "message": "Cart item updated.",
            "data":
                build_cart_response(
                    cart
                ),
        }


    except HTTPException:

        raise

    except Exception as error:

        logger.exception(
            "Failed to update cart item"
        )

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update cart item: {str(error)}",
        )


# ============================================================
# DELETE CART ITEM
# ============================================================


@router.delete("/items/{item_id}")
def delete_cart_item(
    item_id: UUID,
    customer_id: str = Depends(
        get_current_customer_id
    ),
):

    try:

        cart = get_or_create_cart(
            customer_id
        )


        cart_id = cart["id"]


        item_response = (
            supabase
            .table("cart_items")
            .select(
                "id"
            )
            .eq(
                "id",
                str(item_id),
            )
            .eq(
                "cart_id",
                cart_id,
            )
            .limit(1)
            .execute()
        )


        if not item_response.data:

            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Cart item not found.",
            )


        (
            supabase
            .table("cart_items")
            .delete()
            .eq(
                "id",
                str(item_id),
            )
            .eq(
                "cart_id",
                cart_id,
            )
            .execute()
        )


        return {
            "status": "success",
            "message": "Cart item removed.",
            "data":
                build_cart_response(
                    cart
                ),
        }


    except HTTPException:

        raise

    except Exception as error:

        logger.exception(
            "Failed to delete cart item"
        )

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete cart item: {str(error)}",
        )


# ============================================================
# CLEAR CART
# ============================================================


@router.delete("")
def clear_cart(
    customer_id: str = Depends(
        get_current_customer_id
    ),
):

    try:

        cart = get_or_create_cart(
            customer_id
        )


        cart_id = cart["id"]


        (
            supabase
            .table("cart_items")
            .delete()
            .eq(
                "cart_id",
                cart_id,
            )
            .execute()
        )


        return {
            "status": "success",
            "message": "Cart cleared.",
            "data":
                build_cart_response(
                    cart
                ),
        }


    except HTTPException:

        raise

    except Exception as error:

        logger.exception(
            "Failed to clear cart"
        )

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to clear cart: {str(error)}",
        )