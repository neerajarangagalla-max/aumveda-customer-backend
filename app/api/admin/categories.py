import re
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.core.security import get_current_admin
from app.core.supabase import supabase

router = APIRouter(
    prefix="/admin/categories",
    tags=["Admin Categories"],
    dependencies=[Depends(get_current_admin)],
)


class CategoryCreate(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    slug: str | None = Field(default=None, max_length=180)
    parent_id: str | None = None


class CategoryUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=150)
    slug: str | None = Field(default=None, max_length=180)
    parent_id: str | None = None


def make_slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


@router.get("")
def list_categories():
    try:
        result = (
            supabase.table("categories")
            .select("*")
            .order("name")
            .execute()
        )
        items = result.data or []
        return {"items": items, "total": len(items)}
    except Exception as exc:
        raise HTTPException(500, "Unable to retrieve categories") from exc


@router.post("", status_code=201)
def create_category(payload: CategoryCreate):
    try:
        data: dict[str, Any] = payload.model_dump(exclude_none=True)
        data["name"] = data["name"].strip()
        data["slug"] = make_slug(data.get("slug") or data["name"])

        if not data["name"] or not data["slug"]:
            raise HTTPException(422, "Category name and slug are required")

        result = supabase.table("categories").insert(data).execute()
        if not result.data:
            raise HTTPException(500, "Category was not created")
        return result.data[0]
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            500,
            "Unable to create category; check the category schema and slug uniqueness",
        ) from exc


@router.patch("/{category_id}")
def update_category(category_id: str, payload: CategoryUpdate):
    try:
        data = payload.model_dump(exclude_unset=True)
        if not data:
            raise HTTPException(422, "Provide at least one field to update")

        if "name" in data and data["name"] is not None:
            data["name"] = data["name"].strip()
            if not data["name"]:
                raise HTTPException(422, "Category name cannot be empty")

        if "slug" in data and data["slug"] is not None:
            data["slug"] = make_slug(data["slug"])
        elif "name" in data and data["name"]:
            data["slug"] = make_slug(data["name"])

        result = (
            supabase.table("categories")
            .update(data)
            .eq("id", category_id)
            .execute()
        )
        if not result.data:
            raise HTTPException(404, "Category not found or not updated")
        return result.data[0]
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, "Unable to update category") from exc
