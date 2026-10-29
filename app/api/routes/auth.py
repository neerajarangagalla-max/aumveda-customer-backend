import logging
from app.core.config import settings
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, EmailStr
from app.core.supabase import supabase_admin, supabase_auth
from app.core.security import get_current_user

router = APIRouter(
        prefix="/auth",
        tags=["Authentication"],
    )

logger = logging.getLogger(__name__)


class AuthRequest(BaseModel):
        email: EmailStr
        password: str


class RefreshSessionRequest(BaseModel):
        refresh_token: str


@router.post("/register")
async def register_user(payload: AuthRequest):

        try:
            if len(payload.password) < 6:
                raise HTTPException(
                    status_code=400,
                    detail="Password must contain at least 6 characters.",
                )

            response = supabase_auth.auth.sign_up(
                {
                    "email": payload.email,
                    "password": payload.password,
                }
            )

            if not response.user:
                raise HTTPException(
                    status_code=400,
                    detail="Unable to create account.",
                )

            return {
                "status": "success",
                "message": "Account created successfully.",
                "user": {
                    "id": response.user.id,
                    "email": response.user.email,
                },
                "access_token": (
                    response.session.access_token
                    if response.session
                    else None
                ),
                "refresh_token": (
                    response.session.refresh_token
                    if response.session
                    else None
                ),
            }

        except HTTPException:
            raise
        except Exception:
            logger.exception("Registration failed")
            raise HTTPException(
        status_code=400,
        detail="Unable to register. Please try again.",
    )


@router.post("/login")
async def login_user(payload: AuthRequest):

        try:
            response = (
                supabase_auth.auth.sign_in_with_password(
                    {
                        "email": payload.email,
                        "password": payload.password,
                    }
                )
            )

            if not response.user:
                raise HTTPException(
                    status_code=401,
                    detail="Invalid email or password.",
                )

            return {
                "status": "success",
                "message": "Login successful.",
                "user": {
                    "id": response.user.id,
                    "email": response.user.email,
                },
                "access_token": response.session.access_token,
                "refresh_token": response.session.refresh_token,
            }

        except HTTPException:
            raise

        except Exception:
            logger.exception(
                "Login failed"
            )

            raise HTTPException(
                status_code=401,
                detail="Invalid email or password.",
            )


@router.post("/refresh")
async def refresh_auth_session(payload: RefreshSessionRequest):
        try:
            response = supabase_auth.auth.refresh_session(
                {"refresh_token": payload.refresh_token}
            )
            session = getattr(response, "session", None)
            if not session:
                raise HTTPException(
                    status_code=401,
                    detail="Invalid or expired refresh token.",
                )

            return {
                "status": "success",
                "access_token": session.access_token,
                "refresh_token": session.refresh_token,
            }

        except HTTPException:
            raise

        except Exception:
            logger.exception("Session refresh failed")
            raise HTTPException(
                status_code=401,
                detail="Unable to refresh session.",
            )



@router.get("/profile")
async def get_profile(user=Depends(get_current_user)):
    try:
        response = (
            supabase_admin.table("profiles")
            .select("*")
            .eq("id", user.id)
            .limit(1)
            .execute()
        )

        profile_rows = response.data or []
        profile = profile_rows[0] if profile_rows else {}

        return {
            "status": "success",
            "data": {
                **profile,
                "id": user.id,
                "email": user.email,
            },
        }

    except Exception as error:
        logger.exception("Profile retrieval failed")
        raise HTTPException(
            status_code=500,
            detail="Unable to retrieve profile.",
        ) from error


@router.post("/forgot-password")
async def forgot_password(payload: ForgotPasswordRequest):
    try:
        supabase_auth.auth.reset_password_for_email(
            payload.email,
            {
                "redirect_to": settings.mobile_reset_url,
                }
        )

        return {
            "status": "success",
            "message": "If an account exists with this email, a password reset link has been sent.",
        }
    except Exception:
        logger.exception("Password reset request failed")

    raise HTTPException(
        status_code=400,
        detail="Unable to process the password reset request.",
    )

@router.post("/reset-password")
async def reset_password(payload: ResetPasswordRequest):
    if len(payload.password) < 6:
        raise HTTPException(
            status_code=400,
            detail="Password must contain at least 6 characters.",
        )

    try:
        auth_response = supabase_auth.auth.get_user(payload.access_token)
        user = auth_response.user if auth_response else None

        if not user:
            raise HTTPException(
                status_code=401,
                detail="Invalid or expired password reset link.",
            )

        supabase_admin.auth.admin.update_user_by_id(
            user.id,
            {"password": payload.password},
        )

        return {
            "status": "success",
            "message": "Password updated successfully.",
        }

    except HTTPException:
        raise

    except Exception as error:
        logger.exception("Password reset failed")
        raise HTTPException(
            status_code=400,
            detail="Unable to reset password.",
        ) from error