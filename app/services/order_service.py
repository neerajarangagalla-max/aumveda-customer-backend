import uuid
from datetime import datetime

from app.core.supabase import supabase_admin


def get_orders(user_id: str):
    response = (
        supabase_admin.table("orders")
        .select("*")
        .eq("user_id", user_id)
        .order("created_at", desc=True)
        .execute()
    )

    return response.data or []


def get_order(user_id: str, order_id: str):
    response = (
        supabase_admin.table("orders")
        .select("*")
        .eq("user_id", user_id)
        .eq("id", order_id)
        .limit(1)
        .execute()
    )

    data = response.data or []
    return data[0] if data else None


def create_order(user_id: str, payload: dict):
    order_number = (
        f"AUM-{datetime.now().strftime('%Y%m%d')}-"
        f"{uuid.uuid4().hex[:6].upper()}"
    )

    total_amount = float(payload.get("total_amount", 0))

    order_payload = {
        "order_number": order_number,
        "user_id": user_id,
        "customer_id": user_id,
        "shipping_address": payload.get(
            "shipping_address",
            {},
        ),
        "payment_method": payload.get(
            "payment_method",
            "cod",
        ),
        "total_amount": total_amount,
    }

    response = (
        supabase_admin.table("orders")
        .insert(order_payload)
        .execute()
    )

    data = response.data or []
    return data[0] if data else None