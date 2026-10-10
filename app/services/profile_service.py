from app.core.supabase import supabase_admin


def get_profile(user_id: str):
    response = (
        supabase_admin.table("profiles")
        .select("*")
        .eq("id", user_id)
        .limit(1)
        .execute()
    )

    data = response.data or []
    return data[0] if data else None


def update_profile(user_id: str, payload: dict):
    clean_payload = {
        key: value
        for key, value in payload.items()
        if value is not None
    }

    if not clean_payload:
        return get_profile(user_id)

    response = (
        supabase_admin.table("profiles")
        .update(clean_payload)
        .eq("id", user_id)
        .execute()
    )

    data = response.data or []
    return data[0] if data else get_profile(user_id)
