
import logging

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.supabase import supabase_auth, supabase_admin

logger = logging.getLogger(__name__)
security = HTTPBearer()


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    token = credentials.credentials

    try:
        response = supabase_auth.auth.get_user(token)

        if not response or not response.user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired token",
            )

        return response.user

    except HTTPException:
        raise

    except Exception as exc:
        logger.exception("Failed to verify Supabase access token")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        ) from exc


def get_current_admin(
    current_user=Depends(get_current_user),
):
    try:
        response = (
            supabase_admin
            .table("profiles")
            .select("id, role, is_active")
            .eq("id", str(current_user.id))
            .maybe_single()
            .execute()
        )

        profile = response.data

        if not profile or profile.get("role") != "admin":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Administrator access required",
            )

        if profile.get("is_active") is False:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="This account is inactive",
            )

        return current_user

    except HTTPException:
        raise

    except Exception as exc:
        logger.exception("Failed to verify administrator permissions")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to verify administrator permissions",
        ) from exc
