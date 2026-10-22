
import logging

from fastapi import APIRouter, Depends, HTTPException

from app.core.security import get_current_user
from app.core.supabase import supabase_admin
from app.schemas.address import AddressCreate, AddressUpdate

router = APIRouter(
    prefix="/addresses",
    tags=["Addresses"],
)

logger = logging.getLogger(__name__)

ADDRESS_TABLE = "customer_addresses"


def _get_addresses(user_id: str):
    response = (
        supabase_admin
        .table(ADDRESS_TABLE)
        .select("*")
        .eq("customer_id", user_id)
        .order("is_default", desc=True)
        .order("created_at", desc=True)
        .execute()
    )
    return response.data or []


def _get_address(user_id: str, address_id: str):
    response = (
        supabase_admin
        .table(ADDRESS_TABLE)
        .select("*")
        .eq("id", address_id)
        .eq("customer_id", user_id)
        .limit(1)
        .execute()
    )
    data = response.data or []
    return data[0] if data else None


def _create_address(user_id: str, payload: dict):
    is_default = payload.get("is_default", False)

    existing = _get_addresses(user_id)

    # The first address becomes the default automatically.
    if not existing:
        is_default = True

    # Clear the previous default before setting a new one.
    if is_default:
        (
            supabase_admin
            .table(ADDRESS_TABLE)
            .update({"is_default": False})
            .eq("customer_id", user_id)
            .execute()
        )

    address_payload = {
        "customer_id": user_id,
        "label": payload.get("label"),
        "recipient_name": payload["recipient_name"],
        "phone": payload["phone"],
        "address_line1": payload["address_line1"],
        "address_line2": payload.get("address_line2"),
        "city": payload["city"],
        "state": payload["state"],
        "postal_code": payload["postal_code"],
        "country": payload.get("country", "India"),
        "is_default": is_default,
    }

    response = (
        supabase_admin
        .table(ADDRESS_TABLE)
        .insert(address_payload)
        .execute()
    )

    data = response.data or []
    return data[0] if data else None


def _update_address(
    user_id: str,
    address_id: str,
    payload: dict,
):
    existing = _get_address(user_id, address_id)

    if not existing:
        return None

    clean_payload = {
        key: value
        for key, value in payload.items()
        if value is not None
    }

    if clean_payload.get("is_default") is True:
        (
            supabase_admin
            .table(ADDRESS_TABLE)
            .update({"is_default": False})
            .eq("customer_id", user_id)
            .execute()
        )

    if not clean_payload:
        return existing

    response = (
        supabase_admin
        .table(ADDRESS_TABLE)
        .update(clean_payload)
        .eq("id", address_id)
        .eq("customer_id", user_id)
        .execute()
    )

    data = response.data or []

    return data[0] if data else _get_address(
        user_id,
        address_id,
    )


def _delete_address(user_id: str, address_id: str):
    existing = _get_address(user_id, address_id)

    if not existing:
        return False

    was_default = existing.get("is_default", False)

    (
        supabase_admin
        .table(ADDRESS_TABLE)
        .delete()
        .eq("id", address_id)
        .eq("customer_id", user_id)
        .execute()
    )

    # Promote the next address if the default was deleted.
    if was_default:
        remaining = _get_addresses(user_id)

        if remaining:
            (
                supabase_admin
                .table(ADDRESS_TABLE)
                .update({"is_default": True})
                .eq("id", remaining[0]["id"])
                .eq("customer_id", user_id)
                .execute()
            )

    return True


@router.get("")
async def list_addresses(user=Depends(get_current_user)):
    try:
        data = _get_addresses(user.id)
        return {
            "status": "success",
            "count": len(data),
            "data": data,
        }
    except Exception:
        logger.exception("Address retrieval failed")
        raise HTTPException(
            status_code=500,
            detail="Unable to retrieve addresses.",
        )


@router.get("/{address_id}")
async def get_single_address(
    address_id: str,
    user=Depends(get_current_user),
):
    try:
        data = _get_address(user.id, address_id)

        if not data:
            raise HTTPException(
                status_code=404,
                detail="Address not found.",
            )

        return {"status": "success", "data": data}

    except HTTPException:
        raise
    except Exception:
        logger.exception("Address lookup failed")
        raise HTTPException(
            status_code=500,
            detail="Unable to retrieve address.",
        )


@router.post("")
async def create_address_route(
    payload: AddressCreate,
    user=Depends(get_current_user),
):
    try:
        data = _create_address(
            user.id,
            payload.model_dump(),
        )

        if not data:
            raise HTTPException(
                status_code=500,
                detail="Unable to create address.",
            )

        return {"status": "success", "data": data}

    except HTTPException:
        raise
    except Exception:
        logger.exception("Address creation failed")
        raise HTTPException(
            status_code=500,
            detail="Unable to create address.",
        )


@router.patch("/{address_id}")
async def update_address_route(
    address_id: str,
    payload: AddressUpdate,
    user=Depends(get_current_user),
):
    try:
        data = _update_address(
            user.id,
            address_id,
            payload.model_dump(),
        )

        if not data:
            raise HTTPException(
                status_code=404,
                detail="Address not found.",
            )

        return {"status": "success", "data": data}

    except HTTPException:
        raise
    except Exception:
        logger.exception("Address update failed")
        raise HTTPException(
            status_code=500,
            detail="Unable to update address.",
        )


@router.delete("/{address_id}")
async def delete_address_route(
    address_id: str,
    user=Depends(get_current_user),
):
    try:
        deleted = _delete_address(user.id, address_id)

        if not deleted:
            raise HTTPException(
                status_code=404,
                detail="Address not found.",
            )

        return {
            "status": "success",
            "message": "Address deleted successfully.",
        }

    except HTTPException:
        raise
    except Exception:
        logger.exception("Address deletion failed")
        raise HTTPException(
            status_code=500,
            detail="Unable to delete address.",
        )


@router.patch("/{address_id}/default")
async def set_default_address(
    address_id: str,
    user=Depends(get_current_user),
):
    try:
        data = _update_address(
            user.id,
            address_id,
            {"is_default": True},
        )

        if not data:
            raise HTTPException(
                status_code=404,
                detail="Address not found.",
            )

        return {"status": "success", "data": data}

    except HTTPException:
        raise
    except Exception:
        logger.exception("Setting default address failed")
        raise HTTPException(
            status_code=500,
            detail="Unable to set default address.",
        )
