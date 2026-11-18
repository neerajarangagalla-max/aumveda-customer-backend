
import re
from uuid import uuid4

from fastapi import HTTPException, status
from app.core.supabase import supabase_admin


# ============================================================
# CONFIGURATION
# ============================================================

PRODUCT_COLUMNS = {
    "category_id",
    "name",
    "short_description",
    "description",
    "ingredients",
    "benefits",
    "directions",
    "warnings",
}

VARIANT_COLUMNS = {
    "name",
    "sku",
    "price",
    "compare_at_price",
    "cost_price",
    "stock_quantity",
    "is_active",
}

VARIANT_METADATA_FIELDS = {
    "size_value",
    "size_unit",
    "low_stock_threshold",
    "is_default",
}

CONTENT_EDITABLE_STATUSES = {
    "draft",
    "rejected",
}

ACTIVE_VARIANT_EDITABLE_FIELDS = {
    "stock_quantity",
    "low_stock_threshold",
}


# ============================================================
# COMMON HELPERS
# ============================================================

def _slugify(value: str) -> str:
    value = str(value or "").strip().lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    return value.strip("-") or "product"


def _generate_product_slug(name: str) -> str:
    return f"{_slugify(name)}-{uuid4().hex[:8]}"


def _raise_server_error(
    message: str,
    exc: Exception,
):
    if isinstance(exc, HTTPException):
        raise exc

    raise HTTPException(
        status_code=500,
        detail=f"{message}: {str(exc)}",
    ) from exc


def _ensure_category_exists(category_id: str) -> None:
    if not category_id:
        raise HTTPException(
            status_code=400,
            detail="Product category is required.",
        )

    try:
        response = (
            supabase_admin
            .table("categories")
            .select("id")
            .eq("id", category_id)
            .limit(1)
            .execute()
        )

        if not response.data:
            raise HTTPException(
                status_code=400,
                detail="Selected category does not exist.",
            )

    except Exception as exc:
        _raise_server_error(
            "Unable to validate product category",
            exc,
        )


def _validate_product_payload(payload: dict) -> None:
    if payload.get("formulation_id") is not None:
        raise HTTPException(
            status_code=400,
            detail=(
                "Formulation selection is not supported "
                "by the current products database schema."
            ),
        )


# ============================================================
# OWNERSHIP HELPERS
# ============================================================

def _get_owned_product(
    vendor_id: str,
    product_id: str,
) -> dict:
    try:
        response = (
            supabase_admin
            .table("products")
            .select("*")
            .eq("id", product_id)
            .eq("vendor_id", vendor_id)
            .limit(1)
            .execute()
        )

        rows = response.data or []

        if not rows:
            raise HTTPException(
                status_code=404,
                detail="Product was not found.",
            )

        return rows[0]

    except Exception as exc:
        _raise_server_error("Unable to load product", exc)


def _get_owned_variant(
    vendor_id: str,
    variant_id: str,
) -> tuple[dict, dict]:
    try:
        response = (
            supabase_admin
            .table("product_variants")
            .select("*")
            .eq("id", variant_id)
            .limit(1)
            .execute()
        )

        rows = response.data or []

        if not rows:
            raise HTTPException(
                status_code=404,
                detail="Product variant was not found.",
            )

        variant = rows[0]

        product = _get_owned_product(
            vendor_id,
            variant["product_id"],
        )

        return variant, product

    except Exception as exc:
        _raise_server_error(
            "Unable to load product variant",
            exc,
        )


# ============================================================
# APPROVAL SECURITY
# ============================================================

def _product_status(product: dict) -> str:
    return str(
        product.get("status") or ""
    ).strip().lower()


def _ensure_content_editable(product: dict) -> None:
    current_status = _product_status(product)

    if current_status not in CONTENT_EDITABLE_STATUSES:
        raise HTTPException(
            status_code=409,
            detail=(
                "Product information cannot be modified "
                f"while product status is '{current_status}'. "
                "Only draft or rejected products can be edited."
            ),
        )


