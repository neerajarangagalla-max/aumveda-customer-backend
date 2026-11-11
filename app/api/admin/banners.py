from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    UploadFile,
    File,
    Form,
)
from uuid import UUID, uuid4
from io import BytesIO

from PIL import Image

from app.core.security import get_current_admin
from app.core.supabase import supabase


router = APIRouter(
    prefix="/admin/banners",
    tags=["Admin Banners"],
    dependencies=[Depends(get_current_admin)],
)

@router.get("/storage/folders")
def list_banner_storage_folders():
    try:
        items = (
            supabase
            .storage
            .from_("site_assets")
            .list("")
        )
        folders = [
            item
            for item in (items or [])
            if item.get("id") is None
        ]
        return {
            "bucket": "site_assets",
            "folders": folders,
        }
    except Exception as exc:
        print("STORAGE FOLDER LIST ERROR:", repr(exc))
        raise HTTPException(
            status_code=500,
            detail="Unable to list Supabase Storage folders",
        ) from exc


@router.get("/storage/files")
def list_banner_storage_files(
    path: str = Query(default=""),
):
    try:
        items = (
            supabase
            .storage
            .from_("site_assets")
            .list(path)
        )
        files = []
        for item in items or []:
            name = item.get("name")
            if not name:
                continue
            if item.get("id") is None:
                continue

            file_path = f"{path.rstrip('/')}/{name}" if path else name
            public_url = (
                supabase
                .storage
                .from_("site_assets")
                .get_public_url(file_path)
            )
            files.append({
                "name": name,
                "storage_path": file_path,
                "public_url": public_url,
            })

        return {
            "path": path,
            "files": files,
        }
    except Exception as exc:
        print("STORAGE FILE LIST ERROR:", repr(exc))
        raise HTTPException(
            status_code=500,
            detail="Unable to list Supabase Storage files",
        ) from exc


# =========================================================
# APP PROMOTIONAL BANNERS
# =========================================================

@router.get("")
def list_banners(
    publish_status: str | None = Query(default=None),
    platform: str | None = Query(default=None),
    placement: str | None = Query(default=None),
):
    try:
        query = (
            supabase
            .table("banners")
            .select("*", count="exact")
        )

        if publish_status:
            query = query.eq(
                "publish_status",
                publish_status
            )

        if platform:
            query = query.eq(
                "platform",
                platform
            )

        if placement:
            query = query.eq(
                "placement",
                placement
            )

        result = (
            query
            .order("sort_order", desc=False)
            .order("created_at", desc=False)
            .execute()
        )

        return {
            "source": "banners-table",
            "items": result.data or [],
            "total": result.count or 0,
        }

    except Exception as exc:
        print("BANNER LIST ERROR:", repr(exc))

        raise HTTPException(
            status_code=500,
            detail="Unable to retrieve banners",
        ) from exc

