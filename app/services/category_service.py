from app.core.supabase import supabase_admin


def get_categories():
    response = (
        supabase_admin.table("categories")
        .select(
            """
            id,
            name,
            slug,
            description,
            image_url,
            is_active,
            home_sort_order
            """
        )
        .eq("is_active", True)
        .order("home_sort_order")
        .execute()
    )

    return response.data or []


def get_category(slug: str):
    response = (
        supabase_admin.table("categories")
        .select(
            """
            id,
            name,
            slug,
            description,
            image_url,
            is_active,
            home_sort_order
            """
        )
        .eq("slug", slug)
        .eq("is_active", True)
        .limit(1)
        .execute()
    )

    data = response.data or []
    return data[0] if data else None
