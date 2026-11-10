from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    UploadFile,
    File,
    Form,
)
from uuid import uuid4
from io import BytesIO

from PIL import Image

from app.core.security import get_current_admin
from app.core.supabase import supabase


router = APIRouter(
    prefix="/admin/banners",
    tags=["Admin Banners"],
    dependencies=[Depends(get_current_admin)],
)


# =========================================================
# APP PROMOTIONAL BANNERS
# =========================================================

@router.get("")
def list_banners(
    publish_status: str | None = Query(default=None),
    platform: str | None = Query(default=None),
    placement: str | None = Query(default=None),
):
    """
    List app promotional banners.

    App promotional banners are stored in the `banners` table
    with:
        platform = app
        placement = home
    """

    try:
        query = (
            supabase
            .table("banners")
            .select("*", count="exact")
            .eq("platform", "app")
            .eq("placement", "home")
        )

        if publish_status:
            query = query.eq("publish_status", publish_status)

        if platform:
            query = query.eq("platform", platform)

        if placement:
            query = query.eq("placement", placement)

        result = (
            query
            .order("sort_order", desc=False)
            .order("created_at", desc=False)
            .execute()
        )

        return {
            "items": result.data or [],
            "total": result.count or 0,
        }

    except Exception as exc:
        print("BANNER LIST ERROR:", repr(exc))

        raise HTTPException(
            status_code=500,
            detail="Unable to retrieve app banners",
        ) from exc


@router.post("")
async def create_banner(
    image: UploadFile = File(...),
    display_location: str = Form(...),
    display_order: int = Form(0),
    publish_status: str = Form("draft"),
    starts_at: str | None = Form(None),
    ends_at: str | None = Form(None),
):
    """
    Create an app promotional banner.

    The banner is stored in the same `banners` table used by
    the customer `/home/app-banners` API.
    """

    try:
        # ---------------------------------------------------------
        # 1. Validate image type
        # ---------------------------------------------------------
        allowed_types = {
            "image/jpeg",
            "image/png",
            "image/webp",
        }

        if image.content_type not in allowed_types:
            raise HTTPException(
                status_code=400,
                detail="Only JPG, PNG, and WEBP images are allowed",
            )

        # ---------------------------------------------------------
        # 2. Read image
        # ---------------------------------------------------------
        file_bytes = await image.read()

        if not file_bytes:
            raise HTTPException(
                status_code=400,
                detail="Banner image is empty",
            )

        # ---------------------------------------------------------
        # 3. Validate image
        # ---------------------------------------------------------
        try:
            img = Image.open(BytesIO(file_bytes))
            width, height = img.size

        except Exception as exc:
            raise HTTPException(
                status_code=400,
                detail="Invalid image file",
            ) from exc

        if height == 0:
            raise HTTPException(
                status_code=400,
                detail="Invalid image dimensions",
            )

        # ---------------------------------------------------------
        # 4. Validate 7:3 aspect ratio
        # ---------------------------------------------------------
        ratio = width / height

        if abs(ratio - (7 / 3)) > 0.03:
            raise HTTPException(
                status_code=400,
                detail="Banner image must use a 7:3 aspect ratio",
            )

        # ---------------------------------------------------------
        # 5. Generate storage filename
        # ---------------------------------------------------------
        extension = (
            image.filename.split(".")[-1].lower()
            if image.filename and "." in image.filename
            else "png"
        )

        file_name = f"{uuid4()}.{extension}"

        storage_path = f"banners/app/{file_name}"

        # ---------------------------------------------------------
        # 6. Upload image to Supabase Storage
        # ---------------------------------------------------------
        supabase.storage.from_("site_assets").upload(
            storage_path,
            file_bytes,
            {
                "content-type": image.content_type,
                "upsert": "false",
            },
        )

        # ---------------------------------------------------------
        # 7. Get public image URL
        # ---------------------------------------------------------
        image_url = (
            supabase
            .storage
            .from_("site_assets")
            .get_public_url(storage_path)
        )

        # ---------------------------------------------------------
        # 8. Prepare banner data
        # ---------------------------------------------------------
        banner_data = {
            # IMPORTANT:
            # Customer /home/app-banners reads these values.
            "platform": "app",
            "placement": "home",

            "title": display_location,
            "image_url": image_url,
            "storage_path": storage_path,

            # App promotional banners do not target a category.
            "target_type": "home",
            "target_id": None,
            "category_id": None,

            "sort_order": display_order,

            "is_visible": publish_status == "published",
            "publish_status": publish_status,

            "starts_at": starts_at or None,
            "ends_at": ends_at or None,

            "metadata": {
                "display_location": display_location,
                "aspect_ratio": "7:3",
            },
        }

        # ---------------------------------------------------------
        # 9. Insert into banners table
        # ---------------------------------------------------------
        result = (
            supabase
            .table("banners")
            .insert(banner_data)
            .execute()
        )

        # ---------------------------------------------------------
        # 10. Return created banner
        # ---------------------------------------------------------
        return {
            "message": "App banner created successfully",
            "item": result.data[0] if result.data else None,
        }

    except HTTPException:
        raise

    except Exception as exc:
        print("BANNER CREATE ERROR:", repr(exc))

        raise HTTPException(
            status_code=500,
            detail=str(exc),
        ) from exc


