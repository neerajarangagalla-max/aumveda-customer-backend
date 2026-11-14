import logging
import re
import secrets
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, EmailStr, Field

from app.core.security import get_current_admin
from app.core.supabase import supabase, supabase_admin


router = APIRouter(
    prefix="/admin/vendors",
    tags=["Admin Vendors"],
    dependencies=[Depends(get_current_admin)],
)

VendorStatus = Literal[
    "approved",
    "rejected",
    "suspended",
    "pending",
]

logger = logging.getLogger(__name__)


# ============================================================
# CREATE VENDOR REQUEST
# ============================================================

class CreateVendorRequest(BaseModel):
    business_name: str = Field(
        ...,
        min_length=1,
        max_length=255,
    )

    email: EmailStr

    phone: str = Field(
        ...,
        min_length=5,
        max_length=50,
    )

    password: str = Field(
        ...,
        min_length=6,
        max_length=100,
    )

    legal_name: str | None = Field(
        default=None,
        max_length=255,
    )

    description: str | None = None

    address_line1: str | None = Field(
        default=None,
        max_length=255,
    )

    address_line2: str | None = Field(
        default=None,
        max_length=255,
    )

    city: str | None = Field(
        default=None,
        max_length=100,
    )

    state: str | None = Field(
        default=None,
        max_length=100,
    )

    postal_code: str | None = Field(
        default=None,
        max_length=20,
    )

    country: str = Field(
        default="India",
        max_length=100,
    )

    commission_rate: float = Field(
        default=0,
        ge=0,
        le=100,
    )


# ============================================================
# HELPERS
# ============================================================

def generate_vendor_slug(
    business_name: str,
) -> str:

    base_slug = re.sub(
        r"[^a-z0-9]+",
        "-",
        business_name.lower().strip(),
    ).strip("-")

    return f"{base_slug}-{secrets.token_hex(4)}"


def rollback_vendor_creation(
    vendor_id: str | None,
    auth_user_id: str | None,
) -> None:

    if vendor_id and auth_user_id:
        try:
            (
                supabase_admin
                .table("vendor_members")
                .delete()
                .eq("vendor_id", vendor_id)
                .eq("user_id", auth_user_id)
                .execute()
            )

        except Exception:
            logger.exception(
                "Failed to remove vendor membership during rollback"
            )

    if vendor_id:
        try:
            (
                supabase_admin
                .table("vendors")
                .delete()
                .eq("id", vendor_id)
                .execute()
            )

        except Exception:
            logger.exception(
                "Failed to remove vendor during rollback"
            )

    if auth_user_id:
        try:
            supabase_admin.auth.admin.delete_user(
                auth_user_id
            )

        except Exception:
            logger.exception(
                "Failed to remove Auth user during rollback"
            )


def database_error(
    exc: Exception,
) -> HTTPException:

    message = str(exc).lower()

    if "invalid input syntax" in message:
        return HTTPException(
            status_code=400,
            detail="Invalid vendor ID or input",
        )

    if (
        "duplicate key" in message
        or "unique constraint" in message
    ):
        return HTTPException(
            status_code=409,
            detail="A conflicting vendor record exists",
        )

    logger.exception(
        "Vendor database operation failed",
        exc_info=exc,
    )

    return HTTPException(
        status_code=500,
        detail="Vendor operation failed",
    )


# ============================================================
# CREATE VENDOR
# ============================================================

