from app.core.supabase import supabase_admin


def get_or_create_cart(user_id: str):
    response = (
        supabase_admin.table("carts")
        .select("*")
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    )

    if response.data:
        return response.data[0]

    created = (
        supabase_admin.table("carts")
        .insert({"user_id": user_id})
        .execute()
    )

    return (created.data or [{}])[0]


def get_cart(user_id: str):
    cart = get_or_create_cart(user_id)
    cart_id = cart.get("id")

    if not cart_id:
        return {"items": []}

    response = (
        supabase_admin.table("cart_items")
        .select("*")
        .eq("cart_id", cart_id)
        .execute()
    )

    return {
        "id": cart_id,
        "items": response.data or [],
    }


def add_item(user_id: str, product_id: str, variant_id: str, quantity: int = 1):
    cart = get_or_create_cart(user_id)
    cart_id = cart.get("id")

    if not cart_id:
        raise ValueError("Unable to initialize cart.")

    response = (
        supabase_admin.table("cart_items")
        .insert(
            {
                "cart_id": cart_id,
                "product_id": product_id,
                "variant_id": variant_id,
                "quantity": quantity,
            }
        )
        .execute()
    )

    return response.data or []


def update_item(item_id: str, quantity: int):
    response = (
        supabase_admin.table("cart_items")
        .update({"quantity": quantity})
        .eq("id", item_id)
        .execute()
    )

    return response.data or []


def remove_item(item_id: str):
    response = (
        supabase_admin.table("cart_items")
        .delete()
        .eq("id", item_id)
        .execute()
    )

    return response.data or []
