
"""
AUMVEDA Vendor Backend
Business Branding Service

Policy:
- Logo and banner updates take effect immediately.
- Admin approval is not required.
- Vendor ID comes from authenticated backend context.
- Upload endpoints must require get_vendor_owner.
- Approved image URLs are stored in public.vendors.
- Legacy approval requests are retained as history.
"""

import logging
import os
import uuid

from fastapi import HTTPException, UploadFile, status

from app.core.supabase import supabase_admin


logger = logging.getLogger(
    "aumveda.vendor.branding"
)


# ============================================================
# STORAGE CONFIGURATION
# ============================================================

BUCKET_NAME = os.getenv(
    "VENDOR_BRANDING_BUCKET",
    "vendor_images",
).strip()

ALLOWED_CONTENT_TYPES = {
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}

MAX_FILE_SIZE = 5 * 1024 * 1024


# ============================================================
# ERROR HELPERS
# ============================================================

def _storage_error() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail=(
            "Unable to upload the branding image. "
            "Verify the configured Supabase Storage bucket."
        ),
    )


def _database_error() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="Unable to update business branding.",
    )


# ============================================================
# LOAD VENDOR
# ============================================================

def _get_vendor(vendor_id: str) -> dict:
    try:
        response = (
            supabase_admin
            .table("vendors")
            .select(
                "id,business_name,logo_url,banner_url,"
                "status,is_active"
            )
            .eq("id", vendor_id)
            .limit(1)
            .execute()
        )

        rows = response.data or []

    except Exception:
        logger.exception(
            "Failed to load vendor branding: vendor_id=%s",
            vendor_id,
        )
        raise _database_error() from None

    if not rows:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Vendor was not found.",
        )

    return rows[0]


# ============================================================
# VALIDATE IMAGE
# ============================================================

async def _read_and_validate_image(
    file: UploadFile,
) -> tuple[bytes, str, str]:

    content_type = (
        file.content_type or ""
    ).strip().lower()

    if content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Only JPG, PNG and WEBP images are allowed."
            ),
        )

    # Read no more than the permitted limit plus one byte.
    content = await file.read(MAX_FILE_SIZE + 1)

    if not content:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded image is empty.",
        )

    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Image size must not exceed 5 MB.",
        )

    # Check the actual file signature, not only
    # the Content-Type supplied by the browser.

    if content_type in ("image/jpeg", "image/jpg"):
        valid_image = content.startswith(b"\xff\xd8\xff")

    elif content_type == "image/png":
        valid_image = content.startswith(
            b"\x89PNG\r\n\x1a\n"
        )

    else:
        valid_image = (
            len(content) >= 12
            and content[:4] == b"RIFF"
            and content[8:12] == b"WEBP"
        )

    if not valid_image:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "The uploaded file does not match "
                "its declared image format."
            ),
        )

    extension = ALLOWED_CONTENT_TYPES[content_type]

    storage_content_type = (
        "image/jpeg"
        if content_type == "image/jpg"
        else content_type
    )

    return content, extension, storage_content_type


# ============================================================
# GENERATE UNIQUE STORAGE PATH
# ============================================================

def _build_storage_path(
    vendor_id: str,
    request_type: str,
    extension: str,
) -> str:

    file_id = uuid.uuid4().hex

    return (
        f"{vendor_id}/branding/"
        f"{request_type}/"
        f"{file_id}{extension}"
    )


# ============================================================
# GENERATE PUBLIC IMAGE URL
# ============================================================

def _get_public_url(path: str) -> str:
    try:
        result = (
            supabase_admin
            .storage
            .from_(BUCKET_NAME)
            .get_public_url(path)
        )

        if isinstance(result, str):
            url = result

        elif isinstance(result, dict):
            url = (
                result.get("publicUrl")
                or result.get("public_url")
                or ""
            )

        else:
            url = str(result)

        if not url or not url.startswith(
            ("https://", "http://")
        ):
            raise ValueError(
                "Invalid public branding image URL."
            )

        return url

    except Exception:
        logger.exception(
            "Failed to generate branding image URL."
        )
        raise _storage_error() from None