@router.post("/create")
def create_vendor(
    payload: CreateVendorRequest,
    current_admin=Depends(get_current_admin),
):

    vendor_id = None
    auth_user_id = None
    created_auth_user = False

    try:

        email = str(
            payload.email
        ).lower().strip()

        # ----------------------------------------------------
        # 1. CHECK EXISTING VENDOR
        # ----------------------------------------------------

        existing_vendor = (
            supabase_admin
            .table("vendors")
            .select("id")
            .eq("email", email)
            .limit(1)
            .execute()
        )

        if existing_vendor.data:

            raise HTTPException(
                status_code=409,
                detail=(
                    "A vendor with this email already exists."
                ),
            )

        # ----------------------------------------------------
        # 2. FIND EXISTING AUTH USER
        # ----------------------------------------------------

        existing_auth_user = None

        try:

            page = 1
            per_page = 1000

            while True:

                users_response = (
                    supabase_admin
                    .auth
                    .admin
                    .list_users(
                        page=page,
                        per_page=per_page,
                    )
                )

                if isinstance(
                    users_response,
                    list,
                ):
                    users = users_response
                else:
                    users = (
                        getattr(
                            users_response,
                            "users",
                            None,
                        )
                        or []
                    )

                for user in users:

                    user_email = (
                        getattr(
                            user,
                            "email",
                            None,
                        )
                        or ""
                    ).lower().strip()

                    if user_email == email:

                        existing_auth_user = user
                        break

                if (
                    existing_auth_user
                    or len(users) < per_page
                ):
                    break

                page += 1

        except Exception as exc:

            logger.exception(
                "Failed to search existing Auth users"
            )

            raise HTTPException(
                status_code=500,
                detail=(
                    "Unable to verify the existing account."
                ),
            ) from exc

        # ----------------------------------------------------
        # 3. REUSE EXISTING AUTH USER
        # ----------------------------------------------------

        if existing_auth_user:

            auth_user_id = str(
                existing_auth_user.id
            )

        # ----------------------------------------------------
        # 4. CREATE AUTH USER IF NEEDED
        # ----------------------------------------------------

        else:

            try:

                auth_response = (
                    supabase_admin
                    .auth
                    .admin
                    .create_user(
                        {
                            "email": email,
                            "password": payload.password,
                            "email_confirm": True,
                            "user_metadata": {
                                "role": "vendor",
                                "full_name": (
                                    payload.business_name.strip()
                                ),
                            },
                        }
                    )
                )

                auth_user = getattr(
                    auth_response,
                    "user",
                    None,
                )

                if not auth_user:

                    raise HTTPException(
                        status_code=500,
                        detail=(
                            "Unable to create the vendor account."
                        ),
                    )

                auth_user_id = str(
                    auth_user.id
                )

                created_auth_user = True

            except Exception as exc:

                error_message = str(exc).lower()

                if (
                    "already registered"
                    in error_message
                    or "already exists"
                    in error_message
                    or "duplicate key"
                    in error_message
                    or "unique constraint"
                    in error_message
                ):

                    existing_auth_user = None

                    try:

                        page = 1
                        per_page = 1000

                        while True:

                            users_response = (
                                supabase_admin
                                .auth
                                .admin
                                .list_users(
                                    page=page,
                                    per_page=per_page,
                                )
                            )

                            if isinstance(
                                users_response,
                                list,
                            ):
                                users = users_response
                            else:
                                users = (
                                    getattr(
                                        users_response,
                                        "users",
                                        None,
                                    )
                                    or []
                                )

                            for user in users:

                                user_email = (
                                    getattr(
                                        user,
                                        "email",
                                        None,
                                    )
                                    or ""
                                ).lower().strip()

                                if user_email == email:

                                    existing_auth_user = user
                                    break

                            if (
                                existing_auth_user
                                or len(users) < per_page
                            ):
                                break

                            page += 1

                    except Exception as lookup_exc:

                        logger.exception(
                            "Failed to find existing Auth user"
                        )

                        raise HTTPException(
                            status_code=500,
                            detail=(
                                "The email already exists, "
                                "but the existing account "
                                "could not be located."
                            ),
                        ) from lookup_exc

                    if existing_auth_user:

                        auth_user_id = str(
                            existing_auth_user.id
                        )

                        created_auth_user = False

                    else:

                        raise HTTPException(
                            status_code=409,
                            detail=(
                                "The email already exists in "
                                "Auth, but the existing account "
                                "could not be found."
                            ),
                        ) from exc

                else:
                    raise

        # ----------------------------------------------------
        # 5. PROFILE
        # ----------------------------------------------------

        if created_auth_user:

            profile_result = (
                supabase_admin
                .table("profiles")
                .update(
                    {
                        "role": "vendor",
                        "full_name": (
                            payload.business_name.strip()
                        ),
                    }
                )
                .eq("id", auth_user_id)
                .select("id")
                .execute()
            )

            if not profile_result.data:

                raise HTTPException(
                    status_code=500,
                    detail=(
                        "Unable to set up the vendor profile."
                    ),
                )

        # ----------------------------------------------------
        # 6. CREATE VENDOR
        # ----------------------------------------------------

        vendor_data = payload.model_dump(
            exclude={"password"},
            exclude_none=True,
        )

        vendor_data.update(
            {
                "email": email,
                "status": "approved",
                "slug": generate_vendor_slug(
                    payload.business_name
                ),
            }
        )

        vendor_result = (
            supabase_admin
            .table("vendors")
            .insert(vendor_data)
            .select("*")
            .execute()
        )

        if not vendor_result.data:

            raise HTTPException(
                status_code=500,
                detail=(
                    "Unable to create the vendor record."
                ),
            )

        vendor_record = vendor_result.data[0]

        vendor_id = str(
            vendor_record["id"]
        )

        # ----------------------------------------------------
        # 7. CREATE OWNER MEMBERSHIP
        # ----------------------------------------------------

        membership_result = (
            supabase_admin
            .table("vendor_members")
            .insert(
                {
                    "user_id": auth_user_id,
                    "vendor_id": vendor_id,
                    "member_role": "owner",
                    "is_active": True,
                    "permission_mode": "legacy",
                }
            )
            .select("vendor_id")
            .execute()
        )

        if not membership_result.data:

            raise HTTPException(
                status_code=500,
                detail=(
                    "Unable to link the vendor account."
                ),
            )

        return {
            "message": "Vendor created successfully",
            "vendor": vendor_record,
        }

    except HTTPException:

        if vendor_id:

            rollback_vendor_creation(
                vendor_id,
                (
                    auth_user_id
                    if created_auth_user
                    else None
                ),
            )

        elif (
            created_auth_user
            and auth_user_id
        ):

            rollback_vendor_creation(
                None,
                auth_user_id,
            )

        raise

    except Exception as exc:

        logger.exception(
            "CREATE VENDOR FAILED"
        )

        if vendor_id:

            rollback_vendor_creation(
                vendor_id,
                (
                    auth_user_id
                    if created_auth_user
                    else None
                ),
            )

        elif (
            created_auth_user
            and auth_user_id
        ):

            rollback_vendor_creation(
                None,
                auth_user_id,
            )

        raise database_error(exc) from exc


# ============================================================
# LIST VENDORS
# ============================================================

