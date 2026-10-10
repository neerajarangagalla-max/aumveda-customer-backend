from functools import lru_cache

from supabase import Client, create_client

from app.core.config import settings


@lru_cache
def get_supabase_client() -> Client:
    return create_client(
        settings.supabase_url,
        settings.auth_client_key,
    )


@lru_cache
def get_supabase_admin_client() -> Client:
    return create_client(
        settings.supabase_url,
        settings.admin_client_key,
    )


supabase: Client = get_supabase_client()
supabase_admin: Client = get_supabase_admin_client()