@router.post("")
async def create_banner(
    image: UploadFile = File(...),
    display_location: str | None = Form(None),
    display_order: int | None = Form(None),
    publish_status: str = Form("draft"),
    starts_at: str | None = Form(None),
    ends_at: str | None = Form(None),
    platform: str = Form(default="app"),
    placement: str = Form(default="home"),
    title: str | None = Form(None),
    sort_order: int | None = Form(None),
):
    try:
        if platform not in {"app", "web"}:
            raise HTTPException(
                status_code=400,
                detail="Invalid platform. Use 'app' or 'web'.",
            )

        if not placement or not placement.strip():
            raise HTTPException(
                status_code=400,
                detail="Banner placement is required.",
            )

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

        file_bytes = await image.read()

        if not file_bytes:
            raise HTTPException(
                status_code=400,
                detail="Banner image is empty",
            )

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

        ratio = width / height

        if (
            (platform == "app" or placement.strip() == "hero")
            and abs(ratio - (7 / 3)) > 0.03
        ):
            raise HTTPException(
                status_code=400,
                detail="Banner image must use a 7:3 aspect ratio",
            )

        extension = (
            image.filename.split(".")[-1].lower()
            if image.filename and "." in image.filename
            else "png"
        )

        storage_folder = {
            ("web", "hero"): "banners/web/hero",
            ("web", "main-promo-banner"): "main-promo-banner",
            ("web", "shop-by-need"): "shop-by-need",
        }.get(
            (platform, placement.strip()),
            f"banners/{platform}/{placement.strip()}",
        )
        storage_path = f"{storage_folder}/{uuid4()}.{extension}"

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

        banner_title = (
            title
            if title is not None
            else display_location or "Hero Banner"
        )
        banner_sort_order = (
            sort_order
            if sort_order is not None
            else display_order if display_order is not None else 0
        )
        metadata = {
            "display_location": display_location or banner_title,
        }
        if platform == "app" or placement.strip() == "hero":
            metadata["aspect_ratio"] = "7:3"

        banner_data = {
            "platform": platform,
            "placement": placement.strip(),
            "title": banner_title,
            "image_url": image_url,
            "storage_path": storage_path,
            "target_type": "home",
            "target_id": None,
            "category_id": None,
            "sort_order": banner_sort_order,
            "is_visible": publish_status == "published",
            "publish_status": publish_status,
            "starts_at": starts_at or None,
            "ends_at": ends_at or None,
            "metadata": metadata,
        }

        result = (
            supabase
            .table("banners")
            .insert(banner_data)
            .execute()
        )

        return {
            "message": f"{platform.capitalize()} banner created successfully",
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


@router.patch("/{banner_id}")
async def update_banner(
    banner_id: str,
    title: str | None = Form(default=None),
    target_type: str | None = Form(default=None),
    target_id: str | None = Form(default=None),
    target_url: str | None = Form(default=None),
    sort_order: int | None = Form(default=None),
    is_visible: bool | None = Form(default=None),
    publish_status: str | None = Form(default=None),
    starts_at: str | None = Form(default=None),
    ends_at: str | None = Form(default=None),
    image: UploadFile | None = File(default=None),
):
    try:
        existing_result = (
            supabase
            .table("banners")
            .select("*")
            .eq("id", banner_id)
            .maybe_single()
            .execute()
        )
        existing = existing_result.data

        if not existing:
            raise HTTPException(
                status_code=404,
                detail="Banner not found",
            )

        if existing.get("platform") != "web":
            raise HTTPException(
                status_code=400,
                detail="This endpoint only supports Web banners",
            )

        update_data = {}

        if title is not None:
            update_data["title"] = title

        if target_type is not None:
            update_data["target_type"] = target_type

        if target_id is not None:
            update_data["target_id"] = target_id or None

        if target_url is not None:
            update_data["target_url"] = target_url or None

        if sort_order is not None:
            update_data["sort_order"] = sort_order

        if is_visible is not None:
            update_data["is_visible"] = is_visible

        if publish_status is not None:
            update_data["publish_status"] = publish_status

        if starts_at is not None:
            update_data["starts_at"] = starts_at or None

        if ends_at is not None:
            update_data["ends_at"] = ends_at or None

        new_storage_path = None

        if image is not None:
            placement = existing.get("placement")
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

            file_bytes = await image.read()

            if not file_bytes:
                raise HTTPException(
                    status_code=400,
                    detail="Banner image is empty",
                )

            try:
                img = Image.open(BytesIO(file_bytes))
                width, height = img.size
            except Exception as exc:
                raise HTTPException(
                    status_code=400,
                    detail="Invalid image file",
                ) from exc

            if height <= 0:
                raise HTTPException(
                    status_code=400,
                    detail="Invalid image dimensions",
                )

            if (
                placement == "hero"
                and abs(width / height - (7 / 3)) > 0.03
            ):
                raise HTTPException(
                    status_code=400,
                    detail="Banner image must use a 7:3 aspect ratio",
                )

            extension = (
                image.filename.rsplit(".", 1)[-1].lower()
                if image.filename and "." in image.filename
                else "png"
            )
            storage_folder = {
                "hero": "banners/web/hero",
                "main-promo-banner": "main-promo-banner",
                "shop-by-need": "shop-by-need",
            }.get(placement)
            if not storage_folder:
                raise HTTPException(
                    status_code=400,
                    detail="Unsupported Web banner placement",
                )

            new_storage_path = f"{storage_folder}/{uuid4()}.{extension}"

            supabase.storage.from_("site_assets").upload(
                new_storage_path,
                file_bytes,
                {
                    "content-type": image.content_type,
                    "upsert": "false",
                },
            )

            update_data["image_url"] = (
                supabase
                .storage
                .from_("site_assets")
                .get_public_url(new_storage_path)
            )
            update_data["storage_path"] = new_storage_path

        if not update_data:
            return {
                "message": "No changes provided",
                "item": existing,
            }

        try:
            result = (
                supabase
                .table("banners")
                .update(update_data)
                .eq("id", banner_id)
                .execute()
            )
        except Exception:
            if new_storage_path:
                delete_storage_file(new_storage_path)
            raise

        if new_storage_path:
            old_storage_path = existing.get("storage_path")
            placement = existing.get("placement")
            old_storage_folder = {
                "hero": "banners/web/hero",
                "main-promo-banner": "main-promo-banner",
                "shop-by-need": "shop-by-need",
            }.get(placement)
            if (
                old_storage_path
                and old_storage_folder
                and old_storage_path.startswith(f"{old_storage_folder}/")
            ):
                delete_storage_file(old_storage_path)

        return {
            "message": "Web banner updated successfully",
            "item": result.data[0] if result.data else None,
        }

    except HTTPException:
        raise

    except Exception as exc:
        print("BANNER UPDATE ERROR:", repr(exc))

        raise HTTPException(
            status_code=500,
            detail=str(exc),
        ) from exc


@router.delete("/{banner_id}")
def delete_banner(
    banner_id: str,
):
    try:
        existing_result = (
            supabase
            .table("banners")
            .select("*")
            .eq("id", banner_id)
            .maybe_single()
            .execute()
        )
        existing = existing_result.data

        if not existing:
            raise HTTPException(
                status_code=404,
                detail="Banner not found",
            )

        if existing.get("platform") != "web":
            raise HTTPException(
                status_code=400,
                detail="This endpoint only supports Web banners",
            )

        (
            supabase
            .table("banners")
            .delete()
            .eq("id", banner_id)
            .execute()
        )

        storage_path = existing.get("storage_path")
        storage_folder = {
            "hero": "banners/web/hero",
            "main-promo-banner": "main-promo-banner",
            "shop-by-need": "shop-by-need",
        }.get(existing.get("placement"))
        if (
            storage_path
            and storage_folder
            and storage_path.startswith(f"{storage_folder}/")
        ):
            delete_storage_file(storage_path)

        return {
            "message": "Web banner deleted successfully",
        }

    except HTTPException:
        raise

    except Exception as exc:
        print("BANNER DELETE ERROR:", repr(exc))

        raise HTTPException(
            status_code=500,
            detail=str(exc),
        ) from exc


# =========================================================
# APP CATEGORY BANNERS
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

        file_bytes = await image.read()

        if not file_bytes:
            raise HTTPException(
                status_code=400,
                detail="Banner image is empty",
            )

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

        ratio = width / height

        if abs(ratio - 3.0) > 0.03:
            raise HTTPException(
                status_code=400,
                detail="Category banner must use a 3:1 aspect ratio",
            )

        extension = (
            image.filename.split(".")[-1].lower()
            if image.filename and "." in image.filename
            else "png"
        )

        file_name = f"{uuid4()}.{extension}"
        storage_path = f"banners/app/category/{file_name}"

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

        result = (
            supabase
            .table("banners")
            .insert(banner_data)
            .execute()
        )

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


# =========================================================
# CATEGORY CAMPAIGNS
# APP + WEB
# =========================================================

CAMPAIGN_BUCKET = "site_assets"


def validate_campaign_image(file: UploadFile, file_bytes: bytes):
    allowed_types = {
        "image/jpeg",
        "image/png",
        "image/webp",
    }

    if file.content_type not in allowed_types:
        raise HTTPException(
            status_code=400,
            detail="Only JPG, PNG, and WEBP images are allowed",
        )

    if not file_bytes:
        raise HTTPException(
            status_code=400,
            detail="Campaign image is empty",
        )

    try:
        img = Image.open(BytesIO(file_bytes))
        width, height = img.size
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail="Invalid campaign image",
        ) from exc

    if width <= 0 or height <= 0:
        raise HTTPException(
            status_code=400,
            detail="Invalid campaign image dimensions",
        )

    return width, height


