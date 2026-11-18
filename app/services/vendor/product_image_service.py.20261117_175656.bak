
from __future__ import annotations

import mimetypes
import uuid

from urllib.parse import unquote, urlparse

from fastapi import HTTPException, UploadFile, status

from app.core.supabase import supabase_admin


# ============================================================
# CONFIGURATION
# ============================================================

PRODUCT_IMAGE_BUCKET = "product_images"

MAX_IMAGE_SIZE_BYTES = 8 * 1024 * 1024

ALLOWED_IMAGE_TYPES = {
    "image/jpeg",
    "image/jpg",
    "image/png",
    "image/webp",
}

# Only products in these states may have images
# modified directly through Vendor Backend.
IMAGE_EDITABLE_PRODUCT_STATUSES = {
    "draft",
    "rejected",
}


# ============================================================
# PRODUCT OWNERSHIP AND APPROVAL PROTECTION
# ============================================================

def _get_owned_product(
    vendor_id: str,
    product_id: str,
) -> dict:
    """
    Verify that the product belongs to the authenticated
    vendor. Never trust vendor_id from frontend input.
    """

    try:
        response = (
            supabase_admin
            .table("products")
            .select("id,vendor_id,name,status")
            .eq("id", product_id)
            .eq("vendor_id", vendor_id)
            .limit(1)
            .execute()
        )

    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to verify product ownership.",
        ) from exc

    rows = response.data or []

    if not rows:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product not found.",
        )

    return rows[0]


def _ensure_product_images_editable(
    vendor_id: str,
    product_id: str,
) -> dict:
    """
    Protect product approval.

    Image modifications are allowed only for:
    - draft
    - rejected

    Pending, active and archived products cannot have
    their images changed through the Vendor API.

    Admin approval will later be integrated separately.
    """

    product = _get_owned_product(
        vendor_id=vendor_id,
        product_id=product_id,
    )

    product_status = str(
        product.get("status") or ""
    ).strip().lower()

    if product_status not in IMAGE_EDITABLE_PRODUCT_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Product images cannot be modified while "
                f"the product status is '{product_status}'. "
                "Only draft or rejected products may have "
                "their images changed. Approved-product "
                "image changes require a separate review."
            ),
        )

    return product


# ============================================================
# IMAGE HELPERS
# ============================================================

def _get_product_image(
    vendor_id: str,
    product_id: str,
    image_id: str,
) -> dict:
    """
    Return the image only when it belongs to
    the specified product and vendor.
    """

    _get_owned_product(
        vendor_id=vendor_id,
        product_id=product_id,
    )

    try:
        response = (
            supabase_admin
            .table("product_images")
            .select(
                "id,"
                "product_id,"
                "variant_id,"
                "image_url,"
                "alt_text,"
                "sort_order,"
                "is_primary,"
                "created_at"
            )
            .eq("id", image_id)
            .eq("product_id", product_id)
            .limit(1)
            .execute()
        )

    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to load product image.",
        ) from exc

    rows = response.data or []

    if not rows:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product image not found.",
        )

    return rows[0]


def _get_extension(
    filename: str | None,
    content_type: str | None,
) -> str:
    """
    Determine the image extension without using
    the original filename as the storage object name.
    """

    extension = ""

    if filename:
        filename = filename.lower().strip()

        if "." in filename:
            extension = "." + filename.rsplit(".", 1)[1]

    allowed_extensions = {
        ".jpg",
        ".jpeg",
        ".png",
        ".webp",
    }

    if extension in allowed_extensions:
        return extension

    guessed_extension = (
        mimetypes.guess_extension(content_type or "")
        or ""
    )

    if guessed_extension in allowed_extensions:
        return guessed_extension

    if content_type in {"image/jpeg", "image/jpg"}:
        return ".jpg"

    if content_type == "image/png":
        return ".png"

    if content_type == "image/webp":
        return ".webp"

    return ".jpg"


def _extract_storage_path(
    image_url: str,
) -> str | None:
    """
    Existing product_images schema stores image_url,
    not storage_path.

    Extract storage path from a public Supabase URL.
    """

    if not image_url:
        return None

    marker = (
        "/storage/v1/object/public/"
        f"{PRODUCT_IMAGE_BUCKET}/"
    )

    try:
        parsed = urlparse(image_url)
        path = unquote(parsed.path)
    except Exception:
        return None

    if marker not in path:
        return None

    storage_path = (
        path.split(marker, 1)[1].lstrip("/")
    )

    return storage_path or None