def _ensure_variant_update_allowed(
    product: dict,
    payload: dict,
) -> None:
    current_status = _product_status(product)

    if current_status in CONTENT_EDITABLE_STATUSES:
        return

    if current_status == "active":
        requested_fields = {
            key
            for key, value in payload.items()
            if value is not None
        }

        forbidden_fields = (
            requested_fields
            - ACTIVE_VARIANT_EDITABLE_FIELDS
        )

        if forbidden_fields:
            raise HTTPException(
                status_code=409,
                detail=(
                    "Approved product variants permit only "
                    "stock quantity and low-stock threshold "
                    "updates. Changes requiring approval: "
                    + ", ".join(sorted(forbidden_fields))
                ),
            )

        return

    raise HTTPException(
        status_code=409,
        detail=(
            "Product variants cannot be modified "
            f"while product status is '{current_status}'."
        ),
    )


def _ensure_content_status_still_editable(
    vendor_id: str,
    product_id: str,
) -> None:
    product = _get_owned_product(
        vendor_id,
        product_id,
    )

    _ensure_content_editable(product)


# ============================================================
# VARIANT NORMALIZATION
# ============================================================

def _normalize_variant(variant: dict) -> dict:
    result = dict(variant)

    attributes = result.get("attributes")

    if not isinstance(attributes, dict):
        attributes = {}

    result["attributes"] = attributes
    result["size_value"] = attributes.get("size_value")
    result["size_unit"] = attributes.get("size_unit")

    result["low_stock_threshold"] = attributes.get(
        "low_stock_threshold",
        5,
    )

    result["is_default"] = bool(
        attributes.get("is_default", False)
    )

    return result


def _normalize_variants(
    variants: list[dict],
) -> list[dict]:
    result = [
        _normalize_variant(variant)
        for variant in variants
    ]

    if result and not any(
        item["is_default"]
        for item in result
    ):
        first_active = next(
            (
                item
                for item in result
                if item.get("is_active", True)
            ),
            None,
        )

        if first_active is not None:
            first_active["is_default"] = True

    return result


def _get_product_variants(
    product_id: str,
) -> list[dict]:
    response = (
        supabase_admin
        .table("product_variants")
        .select("*")
        .eq("product_id", product_id)
        .order("created_at", desc=False)
        .execute()
    )

    return _normalize_variants(
        response.data or []
    )


# ============================================================
# VARIANT VALIDATION
# ============================================================

def _build_variant_attributes(
    payload: dict,
    existing: dict | None = None,
) -> dict:
    attributes = dict(existing or {})

    for field in VARIANT_METADATA_FIELDS:
        if (
            field in payload
            and payload[field] is not None
        ):
            attributes[field] = payload[field]

    if "low_stock_threshold" in attributes:
        try:
            threshold = int(
                attributes["low_stock_threshold"]
            )
        except (ValueError, TypeError):
            raise HTTPException(
                status_code=400,
                detail="Low-stock threshold must be an integer.",
            )

        if threshold < 0:
            raise HTTPException(
                status_code=400,
                detail="Low-stock threshold cannot be negative.",
            )

        attributes["low_stock_threshold"] = threshold

    if "is_default" in attributes:
        attributes["is_default"] = bool(
            attributes["is_default"]
        )

    return attributes


def _validate_variant_values(data: dict) -> None:
    for field in (
        "price",
        "compare_at_price",
        "cost_price",
    ):
        value = data.get(field)

        if value is not None:
            try:
                if float(value) < 0:
                    raise ValueError()
            except (TypeError, ValueError):
                raise HTTPException(
                    status_code=400,
                    detail=f"{field} must be a non-negative number.",
                )

    if "stock_quantity" in data:
        try:
            stock = int(data["stock_quantity"])
        except (TypeError, ValueError):
            raise HTTPException(
                status_code=400,
                detail="Stock quantity must be an integer.",
            )

        if stock < 0:
            raise HTTPException(
                status_code=400,
                detail="Stock quantity cannot be negative.",
            )

        data["stock_quantity"] = stock


