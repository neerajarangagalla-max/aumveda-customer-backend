
"""Admin-only product image upload and replacement operations."""

from __future__ import annotations

import logging
import uuid
from urllib.parse import unquote, urlparse

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    UploadFile,
    status,
)

from app.core.config import settings
from app.core.security import get_current_admin
from app.core.supabase import supabase_admin

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/admin/products",
    tags=["Admin Product Images"],
    dependencies=[Depends(get_current_admin)],
)

BUCKET = "product_images"
MAX_IMAGE_BYTES = 5 * 1024 * 1024

ALLOWED_TYPES = {
    "image/jpeg": (
        "jpg",
        lambda b: b.startswith(b"\xff\xd8\xff"),
    ),
    "image/png": (
        "png",
        lambda b: b.startswith(b"\x89PNG\r\n\x1a\n"),
    ),
    "image/webp": (
        "webp",
        lambda b: (
            len(b) >= 12
            and b[:4] == b"RIFF"
            and b[8:12] == b"WEBP"
        ),
    ),
}


def _validate_image(content_type: str | None, content: bytes) -> str:
    image_type = (content_type or "").split(";", 1)[0].strip().lower()
    definition = ALLOWED_TYPES.get(image_type)

    if not definition or not definition[1](content):
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Only valid JPG, PNG, and WebP images are supported.",
        )

    if len(content) > MAX_IMAGE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Image must be 5 MB or smaller.",
        )

    return definition[0]


async def _read_and_validate(file: UploadFile):
    content = await file.read(MAX_IMAGE_BYTES + 1)

    if not content:
        raise HTTPException(
            status_code=400,
            detail="Choose an image file to upload.",
        )

    if len(content) > MAX_IMAGE_BYTES:
        raise HTTPException(
            status_code=413,
            detail="Image must be 5 MB or smaller.",
        )

    extension = _validate_image(file.content_type, content)
    content_type = (file.content_type or "").split(";", 1)[0].lower()

    return content, extension, content_type


def _remove_new_object(object_path: str) -> None:
    try:
        supabase_admin.storage.from_(BUCKET).remove([object_path])
    except Exception:
        logger.exception(
            "Could not clean up newly uploaded product image: %s",
            object_path,
        )


def _upload_unique_image(
    product_id: str,
    image_id: str,
    extension: str,
    content_type: str,
    content: bytes,
) -> tuple[str, str]:

    object_path = (
        f"admin/{product_id}/{image_id}/{uuid.uuid4().hex}.{extension}"
    )

    try:
        uploaded = supabase_admin.storage.from_(BUCKET).upload(
            object_path,
            content,
            file_options={
                "content-type": content_type,
                "upsert": "false",
            },
        )

        if not uploaded:
            raise RuntimeError("Storage upload did not confirm success")

        public_url = (
            supabase_admin.storage
            .from_(BUCKET)
            .get_public_url(object_path)
        )

        if (
            not isinstance(public_url, str)
            or not public_url.startswith(("http://", "https://"))
        ):
            raise RuntimeError("Storage did not return a valid public URL")

        return object_path, public_url

    except Exception:
        _remove_new_object(object_path)
        raise


def _storage_path_from_public_url(
    image_url: str | None,
) -> str | None:

    if not image_url:
        return None

    parsed = urlparse(image_url)
    configured = urlparse(settings.supabase_url)

    if (
        parsed.scheme not in {"http", "https"}
        or parsed.netloc != configured.netloc
    ):
        return None

    prefix = f"/storage/v1/object/public/{BUCKET}/"

    if not parsed.path.startswith(prefix):
        return None

    path = unquote(parsed.path[len(prefix):]).strip("/")

    if not path or path.startswith("../") or "/../" in path:
        return None

    return path


def _delete_old_object_if_unreferenced(
    old_url: str | None,
    image_id: str,
) -> None:

    old_path = _storage_path_from_public_url(old_url)

    if not old_path:
        return

    try:
        references = (
            supabase_admin.table("product_images")
            .select("id")
            .eq("image_url", old_url)
            .neq("id", image_id)
            .limit(1)
            .execute()
        )

        if references.data:
            logger.info(
                "Retaining old image object because another image "
                "record references it."
            )
            return

        supabase_admin.storage.from_(BUCKET).remove([old_path])

    except Exception:
        logger.exception(
            "Could not clean up old product image object: %s",
            old_path,
        )


