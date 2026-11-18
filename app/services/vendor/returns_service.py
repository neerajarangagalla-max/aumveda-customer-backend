import logging

from fastapi import HTTPException
from postgrest.exceptions import APIError

from app.core.supabase import supabase_admin


logger = logging.getLogger("aumveda.vendor.returns")


# ============================================================
# VENDOR-VISIBLE REQUEST STATUSES
# ============================================================

VISIBLE_STATUSES = (
    "approved",
    "pickup_scheduled",
    "item_received",
    "replacement_processing",
    "refund_processing",
    "completed",
)


# ============================================================
# HELPERS
# ============================================================

def _first(response):

    rows = response.data or []

    return rows[0] if rows else None


def _database_error(exc):

    logger.exception(
        "Vendor returns database operation failed"
    )

    if isinstance(exc, APIError):

        code = str(exc.code or "")

        if code == "23505":

            return HTTPException(
                status_code=409,
                detail="A duplicate record or AWB already exists.",
            )

        if code in {
            "P0001",
            "22023",
            "23514",
        }:

            return HTTPException(
                status_code=409,
                detail=(
                    "This action cannot be performed "
                    "in the current fulfillment state. "
                    "Check the request status, "
                    "replacement selection and stock."
                ),
            )

        if code == "P0002":

            return HTTPException(
                status_code=404,
                detail="Return request not found.",
            )

    return HTTPException(
        status_code=500,
        detail="Unable to process return operation.",
    )


# ============================================================
# VERIFY VENDOR OWNERSHIP
# ============================================================

def _get_owned_request(
    vendor_id: str,
    return_id: str,
) -> dict:

    response = (
        supabase_admin
        .table("return_requests")
        .select("*")
        .eq("id", return_id)
        .eq("vendor_id", vendor_id)
        .in_("status", list(VISIBLE_STATUSES))
        .limit(1)
        .execute()
    )

    request = _first(response)

    if not request:

        raise HTTPException(
            status_code=404,
            detail="Return request not found.",
        )

    return request


# ============================================================
# GET FULFILLMENT
# ============================================================

def _get_fulfillment(
    vendor_id: str,
    return_id: str,
):

    return _first(
        supabase_admin
        .table("return_fulfillments")
        .select("*")
        .eq("vendor_id", vendor_id)
        .eq("return_request_id", return_id)
        .limit(1)
        .execute()
    )


# ============================================================
# GET ORIGINAL ORDER ITEM
# ============================================================

def _get_original_item(
    vendor_id: str,
    request: dict,
):

    return _first(
        supabase_admin
        .table("order_items")
        .select(
            "id,order_id,product_id,"
            "variant_id,product_name,"
            "variant_name,sku,quantity,"
            "unit_price,total_price,status"
        )
        .eq("id", request["order_item_id"])
        .eq("order_id", request["order_id"])
        .eq("vendor_id", vendor_id)
        .limit(1)
        .execute()
    )


# ============================================================
# GET ASSOCIATED ORDER
# ============================================================

def _get_order(request: dict):

    return _first(
        supabase_admin
        .table("orders")
        .select(
            "id,order_number,shipping_address,"
            "status,created_at"
        )
        .eq("id", request["order_id"])
        .eq("customer_id", request["customer_id"])
        .limit(1)
        .execute()
    )


# ============================================================
# GET REPLACEMENT PRODUCT
# ============================================================

def _get_replacement(
    vendor_id: str,
    request: dict,
):

    if request["request_type"] != "replacement":

        return None

    product_id = request.get(
        "replacement_product_id"
    )

    variant_id = request.get(
        "replacement_variant_id"
    )

    if not product_id or not variant_id:

        return None

    product = _first(
        supabase_admin
        .table("products")
        .select("id,name,slug,status")
        .eq("id", product_id)
        .eq("vendor_id", vendor_id)
        .limit(1)
        .execute()
    )

    if not product:

        return None

    variant = _first(
        supabase_admin
        .table("product_variants")
        .select(
            "id,product_id,name,sku,"
            "price,stock_quantity,is_active"
        )
        .eq("id", variant_id)
        .eq("product_id", product_id)
        .limit(1)
        .execute()
    )

    if not variant:

        return None

    return {
        "product": product,
        "variant": variant,
    }


# ============================================================
# RESPONSE BUILDER
# ============================================================