# ============================================================
# GET CURRENT BRANDING
#
# Keep frontend response structure compatible.
# Previous pending requests remain in the database,
# but no longer block new uploads.
# ============================================================

def get_vendor_branding(
    vendor_id: str,
) -> dict:

    vendor = _get_vendor(vendor_id)

    return {
        "approved": {
            "logo_url": vendor.get("logo_url"),
            "banner_url": vendor.get("banner_url"),
        },
        "pending": {
            "logo": None,
            "banner": None,
        },
        "latest": {
            "logo": None,
            "banner": None,
        },
    }


# ============================================================
# HISTORICAL BRANDING REQUESTS
#
# Read-only legacy functionality.
# Existing records are not deleted or altered.
# ============================================================

def list_vendor_branding_requests(
    vendor_id: str,
) -> list[dict]:

    try:
        response = (
            supabase_admin
            .table("vendor_branding_requests")
            .select("*")
            .eq("vendor_id", vendor_id)
            .order("created_at", desc=True)
            .execute()
        )

        return response.data or []

    except Exception:
        logger.exception(
            "Unable to load branding history: vendor_id=%s",
            vendor_id,
        )
        raise _database_error() from None


# ============================================================
# UPLOAD AND APPLY BRANDING IMMEDIATELY
#
# Required route authorization:
#     Depends(get_vendor_owner)
#
# Logo:
#     vendors.logo_url
#
# Banner:
#     vendors.banner_url
#
# No approval request is created.
# ============================================================

async def upload_vendor_branding_image(
    vendor_id: str,
    request_type: str,
    file: UploadFile,
) -> dict:

    normalized_type = str(
        request_type
    ).strip().lower()

    if normalized_type not in ("logo", "banner"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid branding image type.",
        )

    vendor = _get_vendor(vendor_id)

    # Defensive check even though the API
    # requires an approved, active Vendor Owner.

    if (
        vendor.get("status") != "approved"
        or vendor.get("is_active") is not True
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Vendor account is not approved and active.",
        )

    content, extension, content_type = (
        await _read_and_validate_image(file)
    )

    storage_path = _build_storage_path(
        vendor_id=vendor_id,
        request_type=normalized_type,
        extension=extension,
    )

    # --------------------------------------------------------
    # 1. UPLOAD TO SUPABASE STORAGE
    # --------------------------------------------------------

    try:
        (
            supabase_admin
            .storage
            .from_(BUCKET_NAME)
            .upload(
                path=storage_path,
                file=content,
                file_options={
                    "content-type": content_type,
                    "upsert": "false",
                },
            )
        )

    except Exception:
        logger.exception(
            "Branding upload failed: vendor_id=%s type=%s "
            "bucket=%s",
            vendor_id,
            normalized_type,
            BUCKET_NAME,
        )
        raise _storage_error() from None

    # --------------------------------------------------------
    # 2. GENERATE PUBLIC URL
    # --------------------------------------------------------

    public_url = _get_public_url(storage_path)

    # --------------------------------------------------------
    # 3. APPLY NEW IMAGE TO VENDOR
    #
    # Existing image remains active if the upload
    # fails before the database update.
    # --------------------------------------------------------

    target_column = (
        "logo_url"
        if normalized_type == "logo"
        else "banner_url"
    )

    try:
        response = (
            supabase_admin
            .table("vendors")
            .update({
                target_column: public_url,
            })
            .eq("id", vendor_id)
            .eq("status", "approved")
            .eq("is_active", True)
            .execute()
        )

        rows = response.data or []

        if not rows:
            raise RuntimeError(
                "Vendor branding update returned no record."
            )

    except Exception:
        logger.exception(
            "Branding database update failed: "
            "vendor_id=%s type=%s",
            vendor_id,
            normalized_type,
        )

        # Do not automatically delete the newly uploaded
        # image after an uncertain database write.
        # The update might have committed before a
        # network failure. Reconcile unused objects later.

        raise _database_error() from None

    # --------------------------------------------------------
    # 4. RETURN SUCCESS
    # --------------------------------------------------------

    return {
        "status": "success",
        "message": (
            f"{normalized_type.capitalize()} "
            "updated successfully."
        ),
        "image_type": normalized_type,
        "image_url": public_url,
        "vendor_id": vendor_id,
    }
