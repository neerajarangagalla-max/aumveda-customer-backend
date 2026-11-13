from __future__ import annotations

from io import BytesIO
from typing import Any, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from PIL import Image
from pydantic import BaseModel, ConfigDict, Field

from app.core.security import get_current_admin
from app.core.supabase import supabase

router = APIRouter(
    prefix="/admin/content-management",
    tags=["Admin Content Management"],
    dependencies=[Depends(get_current_admin)],
)

Platform = Literal["app", "web"]


class SectionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    platform: Platform
    page_key: str = Field(default="home", min_length=1, max_length=100)
    section_key: str = Field(min_length=1, max_length=150)
    section_type: str = Field(min_length=1, max_length=100)
    title: str | None = Field(default=None, max_length=500)
    subtitle: str | None = Field(default=None, max_length=1000)
    eyebrow: str | None = Field(default=None, max_length=500)
    sort_order: int = Field(default=0, ge=0)
    is_visible: bool = True
    publish_status: str = Field(default="draft", max_length=30)
    selection_mode: str = Field(default="manual", max_length=30)
    category_id: UUID | None = None
    product_limit: int | None = Field(default=12, ge=1, le=100)
    layout_config: dict[str, Any] = Field(default_factory=dict)
    content_config: dict[str, Any] = Field(default_factory=dict)


class SectionUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    section_key: str | None = Field(default=None, min_length=1, max_length=150)
    section_type: str | None = Field(default=None, min_length=1, max_length=100)
    title: str | None = Field(default=None, max_length=500)
    subtitle: str | None = Field(default=None, max_length=1000)
    eyebrow: str | None = Field(default=None, max_length=500)
    sort_order: int | None = Field(default=None, ge=0)
    is_visible: bool | None = None
    publish_status: str | None = Field(default=None, max_length=30)
    selection_mode: str | None = Field(default=None, max_length=30)
    category_id: UUID | None = None
    product_limit: int | None = Field(default=None, ge=1, le=100)
    layout_config: dict[str, Any] | None = None
    content_config: dict[str, Any] | None = None


class VisibilityUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    is_visible: bool


class SectionOrderItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: UUID
    sort_order: int = Field(ge=0)


class SectionReorderRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sections: list[SectionOrderItem] = Field(min_length=1)


class ItemCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item_key: str | None = Field(default=None, max_length=150)
    item_type: str = Field(min_length=1, max_length=100)
    title: str | None = Field(default=None, max_length=500)
    subtitle: str | None = Field(default=None, max_length=1000)
    description: str | None = None
    eyebrow: str | None = Field(default=None, max_length=500)
    image_url: str | None = None
    mobile_image_url: str | None = None
    video_url: str | None = None
    alt_text: str | None = Field(default=None, max_length=500)
    badge_text: str | None = Field(default=None, max_length=200)
    badge_style: str | None = Field(default=None, max_length=100)
    primary_cta_text: str | None = Field(default=None, max_length=200)
    primary_cta_url: str | None = None
    secondary_cta_text: str | None = Field(default=None, max_length=200)
    secondary_cta_url: str | None = None
    target_type: str = Field(default="none", max_length=50)
    target_id: UUID | None = None
    target_url: str | None = None
    sort_order: int = Field(default=0, ge=0)
    is_visible: bool = True
    publish_status: str = Field(default="draft", max_length=30)
    style_config: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ItemUpdate(ItemCreate):
    pass


def _database_error(exc: Exception) -> HTTPException:
    message = str(exc).lower()
    if "duplicate key" in message or "unique constraint" in message:
        return HTTPException(
            status_code=409,
            detail="A content record with the same unique key already exists.",
        )
    return HTTPException(
        status_code=500,
        detail="Content management operation failed.",
    )


def _get_section(section_id: UUID):
    result = (
        supabase
        .table("homepage_sections")
        .select("*")
        .eq("id", str(section_id))
        .limit(1)
        .execute()
    )
    if not result.data:
        raise HTTPException(status_code=404, detail="Content section not found.")
    return result.data[0]