@router.get("")
def list_vendors(
    status_filter: VendorStatus | None = Query(
        default=None,
        alias="status",
    ),
    search: str | None = Query(
        default=None,
        max_length=100,
    ),
    limit: int = Query(
        default=50,
        ge=1,
        le=100,
    ),
    offset: int = Query(
        default=0,
        ge=0,
    ),
):

    try:

        query = (
            supabase_admin
            .table("vendors")
            .select(
                "*",
                count="exact",
            )
        )

        if status_filter:

            query = query.eq(
                "status",
                status_filter,
            )

        if search and search.strip():

            term = (
                search.strip()
                .replace("\\", "\\\\")
                .replace("%", "\\%")
                .replace("_", "\\_")
                .replace(",", "")
                .replace("(", "")
                .replace(")", "")
            )

            if term:

                query = query.or_(
                    f"business_name.ilike.%{term}%,"
                    f"legal_name.ilike.%{term}%,"
                    f"email.ilike.%{term}%"
                )

        result = (
            query
            .order(
                "created_at",
                desc=True,
            )
            .range(
                offset,
                offset + limit - 1,
            )
            .execute()
        )

        # Global summary counts are returned with every vendor-list
        # response so the Admin Web does not need another service method.
        all_vendors_result = (
            supabase_admin
            .table("vendors")
            .select("status")
            .execute()
        )

        all_vendors = all_vendors_result.data or []

        pending_profile_result = (
            supabase_admin
            .table("vendor_profile_change_requests")
            .select("id")
            .eq("status", "pending")
            .execute()
        )

        pending_branding_result = (
            supabase_admin
            .table("vendor_branding_requests")
            .select("id")
            .eq("status", "pending")
            .execute()
        )

        return {
            "items": result.data or [],
            "total": result.count or 0,
            "limit": limit,
            "offset": offset,
            "summary": {
                "total_vendors": len(all_vendors),
                "pending_vendors": sum(
                    1
                    for vendor in all_vendors
                    if str(vendor.get("status", "")).lower() == "pending"
                ),
                "approved_vendors": sum(
                    1
                    for vendor in all_vendors
                    if str(vendor.get("status", "")).lower() == "approved"
                ),
                "notifications": (
                    len(pending_profile_result.data or [])
                    + len(pending_branding_result.data or [])
                ),
            },
        }

    except Exception as exc:

        logger.exception(
            "LIST VENDORS FAILED"
        )

        raise HTTPException(
            status_code=500,
            detail="Unable to retrieve vendors",
        ) from exc


# ============================================================
# VENDOR DETAILS
#
# GET /admin/vendors/{vendor_id}
#
# Returns:
# - Vendor business information
# - Products
# - Team members
# - Orders
# - Earnings
# - Ledger
# - Payouts
# - Branding requests
# - Profile change requests
# ============================================================

@router.get("/summary")
def get_vendor_summary():
    """Return vendor overview counts for the admin Vendors page.

    Notifications represent vendor-level requests that require admin
    attention. Product activity is intentionally handled inside the
    individual vendor details page.
    """
    try:
        vendors_result = (
            supabase_admin
            .table("vendors")
            .select("status", count="exact")
            .execute()
        )

        vendors = vendors_result.data or []

        total_vendors = len(vendors)
        pending_vendors = sum(
            1 for vendor in vendors
            if str(vendor.get("status", "")).lower() == "pending"
        )
        approved_vendors = sum(
            1 for vendor in vendors
            if str(vendor.get("status", "")).lower() == "approved"
        )

        profile_requests_result = (
            supabase_admin
            .table("vendor_profile_change_requests")
            .select("id", count="exact")
            .eq("status", "pending")
            .execute()
        )

        branding_requests_result = (
            supabase_admin
            .table("vendor_branding_requests")
            .select("id", count="exact")
            .eq("status", "pending")
            .execute()
        )

        pending_profile_requests = (
            profile_requests_result.count
            if profile_requests_result.count is not None
            else len(profile_requests_result.data or [])
        )

        pending_branding_requests = (
            branding_requests_result.count
            if branding_requests_result.count is not None
            else len(branding_requests_result.data or [])
        )

        return {
            "total_vendors": total_vendors,
            "pending_vendors": pending_vendors,
            "approved_vendors": approved_vendors,
            "notifications": (
                pending_profile_requests
                + pending_branding_requests
            ),
            "pending_profile_requests": pending_profile_requests,
            "pending_branding_requests": pending_branding_requests,
        }

    except Exception as exc:
        logger.exception("GET VENDOR SUMMARY FAILED")
        raise database_error(exc) from exc