def validate_platform(platform: str):
    if platform not in {"app", "web"}:
        raise HTTPException(
            status_code=400,
            detail="Platform must be either 'app' or 'web'",
        )


def campaign_storage_path(platform: str, extension: str):
    return f"banners/{platform}/campaigns/{uuid4()}.{extension}"


def delete_storage_file(storage_path: str | None):
    if not storage_path:
        return

    try:
        supabase.storage.from_(CAMPAIGN_BUCKET).remove([storage_path])
    except Exception as exc:
        print("CAMPAIGN STORAGE DELETE WARNING:", repr(exc))


@router.get("/category-campaigns")
def list_category_campaigns(
    platform: str = Query(...),
    category_id: str | None = Query(default=None),
    is_active: bool | None = Query(default=None),
):
    """
    List category campaigns for App or Web.
    """

    validate_platform(platform)

    try:
        query = (
            supabase
            .table("category_campaigns")
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
            .eq("platform", platform)
        )

        if category_id:
            query = query.eq("category_id", category_id)

        if is_active is not None:
            query = query.eq("is_active", is_active)

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
        print("CATEGORY CAMPAIGN LIST ERROR:", repr(exc))

        raise HTTPException(
            status_code=500,
            detail="Unable to retrieve category campaigns",
        ) from exc