def _ensure_unique_sku(
    sku: str,
    exclude_variant_id: str | None = None,
) -> None:
    if not sku:
        raise HTTPException(
            status_code=400,
            detail="SKU is required.",
        )

    try:
        query = (
            supabase_admin
            .table("product_variants")
            .select("id")
            .eq("sku", sku)
        )

        if exclude_variant_id:
            query = query.neq(
                "id",
                exclude_variant_id,
            )

        response = query.limit(1).execute()

        if response.data:
            raise HTTPException(
                status_code=409,
                detail=(
                    "A product variant with this SKU "
                    "already exists."
                ),
            )

    except Exception as exc:
        _raise_server_error(
            "Unable to validate SKU",
            exc,
        )


def _clear_other_default_variants(
    product_id: str,
    exclude_variant_id: str | None = None,
) -> None:
    try:
        response = (
            supabase_admin
            .table("product_variants")
            .select("id, attributes")
            .eq("product_id", product_id)
            .execute()
        )

        for variant in response.data or []:
            if variant["id"] == exclude_variant_id:
                continue

            attributes = dict(
                variant.get("attributes") or {}
            )

            if not attributes.get("is_default"):
                continue

            attributes["is_default"] = False

            (
                supabase_admin
                .table("product_variants")
                .update({"attributes": attributes})
                .eq("id", variant["id"])
                .execute()
            )

    except Exception as exc:
        _raise_server_error(
            "Unable to update default variants",
            exc,
        )


# ============================================================
# PRODUCTS — LIST
# ============================================================

def list_vendor_products(
    vendor_id: str,
) -> list[dict]:
    try:
        response = (
            supabase_admin
            .table("products")
            .select("*")
            .eq("vendor_id", vendor_id)
            .order("created_at", desc=True)
            .execute()
        )

        products = response.data or []
        result = []

        for product in products:
            product = dict(product)

            variants = _get_product_variants(
                product["id"]
            )

            product["variants"] = variants
            product["variant_count"] = len(variants)

            product["total_stock"] = sum(
                int(variant.get("stock_quantity") or 0)
                for variant in variants
            )

            result.append(product)

        return result

    except Exception as exc:
        _raise_server_error(
            "Unable to load vendor products",
            exc,
        )


# ============================================================
# PRODUCTS — CREATE
# ============================================================

def create_vendor_product(
    vendor_id: str,
    payload: dict,
) -> dict:
    category_id = payload.get("category_id")

    _ensure_category_exists(category_id)
    _validate_product_payload(payload)

    name = str(
        payload.get("name") or ""
    ).strip()

    if not name:
        raise HTTPException(
            status_code=400,
            detail="Product name is required.",
        )

    product_data = {
        "vendor_id": vendor_id,
        "category_id": category_id,
        "name": name,
        "slug": _generate_product_slug(name),

        "short_description": payload.get(
            "short_description"
        ),
        "description": payload.get(
            "description"
        ),
        "ingredients": payload.get(
            "ingredients"
        ),
        "benefits": payload.get(
            "benefits"
        ),
        "directions": payload.get(
            "directions"
        ),
        "warnings": payload.get(
            "warnings"
        ),

        # Vendors create drafts, never approved products.
        "status": "draft",

        "is_featured": False,
        "average_rating": 0,
        "review_count": 0,
    }

    try:
        response = (
            supabase_admin
            .table("products")
            .insert(product_data)
            .execute()
        )

        rows = response.data or []

        if not rows:
            raise RuntimeError(
                "Product was not created."
            )

        product = rows[0]
        product["variants"] = []
        product["variant_count"] = 0
        product["total_stock"] = 0

        return product

    except Exception as exc:
        _raise_server_error(
            "Unable to create product",
            exc,
        )


# ============================================================
# PRODUCTS — DETAIL
# ============================================================

def get_vendor_product(
    vendor_id: str,
    product_id: str,
) -> dict:
    product = _get_owned_product(
        vendor_id,
        product_id,
    )

    try:
        product["variants"] = _get_product_variants(
            product_id
        )

        return product

    except Exception as exc:
        _raise_server_error(
            "Unable to load product variants",
            exc,
        )


# ============================================================
# PRODUCTS — UPDATE
# ============================================================

