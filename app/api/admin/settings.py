from datetime import datetime, timezone
from io import BytesIO
import logging
import re
from urllib.parse import urlsplit
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.exceptions import RequestValidationError
from PIL import Image
from pydantic import BaseModel, Field, ValidationError, field_validator

from app.core.security import get_current_admin
from app.core.supabase import supabase

logger = logging.getLogger(__name__)
router = APIRouter(
    prefix="/admin/settings",
    tags=["Admin Settings"],
    dependencies=[Depends(get_current_admin)],
)

SENSITIVE_SETTING_PATTERN = re.compile(
    r"password|secret|token|credential|private.?key|service.?role|api.?key",
    re.IGNORECASE,
)


class BrandingSettingUpdate(BaseModel):
    site_name: str = Field(max_length=100)
    logo_url: str = Field(max_length=2048)
    favicon_url: str = Field(max_length=2048)

    @field_validator("site_name")
    @classmethod
    def validate_site_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Site name cannot be empty.")
        return normalized

    @field_validator("logo_url", "favicon_url")
    @classmethod
    def validate_asset_url(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            return normalized

        parsed = urlsplit(normalized)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.netloc
            or parsed.username
            or parsed.password
        ):
            raise ValueError("Logo and favicon URLs must be public HTTP(S) URLs.")
        return normalized


class InventoryThresholdUpdate(BaseModel):
    setting_value: int = Field(ge=0, le=100000, strict=True)


def save_setting(setting_key: str, setting_value):
    updated_at = datetime.now(timezone.utc).isoformat()
    values = {
        "setting_value": setting_value,
        "updated_at": updated_at,
    }
    columns = "setting_key, setting_value, updated_at"

    result = (
        supabase.table("site_settings")
        .update(values)
        .eq("setting_key", setting_key)
        .select(columns)
        .execute()
    )
    if result.data:
        return result.data[0]

    result = (
        supabase.table("site_settings")
        .insert({
            "setting_key": setting_key,
            **values,
        })
        .select(columns)
        .execute()
    )
    if not result.data:
        raise RuntimeError("The setting update returned no row.")
    return result.data[0]


def redact_sensitive_values(value):
    if isinstance(value, dict):
        return {
            key: (
                "[REDACTED]"
                if SENSITIVE_SETTING_PATTERN.search(str(key))
                else redact_sensitive_values(nested_value)
            )
            for key, nested_value in value.items()
        }

    if isinstance(value, list):
        return [redact_sensitive_values(item) for item in value]

    return value


@router.get("")
def list_site_settings():
    try:
        result = (
            supabase.table("site_settings")
            .select("setting_key, setting_value, updated_at")
            .execute()
        )

        items = []
        for row in result.data or []:
            item = dict(row)
            if SENSITIVE_SETTING_PATTERN.search(
                str(item.get("setting_key") or "")
            ):
                item["setting_value"] = "[REDACTED]"
            else:
                item["setting_value"] = redact_sensitive_values(
                    item.get("setting_value")
                )
            items.append(item)
        return {
            "items": items,
            "total": len(items),
        }
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=(
                "Unable to retrieve site settings; "
                "verify the site_settings table exists"
            ),
        ) from exc


@router.patch("/branding")
async def update_branding_settings(
    site_name: str = Form(...),
    logo_url: str = Form(default=""),
    favicon_url: str = Form(default=""),
    logo_file: UploadFile | None = File(default=None),
):
    storage_path = None
    try:
        try:
            payload = BrandingSettingUpdate(
                site_name=site_name,
                logo_url="" if logo_file else logo_url,
                favicon_url=favicon_url,
            )
        except ValidationError as exc:
            raise RequestValidationError(exc.errors()) from exc

        result = (
            supabase.table("site_settings")
            .select("setting_value")
            .eq("setting_key", "branding")
            .maybe_single()
            .execute()
        )
        current_value = (
            result.data.get("setting_value")
            if result.data
            else {}
        )
        if current_value is None:
            current_value = {}
        if not isinstance(current_value, dict):
            raise HTTPException(
                status_code=500,
                detail="Stored branding settings are invalid.",
            )

        version = current_value.get("branding_version", 0)
        if isinstance(version, bool) or not isinstance(version, int) or version < 0:
            raise HTTPException(
                status_code=500,
                detail="Stored branding version is invalid.",
            )

        if logo_file:
            allowed_types = {
                "image/jpeg": "jpg",
                "image/png": "png",
                "image/webp": "webp",
            }
            extension = allowed_types.get(logo_file.content_type or "")
            if not extension:
                raise HTTPException(
                    status_code=400,
                    detail="Choose a JPG, PNG, or WebP logo image.",
                )

            file_bytes = await logo_file.read(10 * 1024 * 1024 + 1)
            if not file_bytes:
                raise HTTPException(
                    status_code=400,
                    detail="The selected logo file is empty.",
                )
            if len(file_bytes) > 10 * 1024 * 1024:
                raise HTTPException(
                    status_code=413,
                    detail="Logo images must be smaller than 10 MB.",
                )

            try:
                with Image.open(BytesIO(file_bytes)) as uploaded_image:
                    uploaded_image.verify()
            except Exception as exc:
                raise HTTPException(
                    status_code=400,
                    detail="The selected logo is not a valid image.",
                ) from exc

            storage_path = f"branding/{uuid4()}.{extension}"
            supabase.storage.from_("site_assets").upload(
                storage_path,
                file_bytes,
                {
                    "content-type": logo_file.content_type,
                    "upsert": "false",
                },
            )
            payload.logo_url = (
                supabase.storage
                .from_("site_assets")
                .get_public_url(storage_path)
            )
            try:
                payload = BrandingSettingUpdate(
                    site_name=payload.site_name,
                    logo_url=payload.logo_url,
                    favicon_url=payload.favicon_url,
                )
            except ValidationError as exc:
                raise RequestValidationError(exc.errors()) from exc

        updated_value = {
            **current_value,
            **payload.model_dump(),
            "branding_version": version + 1,
        }
        item = save_setting("branding", updated_value)
        item["setting_value"] = redact_sensitive_values(
            item.get("setting_value")
        )
        return {"item": item}
    except RequestValidationError:
        raise
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Unable to update site branding")
        raise HTTPException(
            status_code=500,
            detail="Unable to update site branding.",
        ) from exc


@router.patch("/inventory.low_stock_threshold")
def update_inventory_threshold(payload: InventoryThresholdUpdate):
    try:
        item = save_setting(
            "inventory.low_stock_threshold",
            payload.setting_value,
        )
        return {"item": item}
    except Exception as exc:
        logger.exception("Unable to update the inventory low-stock threshold")
        raise HTTPException(
            status_code=500,
            detail="Unable to update the inventory low-stock threshold.",
        ) from exc
