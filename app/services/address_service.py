from app.core.supabase import supabase_admin


def get_addresses(user_id: str):
    response = (
        supabase_admin
        .table("customer_addresses")
        .select("*")
        .eq("customer_id", user_id)
        .order("is_default", desc=True)
        .order("created_at", desc=True)
        .execute()
    )

    return response.data or []


def get_address(user_id: str, address_id: str):
    response = (
        supabase_admin
        .table("customer_addresses")
        .select("*")
        .eq("id", address_id)
        .eq("customer_id", user_id)
        .limit(1)
        .execute()
    )

    data = response.data or []

    return data[0] if data else None


def create_address(
    user_id: str,
    payload: dict,
):
    is_default = payload.get(
        "is_default",
        False,
    )

    # If this is the first address,
    # automatically make it default.
    existing = get_addresses(user_id)

    if not existing:
        is_default = True

    # If this address should become default,
    # remove default from existing addresses.
    if is_default:
        (
            supabase_admin
            .table("customer_addresses")
            .update({"is_default": False})
            .eq("customer_id", user_id)
            .execute()
        )

    address_payload = {
        "customer_id": user_id,
        "label": payload.get("label"),
        "recipient_name": payload["recipient_name"],
        "phone": payload["phone"],
        "address_line1": payload["address_line1"],
        "address_line2": payload.get("address_line2"),
        "city": payload["city"],
        "state": payload["state"],
        "postal_code": payload["postal_code"],
        "country": payload.get(
            "country",
            "India",
        ),
        "is_default": is_default,
    }

    response = (
        supabase_admin
        .table("customer_addresses")
        .insert(address_payload)
        .execute()
    )

    data = response.data or []

    return data[0] if data else None


def update_address(
    user_id: str,
    address_id: str,
    payload: dict,
):
    existing = get_address(
        user_id,
        address_id,
    )

    if not existing:
        return None

    clean_payload = {
        key: value
        for key, value in payload.items()
        if value is not None
    }

    if clean_payload.get("is_default") is True:
        (
            supabase_admin
            .table("customer_addresses")
            .update({"is_default": False})
            .eq("customer_id", user_id)
            .execute()
        )

    if not clean_payload:
        return existing

    response = (
        supabase_admin
        .table("customer_addresses")
        .update(clean_payload)
        .eq("id", address_id)
        .eq("customer_id", user_id)
        .execute()
    )

    data = response.data or []

    return data[0] if data else get_address(
        user_id,
        address_id,
    )


def delete_address(
    user_id: str,
    address_id: str,
):
    existing = get_address(
        user_id,
        address_id,
    )

    if not existing:
        return False

    was_default = existing.get(
        "is_default",
        False,
    )

    (
        supabase_admin
        .table("customer_addresses")
        .delete()
        .eq("id", address_id)
        .eq("customer_id", user_id)
        .execute()
    )

    # If default address was deleted,
    # make another address default.
    if was_default:
        remaining = get_addresses(user_id)

        if remaining:
            (
                supabase_admin
                .table("customer_addresses")
                .update({"is_default": True})
                .eq("id", remaining[0]["id"])
                .eq("customer_id", user_id)
                .execute()
            )

    return True