def update_vendor_product(
    vendor_id: str,
    product_id: str,
    payload: dict,
) -> dict:
    product = _get_owned_product(
        vendor_id,
        product_id,
    )

    if "status" in payload:
        raise HTTPException(
            status_code=403,
            detail=(
                "Product approval status cannot be changed "
                "through the vendor product update API."
            ),
        )

    _validate_product_payload(payload)

    update_data = {
        key: value
        for key, value in payload.items()
        if key in PRODUCT_COLUMNS
        and value is not None
    }

    if not update_data:
        return get_vendor_product(
            vendor_id,
            product_id,
        )

    _ensure_content_editable(product)

    if "category_id" in update_data:
        _ensure_category_exists(
            update_data["category_id"]
        )

    if "name" in update_data:
        name = str(
            update_data["name"]
        ).strip()

        if not name:
            raise HTTPException(
                status_code=400,
                detail="Product name cannot be empty.",
            )

        update_data["name"] = name

    try:
        response = (
            supabase_admin
            .table("products")
            .update(update_data)
            .eq("id", product_id)
            .eq("vendor_id", vendor_id)
            .in_(
                "status",
                ["draft", "rejected"],
            )
            .execute()
        )

        if not response.data:
            raise HTTPException(
                status_code=409,
                detail=(
                    "Product was not updated. "
                    "Its approval status may have changed."
                ),
            )

        return get_vendor_product(
            vendor_id,
            product_id,
        )

    except Exception as exc:
        _raise_server_error(
            "Unable to update product",
            exc,
        )


# ============================================================
# PRODUCTS — ARCHIVE
# ============================================================

def archive_vendor_product(
    vendor_id: str,
    product_id: str,
) -> dict:
    product = _get_owned_product(
        vendor_id,
        product_id,
    )

    current_status = _product_status(product)

    if current_status == "pending":
        raise HTTPException(
            status_code=409,
            detail=(
                "Products awaiting approval cannot "
                "be archived."
            ),
        )

    if current_status == "archived":
        return {
            "message": "Product is already archived.",
            "product_id": product_id,
        }

    if current_status not in {
        "draft",
        "rejected",
        "active",
    }:
        raise HTTPException(
            status_code=409,
            detail="Product cannot be archived in this state.",
        )

    try:
        response = (
            supabase_admin
            .table("products")
            .update({"status": "archived"})
            .eq("id", product_id)
            .eq("vendor_id", vendor_id)
            .eq("status", current_status)
            .execute()
        )

        if not response.data:
            raise HTTPException(
                status_code=409,
                detail=(
                    "Product status changed before "
                    "archive could be completed."
                ),
            )

        return {
            "message": "Product archived successfully.",
            "product_id": product_id,
        }

    except Exception as exc:
        _raise_server_error(
            "Unable to archive product",
            exc,
        )


# ============================================================
# PRODUCT VARIANTS — LIST
# ============================================================

def list_product_variants(
    vendor_id: str,
    product_id: str,
) -> list[dict]:
    _get_owned_product(
        vendor_id,
        product_id,
    )

    try:
        return _get_product_variants(
            product_id
        )

    except Exception as exc:
        _raise_server_error(
            "Unable to load product variants",
            exc,
        )


# ============================================================
# PRODUCT VARIANTS — CREATE
# ============================================================

def create_product_variant(
    vendor_id: str,
    product_id: str,
    payload: dict,
) -> dict:
    product = _get_owned_product(
        vendor_id,
        product_id,
    )

    _ensure_content_editable(product)

    sku = str(
        payload.get("sku") or ""
    ).strip()

    _ensure_unique_sku(sku)

    variant_data = {
        "product_id": product_id,
        "name": payload.get("name"),
        "sku": sku,
        "price": payload.get("price"),
        "compare_at_price": payload.get(
            "compare_at_price"
        ),
        "cost_price": payload.get(
            "cost_price"
        ),
        "stock_quantity": payload.get(
            "stock_quantity",
            0,
        ),
        "is_active": payload.get(
            "is_active",
            True,
        ),
        "attributes": _build_variant_attributes(
            payload,
            {
                "low_stock_threshold": 5,
                "is_default": False,
            },
        ),
    }

    if variant_data["price"] is None:
        raise HTTPException(
            status_code=400,
            detail="Variant price is required.",
        )

    _validate_variant_values(
        variant_data
    )

    _ensure_content_status_still_editable(
        vendor_id,
        product_id,
    )

    if variant_data["attributes"].get("is_default"):
        _clear_other_default_variants(
            product_id
        )

    try:
        _ensure_content_status_still_editable(
            vendor_id,
            product_id,
        )

        response = (
            supabase_admin
            .table("product_variants")
            .insert(variant_data)
            .execute()
        )

        rows = response.data or []

        if not rows:
            raise RuntimeError(
                "Product variant was not created."
            )

        return _normalize_variant(
            rows[0]
        )

    except Exception as exc:
        _raise_server_error(
            "Unable to create product variant",
            exc,
        )