def _public_url_for_path(
    storage_path: str,
) -> str:
    try:
        result = (
            supabase_admin
            .storage
            .from_(PRODUCT_IMAGE_BUCKET)
            .get_public_url(storage_path)
        )

    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to generate product image URL.",
        ) from exc

    if isinstance(result, str):
        return result

    if isinstance(result, dict):
        return (
            result.get("publicUrl")
            or result.get("public_url")
            or result.get("signedURL")
        )

    return str(result)


def _set_only_primary_image(
    product_id: str,
    image_id: str,
) -> None:
    """
    Clear other primary flags and set the selected image
    as primary.

    Note: these operations are not currently atomic.
    """

    try:
        (
            supabase_admin
            .table("product_images")
            .update({"is_primary": False})
            .eq("product_id", product_id)
            .execute()
        )

        (
            supabase_admin
            .table("product_images")
            .update({"is_primary": True})
            .eq("id", image_id)
            .eq("product_id", product_id)
            .execute()
        )

    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to update primary product image.",
        ) from exc


# ============================================================
# LIST PRODUCT IMAGES
# ============================================================

def list_product_images(
    vendor_id: str,
    product_id: str,
) -> dict:
    """
    Vendors can view their own images in any product status.
    """

    _get_owned_product(
        vendor_id=vendor_id,
        product_id=product_id,
    )

    try:
        response = (
            supabase_admin
            .table("product_images")
            .select(
                "id,"
                "product_id,"
                "variant_id,"
                "image_url,"
                "alt_text,"
                "sort_order,"
                "is_primary,"
                "created_at"
            )
            .eq("product_id", product_id)
            .order("is_primary", desc=True)
            .order("sort_order")
            .order("created_at")
            .execute()
        )

    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to load product images.",
        ) from exc

    images = response.data or []

    return {
        "product_id": product_id,
        "count": len(images),
        "images": images,
    }


# ============================================================
# UPLOAD PRODUCT IMAGE
# ============================================================

async def upload_product_image(
    *,
    vendor_id: str,
    product_id: str,
    file: UploadFile,
    alt_text: str | None = None,
    sort_order: int = 0,
    is_primary: bool = False,
) -> dict:
    """
    Upload images for draft or rejected products only.

    Pending and approved product images must not be
    modified through Vendor Backend.
    """

    # APPROVAL SECURITY:
    # Check ownership and status before uploading.
    product = _ensure_product_images_editable(
        vendor_id=vendor_id,
        product_id=product_id,
    )

    content_type = (
        file.content_type or ""
    ).lower()

    if content_type not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Unsupported image type. "
                "Use JPG, PNG or WEBP."
            ),
        )

    file_bytes = await file.read()

    if not file_bytes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded image is empty.",
        )

    if len(file_bytes) > MAX_IMAGE_SIZE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Image must be 8 MB or smaller.",
        )

    extension = _get_extension(
        file.filename,
        content_type,
    )

    unique_filename = f"{uuid.uuid4().hex}{extension}"

    storage_path = (
        f"{vendor_id}/"
        f"{product_id}/"
        f"{unique_filename}"
    )

    # --------------------------------------------------------
    # UPLOAD TO SUPABASE STORAGE
    # --------------------------------------------------------

    try:
        (
            supabase_admin
            .storage
            .from_(PRODUCT_IMAGE_BUCKET)
            .upload(
                path=storage_path,
                file=file_bytes,
                file_options={
                    "content-type": content_type,
                    "upsert": "false",
                },
            )
        )

    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to upload product image.",
        ) from exc

    image_url = _public_url_for_path(storage_path)

    # --------------------------------------------------------
    # CHECK EXISTING IMAGE COUNT
    # --------------------------------------------------------

    try:
        count_response = (
            supabase_admin
            .table("product_images")
            .select("id", count="exact")
            .eq("product_id", product_id)
            .execute()
        )

        existing_count = (
            count_response.count
            if count_response.count is not None
            else len(count_response.data or [])
        )

    except Exception:
        existing_count = 0

    should_be_primary = (
        is_primary or existing_count == 0
    )

    # --------------------------------------------------------
    # CREATE IMAGE METADATA
    # --------------------------------------------------------

    payload = {
        "product_id": product_id,
        "variant_id": None,
        "image_url": image_url,
        "alt_text": (
            alt_text.strip()
            if alt_text and alt_text.strip()
            else product.get("name")
        ),
        "sort_order": max(0, int(sort_order or 0)),
        "is_primary": False,
    }

    try:
        # Recheck immediately before metadata mutation.
        _ensure_product_images_editable(
            vendor_id=vendor_id,
            product_id=product_id,
        )

        response = (
            supabase_admin
            .table("product_images")
            .insert(payload)
            .execute()
        )

    except Exception as exc:
        # Best-effort cleanup of the uploaded object.
        try:
            (
                supabase_admin
                .storage
                .from_(PRODUCT_IMAGE_BUCKET)
                .remove([storage_path])
            )
        except Exception:
            pass

        if isinstance(exc, HTTPException):
            raise

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to save product image metadata.",
        ) from exc

    rows = response.data or []

    if not rows:
        try:
            (
                supabase_admin
                .storage
                .from_(PRODUCT_IMAGE_BUCKET)
                .remove([storage_path])
            )
        except Exception:
            pass

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Product image was not created.",
        )

    image = rows[0]

    if should_be_primary:
        _set_only_primary_image(
            product_id=product_id,
            image_id=image["id"],
        )

        image["is_primary"] = True

    return {
        "message": "Product image uploaded successfully.",
        "image": image,
    }