@router.get("/{vendor_id}")
def get_vendor(
    vendor_id: UUID,
):

    vendor_id = str(vendor_id)

    try:

        # ====================================================
        # 1. VENDOR
        # ====================================================

        vendor_result = (
            supabase_admin
            .table("vendors")
            .select("*")
            .eq("id", vendor_id)
            .limit(1)
            .execute()
        )

        vendors = (
            vendor_result.data
            or []
        )

        if not vendors:

            raise HTTPException(
                status_code=404,
                detail="Vendor not found",
            )

        vendor = vendors[0]

        # ====================================================
        # 2. PRODUCTS
        # ====================================================

        products = []

        try:

            products_result = (
                supabase_admin
                .table("products")
                .select("*")
                .eq("vendor_id", vendor_id)
                .order("created_at", desc=True)
                .execute()
                )

            products = (
                products_result.data
                or []
            )

        except Exception:

            logger.exception(
                "Failed to load vendor products: %s",
                vendor_id,
            )

        # ====================================================
        # 3. PRODUCT IMAGES
        # ====================================================

        if products:

            product_ids = [
                str(product["id"])
                for product in products
                if product.get("id")
            ]

            if product_ids:

                try:

                    images_result = (
                        supabase_admin
                        .table("product_images")
                        .select(
                            "id,"
                            "product_id,"
                            "image_url,"
                            "alt_text,"
                            "sort_order,"
                            "is_primary"
                        )
                        .in_(
                            "product_id",
                            product_ids,
                        )
                        .order(
                            "sort_order"
                        )
                        .execute()
                    )

                    images = (
                        images_result.data
                        or []
                    )

                    images_by_product = {}

                    for image in images:

                        key = str(
                            image.get(
                                "product_id"
                            )
                        )

                        images_by_product.setdefault(
                            key,
                            [],
                        ).append(image)

                    for product in products:

                        product["images"] = (
                            images_by_product.get(
                                str(
                                    product["id"]
                                ),
                                [],
                            )
                        )

                        primary_image = next(
                            (
                                image
                                for image
                                in product["images"]
                                if image.get(
                                    "is_primary"
                                )
                            ),
                            None,
                        )

                        if primary_image:

                            product["image_url"] = (
                                primary_image.get(
                                    "image_url"
                                )
                            )

                except Exception:

                    logger.exception(
                        "Failed to load vendor product images: %s",
                        vendor_id,
                    )

        # ====================================================
        # 4. TEAM MEMBERS
        # ====================================================

        team_members = []

        try:

            members_result = (
                supabase_admin
                .table("vendor_members")
                .select("*")
                .eq("vendor_id", vendor_id)
                .order("created_at")
                .execute()
                )

            members = (
                members_result.data
                or []
            )

            user_ids = [
                str(member["user_id"])
                for member in members
                if member.get("user_id")
            ]

            profiles_by_id = {}

            if user_ids:

                profiles_result = (
                    supabase_admin
                    .table("profiles")
                    .select(
                        "id,"
                        "full_name,"
                        "phone,"
                        "avatar_url,"
                        "role,"
                        "is_active"
                    )
                    .in_(
                        "id",
                        user_ids,
                    )
                    .execute()
                )

                profiles = (
                    profiles_result.data
                    or []
                )

                profiles_by_id = {
                    str(profile["id"]): profile
                    for profile in profiles
                }

            for member in members:

                profile = profiles_by_id.get(
                    str(
                        member.get(
                            "user_id"
                        )
                    ),
                    {},
                )

                team_members.append(
                    {
                        **member,
                        "profile": profile,
                    }
                )

        except Exception:

            logger.exception(
                "Failed to load vendor team: %s",
                vendor_id,
            )

        # ====================================================
        # 5. ORDER ITEMS
        # ====================================================

        order_items = []

        try:

            order_items_result = (
                supabase_admin
                .table("order_items")
                .select("*")
                .eq("vendor_id", vendor_id)
                .order("created_at", desc=True)
                .execute()
            )

            order_items = (
                order_items_result.data
                or []
            )

        except Exception:

            logger.exception(
                "Failed to load vendor order items: %s",
                vendor_id,
            )

        # ====================================================
        # 6. ORDERS
        #
        # One order can contain multiple products from
        # the same vendor, so we deduplicate by order_id.
        # ====================================================

        order_ids = list(
            dict.fromkeys(
                str(item["order_id"])
                for item in order_items
                if item.get("order_id")
            )
        )

        orders = []

        if order_ids:

            try:

                orders_result = (
                    supabase_admin
                    .table("orders")
                    .select(
                        "id,"
                        "order_number,"
                        "customer_id,"
                        "status,"
                        "payment_status,"
                        "payment_method,"
                        "currency,"
                        "created_at,"
                        "updated_at"
                    )
                    .in_(
                        "id",
                        order_ids,
                    )
                    .order(
                        "created_at",
                        desc=True,
                    )
                    .execute()
                )

                orders = (
                    orders_result.data
                    or []
                )

            except Exception:

                logger.exception(
                    "Failed to load vendor orders: %s",
                    vendor_id,
                )

        # ====================================================
        # 7. LEDGER
        # ====================================================

        ledger_entries = []

        try:

            ledger_result = (
                supabase_admin
                .table("vendor_ledger_entries")
                .select(
                    "id,"
                    "vendor_id,"
                    "order_item_id,"
                    "entry_type,"
                    "amount,"
                    "description,"
                    "reference_id,"
                    "created_at"
                )
                .eq(
                    "vendor_id",
                    vendor_id,
                )
                .order(
                    "created_at",
                    desc=True,
                )
                .execute()
            )

            ledger_entries = (
                ledger_result.data
                or []
            )

        except Exception:

            logger.exception(
                "Failed to load vendor ledger: %s",
                vendor_id,
            )

        # ====================================================
        # 8. PAYOUTS
        # ====================================================

        payouts = []

        try:

            payouts_result = (
                supabase_admin
                .table("vendor_payouts")
                .select("*")
                .eq(
                    "vendor_id",
                    vendor_id,
                )
                .order(
                    "created_at",
                    desc=True,
                )
                .execute()
            )

            payouts = (
                payouts_result.data
                or []
            )

        except Exception:

            logger.exception(
                "Failed to load vendor payouts: %s",
                vendor_id,
            )

        # ====================================================
        # 9. BRANDING REQUESTS
        # ====================================================

        branding_requests = []

        try:

            branding_result = (
                supabase_admin
                .table(
                    "vendor_branding_requests"
                )
                .select("*")
                .eq(
                    "vendor_id",
                    vendor_id,
                )
                .order(
                    "created_at",
                    desc=True,
                )
                .execute()
            )

            branding_requests = (
                branding_result.data
                or []
            )

        except Exception:

            logger.exception(
                "Failed to load vendor branding requests: %s",
                vendor_id,
            )

        # ====================================================
        # 10. PROFILE CHANGE REQUESTS
        # ====================================================

        profile_change_requests = []

        try:

            profile_change_result = (
                supabase_admin
                .table(
                    "vendor_profile_change_requests"
                )
                .select("*")
                .eq(
                    "vendor_id",
                    vendor_id,
                )
                .order(
                    "created_at",
                    desc=True,
                )
                .execute()
            )

            profile_change_requests = (
                profile_change_result.data
                or []
            )

        except Exception:

            logger.exception(
                "Failed to load vendor profile change requests: %s",
                vendor_id,
            )

        # ====================================================
        # 11. CALCULATE STATISTICS
        # ====================================================

        total_orders = len(
            set(order_ids)
        )

        total_products = len(
            products
        )

        active_products = sum(
            1
            for product in products
            if product.get("status") == "active"
        )

        pending_products = sum(
            1
            for product in products
            if product.get("status") == "pending"
        )

        delivered_order_items = [
            item
            for item in order_items
            if item.get("status") == "delivered"
        ]

        total_sales = sum(
            float(
                item.get(
                    "total_price"
                )
                or 0
            )
            for item in order_items
        )

        delivered_sales = sum(
            float(
                item.get(
                    "total_price"
                )
                or 0
            )
            for item in delivered_order_items
        )

        vendor_net_earnings = sum(
            float(
                item.get(
                    "vendor_net_amount"
                )
                or 0
            )
            for item in order_items
        )

        sales_ledger = sum(
            float(
                entry.get(
                    "amount"
                )
                or 0
            )
            for entry in ledger_entries
            if entry.get(
                "entry_type"
            ) == "sale"
        )

        commission_ledger = sum(
            float(
                entry.get(
                    "amount"
                )
                or 0
            )
            for entry in ledger_entries
            if entry.get(
                "entry_type"
            ) == "commission"
        )

        refund_ledger = sum(
            float(
                entry.get(
                    "amount"
                )
                or 0
            )
            for entry in ledger_entries
            if entry.get(
                "entry_type"
            ) == "refund"
        )

        payout_ledger = sum(
            float(
                entry.get(
                    "amount"
                )
                or 0
            )
            for entry in ledger_entries
            if entry.get(
                "entry_type"
            ) == "payout"
        )

        total_payouts = sum(
            float(
                payout.get(
                    "amount"
                )
                or 0
            )
            for payout in payouts
            if payout.get(
                "status"
            ) == "paid"
        )

        pending_payouts = sum(
            float(
                payout.get(
                    "amount"
                )
                or 0
            )
            for payout in payouts
            if payout.get(
                "status"
            )
            in {
                "pending",
                "processing",
            }
        )

        pending_branding_requests = sum(
            1
            for request
            in branding_requests
            if request.get(
                "status"
            ) == "pending"
        )

        pending_profile_changes = sum(
            1
            for request
            in profile_change_requests
            if request.get(
                "status"
            ) == "pending"
        )

        # ====================================================
        # 12. REQUESTS + ACTIVITY
        # ====================================================
        requests_activity = []

        for request in profile_change_requests:
            requests_activity.append({
                "id": request.get("id"),
                "activity_type": "profile_change_request",
                "title": "Vendor profile change request",
                "description": request.get("section") or "Business information change",
                "status": request.get("status") or "pending",
                "created_at": request.get("created_at"),
                "source": "vendor_profile_change_requests",
                "request": request,
            })

        for request in branding_requests:
            request_type = request.get("request_type") or "branding"
            requests_activity.append({
                "id": request.get("id"),
                "activity_type": "branding_request",
                "title": "Vendor branding request",
                "description": f"{str(request_type).capitalize()} update requested",
                "status": request.get("status") or "pending",
                "created_at": request.get("created_at"),
                "source": "vendor_branding_requests",
                "request": request,
            })

        for product in products:
            created_at = product.get("created_at")
            updated_at = product.get("updated_at")

            if updated_at and created_at and updated_at != created_at:
                requests_activity.append({
                    "id": f"product-update-{product.get('id')}",
                    "activity_type": "product_updated",
                    "title": "Product updated",
                    "description": product.get("name") or "Vendor product",
                    "status": product.get("status") or "—",
                    "created_at": updated_at,
                    "source": "products",
                    "product_id": product.get("id"),
                })
            elif created_at:
                requests_activity.append({
                    "id": f"product-created-{product.get('id')}",
                    "activity_type": "product_created",
                    "title": "Product submitted",
                    "description": product.get("name") or "Vendor product",
                    "status": product.get("status") or "—",
                    "created_at": created_at,
                    "source": "products",
                    "product_id": product.get("id"),
                })

        requests_activity.sort(
            key=lambda item: item.get("created_at") or "",
            reverse=True,
        )

        # ====================================================
        # 12. FINAL RESPONSE
        # ====================================================

        return {
            "vendor": vendor,

            "stats": {
                "total_products": total_products,
                "active_products": active_products,
                "pending_products": pending_products,
                "total_orders": total_orders,
                "total_order_items": len(
                    order_items
                ),
                "total_sales": total_sales,
                "delivered_sales": delivered_sales,
                "vendor_net_earnings": (
                    vendor_net_earnings
                ),
                "sales_ledger": sales_ledger,
                "commission_ledger": (
                    commission_ledger
                ),
                "refund_ledger": refund_ledger,
                "payout_ledger": payout_ledger,
                "total_payouts": total_payouts,
                "pending_payouts": pending_payouts,
                "team_members": len(
                    team_members
                ),
                "pending_branding_requests": (
                    pending_branding_requests
                ),
                "pending_profile_changes": (
                    pending_profile_changes
                ),
                "pending_requests": (
                    pending_branding_requests
                    + pending_profile_changes
                ),
            },

            "products": products,

            "team_members": team_members,

            "orders": orders,

            "order_items": order_items,

            "ledger": ledger_entries,

            "payouts": payouts,

            "branding_requests": (
                branding_requests
            ),

            "profile_change_requests": (
                profile_change_requests
            ),

            "requests_activity": requests_activity,
        }

    except HTTPException:
        raise

    except Exception as exc:

        logger.exception(
            "GET VENDOR DETAILS FAILED: %s",
            vendor_id,
        )

        raise database_error(exc) from exc


