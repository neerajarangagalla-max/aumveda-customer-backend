
from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    UploadFile,
)

from app.dependencies.vendor_permissions import (
    require_vendor_permission,
)

from app.schemas.vendor.products import (
    VendorProductCreateRequest,
    VendorProductUpdateRequest,
    VendorVariantCreateRequest,
    VendorVariantUpdateRequest,
)

from app.services.vendor.product_service import (
    archive_vendor_product,
    create_product_variant,
    create_vendor_product,
    delete_product_variant,
    get_vendor_product,
    list_product_variants,
    list_vendor_products,
    submit_vendor_product_for_approval,
    update_product_variant,
    update_vendor_product,
)

from app.services.vendor.product_image_service import (
    delete_product_image,
    list_product_images,
    set_primary_product_image,
    upload_product_image,
)


router = APIRouter(
    prefix="/products",
    tags=["Vendor Products"],
)


# ============================================================
# PRODUCTS — LIST
# Permission: products.view
# ============================================================

@router.get("")
def vendor_products(
    vendor_context=Depends(
        require_vendor_permission("products.view")
    ),
):
    return list_vendor_products(
        vendor_context["vendor_id"]
    )


# ============================================================
# PRODUCTS — CREATE
# Permission: products.create
# ============================================================

@router.post("")
def vendor_create_product(
    payload: VendorProductCreateRequest,
    vendor_context=Depends(
        require_vendor_permission("products.create")
    ),
):
    """
    New products begin in draft status.

    Product approval is not granted by this route.
    """

    return create_vendor_product(
        vendor_id=vendor_context["vendor_id"],
        payload=payload.model_dump(mode="json"),
    )


# ============================================================
# PRODUCTS — SUBMIT FOR APPROVAL
# Permission: products.update
# ============================================================

@router.post("/{product_id}/submit-for-approval")
def vendor_submit_product_for_approval(
    product_id: str,
    vendor_context=Depends(
        require_vendor_permission("products.update")
    ),
):
    """
    Existing approval workflow remains unchanged.

    Only the backend service may validate the
    product and transition it to pending review.
    """

    return submit_vendor_product_for_approval(
        vendor_id=vendor_context["vendor_id"],
        product_id=product_id,
    )


# ============================================================
# PRODUCTS — DETAIL
# Permission: products.view
# ============================================================

@router.get("/{product_id}")
def vendor_product_detail(
    product_id: str,
    vendor_context=Depends(
        require_vendor_permission("products.view")
    ),
):
    return get_vendor_product(
        vendor_id=vendor_context["vendor_id"],
        product_id=product_id,
    )


# ============================================================
# PRODUCTS — UPDATE
# Permission: products.update
# ============================================================

@router.patch("/{product_id}")
def vendor_edit_product(
    product_id: str,
    payload: VendorProductUpdateRequest,
    vendor_context=Depends(
        require_vendor_permission("products.update")
    ),
):
    """
    Editable product statuses remain controlled
    by the existing product service.

    Only explicitly provided fields are updated.
    """

    return update_vendor_product(
        vendor_id=vendor_context["vendor_id"],
        product_id=product_id,
        payload=payload.model_dump(
            mode="json",
            exclude_unset=True,
        ),
    )


# ============================================================
# PRODUCTS — ARCHIVE
# Permission: products.update
# ============================================================

@router.delete("/{product_id}")
def vendor_delete_product(
    product_id: str,
    vendor_context=Depends(
        require_vendor_permission("products.update")
    ),
):
    return archive_vendor_product(
        vendor_id=vendor_context["vendor_id"],
        product_id=product_id,
    )


# ============================================================
# PRODUCT IMAGES — LIST
# Permission: products.view
# ============================================================

@router.get("/{product_id}/images")
def vendor_product_images(
    product_id: str,
    vendor_context=Depends(
        require_vendor_permission("products.view")
    ),
):
    return list_product_images(
        vendor_id=vendor_context["vendor_id"],
        product_id=product_id,
    )