# ============================================================
# SET PRIMARY PRODUCT IMAGE
# ============================================================

def set_primary_product_image(
    *,
    vendor_id: str,
    product_id: str,
    image_id: str,
) -> dict:
    """
    Only draft or rejected products may have
    their primary image changed.
    """

    _ensure_product_images_editable(
        vendor_id=vendor_id,
        product_id=product_id,
    )

    image = _get_product_image(
        vendor_id=vendor_id,
        product_id=product_id,
        image_id=image_id,
    )

    _set_only_primary_image(
        product_id=product_id,
        image_id=image_id,
    )

    image["is_primary"] = True

    return {
        "message": "Primary product image updated.",
        "image": image,
    }


# ============================================================
# DELETE PRODUCT IMAGE
# ============================================================

def delete_product_image(
    *,
    vendor_id: str,
    product_id: str,
    image_id: str,
) -> dict:
    """
    Delete an image only when the parent product is
    a draft or rejected product.
    """

    _ensure_product_images_editable(
        vendor_id=vendor_id,
        product_id=product_id,
    )

    image = _get_product_image(
        vendor_id=vendor_id,
        product_id=product_id,
        image_id=image_id,
    )

    storage_path = _extract_storage_path(
        image.get("image_url", "")
    )

    was_primary = bool(image.get("is_primary"))

    # --------------------------------------------------------
    # DELETE IMAGE METADATA
    # --------------------------------------------------------

    try:
        (
            supabase_admin
            .table("product_images")
            .delete()
            .eq("id", image_id)
            .eq("product_id", product_id)
            .execute()
        )

    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to delete product image.",
        ) from exc

    # --------------------------------------------------------
    # BEST-EFFORT STORAGE CLEANUP
    # --------------------------------------------------------

    if storage_path:
        try:
            (
                supabase_admin
                .storage
                .from_(PRODUCT_IMAGE_BUCKET)
                .remove([storage_path])
            )
        except Exception:
            pass

    # --------------------------------------------------------
    # PROMOTE ANOTHER IMAGE IF PRIMARY WAS DELETED
    # --------------------------------------------------------

    new_primary = None

    if was_primary:
        try:
            response = (
                supabase_admin
                .table("product_images")
                .select(
                    "id,"
                    "product_id,"
                    "variant_id,"
                    "image_url,"
                    "alt_text,"
                    "sort_order,"
                    "is_primary,"
                    "created_at"
                )
                .eq("product_id", product_id)
                .order("sort_order")
                .order("created_at")
                .limit(1)
                .execute()
            )

            remaining = response.data or []

            if remaining:
                new_primary = remaining[0]

                _set_only_primary_image(
                    product_id=product_id,
                    image_id=new_primary["id"],
                )

                new_primary["is_primary"] = True

        except Exception:
            new_primary = None

    return {
        "message": "Product image deleted successfully.",
        "deleted_image_id": image_id,
        "new_primary_image": new_primary,
    }