# =========================================================
# CATEGORY BANNERS
# =========================================================

@router.get("/category")
def list_category_banners(
    category_id: str | None = Query(default=None),
    publish_status: str | None = Query(default=None),
):
    try:
        query = (
            supabase
            .table("banners")
            .select(
                """
                *,
                categories (
                    id,
                    name,
                    slug
                )
                """,
                count="exact",
            )
            .eq("platform", "app")
            .eq("placement", "category")
        )

        if category_id:
            query = query.eq("category_id", category_id)

        if publish_status:
            query = query.eq("publish_status", publish_status)

        result = (
            query
            .order("sort_order", desc=False)
            .order("created_at", desc=False)
            .execute()
        )

        return {
            "items": result.data or [],
            "total": result.count or 0,
        }

    except Exception as exc:
        print("CATEGORY BANNER LIST ERROR:", repr(exc))

        raise HTTPException(
            status_code=500,
            detail="Unable to retrieve category banners",
        ) from exc


@router.post("/category")
async def create_category_banner(
    category_id: str = Form(...),
    image: UploadFile = File(...),
    display_order: int = Form(0),
    publish_status: str = Form("draft"),
    starts_at: str | None = Form(None),
    ends_at: str | None = Form(None),
):
    try:
        # ---------------------------------------------------------
        # 1. Validate image type
        # ---------------------------------------------------------
        allowed_types = {
            "image/jpeg",
            "image/png",
            "image/webp",
        }

        if image.content_type not in allowed_types:
            raise HTTPException(
                status_code=400,
                detail="Only JPG, PNG, and WEBP images are allowed",
            )

        # ---------------------------------------------------------
        # 2. Verify category exists
        # ---------------------------------------------------------
        category_result = (
            supabase
            .table("categories")
            .select("id, name")
            .eq("id", category_id)
            .single()
            .execute()
        )

        if not category_result.data:
            raise HTTPException(
                status_code=404,
                detail="Category not found",
            )

        category = category_result.data

        # ---------------------------------------------------------
        # 3. Read image
        # ---------------------------------------------------------
        file_bytes = await image.read()

        if not file_bytes:
            raise HTTPException(
                status_code=400,
                detail="Banner image is empty",
            )

        # ---------------------------------------------------------
        # 4. Validate image dimensions
        # ---------------------------------------------------------
        try:
            img = Image.open(BytesIO(file_bytes))
            width, height = img.size

        except Exception as exc:
            raise HTTPException(
                status_code=400,
                detail="Invalid image file",
            ) from exc

        if height == 0:
            raise HTTPException(
                status_code=400,
                detail="Invalid image dimensions",
            )

        # ---------------------------------------------------------
        # 5. Validate 3:1 aspect ratio
        # ---------------------------------------------------------
        ratio = width / height

        if abs(ratio - 3.0) > 0.03:
            raise HTTPException(
                status_code=400,
                detail="Category banner must use a 3:1 aspect ratio",
            )

        # ---------------------------------------------------------
        # 6. Generate storage filename
        # ---------------------------------------------------------
        extension = (
            image.filename.split(".")[-1].lower()
            if image.filename and "." in image.filename
            else "png"
        )

        file_name = f"{uuid4()}.{extension}"

        storage_path = f"banners/app/category/{file_name}"

        # ---------------------------------------------------------
        # 7. Upload image
        # ---------------------------------------------------------
        supabase.storage.from_("site_assets").upload(
            storage_path,
            file_bytes,
            {
                "content-type": image.content_type,
                "upsert": "false",
            },
        )

        # ---------------------------------------------------------
        # 8. Get public URL
        # ---------------------------------------------------------
        image_url = (
            supabase
            .storage
            .from_("site_assets")
            .get_public_url(storage_path)
        )

        # ---------------------------------------------------------
        # 9. Prepare category banner data
        # ---------------------------------------------------------
        banner_data = {
            "platform": "app",
            "placement": "category",

            "category_id": category_id,

            "title": category["name"],
            "image_url": image_url,
            "storage_path": storage_path,

            "target_type": "category",
            "target_id": category_id,

            "sort_order": display_order,

            "is_visible": publish_status == "published",
            "publish_status": publish_status,

            "starts_at": starts_at or None,
            "ends_at": ends_at or None,

            "metadata": {
                "aspect_ratio": "3:1",
                "category_id": category_id,
            },
        }

        # ---------------------------------------------------------
        # 10. Insert into banners table
        # ---------------------------------------------------------
        result = (
            supabase
            .table("banners")
            .insert(banner_data)
            .execute()
        )

        # ---------------------------------------------------------
        # 11. Return created banner
        # ---------------------------------------------------------
        return {
            "message": "Category banner created successfully",
            "item": result.data[0] if result.data else None,
        }

    except HTTPException:
        raise

    except Exception as exc:
        print("CATEGORY BANNER CREATE ERROR:", repr(exc))

        raise HTTPException(
            status_code=500,
            detail=str(exc),
        ) from exc