# ============================================================
# PRODUCT VARIANTS — UPDATE
# ============================================================

def update_product_variant(
    vendor_id: str,
    variant_id: str,
    payload: dict,
) -> dict:
    variant, product = _get_owned_variant(
        vendor_id,
        variant_id,
    )

    _ensure_variant_update_allowed(
        product,
        payload,
    )

    update_data = {
        key: value
        for key, value in payload.items()
        if key in VARIANT_COLUMNS
        and value is not None
    }

    metadata_requested = any(
        field in payload
        and payload[field] is not None
        for field in VARIANT_METADATA_FIELDS
    )

    if metadata_requested:
        update_data["attributes"] = (
            _build_variant_attributes(
                payload,
                variant.get("attributes") or {},
            )
        )

    if "sku" in update_data:
        sku = str(
            update_data["sku"]
        ).strip()

        _ensure_unique_sku(
            sku,
            exclude_variant_id=variant_id,
        )

        update_data["sku"] = sku

    _validate_variant_values(
        update_data
    )

    if not update_data:
        return _normalize_variant(
            variant
        )

    product_id = product["id"]

    current_product = _get_owned_product(
        vendor_id,
        product_id,
    )

    _ensure_variant_update_allowed(
        current_product,
        payload,
    )

    if (
        metadata_requested
        and update_data.get("attributes", {}).get(
            "is_default"
        )
        and payload.get("is_default") is True
    ):
        _clear_other_default_variants(
            product_id,
            exclude_variant_id=variant_id,
        )

    try:
        response = (
            supabase_admin
            .table("product_variants")
            .update(update_data)
            .eq("id", variant_id)
            .eq("product_id", product_id)
            .execute()
        )

        rows = response.data or []

        if rows:
            return _normalize_variant(
                rows[0]
            )

        raise HTTPException(
            status_code=404,
            detail="Product variant was not updated.",
        )

    except Exception as exc:
        _raise_server_error(
            "Unable to update product variant",
            exc,
        )


# ============================================================
# PRODUCT VARIANTS — DEACTIVATE
# ============================================================

def delete_product_variant(
    vendor_id: str,
    variant_id: str,
) -> dict:
    variant, product = _get_owned_variant(
        vendor_id,
        variant_id,
    )

    _ensure_content_editable(product)

    product_id = product["id"]

    attributes = dict(
        variant.get("attributes") or {}
    )

    attributes["is_default"] = False

    try:
        _ensure_content_status_still_editable(
            vendor_id,
            product_id,
        )

        response = (
            supabase_admin
            .table("product_variants")
            .update({
                "is_active": False,
                "attributes": attributes,
            })
            .eq("id", variant_id)
            .eq("product_id", product_id)
            .execute()
        )

        if not response.data:
            raise HTTPException(
                status_code=404,
                detail="Product variant was not found.",
            )

        return {
            "message": (
                "Product variant deactivated successfully."
            ),
            "variant_id": variant["id"],
        }

    except Exception as exc:
        _raise_server_error(
            "Unable to deactivate product variant",
            exc,
        )


# ============================================================
# PRODUCTS — SUBMIT FOR APPROVAL
# ============================================================

