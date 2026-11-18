from functools import lru_cache

import httpx
from supabase import Client, create_client
from supabase.client import ClientOptions

from app.core.config import settings


def _create_supabase_client(api_key: str) -> Client:
    # Render traces showed intermittent HTTP/2 ReadErrors from PostgREST.
    options = ClientOptions(
        httpx_client=httpx.Client(
            http2=False,
            timeout=ClientOptions().postgrest_client_timeout,
        )
    )

    return create_client(
        settings.supabase_url,
        api_key,
        options=options,
    )


# ============================================================
# AUTH CLIENT
# Used for Supabase Auth operations:
# login, signup, reset password, get user, etc.
# ============================================================

@lru_cache
def get_supabase_auth_client() -> Client:
    return _create_supabase_client(
        settings.auth_client_key
    )


# ============================================================
# SERVER / ADMIN CLIENT
# Used for backend database operations.
# ============================================================

@lru_cache
def get_supabase_admin_client() -> Client:
    return _create_supabase_client(
        settings.admin_client_key
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