# ============================================================
# PRODUCT IMAGES — UPLOAD
# Permission: products.images
# ============================================================

@router.post("/{product_id}/images")
async def vendor_upload_product_image(
    product_id: str,
    file: UploadFile = File(...),
    alt_text: str | None = Form(default=None),
    sort_order: int = Form(default=0),
    is_primary: bool = Form(default=False),
    vendor_context=Depends(
        require_vendor_permission("products.images")
    ),
):
    """
    Retains the existing multipart upload
    and image service validation.
    """

    return await upload_product_image(
        vendor_id=vendor_context["vendor_id"],
        product_id=product_id,
        file=file,
        alt_text=alt_text,
        sort_order=sort_order,
        is_primary=is_primary,
    )


# ============================================================
# PRODUCT IMAGES — SET PRIMARY
# Permission: products.images
# ============================================================

@router.patch(
    "/{product_id}/images/{image_id}/primary"
)
def vendor_set_primary_product_image(
    product_id: str,
    image_id: str,
    vendor_context=Depends(
        require_vendor_permission("products.images")
    ),
):
    return set_primary_product_image(
        vendor_id=vendor_context["vendor_id"],
        product_id=product_id,
        image_id=image_id,
    )


# ============================================================
# PRODUCT IMAGES — DELETE
# Permission: products.images
# ============================================================

@router.delete(
    "/{product_id}/images/{image_id}"
)
def vendor_delete_product_image(
    product_id: str,
    image_id: str,
    vendor_context=Depends(
        require_vendor_permission("products.images")
    ),
):
    return delete_product_image(
        vendor_id=vendor_context["vendor_id"],
        product_id=product_id,
        image_id=image_id,
    )


# ============================================================
# PRODUCT VARIANTS — LIST
# Permission: products.view
# ============================================================

@router.get("/{product_id}/variants")
def vendor_product_variants(
    product_id: str,
    vendor_context=Depends(
        require_vendor_permission("products.view")
    ),
):
    return list_product_variants(
        vendor_id=vendor_context["vendor_id"],
        product_id=product_id,
    )


# ============================================================
# PRODUCT VARIANTS — CREATE
# Permission: products.create
# ============================================================

@router.post("/{product_id}/variants")
def vendor_create_variant(
    product_id: str,
    payload: VendorVariantCreateRequest,
    vendor_context=Depends(
        require_vendor_permission("products.create")
    ),
):
    """
    Uses model_dump(mode="json") so Decimal
    fields are JSON serializable.
    """

    return create_product_variant(
        vendor_id=vendor_context["vendor_id"],
        product_id=product_id,
        payload=payload.model_dump(mode="json"),
    )


# ============================================================
# PRODUCT VARIANTS — UPDATE
#
# TEMPORARY STRICT RULE:
# Requires BOTH products.update AND inventory.update.
#
# This route can update product content and also
# stock-related fields for active variants.
#
# Until the mixed operations are separated and
# the request schema is audited, requiring both
# prevents product-only staff from bypassing
# inventory permissions.
# ============================================================

@router.patch("/variants/{variant_id}")
def vendor_edit_variant(
    variant_id: str,
    payload: VendorVariantUpdateRequest,
    vendor_context=Depends(
        require_vendor_permission("products.update")
    ),
    _inventory_context=Depends(
        require_vendor_permission("inventory.update")
    ),
):
    return update_product_variant(
        vendor_id=vendor_context["vendor_id"],
        variant_id=variant_id,
        payload=payload.model_dump(
            mode="json",
            exclude_unset=True,
        ),
    )


# ============================================================
# PRODUCT VARIANTS — DEACTIVATE
# Permission: products.update
# ============================================================

@router.delete("/variants/{variant_id}")
def vendor_delete_variant(
    variant_id: str,
    vendor_context=Depends(
        require_vendor_permission("products.update")
    ),
):
    return delete_product_variant(
        vendor_id=vendor_context["vendor_id"],
        variant_id=variant_id,
    )
