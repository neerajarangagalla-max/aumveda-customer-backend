from fastapi import HTTPException, status

from app.core.supabase import supabase_admin


PUBLIC_SETTING_KEYS = {
    "branding",
}


def get_public_site_settings():
    try:
        response = (
            supabase_admin
            .table("site_settings")
            .select(
                "setting_key, setting_value, updated_at"
            )
            .in_(
                "setting_key",
                list(PUBLIC_SETTING_KEYS)
            )
            .execute()
        )

        rows = response.data or []

        settings = {}

        for row in rows:
            key = row.get("setting_key")
            value = row.get("setting_value")

            if key:
                settings[key] = value

        return settings

    except Exception as exc:
        print(
            "Failed to load public site settings:",
            exc
        )

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to load site settings.",
        )


def get_branding_settings():
    try:
        response = (
            supabase_admin
            .table("site_settings")
            .select(
                "setting_value, updated_at"
            )
            .eq(
                "setting_key",
                "branding"
            )
            .limit(1)
            .execute()
        )

        rows = response.data or []

        if not rows:
            return {
                "site_name": "AUMVEDA",
                "logo_url": "",
                "favicon_url": "",
                "branding_version": 1,
            }

        branding = (
            rows[0].get("setting_value")
            or {}
        )

        return {
            "site_name": branding.get(
                "site_name",
                "AUMVEDA"
            ),
            "logo_url": branding.get(
                "logo_url",
                ""
            ),
            "favicon_url": branding.get(
                "favicon_url",
                ""
            ),
            "branding_version": branding.get(
                "branding_version",
                1
            ),
        }

    except Exception as exc:
        print(
            "Failed to load branding:",
            exc
        )

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to load branding.",
        )