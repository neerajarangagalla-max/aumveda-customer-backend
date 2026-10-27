
import re
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from app.core.security import get_current_admin
from app.core.supabase import supabase

router = APIRouter(
    prefix="/admin/categories",
    tags=["Admin Categories"],
    dependencies=[Depends(get_current_admin)],
)


class CategoryFields(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=150)
    slug: str | None = Field(default=None, max_length=180)
    parent_id: UUID | None = None
    description: str | None = None
    image_url: str | None = Field(default=None, max_length=2048)
    show_on_home: bool = False
    home_sort_order: int = Field(default=0, ge=0)
    sort_order: int = Field(default=0, ge=0)
    is_active: bool = True


class CategoryCreate(CategoryFields):
    pass


class CategoryUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=150)
    slug: str | None = Field(default=None, max_length=180)
    parent_id: UUID | None = None
    description: str | None = None
    image_url: str | None = Field(default=None, max_length=2048)
    show_on_home: bool | None = None
    home_sort_order: int | None = Field(default=None, ge=0)
    sort_order: int | None = Field(default=None, ge=0)
    is_active: bool | None = None


def make_slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def category_exists(category_id: str) -> bool:
    result = (
        supabase.table("categories")
        .select("id")
        .eq("id", category_id)
        .maybe_single()
        .execute()
    )
    return bool(result.data)


def validate_parent(category_id: str | None, parent_id: str | None):
    if parent_id is None:
        return

    if category_id and str(parent_id) == str(category_id):
        raise HTTPException(
            status_code=422,
            detail="A category cannot be its own parent",
        )

    if not category_exists(str(parent_id)):
        raise HTTPException(
            status_code=422,
            detail="Parent category not found",
        )

    # Walk up the parent chain to prevent circular relationships.
    current_id = str(parent_id)
    visited = set()

    while current_id:
        if current_id in visited:
            raise HTTPException(
                status_code=409,
                detail="Existing category hierarchy contains a cycle",
            )

        visited.add(current_id)

        if category_id and current_id == str(category_id):
            raise HTTPException(
                status_code=422,
                detail="A category cannot become its own descendant",
            )

        result = (
            supabase.table("categories")
            .select("parent_id")
            .eq("id", current_id)
            .maybe_single()
            .execute()
        )

        if not result.data:
            break

        next_parent = result.data.get("parent_id")
        current_id = str(next_parent) if next_parent else ""


def check_database_error(exc: Exception) -> HTTPException:
    message = str(exc).lower()

    if "duplicate key" in message or "unique constraint" in message:
        return HTTPException(
            status_code=409,
            detail="A category with this slug already exists",
        )

    if "foreign key" in message:
        return HTTPException(
            status_code=409,
            detail="Category is referenced by another record",
        )

    return HTTPException(
        status_code=500,
        detail="Category operation failed",
    )


@router.get("")
def list_categories():
    try:
        result = (
            supabase.table("categories")
            .select("*")
            .order("sort_order")
            .order("name")
            .execute()
        )

        items = result.data or []
        return {"items": items, "total": len(items)}

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="Unable to retrieve categories",
        ) from exc


@router.post("", status_code=201)
def create_category(payload: CategoryCreate):
    try:
        data = payload.model_dump(mode="json", exclude_none=True)

        data["name"] = data["name"].strip()
        data["slug"] = make_slug(data.get("slug") or data["name"])

        if not data["name"] or not data["slug"]:
            raise HTTPException(
                status_code=422,
                detail="Category name and slug are required",
            )

        parent_id = data.get("parent_id")
        validate_parent(None, parent_id)

        result = supabase.table("categories").insert(data).execute()

        if not result.data:
            raise HTTPException(
                status_code=500,
                detail="Category was not created",
            )

        return result.data[0]

    except HTTPException:
        raise
    except Exception as exc:
        raise check_database_error(exc) from exc


@router.patch("/{category_id}")
def update_category(category_id: UUID, payload: CategoryUpdate):
    try:
        category_id = str(category_id)

        if not category_exists(category_id):
            raise HTTPException(404, "Category not found")

        data = payload.model_dump(
            mode="json",
            exclude_unset=True,
        )

        if not data:
            raise HTTPException(
                status_code=422,
                detail="Provide at least one field to update",
            )

        if "name" in data and data["name"] is not None:
            data["name"] = data["name"].strip()

            if not data["name"]:
                raise HTTPException(
                    status_code=422,
                    detail="Category name cannot be empty",
                )

        if "slug" in data and data["slug"] is not None:
            data["slug"] = make_slug(data["slug"])
        elif data.get("name"):
            data["slug"] = make_slug(data["name"])

        if "slug" in data and not data["slug"]:
            raise HTTPException(
                status_code=422,
                detail="Category slug cannot be empty",
            )

        if "parent_id" in data:
            validate_parent(category_id, data["parent_id"])

        result = (
            supabase.table("categories")
            .update(data)
            .eq("id", category_id)
            .execute()
        )

        if not result.data:
            raise HTTPException(
                status_code=404,
                detail="Category not found or not updated",
            )

        return result.data[0]

    except HTTPException:
        raise
    except Exception as exc:
        raise check_database_error(exc) from exc


@router.delete("/{category_id}")
def delete_category(category_id: UUID):
    try:
        category_id = str(category_id)

        if not category_exists(category_id):
            raise HTTPException(404, "Category not found")

        # Prevent deletion when products use this category.
        products = (
            supabase.table("products")
            .select("id")
            .eq("category_id", category_id)
            .limit(1)
            .execute()
        )

        if products.data:
            raise HTTPException(
                status_code=409,
                detail=(
                    "Cannot delete this category because products "
                    "are assigned to it. Reassign those products first."
                ),
            )

        # Prevent deletion when child categories depend on it.
        children = (
            supabase.table("categories")
            .select("id")
            .eq("parent_id", category_id)
            .limit(1)
            .execute()
        )

        if children.data:
            raise HTTPException(
                status_code=409,
                detail=(
                    "Cannot delete this category because it has "
                    "child categories. Reassign or remove them first."
                ),
            )

        result = (
            supabase.table("categories")
            .delete()
            .eq("id", category_id)
            .execute()
        )

        if not result.data:
            raise HTTPException(
                status_code=409,
                detail="Category was not deleted",
            )

        return {
            "message": "Category deleted successfully",
            "id": category_id,
        }

    except HTTPException:
        raise
    except Exception as exc:
        raise check_database_error(exc) from exc