def _build_response(
    vendor_id: str,
    request: dict,
) -> dict:

    original_item = _get_original_item(
        vendor_id,
        request,
    )

    if not original_item:

        raise HTTPException(
            status_code=409,
            detail="Return item ownership could not be verified.",
        )

    fulfillment = _get_fulfillment(
        vendor_id,
        request["id"],
    )

    order = _get_order(request)

    replacement = _get_replacement(
        vendor_id,
        request,
    )

    if fulfillment:

        fulfillment_status = (
            fulfillment["fulfillment_status"]
        )

    elif request["status"] == "completed":

        fulfillment_status = "completed"

    elif request["status"] == "approved":

        fulfillment_status = (
            "replacement_preparation"
            if request["request_type"] == "replacement"
            else "awaiting_pickup"
        )

    else:

        fulfillment_status = request["status"]

    return {
        **request,

        "display_request_type": (
            "exchange"
            if request["request_type"] == "replacement"
            else "return"
        ),

        "fulfillment_status": fulfillment_status,

        "original_item": original_item,

        "replacement": replacement,

        "replacement_selection_missing": (
            request["request_type"] == "replacement"
            and replacement is None
        ),

        "order": order,

        "fulfillment": fulfillment,
    }


# ============================================================
# LIST RETURNS AND EXCHANGES
# ============================================================

def list_vendor_returns(
    vendor_id: str,
    request_type: str | None = None,
    request_status: str | None = None,
    limit: int = 50,
    offset: int = 0,
):

    try:

        query = (
            supabase_admin
            .table("return_requests")
            .select("*", count="exact")
            .eq("vendor_id", vendor_id)
            .in_(
                "status",
                list(VISIBLE_STATUSES),
            )
        )

        if request_type:

            query = query.eq(
                "request_type",
                request_type,
            )

        if request_status:

            query = query.eq(
                "status",
                request_status,
            )

        response = (
            query
            .order("created_at", desc=True)
            .order("id", desc=True)
            .range(
                offset,
                offset + limit - 1,
            )
            .execute()
        )

        items = [
            _build_response(vendor_id, request)
            for request in response.data or []
        ]

        return {
            "items": items,
            "total": response.count or 0,
            "limit": limit,
            "offset": offset,
        }

    except HTTPException:

        raise

    except Exception as exc:

        raise _database_error(exc) from exc


# ============================================================
# RETURN DETAILS
# ============================================================

def get_vendor_return(
    vendor_id: str,
    return_id: str,
):

    try:

        request = _get_owned_request(
            vendor_id,
            return_id,
        )

        return _build_response(
            vendor_id,
            request,
        )

    except HTTPException:

        raise

    except Exception as exc:

        raise _database_error(exc) from exc


# ============================================================
# RETURN STATUS HISTORY
# ============================================================

def get_vendor_return_history(
    vendor_id: str,
    return_id: str,
):

    try:

        _get_owned_request(
            vendor_id,
            return_id,
        )

        response = (
            supabase_admin
            .table("return_status_history")
            .select(
                "id,previous_status,new_status,"
                "notes,created_at"
            )
            .eq("vendor_id", vendor_id)
            .eq("return_request_id", return_id)
            .order("created_at", desc=True)
            .execute()
        )

        return response.data or []

    except HTTPException:

        raise

    except Exception as exc:

        raise _database_error(exc) from exc


# ============================================================
# VALIDATE DATABASE OPERATION RESPONSE
# ============================================================

def _validate_rpc_result(
    function_name: str,
    vendor_id: str,
    return_id: str,
    params: dict,
    result,
) -> dict:

    # Support a single JSON object wrapped in a list.

    if (
        isinstance(result, list)
        and len(result) == 1
    ):

        result = result[0]

    if not isinstance(result, dict):

        logger.error(
            "Invalid RPC response: function=%s return_id=%s",
            function_name,
            return_id,
        )

        raise HTTPException(
            status_code=409,
            detail="Return operation was not confirmed.",
        )

    # Never accept an explicitly failed operation.

    if (
        result.get("error")
        or (
            "success" in result
            and result["success"] is not True
        )
    ):

        raise HTTPException(
            status_code=409,
            detail="Return operation was not confirmed.",
        )

    # Validate the returned request ID when supplied.

    returned_id = result.get("return_request_id")

    if (
        returned_id is not None
        and str(returned_id) != str(return_id)
    ):

        raise HTTPException(
            status_code=409,
            detail="Return operation response could not be verified.",
        )

    fulfillment = result.get("fulfillment")

    # Validate fulfillment ownership when supplied.

    if fulfillment is not None:

        if not isinstance(fulfillment, dict):

            raise HTTPException(
                status_code=409,
                detail="Invalid fulfillment response.",
            )

        if (
            str(fulfillment.get("return_request_id"))
            != str(return_id)
            or str(fulfillment.get("vendor_id"))
            != str(vendor_id)
        ):

            raise HTTPException(
                status_code=409,
                detail="Fulfillment ownership could not be verified.",
            )

    # --------------------------------------------------------
    # SCHEDULE PICKUP
    # --------------------------------------------------------

    if function_name == "vendor_schedule_return_pickup_atomic":

        confirmed = (
            returned_id is not None
            and result.get("status") == "pickup_scheduled"
            and bool(result.get("awb_number"))
            and isinstance(fulfillment, dict)
            and fulfillment.get("fulfillment_status")
                == "pickup_scheduled"
            and fulfillment.get("awb_number")
                == result.get("awb_number")
            and bool(fulfillment.get("pickup_scheduled_at"))
        )

    # --------------------------------------------------------
    # UPDATE RETURN FULFILLMENT
    # --------------------------------------------------------

    elif function_name == "vendor_update_return_fulfillment_atomic":

        expected_status = params.get("p_new_status")

        if isinstance(expected_status, str):

            expected_status = expected_status.strip().lower()

        confirmed = (
            returned_id is not None
            and bool(expected_status)
            and result.get("fulfillment_status")
                == expected_status
            and isinstance(fulfillment, dict)
            and fulfillment.get("fulfillment_status")
                == expected_status
        )

    # --------------------------------------------------------
    # PACK REPLACEMENT, REQUEST REFUND AND COMPLETE EXCHANGE
    # --------------------------------------------------------

    else:

        confirmed = result.get("success") is True

    if not confirmed:

        logger.error(
            "Unconfirmed RPC result: function=%s return_id=%s",
            function_name,
            return_id,
        )

        raise HTTPException(
            status_code=409,
            detail=(
                "Return operation could not be confirmed. "
                "Refresh the request before retrying."
            ),
        )

    # Normalize successful responses for the frontend.

    return {
        **result,
        "success": True,
    }


