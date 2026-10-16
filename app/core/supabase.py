from functools import lru_cache

from supabase import Client, create_client

from app.core.config import settings


# ============================================================
# AUTH CLIENT
# Used for Supabase Auth operations:
# login, signup, reset password, get user, etc.
# ============================================================

@lru_cache
def get_supabase_auth_client() -> Client:
    return create_client(
        settings.supabase_url,
        settings.auth_client_key,
    )


# ============================================================
# SERVER / ADMIN CLIENT
# Used for backend database operations.
# ============================================================

@lru_cache
def get_supabase_admin_client() -> Client:
    return create_client(
        settings.supabase_url,
        settings.admin_client_key,
    )


# ------------------------------------------------------------
# IMPORTANT COMPATIBILITY
# ------------------------------------------------------------
#
# Existing Customer Web routes import:
#
#     from app.core.supabase import supabase
#
# Those routes previously used the server secret key.
#
# Therefore keep `supabase` as the server/admin client so the
# existing Web backend behavior is preserved.
# ------------------------------------------------------------

supabase_admin: Client = get_supabase_admin_client()

supabase: Client = supabase_admin


# ------------------------------------------------------------
# Separate auth client for Mobile authentication services
# ------------------------------------------------------------

supabase_auth: Client = get_supabase_auth_client()