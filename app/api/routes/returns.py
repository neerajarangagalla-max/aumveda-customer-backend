import logging
import time
from typing import Literal
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel, Field

from app.api.routes.orders import get_current_customer_id
from app.core.supabase import supabase

logger = logging.getLogger(__name__)
def execute_read_with_retry(query_factory, attempts=3):
    """
    Retry read-only Supabase queries after transient HTTP failures.
    Rebuild the query on each attempt.
    """
    for attempt in range(attempts):
        try:
            return query_factory().execute()

        except (httpx.TransportError, httpx.TimeoutException):
            if attempt == attempts - 1:
                raise

            delay = 0.5 * (2 ** attempt)
            logger.warning(
                "Supabase read failed; retrying in %.1f seconds "
                "(attempt %s/%s).",
                delay,
                attempt + 1,
                attempts,
            )
            time.sleep(delay)
router = APIRouter(
    prefix="/returns",
    tags=["Returns"],
)


class CreateReturnRequest(BaseModel):
    order_id: UUID
    order_item_id: UUID
    request_type: Literal["return", "replacement"] = "return"
    requested_quantity: int = Field(gt=0)
    reason: str | None = Field(default=None, max_length=200)
    description: str | None = Field(default=None, max_length=2000)


ACTIVE_RETURN_STATUSES = [
    "requested",
    "under_review",
    "approved",
    "pickup_scheduled",
    "item_received",
    "replacement_processing",
    "refund_processing",
]



@router.post("", status_code=status.HTTP_201_CREATED)
def create_return_request(
    payload: CreateReturnRequest,
    customer_id: str = Depends(get_current_customer_id),
):
    try:
        result = supabase.rpc(
            "create_customer_return_request",
            {
                "p_customer_id": str(customer_id),
                "p_order_id": str(payload.order_id),
                "p_order_item_id": str(payload.order_item_id),
                "p_request_type": payload.request_type,
                "p_requested_quantity": payload.requested_quantity,
                "p_reason": payload.reason,
                "p_description": payload.description,
            },
        ).execute()

        data = result.data if result else None

        if not isinstance(data, dict):
            logger.error("Unexpected response from create_customer_return_request.")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Unable to create return request.",
            )

        error_code = data.get("error")

        if error_code:
            error_statuses = {
                "order_not_found": status.HTTP_404_NOT_FOUND,
                "item_not_found": status.HTTP_404_NOT_FOUND,
                "order_not_delivered": status.HTTP_400_BAD_REQUEST,
                "item_not_delivered": status.HTTP_400_BAD_REQUEST,
                "invalid_quantity": status.HTTP_400_BAD_REQUEST,
                "invalid_request_type": status.HTTP_400_BAD_REQUEST,
                "quantity_exceeded": status.HTTP_400_BAD_REQUEST,
            }

            raise HTTPException(
                status_code=error_statuses.get(
                    error_code,
                    status.HTTP_500_INTERNAL_SERVER_ERROR,
                ),
                detail=data.get(
                    "message",
                    "Unable to create return request.",
                ),
            )

        return {
            "message": data.get(
                "message",
                "Return request submitted successfully.",
            ),
            "return_request": data.get("return_request"),
        }

    except HTTPException:
        raise

    except Exception as exc:
        logger.exception("Failed to create return request")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to create return request.",
        ) from exc

@router.get("")
def get_customer_return_requests(
    order_id: UUID | None = Query(default=None),
    customer_id: str = Depends(get_current_customer_id),
):
    try:
        query = (
            supabase.table("return_requests")
            .select("*", count="exact")
            .eq("customer_id", str(customer_id))
        )

        if order_id is not None:
            # Verify that the requested order belongs to this customer.
            order_result = execute_read_with_retry(
    lambda: (
        supabase.table("orders")
        .select("id")
        .eq("id", str(order_id))
        .eq("customer_id", str(customer_id))
        .limit(1)
    )
)

            if not order_result.data:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Order not found.",
                )

            query = query.eq("order_id", str(order_id))

        result = execute_read_with_retry(
            lambda: query.order("created_at", desc=True)
        )

        items = result.data or []

        return {
            "items": items,
            "total": result.count if result.count is not None else len(items),
        }

    except HTTPException:
        raise

    except Exception as exc:
        logger.exception("Failed to retrieve customer return requests")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to retrieve return requests.",
        ) from exc
