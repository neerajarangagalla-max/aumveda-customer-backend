from app.core.config import settings
from app.core.supabase import supabase_auth as supabase


def register_user(email: str, password: str):
    if len(password) < 6:
        raise ValueError("Password must contain at least 6 characters.")

    response = supabase.auth.sign_up(
        {
            "email": email,
            "password": password,
        }
    )

    if not response.user:
        raise ValueError("Unable to create account.")

    session = getattr(response, "session", None)

    return {
        "status": "success",
        "message": "Account created successfully.",
        "user": {
            "id": response.user.id,
            "email": response.user.email,
        },
        "access_token": session.access_token if session else None,
        "refresh_token": session.refresh_token if session else None,
    }


def login_user(email: str, password: str):
    response = supabase.auth.sign_in_with_password(
        {
            "email": email,
            "password": password,
        }
    )

    if not response.user:
        raise ValueError("Invalid email or password.")

    session = response.session

    return {
        "status": "success",
        "message": "Login successful.",
        "user": {
            "id": response.user.id,
            "email": response.user.email,
        },
        "access_token": session.access_token if session else None,
        "refresh_token": session.refresh_token if session else None,
    }


def refresh_session(refresh_token: str):
    response = supabase.auth.refresh_session({"refresh_token": refresh_token})
    session = getattr(response, "session", None)

    return {
        "status": "success",
        "access_token": session.access_token if session else None,
        "refresh_token": session.refresh_token if session else None,
    }


def send_reset_email(email: str):
    supabase.auth.reset_password_for_email(
        email,
        {"redirect_to": settings.mobile_reset_url},
    )

    return {
        "status": "success",
        "message": "If an account exists with this email, a password reset link has been sent.",
    }


def reset_password(access_token: str, password: str):
    if len(password) < 6:
        raise ValueError("Password must contain at least 6 characters.")

    auth_response = supabase.auth.get_user(access_token)
    user = auth_response.user if auth_response else None

    if not user:
        raise ValueError("Invalid or expired password reset link.")

    supabase.auth.admin.update_user_by_id(
        user.id,
        {"password": password},
    )

    return {
        "status": "success",
        "message": "Password updated successfully.",
    }


def logout():
    return {
        "status": "success",
        "message": "Logged out successfully.",
    }
