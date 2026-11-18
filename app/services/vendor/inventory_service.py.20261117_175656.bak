
from fastapi import HTTPException, status

from app.core.supabase import supabase_admin


# ============================================================
# HELPERS
# ============================================================

def _attributes(variant: dict) -> dict:
    value = variant.get("attributes")
    return dict(value) if isinstance(value, dict) else {}


def _threshold(variant: dict) -> int:
    value = _attributes(variant).get(
        "low_stock_threshold",
        0,
    )

    try:
        return max(0, int(value))
    except (ValueError, TypeError):
        return 0


def _stock_status(stock: int, threshold: int) -> str:
    if stock <= 0:
        return "out_of_stock"

    if stock <= threshold:
        return "low_stock"

    return "in_stock"


def _get_owned_variant(
    vendor_id: str,
    variant_id: str,
) -> tuple[dict, dict]:

    try:
        variant_response = (
            supabase_admin
            .table("product_variants")
            .select("*")
            .eq("id", variant_id)
            .limit(1)
            .execute()
        )

        variants = variant_response.data or []

        if not variants:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Inventory item not found.",
            )

        variant = variants[0]

        product_response = (
            supabase_admin
            .table("products")
            .select("id,vendor_id,name,slug,status")
            .eq("id", variant["product_id"])
            .eq("vendor_id", vendor_id)
            .limit(1)
            .execute()
        )

        products = product_response.data or []

        if not products:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Inventory item not found.",
            )

        return variant, products[0]

    except HTTPException:
        raise

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Unable to load inventory item: {exc}",
        )


def _build_inventory_item(
    variant: dict,
    product: dict,
) -> dict:

    attributes = _attributes(variant)

    stock = int(
        variant.get("stock_quantity") or 0
    )

    threshold = _threshold(variant)

    return {
        "variant_id": variant["id"],
        "product_id": product["id"],
        "product_name": product.get("name"),
        "product_slug": product.get("slug"),
        "product_status": product.get("status"),

        "variant_name": variant.get("name"),
        "sku": variant.get("sku"),
        "size_value": (
            variant.get("size_value")
            if variant.get("size_value") is not None
            else attributes.get("size_value")
        ),
        "size_unit": (
            variant.get("size_unit")
            or attributes.get("size_unit")
        ),

        "price": variant.get("price"),
        "stock_quantity": stock,
        "low_stock_threshold": threshold,

        "is_low_stock": (
            0 < stock <= threshold
        ),
        "is_out_of_stock": stock == 0,
        "stock_status": _stock_status(
            stock,
            threshold,
        ),

        "is_default": (
            variant.get("is_default")
            if variant.get("is_default") is not None
            else attributes.get("is_default", False)
        ),
        "is_active": variant.get(
            "is_active",
            True,
        ),

        "created_at": variant.get("created_at"),
        "updated_at": variant.get("updated_at"),
    }


# ============================================================
# INVENTORY LIST
# ============================================================

def list_vendor_inventory(
    vendor_id: str,
) -> list[dict]:

    try:
        product_response = (
            supabase_admin
            .table("products")
            .select("id,name,slug,status")
            .eq("vendor_id", vendor_id)
            .order("created_at", desc=True)
            .execute()
        )

        products = product_response.data or []

        inventory = []

        for product in products:
            variant_response = (
                supabase_admin
                .table("product_variants")
                .select("*")
                .eq("product_id", product["id"])
                .order("created_at", desc=False)
                .execute()
            )

            for variant in variant_response.data or []:
                inventory.append(
                    _build_inventory_item(
                        variant=variant,
                        product=product,
                    )
                )

        return inventory

    except HTTPException:
        raise

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Unable to load inventory: {exc}",
        )


# ============================================================
# LOW STOCK
# ============================================================

def list_low_stock_inventory(
    vendor_id: str,
) -> list[dict]:

    inventory = list_vendor_inventory(
        vendor_id
    )

    return [
        item
        for item in inventory
        if (
            item["is_low_stock"]
            or item["is_out_of_stock"]
        )
    ]


# ============================================================
# INVENTORY DETAIL
# ============================================================

def get_inventory_item(
    vendor_id: str,
    variant_id: str,
) -> dict:

    variant, product = _get_owned_variant(
        vendor_id=vendor_id,
        variant_id=variant_id,
    )

    return _build_inventory_item(
        variant,
        product,
    )


# ============================================================
# INVENTORY HISTORY
# ============================================================

def get_inventory_history(
    vendor_id: str,
    variant_id: str,
) -> list[dict]:

    _get_owned_variant(
        vendor_id=vendor_id,
        variant_id=variant_id,
    )

    try:
        response = (
            supabase_admin
            .table("inventory_transactions")
            .select(
                "id,variant_id,vendor_id,"
                "transaction_type,quantity_delta,"
                "reference_type,reference_id,"
                "notes,created_at"
            )
            .eq("vendor_id", vendor_id)
            .eq("variant_id", variant_id)
            .order("created_at", desc=True)
            .execute()
        )

        return response.data or []

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Unable to load inventory history: {exc}",
        )


