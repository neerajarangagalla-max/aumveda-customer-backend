import logging

from fastapi import APIRouter, Depends, HTTPException

from app.core.security import get_current_user

from app.schemas.address import (
    AddressCreate,
    AddressUpdate,
)

from app.services.address_service import (
    get_addresses,
    get_address,
    create_address,
    update_address,
    delete_address,
)

router = APIRouter(
    prefix="/addresses",
    tags=["Addresses"],
)

logger = logging.getLogger(__name__)


@router.get("")
async def list_addresses(
    user=Depends(get_current_user),
):
    try:
        data = get_addresses(user.id)

        return {
            "status": "success",
            "count": len(data),
            "data": data,
        }

    except Exception:
        logger.exception(
            "Address retrieval failed"
        )

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
        data = get_address(
            user.id,
            address_id,
        )

        if not data:
            raise HTTPException(
                status_code=404,
                detail="Address not found.",
            )

        return {
            "status": "success",
            "data": data,
        }

    except HTTPException:
        raise

    except Exception:
        logger.exception(
            "Address lookup failed"
        )

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
        data = create_address(
            user.id,
            payload.model_dump(),
        )

        if not data:
            raise HTTPException(
                status_code=500,
                detail="Unable to create address.",
            )

        return {
            "status": "success",
            "data": data,
        }

    except HTTPException:
        raise

    except Exception:
        logger.exception(
            "Address creation failed"
        )

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
        data = update_address(
            user.id,
            address_id,
            payload.model_dump(),
        )

        if not data:
            raise HTTPException(
                status_code=404,
                detail="Address not found.",
            )

        return {
            "status": "success",
            "data": data,
        }

    except HTTPException:
        raise

    except Exception:
        logger.exception(
            "Address update failed"
        )

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
        deleted = delete_address(
            user.id,
            address_id,
        )

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
        logger.exception(
            "Address deletion failed"
        )

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
        data = update_address(
            user.id,
            address_id,
            {"is_default": True},
        )

        if not data:
            raise HTTPException(
                status_code=404,
                detail="Address not found.",
            )

        return {
            "status": "success",
            "data": data,
        }

    except HTTPException:
        raise

    except Exception as e:
        logger.exception("Address creation failed")

    raise HTTPException(
        status_code=500,
        detail=str(e),
    )