# ============================================================
# UPDATE VENDOR STATUS
# ============================================================

@router.patch("/{vendor_id}/status")
def update_vendor_status(
    vendor_id: UUID,
    new_status: VendorStatus,
):

    try:

        vendor_id = str(vendor_id)

        existing = (
            supabase_admin
            .table("vendors")
            .select("id")
            .eq("id", vendor_id)
            .limit(1)
            .execute()
        )

        if not existing.data:

            raise HTTPException(
                status_code=404,
                detail="Vendor not found",
            )

        result = (
            supabase_admin
            .table("vendors")
            .update(
                {
                    "status": new_status,
                }
            )
            .eq(
                "id",
                vendor_id,
            )
            .select("*")
            .execute()
        )

        if not result.data:

            raise HTTPException(
                status_code=500,
                detail=(
                    "Vendor status was not updated"
                ),
            )

        return {
            "message": (
                "Vendor status updated successfully"
            ),
            "vendor": result.data[0],
        }

    except HTTPException:
        raise

    except Exception as exc:

        logger.exception(
            "UPDATE VENDOR STATUS FAILED"
        )

        raise database_error(exc) from exc


# ============================================================
# UPDATE VENDOR ACTIVE STATUS
# ============================================================

@router.patch("/{vendor_id}/active")
def update_vendor_active_status(
    vendor_id: UUID,
    is_active: bool,
):

    try:

        vendor_id = str(vendor_id)

        existing = (
            supabase_admin
            .table("vendors")
            .select("id")
            .eq("id", vendor_id)
            .limit(1)
            .execute()
        )

        if not existing.data:

            raise HTTPException(
                status_code=404,
                detail="Vendor not found",
            )

        result = (
            supabase_admin
            .table("vendors")
            .update(
                {
                    "is_active": is_active,
                }
            )
            .eq(
                "id",
                vendor_id,
            )
            .select("*")
            .execute()
        )

        if not result.data:

            raise HTTPException(
                status_code=500,
                detail=(
                    "Vendor account status was not updated"
                ),
            )

        return {
            "message": (
                "Vendor account status updated successfully"
            ),
            "vendor": result.data[0],
        }

    except HTTPException:
        raise

    except Exception as exc:

        logger.exception(
            "UPDATE VENDOR ACTIVE STATUS FAILED"
        )

        raise database_error(exc) from exc