# ============================================================
# UPDATE INVENTORY
# ============================================================

def update_inventory_item(
    vendor_id: str,
    variant_id: str,
    payload: dict,
) -> dict:

    variant, product = _get_owned_variant(
        vendor_id=vendor_id,
        variant_id=variant_id,
    )

    current_stock = int(
        variant.get("stock_quantity") or 0
    )

    operation = payload.get("operation")
    quantity = payload.get("quantity")

    # --------------------------------------------------------
    # VALIDATE INPUT
    # --------------------------------------------------------

    if operation not in {"set", "increase", "decrease"}:
        raise HTTPException(
            status_code=400,
            detail="Invalid inventory operation.",
        )

    if (
        isinstance(quantity, bool)
        or not isinstance(quantity, int)
        or quantity < 0
    ):
        raise HTTPException(
            status_code=400,
            detail="Quantity must be a non-negative whole number.",
        )

    if operation != "set" and quantity == 0:
        raise HTTPException(
            status_code=400,
            detail="Enter a quantity greater than zero.",
        )

    # --------------------------------------------------------
    # CALCULATE NEW STOCK
    # --------------------------------------------------------

    if operation == "set":
        new_stock = quantity

    elif operation == "increase":
        new_stock = current_stock + quantity

    else:
        if quantity > current_stock:
            raise HTTPException(
                status_code=400,
                detail="Stock cannot be reduced below zero.",
            )

        new_stock = current_stock - quantity

    delta = new_stock - current_stock

    # --------------------------------------------------------
    # LOW-STOCK THRESHOLD
    # --------------------------------------------------------

    attributes = _attributes(variant)

    requested_threshold = payload.get(
        "low_stock_threshold"
    )

    if requested_threshold is not None:
        if (
            isinstance(requested_threshold, bool)
            or not isinstance(requested_threshold, int)
            or requested_threshold < 0
        ):
            raise HTTPException(
                status_code=400,
                detail="Invalid low-stock alert level.",
            )

        attributes["low_stock_threshold"] = (
            requested_threshold
        )

    # --------------------------------------------------------
    # WRITE TO PRODUCT_VARIANTS
    # --------------------------------------------------------

    update_data = {
        "stock_quantity": new_stock,
    }

    if requested_threshold is not None:
        update_data["attributes"] = attributes

    try:
        response = (
            supabase_admin
            .table("product_variants")
            .update(update_data)
            .eq("id", variant_id)
            .eq("product_id", product["id"])
            .eq("stock_quantity", current_stock)
            .execute()
        )

        rows = response.data or []

        if not rows:
            raise HTTPException(
                status_code=409,
                detail=(
                    "Inventory was changed by another operation. "
                    "Refresh and try again."
                ),
            )

        updated_variant = rows[0]

    except HTTPException:
        raise

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Unable to update inventory: {exc}",
        )

    final_stock = int(
        updated_variant.get("stock_quantity") or 0
    )

    final_threshold = _threshold(updated_variant)

    # --------------------------------------------------------
    # INVENTORY TRANSACTION HISTORY
    # --------------------------------------------------------

    transaction = None
    history_warning = None

    if delta != 0:

        # Supabase only permits:
        # opening, restock, sale, return,
        # adjustment and damage.
        transaction_type = (
            "restock"
            if delta > 0
            else "adjustment"
        )

        transaction_data = {
            "variant_id": variant_id,
            "vendor_id": vendor_id,

            "transaction_type": transaction_type,
            "quantity_delta": delta,

            "reference_type": "vendor_adjustment",
            "reference_id": None,

            "notes": (
                f"Vendor performed '{operation}' operation. "
                f"Previous stock: {current_stock}. "
                f"Updated stock: {final_stock}."
            ),
        }

        try:
            transaction_response = (
                supabase_admin
                .table("inventory_transactions")
                .insert(transaction_data)
                .execute()
            )

            records = transaction_response.data or []

            if records:
                transaction = records[0]
            else:
                history_warning = (
                    "Stock was saved, but the history "
                    "record could not be confirmed."
                )

        except Exception:
            # Do not misreport a successful stock update
            # as a failed one if only audit logging fails.
            history_warning = (
                "Stock was updated, but the inventory "
                "history record could not be saved."
            )

    # --------------------------------------------------------
    # FINAL RESPONSE
    # --------------------------------------------------------

    return {
        "message": "Inventory updated successfully.",

        "product": {
            "id": product["id"],
            "name": product.get("name"),
        },

        "variant_id": variant_id,
        "operation": operation,

        "previous_stock": current_stock,
        "quantity_delta": delta,
        "new_stock": final_stock,

        "low_stock_threshold": final_threshold,

        "is_low_stock": (
            0 < final_stock <= final_threshold
        ),
        "is_out_of_stock": final_stock == 0,
        "stock_status": _stock_status(
            final_stock,
            final_threshold,
        ),

        "requires_admin_approval": False,

        "transaction": transaction,
        "history_warning": history_warning,
    }