@router.post("/sections/{section_id}/image", status_code=201)
async def upload_content_image(
    section_id: UUID,
    image: UploadFile = File(...),
):
    try:
        section = _get_section(section_id)
        allowed_types = {
            "image/jpeg": "jpg",
            "image/png": "png",
            "image/webp": "webp",
        }
        extension = allowed_types.get(image.content_type or "")
        if not extension:
            raise HTTPException(
                status_code=400,
                detail="Only JPG, PNG, and WEBP images are allowed.",
            )

        file_bytes = await image.read(10 * 1024 * 1024 + 1)
        if not file_bytes:
            raise HTTPException(status_code=400, detail="Image file is empty.")
        if len(file_bytes) > 10 * 1024 * 1024:
            raise HTTPException(
                status_code=413,
                detail="Image must be smaller than 10 MB.",
            )

        try:
            with Image.open(BytesIO(file_bytes)) as uploaded_image:
                uploaded_image.verify()
        except Exception as exc:
            raise HTTPException(
                status_code=400,
                detail="Invalid image file.",
            ) from exc

        storage_path = (
            f"homepage-content/{section['platform']}/{section_id}/"
            f"{uuid4()}.{extension}"
        )
        supabase.storage.from_("site_assets").upload(
            storage_path,
            file_bytes,
            {
                "content-type": image.content_type,
                "upsert": "false",
            },
        )
        image_url = (
            supabase
            .storage
            .from_("site_assets")
            .get_public_url(storage_path)
        )
        return {
            "status": "success",
            "data": {
                "image_url": image_url,
                "storage_path": storage_path,
            },
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise _database_error(exc) from exc


@router.get("")
def list_content_sections(
    platform: Platform = Query(...),
    page_key: str = Query("home", min_length=1, max_length=100),
):
    try:
        result = (
            supabase
            .table("homepage_sections")
            .select("*")
            .eq("platform", platform)
            .eq("page_key", page_key)
            .order("sort_order")
            .execute()
        )

        sections = result.data or []
        section_ids = [item["id"] for item in sections if item.get("id")]
        items_by_section: dict[str, list[dict[str, Any]]] = {
            str(section_id): [] for section_id in section_ids
        }

        if section_ids:
            items_result = (
                supabase
                .table("homepage_items")
                .select("*")
                .in_("section_id", section_ids)
                .order("sort_order")
                .execute()
            )
            for item in items_result.data or []:
                key = str(item.get("section_id"))
                if key in items_by_section:
                    items_by_section[key].append(item)

        for section in sections:
            section_items = items_by_section.get(str(section["id"]), [])

            # Web and App content are independent. Some legacy records were
            # previously attached to the same hero section, so do not expose
            # App banners inside the Web hero editor. Keep the database rows
            # intact; only filter the CMS response for the current platform.
            if (
                section.get("platform") == "web"
                and section.get("section_key") in {"hero_banner", "hero"}
            ):
                section_items = [
                    item
                    for item in section_items
                    if item.get("item_type") != "app_banner"
                ]

            section["items"] = section_items

        return {
            "status": "success",
            "data": {"sections": sections},
            "count": len(sections),
            "platform": platform,
            "page_key": page_key,
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise _database_error(exc) from exc


@router.get("/sections/{section_id}")
def get_content_section(section_id: UUID):
    try:
        section = _get_section(section_id)
        items_result = (
            supabase
            .table("homepage_items")
            .select("*")
            .eq("section_id", str(section_id))
            .order("sort_order")
            .execute()
        )
        section_items = items_result.data or []

        if (
            section.get("platform") == "web"
            and section.get("section_key") in {"hero_banner", "hero"}
        ):
            section_items = [
                item
                for item in section_items
                if item.get("item_type") != "app_banner"
            ]

        section["items"] = section_items
        return {"status": "success", "data": {"section": section}}
    except HTTPException:
        raise
    except Exception as exc:
        raise _database_error(exc) from exc


@router.post("/sections", status_code=201)
def create_content_section(payload: SectionCreate):
    try:
        data = payload.model_dump(mode="json")
        result = supabase.table("homepage_sections").insert(data).execute()
        if not result.data:
            raise HTTPException(500, "Content section was not created.")
        return {"status": "success", "data": {"section": result.data[0]}}
    except HTTPException:
        raise
    except Exception as exc:
        raise _database_error(exc) from exc


@router.patch("/sections/{section_id}")
def update_content_section(section_id: UUID, payload: SectionUpdate):
    try:
        data = payload.model_dump(mode="json", exclude_unset=True)
        if not data:
            raise HTTPException(422, "Provide at least one field to update.")
        result = (
            supabase
            .table("homepage_sections")
            .update(data)
            .eq("id", str(section_id))
            .execute()
        )
        if not result.data:
            raise HTTPException(404, "Content section not found.")
        return {"status": "success", "data": {"section": result.data[0]}}
    except HTTPException:
        raise
    except Exception as exc:
        raise _database_error(exc) from exc


@router.patch("/sections/{section_id}/visibility")
def update_content_section_visibility(
    section_id: UUID,
    payload: VisibilityUpdate,
):
    try:
        result = (
            supabase
            .table("homepage_sections")
            .update({"is_visible": payload.is_visible})
            .eq("id", str(section_id))
            .execute()
        )
        if not result.data:
            raise HTTPException(404, "Content section not found.")
        return {"status": "success", "data": {"section": result.data[0]}}
    except HTTPException:
        raise
    except Exception as exc:
        raise _database_error(exc) from exc


@router.post("/sections/reorder")
def reorder_content_sections(payload: SectionReorderRequest):
    try:
        for item in payload.sections:
            (
                supabase
                .table("homepage_sections")
                .update({"sort_order": item.sort_order})
                .eq("id", str(item.id))
                .execute()
            )
        return {"status": "success", "message": "Content sections reordered successfully."}
    except Exception as exc:
        raise _database_error(exc) from exc


@router.delete("/sections/{section_id}")
def delete_content_section(section_id: UUID):
    try:
        _get_section(section_id)
        (
            supabase
            .table("homepage_items")
            .delete()
            .eq("section_id", str(section_id))
            .execute()
        )
        result = (
            supabase
            .table("homepage_sections")
            .delete()
            .eq("id", str(section_id))
            .execute()
        )
        if not result.data:
            raise HTTPException(404, "Content section not found.")
        return {"status": "success", "message": "Content section deleted successfully.", "id": str(section_id)}
    except HTTPException:
        raise
    except Exception as exc:
        raise _database_error(exc) from exc


@router.get("/sections/{section_id}/items")
def list_content_items(section_id: UUID):
    try:
        _get_section(section_id)
        result = (
            supabase
            .table("homepage_items")
            .select("*")
            .eq("section_id", str(section_id))
            .order("sort_order")
            .execute()
        )
        section = _get_section(section_id)
        section_items = result.data or []

        if (
            section.get("platform") == "web"
            and section.get("section_key") in {"hero_banner", "hero"}
        ):
            section_items = [
                item
                for item in section_items
                if item.get("item_type") != "app_banner"
            ]

        return {"status": "success", "data": {"items": section_items}}
    except HTTPException:
        raise
    except Exception as exc:
        raise _database_error(exc) from exc


@router.post("/sections/{section_id}/items", status_code=201)
def create_content_item(section_id: UUID, payload: ItemCreate):
    try:
        _get_section(section_id)
        data = payload.model_dump(mode="json")
        data["section_id"] = str(section_id)
        result = supabase.table("homepage_items").insert(data).execute()
        if not result.data:
            raise HTTPException(500, "Content item was not created.")
        return {"status": "success", "data": {"item": result.data[0]}}
    except HTTPException:
        raise
    except Exception as exc:
        raise _database_error(exc) from exc


@router.patch("/items/{item_id}")
def update_content_item(item_id: UUID, payload: ItemUpdate):
    try:
        data = payload.model_dump(mode="json", exclude_unset=True)
        result = (
            supabase
            .table("homepage_items")
            .update(data)
            .eq("id", str(item_id))
            .execute()
        )
        if not result.data:
            raise HTTPException(404, "Content item not found.")
        return {"status": "success", "data": {"item": result.data[0]}}
    except HTTPException:
        raise
    except Exception as exc:
        raise _database_error(exc) from exc


@router.delete("/items/{item_id}")
def delete_content_item(item_id: UUID):
    try:
        result = (
            supabase
            .table("homepage_items")
            .delete()
            .eq("id", str(item_id))
            .execute()
        )
        if not result.data:
            raise HTTPException(404, "Content item not found.")
        return {"status": "success", "message": "Content item deleted successfully.", "id": str(item_id)}
    except HTTPException:
        raise
    except Exception as exc:
        raise _database_error(exc) from exc