def submit_vendor_product_for_approval(
    vendor_id: str,
    product_id: str,
) -> dict:
    """
    Submit a vendor-owned product for approval.

    Allowed status transitions:

        draft    -> pending
        rejected -> pending

    This function cannot activate or approve products.

    Product approval is performed separately
    by an authorized operator or future Admin Backend.
    """

    # --------------------------------------------------------
    # STEP 1 — VERIFY PRODUCT OWNERSHIP
    # --------------------------------------------------------

    product = _get_owned_product(
        vendor_id,
        product_id,
    )

    current_status = _product_status(product)

    if current_status not in {
        "draft",
        "rejected",
    }:
        raise HTTPException(
            status_code=409,
            detail=(
                "Only draft or rejected products "
                "can be submitted for approval."
            ),
        )

    # --------------------------------------------------------
    # STEP 2 — VALIDATE PRODUCT NAME
    # --------------------------------------------------------

    product_name = str(
        product.get("name") or ""
    ).strip()

    if not product_name:
        raise HTTPException(
            status_code=400,
            detail=(
                "Product name is required "
                "before submission."
            ),
        )

    # --------------------------------------------------------
    # STEP 3 — VALIDATE CATEGORY
    # --------------------------------------------------------

    _ensure_category_exists(
        product.get("category_id")
    )

    # --------------------------------------------------------
    # STEP 4 — VALIDATE DESCRIPTION
    # --------------------------------------------------------

    description = str(
        product.get("description") or ""
    ).strip()

    if not description:
        raise HTTPException(
            status_code=400,
            detail=(
                "Product description is required "
                "before submission."
            ),
        )

    # --------------------------------------------------------
    # STEP 5 — VALIDATE VARIANTS
    # --------------------------------------------------------

    try:
        variants_response = (
            supabase_admin
            .table("product_variants")
            .select(
                "id,sku,price,is_active"
            )
            .eq("product_id", product_id)
            .execute()
        )

        variants = variants_response.data or []

    except Exception as exc:
        _raise_server_error(
            "Unable to validate product variants",
            exc,
        )

    valid_variant_found = False

    for variant in variants:
        if variant.get("is_active") is not True:
            continue

        sku = str(
            variant.get("sku") or ""
        ).strip()

        if not sku:
            continue

        try:
            price = float(
                variant.get("price") or 0
            )
        except (ValueError, TypeError):
            continue

        if price > 0:
            valid_variant_found = True
            break

    if not valid_variant_found:
        raise HTTPException(
            status_code=400,
            detail=(
                "At least one active variant with "
                "a valid SKU and positive price "
                "is required before submission."
            ),
        )

    # --------------------------------------------------------
    # STEP 6 — VALIDATE PRODUCT IMAGES
    # --------------------------------------------------------

    try:
        images_response = (
            supabase_admin
            .table("product_images")
            .select("id,image_url")
            .eq("product_id", product_id)
            .execute()
        )

        images = images_response.data or []

    except Exception as exc:
        _raise_server_error(
            "Unable to validate product images",
            exc,
        )

    has_valid_image = any(
        str(
            image.get("image_url") or ""
        ).strip()
        for image in images
    )

    if not has_valid_image:
        raise HTTPException(
            status_code=400,
            detail=(
                "Upload at least one product image "
                "before submitting for approval."
            ),
        )

    # --------------------------------------------------------
    # STEP 7 — SUBMIT FOR APPROVAL
    # --------------------------------------------------------

    # Conditional update prevents a stale submission
    # request from overwriting another status transition.

    try:
        response = (
            supabase_admin
            .table("products")
            .update({
                "status": "pending",
            })
            .eq("id", product_id)
            .eq("vendor_id", vendor_id)
            .eq("status", current_status)
            .execute()
        )

        rows = response.data or []

        if not rows:
            raise HTTPException(
                status_code=409,
                detail=(
                    "Product status changed before "
                    "submission. Refresh and try again."
                ),
            )

        return {
            "message": (
                "Product submitted for approval."
            ),
            "product_id": product_id,
            "status": "pending",
            "product": rows[0],
        }

    except Exception as exc:
        _raise_server_error(
            "Unable to submit product for approval",
            exc,
        )