@router.post("/{product_id}/images/{image_id}/replace")
async def replace_product_image(
    product_id: uuid.UUID,
    image_id: uuid.UUID,
    file: UploadFile = File(...),
):
    """Replace one image while retaining its existing database row."""

    product_id_text = str(product_id)
    image_id_text = str(image_id)

    product = (
        supabase_admin.table("products")
        .select("id")
        .eq("id", product_id_text)
        .maybe_single()
        .execute()
    )

    if not product.data:
        raise HTTPException(404, "Product not found.")

    image_result = (
        supabase_admin.table("product_images")
        .select("*")
        .eq("id", image_id_text)
        .eq("product_id", product_id_text)
        .maybe_single()
        .execute()
    )

    if not image_result.data:
        raise HTTPException(404, "Product image not found.")

    content, extension, content_type = await _read_and_validate(file)

    old_url = image_result.data.get("image_url")

    try:
        new_object_path, new_url = _upload_unique_image(
            product_id_text,
            image_id_text,
            extension,
            content_type,
            content,
        )

    except Exception as exc:
        logger.exception("Product image upload failed")

        raise HTTPException(
            502,
            "Image upload failed. The existing image was not changed.",
        ) from exc

    try:
        updated = (
            supabase_admin.table("product_images")
            .update({"image_url": new_url})
            .eq("id", image_id_text)
            .eq("product_id", product_id_text)
            .select("*")
            .maybe_single()
            .execute()
        )

        if not updated.data:
            raise RuntimeError("Image record was not updated")

    except Exception as exc:
        _remove_new_object(new_object_path)

        logger.exception("Product image database update failed")

        raise HTTPException(
            500,
            "Image record could not be updated. "
            "The previous image was retained.",
        ) from exc

    _delete_old_object_if_unreferenced(
        old_url,
        image_id_text,
    )

    return {
        "message": "Product image replaced successfully",
        "image": updated.data,
    }


@router.post("/{product_id}/images", status_code=201)
async def add_product_image(
    product_id: uuid.UUID,
    file: UploadFile = File(...),
    alt_text: str | None = Form(default=None),
    sort_order: int = Form(default=0, ge=0),
    is_primary: bool = Form(default=False),
    variant_id: uuid.UUID | None = Form(default=None),
):
    """Add an image using the atomic PostgreSQL RPC."""

    product_id_text = str(product_id)

    product = (
        supabase_admin.table("products")
        .select("id")
        .eq("id", product_id_text)
        .maybe_single()
        .execute()
    )

    if not product.data:
        raise HTTPException(404, "Product not found.")

    content, extension, content_type = await _read_and_validate(file)

    image_id = str(uuid.uuid4())
    new_object_path = None

    try:
        new_object_path, new_url = _upload_unique_image(
            product_id_text,
            image_id,
            extension,
            content_type,
            content,
        )

        result = supabase_admin.rpc(
            "admin_add_product_image",
            {
                "p_image_id": image_id,
                "p_product_id": product_id_text,
                "p_variant_id": str(variant_id) if variant_id else None,
                "p_image_url": new_url,
                "p_alt_text": (alt_text or "").strip() or None,
                "p_sort_order": sort_order,
                "p_is_primary": is_primary,
            },
        ).execute()

        image = result.data

        if isinstance(image, list):
            image = image[0] if image else None

        if isinstance(image, dict) and "image" in image:
            image = image["image"]

        if not image:
            raise RuntimeError("Image insert returned no record")

    except Exception as exc:
        if new_object_path:
            _remove_new_object(new_object_path)

        logger.exception("New product image operation failed")

        raise HTTPException(
            500,
            "Image could not be saved. "
            "Existing product images were not changed.",
        ) from exc

    return {
        "message": "Product image added successfully",
        "image": image,
    }