@router.get("/{vendor_id}/details")
def get_vendor_details(vendor_id: UUID):
    """
    Return the complete admin view for one vendor.

    Includes:
    - vendor profile
    - vendor products
    - vendor team members
    - order statistics
    - earnings
    - ledger entries
    - payouts
    """

    vendor_id = str(vendor_id)

    try:
        # ---------------------------------------------------------
        # 1. VENDOR PROFILE
        # ---------------------------------------------------------
        vendor_result = (
            supabase_admin
            .table("vendors")
            .select("*")
            .eq("id", vendor_id)
            .maybe_single()
            .execute()
        )

        vendor = vendor_result.data

        if not vendor:
            raise HTTPException(
                status_code=404,
                detail="Vendor not found.",
            )

        # ---------------------------------------------------------
        # 2. PRODUCTS BELONGING TO THIS VENDOR
        # ---------------------------------------------------------
        products_result = (
            supabase_admin
            .table("products")
            .select("*")
            .eq("vendor_id", vendor_id)
            .order("created_at", desc=True)
            .execute()
        )

        products = products_result.data or []

        # ---------------------------------------------------------
        # 3. PRODUCT IMAGES
        # ---------------------------------------------------------
        product_ids = [
            str(product["id"])
            for product in products
            if product.get("id")
        ]

        variants_by_product = {}

        if product_ids:
            variants_result = (
                supabase_admin
                .table("product_variants")
                .select(
                    "id, product_id, name, price, "
                    "stock_quantity, is_active"
                )
                .in_("product_id", product_ids)
                .execute()
            )

            for variant in variants_result.data or []:
                variants_by_product.setdefault(
                    str(variant["product_id"]),
                    [],
                ).append(variant)

        for product in products:
            variants = variants_by_product.get(
                str(product["id"]),
                [],
            )
            available_variants = [
                variant
                for variant in variants
                if variant.get("is_active") is not False
            ] or variants

            product["variants"] = variants
            product["variant_count"] = len(variants)
            product["total_stock"] = sum(
                int(variant.get("stock_quantity") or 0)
                for variant in variants
            )
            product["price"] = (
                product.get("price")
                if product.get("price") is not None
                else (
                    available_variants[0].get("price")
                    if available_variants
                    else None
                )
            )

        product_images_by_product = {}

        if product_ids:
            images_result = (
                supabase_admin
                .table("product_images")
                .select("*")
                .in_("product_id", product_ids)
                .order("sort_order")
                .execute()
            )

            for image in images_result.data or []:
                product_id = str(image["product_id"])

                product_images_by_product.setdefault(
                    product_id,
                    [],
                ).append(image)

        for product in products:
            product["images"] = product_images_by_product.get(
                str(product["id"]),
                [],
            )

        # ---------------------------------------------------------
        # 4. VENDOR TEAM MEMBERS
        # ---------------------------------------------------------
        members_result = (
            supabase_admin
            .table("vendor_members")
            .select(
                """
                vendor_id,
                user_id,
                member_role,
                is_active,
                permission_mode,
                created_at
                """
            )
            .eq("vendor_id", vendor_id)
            .order("created_at")
            .execute()
        )

        members = members_result.data or []

        # ---------------------------------------------------------
        # 5. LOAD MEMBER PROFILES
        # ---------------------------------------------------------
        member_user_ids = [
            str(member["user_id"])
            for member in members
            if member.get("user_id")
        ]

        profiles_by_id = {}

        if member_user_ids:
            profiles_result = (
                supabase_admin
                .table("profiles")
                .select(
                    """
                    id,
                    full_name,
                    phone,
                    role,
                    is_active,
                    created_at
                    """
                )
                .in_("id", member_user_ids)
                .execute()
            )

            profiles_by_id = {
                str(profile["id"]): profile
                for profile in (
                    profiles_result.data or []
                )
            }

        for member in members:
            member["profile"] = profiles_by_id.get(
                str(member["user_id"])
            )

        # ---------------------------------------------------------
        # 6. VENDOR ORDERS
        #
        # Orders are connected through order_items.vendor_id.
        # ---------------------------------------------------------
        order_items_result = (
            supabase_admin
            .table("order_items")
            .select(
                """
                id,
                order_id,
                vendor_id,
                product_id,
                variant_id,
                product_name,
                variant_name,
                quantity,
                unit_price,
                total_price,
                status,
                created_at
                """
            )
            .eq("vendor_id", vendor_id)
            .order("created_at", desc=True)
            .execute()
        )

        order_items = order_items_result.data or []

        variant_ids = list({
            str(item["variant_id"])
            for item in order_items
            if item.get("variant_id")
        })
        variants_by_id = {}

        if variant_ids:
            variants_result = (
                supabase_admin
                .table("product_variants")
                .select("id, name")
                .in_("id", variant_ids)
                .execute()
            )
            variants_by_id = {
                str(variant["id"]): variant
                for variant in variants_result.data or []
            }

        for item in order_items:
            variant = variants_by_id.get(
                str(item.get("variant_id"))
            )
            item["variant_name"] = (
                item.get("variant_name")
                or (variant or {}).get("name")
            )

        # ---------------------------------------------------------
        # 7. ORDER IDS
        # ---------------------------------------------------------
        order_ids = list(
            {
                str(item["order_id"])
                for item in order_items
                if item.get("order_id")
            }
        )

        orders = []

        if order_ids:
            orders_result = (
                supabase_admin
                .table("orders")
                .select(
                    """
                    id,
                    order_number,
                    customer_id,
                    status,
                    payment_status,
                    payment_method,
                    total_amount,
                    created_at,
                    updated_at
                    """
                )
                .in_("id", order_ids)
                .order("created_at", desc=True)
                .execute()
            )

            orders = orders_result.data or []

        # ---------------------------------------------------------
        # 8. ORDER STATISTICS
        # ---------------------------------------------------------
        total_orders = len(order_ids)

        total_units = sum(
            int(item.get("quantity") or 0)
            for item in order_items
        )

        total_sales = sum(
            float(item.get("total_price") or 0)
            for item in order_items
        )

        # ---------------------------------------------------------
        # 9. VENDOR LEDGER
        # ---------------------------------------------------------
        ledger_result = (
            supabase_admin
            .table("vendor_ledger_entries")
            .select("*")
            .eq("vendor_id", vendor_id)
            .order("created_at", desc=True)
            .execute()
        )

        ledger_entries = ledger_result.data or []

        # ---------------------------------------------------------
        # 10. CALCULATE EARNINGS
        #
        # Sale      -> positive
        # Refund    -> negative
        # Commission-> negative
        # Adjustment depends on amount
        # Payout    -> negative
        # ---------------------------------------------------------
        total_earnings = 0.0
        total_commission = 0.0
        total_refunds = 0.0
        total_payouts = 0.0

        for entry in ledger_entries:
            entry_type = entry.get("entry_type")
            amount = float(entry.get("amount") or 0)

            if entry_type == "sale":
                total_earnings += amount

            elif entry_type == "commission":
                total_commission += amount
                total_earnings -= amount

            elif entry_type == "refund":
                total_refunds += amount
                total_earnings -= amount

            elif entry_type == "payout":
                total_payouts += amount

        # ---------------------------------------------------------
        # 11. VENDOR PAYOUTS
        # ---------------------------------------------------------
        payouts_result = (
            supabase_admin
            .table("vendor_payouts")
            .select("*")
            .eq("vendor_id", vendor_id)
            .order("created_at", desc=True)
            .execute()
        )

        payouts = payouts_result.data or []

        pending_payout = sum(
            float(payout.get("amount") or 0)
            for payout in payouts
            if payout.get("status") in {
                "pending",
                "processing",
            }
        )

        paid_payout = sum(
            float(payout.get("amount") or 0)
            for payout in payouts
            if payout.get("status") == "paid"
        )

        # ---------------------------------------------------------
        # 12. PRODUCT STATISTICS
        # ---------------------------------------------------------
        approved_products = sum(
            1
            for product in products
            if str(product.get("status", "")).lower()
            in {"approved", "active", "published"}
        )

        pending_products = sum(
            1
            for product in products
            if str(product.get("status", "")).lower()
            == "pending"
        )

        # ---------------------------------------------------------
        # 13. VENDOR REQUESTS + ACTIVITY
        #
        # Requests that require admin attention are kept on the
        # individual vendor details page. Product creation/update
        # activity is also summarized here from the product timestamps.
        # ---------------------------------------------------------
        branding_requests_result = (
            supabase_admin
            .table("vendor_branding_requests")
            .select("*")
            .eq("vendor_id", vendor_id)
            .order("created_at", desc=True)
            .execute()
        )

        branding_requests = branding_requests_result.data or []

        profile_change_requests_result = (
            supabase_admin
            .table("vendor_profile_change_requests")
            .select("*")
            .eq("vendor_id", vendor_id)
            .order("created_at", desc=True)
            .execute()
        )

        profile_change_requests = (
            profile_change_requests_result.data or []
        )

        requests_activity = []

        for request in profile_change_requests:
            requests_activity.append({
                "id": request.get("id"),
                "activity_type": "profile_change_request",
                "title": "Vendor profile change request",
                "description": request.get("section") or "Business information change",
                "status": request.get("status") or "pending",
                "created_at": request.get("created_at"),
                "source": "vendor_profile_change_requests",
                "request": request,
            })

        for request in branding_requests:
            request_type = request.get("request_type") or "branding"
            requests_activity.append({
                "id": request.get("id"),
                "activity_type": "branding_request",
                "title": "Vendor branding request",
                "description": f"{str(request_type).capitalize()} update requested",
                "status": request.get("status") or "pending",
                "created_at": request.get("created_at"),
                "source": "vendor_branding_requests",
                "request": request,
            })

        for product in products:
            created_at = product.get("created_at")
            updated_at = product.get("updated_at")
            if updated_at and created_at and updated_at != created_at:
                requests_activity.append({
                    "id": f"product-update-{product.get('id')}",
                    "activity_type": "product_updated",
                    "title": "Product updated",
                    "description": product.get("name") or "Vendor product",
                    "status": product.get("status") or "—",
                    "created_at": updated_at,
                    "source": "products",
                    "product_id": product.get("id"),
                })
            elif created_at:
                requests_activity.append({
                    "id": f"product-created-{product.get('id')}",
                    "activity_type": "product_created",
                    "title": "Product submitted",
                    "description": product.get("name") or "Vendor product",
                    "status": product.get("status") or "—",
                    "created_at": created_at,
                    "source": "products",
                    "product_id": product.get("id"),
                })

        requests_activity.sort(
            key=lambda item: item.get("created_at") or "",
            reverse=True,
        )

        pending_requests = sum(
            1
            for item in requests_activity
            if item.get("source") in {
                "vendor_profile_change_requests",
                "vendor_branding_requests",
            }
            and item.get("status") == "pending"
        )

        # ---------------------------------------------------------
        # 13. FINAL RESPONSE
        # ---------------------------------------------------------
        return {
            "vendor": vendor,

            "products": products,

            "team_members": members,

            "orders": orders,

            "order_items": order_items,

            "ledger_entries": ledger_entries,

            "payouts": payouts,

            "branding_requests": branding_requests,

            "profile_change_requests": profile_change_requests,

            "requests_activity": requests_activity,

            "stats": {
                "total_products": len(products),
                "approved_products": approved_products,
                "pending_products": pending_products,

                "total_orders": total_orders,
                "total_order_items": len(order_items),
                "total_units": total_units,

                "total_sales": total_sales,

                "total_earnings": total_earnings,
                "total_commission": total_commission,
                "total_refunds": total_refunds,

                "total_payouts": total_payouts,
                "pending_payout": pending_payout,
                "paid_payout": paid_payout,
                "pending_requests": pending_requests,
                "pending_branding_requests": sum(
                    1 for request in branding_requests
                    if request.get("status") == "pending"
                ),
                "pending_profile_changes": sum(
                    1 for request in profile_change_requests
                    if request.get("status") == "pending"
                ),
            },
        }

    except HTTPException:
        raise

    except Exception as exc:
        logger.exception(
            "Failed to load vendor details for %s",
            vendor_id,
        )

        raise database_error(exc) from exc