# ============================================================
# EXECUTE PROTECTED DATABASE FUNCTION
# ============================================================

def _execute_return_rpc(
    function_name: str,
    vendor_id: str,
    return_id: str,
    params: dict,
):

    try:

        # Verify the request belongs to the authenticated vendor.

        _get_owned_request(
            vendor_id,
            return_id,
        )

        response = (
            supabase_admin
            .rpc(
                function_name,
                {
                    "p_vendor_id": vendor_id,
                    "p_return_id": return_id,
                    **params,
                },
            )
            .execute()
        )

        result = _validate_rpc_result(
            function_name=function_name,
            vendor_id=vendor_id,
            return_id=return_id,
            params=params,
            result=response.data,
        )

        logger.info(
            "Vendor return operation completed: "
            "function=%s return_id=%s",
            function_name,
            return_id,
        )

        return result

    except HTTPException:

        raise

    except Exception as exc:

        raise _database_error(exc) from exc


# ============================================================
# RESERVE STOCK AND PACK REPLACEMENT
# ============================================================

def pack_vendor_replacement(
    vendor_id: str,
    return_id: str,
    notes: str | None = None,
):

    return _execute_return_rpc(
        "vendor_pack_replacement_atomic",
        vendor_id,
        return_id,
        {
            "p_vendor_notes": notes,
        },
    )


# ============================================================
# SCHEDULE PICKUP
# ============================================================

def schedule_vendor_return_pickup(
    vendor_id: str,
    return_id: str,
    payload: dict,
):

    return _execute_return_rpc(
        "vendor_schedule_return_pickup_atomic",
        vendor_id,
        return_id,
        {
            "p_pickup_scheduled_at": (
                payload["pickup_scheduled_at"]
            ),

            "p_courier_name": (
                payload["courier_name"]
            ),

            "p_awb_source": (
                payload["awb_source"]
            ),

            "p_awb_number": (
                payload.get("awb_number")
            ),

            "p_vendor_notes": (
                payload.get("vendor_notes")
            ),
        },
    )


# ============================================================
# UPDATE FULFILLMENT STATUS
# ============================================================

def update_vendor_return_status(
    vendor_id: str,
    return_id: str,
    new_status: str,
    notes: str | None = None,
):

    return _execute_return_rpc(
        "vendor_update_return_fulfillment_atomic",
        vendor_id,
        return_id,
        {
            "p_new_status": new_status,
            "p_notes": notes,
        },
    )


# ============================================================
# REQUEST REFUND PROCESSING
# ============================================================

def request_vendor_refund(
    vendor_id: str,
    return_id: str,
    notes: str | None = None,
):

    return _execute_return_rpc(
        "vendor_request_refund_atomic",
        vendor_id,
        return_id,
        {
            "p_notes": notes,
        },
    )


# ============================================================
# COMPLETE EXCHANGE
# ============================================================

def complete_vendor_exchange(
    vendor_id: str,
    return_id: str,
    notes: str | None = None,
):

    return _execute_return_rpc(
        "vendor_complete_exchange_atomic",
        vendor_id,
        return_id,
        {
            "p_notes": notes,
        },
    )