@router.post("/category-campaigns")
async def create_category_campaign(
    platform: str = Form(...),
    category_id: str = Form(...),
    title: str = Form(...),
    image: UploadFile = File(...),
    display_order: int = Form(0),
    is_active: bool = Form(True),
):
    """
    Create an App or Web category campaign.

    Storage:
        banners/app/campaigns/...
        banners/web/campaigns/...
    """

    validate_platform(platform)

    try:
        # ---------------------------------------------------------
        # 1. Validate category
        # ---------------------------------------------------------
        category_result = (
            supabase
            .table("categories")
            .select("id, name, slug")
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
        # 2. Read image
        # ---------------------------------------------------------
        file_bytes = await image.read()

        validate_campaign_image(image, file_bytes)

        # ---------------------------------------------------------
        # 3. Generate storage path
        # ---------------------------------------------------------
        extension = (
            image.filename.split(".")[-1].lower()
            if image.filename and "." in image.filename
            else "png"
        )

        storage_path = campaign_storage_path(
            platform,
            extension,
        )

        # ---------------------------------------------------------
        # 4. Upload to Supabase Storage
        # ---------------------------------------------------------
        supabase.storage.from_(CAMPAIGN_BUCKET).upload(
            storage_path,
            file_bytes,
            {
                "content-type": image.content_type,
                "upsert": "false",
            },
        )

        # ---------------------------------------------------------
        # 5. Public URL
        # ---------------------------------------------------------
        image_url = (
            supabase
            .storage
            .from_(CAMPAIGN_BUCKET)
            .get_public_url(storage_path)
        )

        # ---------------------------------------------------------
        # 6. Database record
        # ---------------------------------------------------------
        campaign_data = {
            "title": title.strip(),
            "image_url": image_url,
            "storage_path": storage_path,
            "category_id": category_id,
            "sort_order": display_order,
            "is_active": is_active,
            "platform": platform,
        }

        result = (
            supabase
            .table("category_campaigns")
            .insert(campaign_data)
            .execute()
        )

        return {
            "message": (
                f"{platform.capitalize()} category campaign "
                "created successfully"
            ),
            "item": result.data[0] if result.data else None,
        }

    except HTTPException:
        raise

    except Exception as exc:
        print("CATEGORY CAMPAIGN CREATE ERROR:", repr(exc))

        raise HTTPException(
            status_code=500,
            detail=str(exc),
        ) from exc


@router.patch("/category-campaigns/{campaign_id}")
async def update_category_campaign(
    campaign_id: UUID,
    platform: str = Form(...),
    category_id: str | None = Form(None),
    title: str | None = Form(None),
    image: UploadFile | None = File(None),
    display_order: int | None = Form(None),
    is_active: bool | None = Form(None),
):
    """
    Update an App or Web category campaign.
    """

    validate_platform(platform)

    try:
        # ---------------------------------------------------------
        # 1. Get existing campaign
        # ---------------------------------------------------------
        existing_result = (
            supabase
            .table("category_campaigns")
            .select("*")
            .eq("id", str(campaign_id))
            .eq("platform", platform)
            .single()
            .execute()
        )

        if not existing_result.data:
            raise HTTPException(
                status_code=404,
                detail="Category campaign not found",
            )

        existing = existing_result.data

        update_data = {}

        # ---------------------------------------------------------
        # 2. Update category
        # ---------------------------------------------------------
        if category_id is not None:
            category_result = (
                supabase
                .table("categories")
                .select("id")
                .eq("id", category_id)
                .single()
                .execute()
            )

            if not category_result.data:
                raise HTTPException(
                    status_code=404,
                    detail="Category not found",
                )

            update_data["category_id"] = category_id

        # ---------------------------------------------------------
        # 3. Update title
        # ---------------------------------------------------------
        if title is not None:
            cleaned_title = title.strip()

            if not cleaned_title:
                raise HTTPException(
                    status_code=400,
                    detail="Campaign title cannot be empty",
                )

            update_data["title"] = cleaned_title

        # ---------------------------------------------------------
        # 4. Update order
        # ---------------------------------------------------------
        if display_order is not None:
            update_data["sort_order"] = display_order

        # ---------------------------------------------------------
        # 5. Update active status
        # ---------------------------------------------------------
        if is_active is not None:
            update_data["is_active"] = is_active

        # ---------------------------------------------------------
        # 6. Replace image if provided
        # ---------------------------------------------------------
        if image is not None:
            file_bytes = await image.read()

            validate_campaign_image(
                image,
                file_bytes,
            )

            extension = (
                image.filename.split(".")[-1].lower()
                if image.filename and "." in image.filename
                else "png"
            )

            new_storage_path = campaign_storage_path(
                platform,
                extension,
            )

            supabase.storage.from_(CAMPAIGN_BUCKET).upload(
                new_storage_path,
                file_bytes,
                {
                    "content-type": image.content_type,
                    "upsert": "false",
                },
            )

            new_image_url = (
                supabase
                .storage
                .from_(CAMPAIGN_BUCKET)
                .get_public_url(new_storage_path)
            )

            update_data["image_url"] = new_image_url
            update_data["storage_path"] = new_storage_path

        # ---------------------------------------------------------
        # 7. Nothing to update
        # ---------------------------------------------------------
        if not update_data:
            return {
                "message": "No changes provided",
                "item": existing,
            }

        # ---------------------------------------------------------
        # 8. Update database
        # ---------------------------------------------------------
        result = (
            supabase
            .table("category_campaigns")
            .update(update_data)
            .eq("id", str(campaign_id))
            .eq("platform", platform)
            .execute()
        )

        # ---------------------------------------------------------
        # 9. Delete old image after successful DB update
        # ---------------------------------------------------------
        if image is not None:
            old_storage_path = existing.get("storage_path")

            if old_storage_path:
                delete_storage_file(old_storage_path)

        return {
            "message": "Category campaign updated successfully",
            "item": result.data[0] if result.data else None,
        }

    except HTTPException:
        raise

    except Exception as exc:
        print("CATEGORY CAMPAIGN UPDATE ERROR:", repr(exc))

        raise HTTPException(
            status_code=500,
            detail=str(exc),
        ) from exc


@router.delete("/category-campaigns/{campaign_id}")
def delete_category_campaign(
    campaign_id: UUID,
    platform: str = Query(...),
):
    """
    Delete an App or Web category campaign and its
    corresponding Storage image.
    """

    validate_platform(platform)

    try:
        # ---------------------------------------------------------
        # 1. Find campaign
        # ---------------------------------------------------------
        existing_result = (
            supabase
            .table("category_campaigns")
            .select("*")
            .eq("id", str(campaign_id))
            .eq("platform", platform)
            .single()
            .execute()
        )

        if not existing_result.data:
            raise HTTPException(
                status_code=404,
                detail="Category campaign not found",
            )

        existing = existing_result.data

        # ---------------------------------------------------------
        # 2. Delete database record
        # ---------------------------------------------------------
        (
            supabase
            .table("category_campaigns")
            .delete()
            .eq("id", str(campaign_id))
            .eq("platform", platform)
            .execute()
        )

        # ---------------------------------------------------------
        # 3. Delete Storage image
        # ---------------------------------------------------------
        delete_storage_file(
            existing.get("storage_path")
        )

        return {
            "message": "Category campaign deleted successfully",
        }

    except HTTPException:
        raise

    except Exception as exc:
        print("CATEGORY CAMPAIGN DELETE ERROR:", repr(exc))

        raise HTTPException(
            status_code=500,
            detail=str(exc),
        ) from exc
@router.post("/storage/sync-web-hero")
def sync_web_hero_banners():
    """
    Create banners-table records for existing Web Hero Banner images
    already stored in Supabase Storage.

    Existing images are NOT moved or duplicated.
    """

    folder = "products-banner"

    try:
        items = (
            supabase
            .storage
            .from_("site_assets")
            .list(folder)
        )

        synced = []
        skipped = []

        for item in items or []:
            name = item.get("name")

            if not name:
                continue

            # Ignore folders
            if item.get("id") is None:
                continue

            storage_path = f"{folder}/{name}"

            image_url = (
                supabase
                .storage
                .from_("site_assets")
                .get_public_url(storage_path)
            )

            # Check whether this image already exists in banners
            existing_response = (
                supabase
                .table("banners")
                .select("id")
                .eq("platform", "web")
                .eq("placement", "hero")
                .eq("storage_path", storage_path)
                .limit(1)
                .execute()
            )
            existing_data = (
                existing_response.data
                if existing_response is not None
                else None
            )
            if existing_data:
                skipped.append({
                    "name": name,
                    "reason": "Already exists",
                    "id": existing_data[0]["id"],
                })
                continue

            # Get current highest sort order
            order_response = (
                supabase
                .table("banners")
                .select("sort_order")
                .eq("platform", "web")
                .eq("placement", "hero")
                .order("sort_order", desc=True)
                .limit(1)
                .execute()
            )

            current_order = 0

            if order_response.data:
                current_order = (
                    order_response.data[0].get("sort_order") or 0
                )

            new_banner = (
                supabase
                .table("banners")
                .insert({
                    "platform": "web",
                    "placement": "hero",
                    "title": name,
                    "image_url": image_url,
                    "storage_path": storage_path,
                    "target_type": "none",
                    "sort_order": current_order + 1,
                    "is_visible": True,
                    "publish_status": "published",
                })
                .execute()
            )

            synced.append({
                "name": name,
                "storage_path": storage_path,
                "image_url": image_url,
                "banner": new_banner.data[0] if new_banner.data else None,
            })

        return {
            "success": True,
            "folder": folder,
            "synced_count": len(synced),
            "skipped_count": len(skipped),
            "synced": synced,
            "skipped": skipped,
        }

    except Exception as exc:
        print("WEB HERO SYNC ERROR:", repr(exc))
        raise HTTPException(
            status_code=500,
            detail=f"Web Hero Banner sync failed: {str(exc)}",
            ) from exc
@router.get("/storage/shop-by-need")
def list_shop_by_need_files():
    try:
        folder = "shop-by-need"

        items = (
            supabase
            .storage
            .from_("site_assets")
            .list(folder)
        )

        files = []

        for item in items or []:
            name = item.get("name")

            if not name:
                continue

            # Skip folders
            if item.get("id") is None:
                continue

            storage_path = f"{folder}/{name}"

            image_url = (
                supabase
                .storage
                .from_("site_assets")
                .get_public_url(storage_path)
            )

            files.append({
                "name": name,
                "storage_path": storage_path,
                "image_url": image_url,
                "metadata": item.get("metadata"),
            })

        return {
            "bucket": "site_assets",
            "folder": folder,
            "files": files,
        }

    except Exception as exc:
        print("SHOP BY NEED STORAGE ERROR:", repr(exc))

        raise HTTPException(
            status_code=500,
            detail="Unable to list Shop by Need images",
        ) from exc

@router.post("/storage/sync-shop-by-need")
def sync_shop_by_need():
    try:
        folder = "shop-by-need"

        items = (
            supabase
            .storage
            .from_("site_assets")
            .list(folder)
        )

        synced = []

        for index, item in enumerate(items or []):
            name = item.get("name")

            if not name or item.get("id") is None:
                continue

            storage_path = f"{folder}/{name}"

            image_url = (
                supabase
                .storage
                .from_("site_assets")
                .get_public_url(storage_path)
            )

            banner_data = {
                "platform": "web",
                "placement": "shop-by-need",
                "title": name,
                "image_url": image_url,
                "storage_path": storage_path,
                "target_type": "none",
                "target_id": None,
                "target_url": None,
                "sort_order": index + 1,
                "is_visible": True,
                "publish_status": "published",
                "category_id": None,
                "metadata": {
                    "source": "site_assets",
                    "folder": folder,
                },
            }

            existing = (
                supabase
                .table("banners")
                .select("id")
                .eq("platform", "web")
                .eq("placement", "shop-by-need")
                .eq("storage_path", storage_path)
                .limit(1)
                .execute()
            )

            if existing.data:
                result = (
                    supabase
                    .table("banners")
                    .update(banner_data)
                    .eq("id", existing.data[0]["id"])
                    .execute()
                )

                synced.append({
                    "action": "updated",
                    "item": result.data[0] if result.data else None,
                })

            else:
                result = (
                    supabase
                    .table("banners")
                    .insert(banner_data)
                    .execute()
                )

                synced.append({
                    "action": "created",
                    "item": result.data[0] if result.data else None,
                })

        return {
            "message": "Shop by Need banners synced successfully",
            "count": len(synced),
            "items": synced,
        }

    except Exception as exc:
        print("SHOP BY NEED SYNC ERROR:", repr(exc))

        raise HTTPException(
            status_code=500,
            detail="Unable to sync Shop by Need banners",
        ) from exc
@router.get("/storage/main-promo-banner")
def list_main_promo_banner_files():
    try:
        folder = "main-promo-banner"

        items = (
            supabase
            .storage
            .from_("site_assets")
            .list(folder)
        )

        files = []

        for item in items or []:
            name = item.get("name")

            if not name or item.get("id") is None:
                continue

            storage_path = f"{folder}/{name}"

            image_url = (
                supabase
                .storage
                .from_("site_assets")
                .get_public_url(storage_path)
            )

            files.append({
                "name": name,
                "storage_path": storage_path,
                "image_url": image_url,
                "metadata": item.get("metadata"),
            })

        return {
            "bucket": "site_assets",
            "folder": folder,
            "files": files,
        }

    except Exception as exc:
        print("MAIN PROMO BANNER STORAGE ERROR:", repr(exc))

        raise HTTPException(
            status_code=500,
            detail="Unable to list Main Promo Banner images",
        ) from exc
@router.post("/storage/sync-main-promo-banner")
def sync_main_promo_banner():
    try:
        folder = "main-promo-banner"

        items = (
            supabase
            .storage
            .from_("site_assets")
            .list(folder)
        )

        synced = []

        for index, item in enumerate(items or []):
            name = item.get("name")

            if not name or item.get("id") is None:
                continue

            storage_path = f"{folder}/{name}"

            image_url = (
                supabase
                .storage
                .from_("site_assets")
                .get_public_url(storage_path)
            )

            banner_data = {
                "platform": "web",
                "placement": "main-promo-banner",
                "title": name,
                "image_url": image_url,
                "storage_path": storage_path,
                "target_type": "none",
                "target_id": None,
                "target_url": None,
                "sort_order": index + 1,
                "is_visible": True,
                "publish_status": "published",
                "category_id": None,
                "metadata": {
                    "source": "site_assets",
                    "folder": folder,
                },
            }

            existing = (
                supabase
                .table("banners")
                .select("id")
                .eq("platform", "web")
                .eq("placement", "main-promo-banner")
                .eq("storage_path", storage_path)
                .limit(1)
                .execute()
            )

            if existing.data:
                result = (
                    supabase
                    .table("banners")
                    .update(banner_data)
                    .eq("id", existing.data[0]["id"])
                    .execute()
                )

                synced.append({
                    "action": "updated",
                    "item": result.data[0] if result.data else None,
                })

            else:
                result = (
                    supabase
                    .table("banners")
                    .insert(banner_data)
                    .execute()
                )

                synced.append({
                    "action": "created",
                    "item": result.data[0] if result.data else None,
                })

        return {
            "message": "Main Promo Banners synced successfully",
            "count": len(synced),
            "items": synced,
        }

    except Exception as exc:
        print("MAIN PROMO BANNER SYNC ERROR:", repr(exc))

        raise HTTPException(
            status_code=500,
            detail="Unable to sync Main Promo Banners",
        ) from exc
@router.post("/storage/sync-category-campaigns")
def sync_category_campaigns():
    try:
        folder = "category-campaigns"

        items = (
            supabase
            .storage
            .from_("site_assets")
            .list(folder)
        )

        synced = []

        for index, item in enumerate(items or []):
            name = item.get("name")

            if not name or item.get("id") is None:
                continue

            storage_path = f"{folder}/{name}"

            image_url = (
                supabase
                .storage
                .from_("site_assets")
                .get_public_url(storage_path)
            )

            # Existing naming convention:
            # mobile-* = App
            # everything else = Web
            platform = (
                "app"
                if name.lower().startswith("mobile-")
                else "web"
            )

            banner_data = {
                "platform": platform,
                "placement": "category-campaign",
                "title": name,
                "image_url": image_url,
                "storage_path": storage_path,
                "target_type": "none",
                "target_id": None,
                "target_url": None,
                "sort_order": index + 1,
                "is_visible": True,
                "publish_status": "published",
                "category_id": None,
                "metadata": {
                    "source": "site_assets",
                    "folder": folder,
                    "platform_source": "filename",
                },
            }

            existing = (
                supabase
                .table("banners")
                .select("id")
                .eq("platform", platform)
                .eq("placement", "category-campaign")
                .eq("storage_path", storage_path)
                .limit(1)
                .execute()
            )

            if existing.data:
                result = (
                    supabase
                    .table("banners")
                    .update(banner_data)
                    .eq("id", existing.data[0]["id"])
                    .execute()
                )

                synced.append({
                    "action": "updated",
                    "platform": platform,
                    "item": result.data[0] if result.data else None,
                })

            else:
                result = (
                    supabase
                    .table("banners")
                    .insert(banner_data)
                    .execute()
                )

                synced.append({
                    "action": "created",
                    "platform": platform,
                    "item": result.data[0] if result.data else None,
                })

        return {
            "message": "Category campaigns synced successfully",
            "count": len(synced),
            "items": synced,
        }

    except Exception as exc:
        print("CATEGORY CAMPAIGN SYNC ERROR:", repr(exc))

        raise HTTPException(
            status_code=500,
            detail="Unable to sync category campaigns",
        ) from exc