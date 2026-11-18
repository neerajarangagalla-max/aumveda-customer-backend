
"""
AUMVEDA Vendor Backend
M12.6.8E - Employee Password Assistance API

Workflow:
Employee -> Request Assistance -> Vendor Owner Notification

Security:
- Public endpoint with development-stage rate limiting.
- Generic response prevents account enumeration.
- No employee OTP generation.
- No password updates.
- No Supabase credentials exposed.
- Existing Team Management remains unchanged.

IMPORTANT:
The router is NOT registered in the main application yet.

The in-memory limiter is suitable for local development
only. Production requires shared rate limiting and a
more efficient server-side email lookup.
"""

import logging
import threading
import time
from collections import deque

from fastapi import APIRouter, Request
from pydantic import BaseModel, EmailStr, Field

from app.services.vendor.employee_password_request_service import (
    request_employee_password_assistance,
)

logger = logging.getLogger(
    "aumveda.vendor.password_assistance_api"
)

router = APIRouter(
    prefix="/auth",
    tags=["Vendor Password Assistance"],
)

# ============================================================
# DEVELOPMENT RATE LIMIT SETTINGS
# ============================================================

RATE_WINDOW_SECONDS = 900

MAX_REQUESTS_PER_IP = 5

MAX_GLOBAL_REQUESTS = 100

MAX_TRACKED_IPS = 1000

_rate_lock = threading.Lock()

_ip_requests = {}

_global_requests = deque()

GENERIC_MESSAGE = (
    "If this email belongs to an eligible employee, "
    "a password assistance request will be sent "
    "to the Vendor Owner."
)


# ============================================================
# SCHEMAS
# ============================================================

class EmployeePasswordRequest(BaseModel):
    email: EmailStr = Field(
        ...,
        description="Registered employee email address",
    )


class EmployeePasswordRequestResponse(BaseModel):
    status: str
    message: str


# ============================================================
# RATE LIMIT HELPER
# ============================================================

def _allow_request(client_ip: str) -> bool:
    now = time.monotonic()
    cutoff = now - RATE_WINDOW_SECONDS

    with _rate_lock:

        # Remove expired global request timestamps.

        while (
            _global_requests
            and _global_requests[0] <= cutoff
        ):
            _global_requests.popleft()

        # Expire old per-IP entries.

        expired_ips = []

        for ip, timestamps in _ip_requests.items():
            while (
                timestamps
                and timestamps[0] <= cutoff
            ):
                timestamps.popleft()

            if not timestamps:
                expired_ips.append(ip)

        for ip in expired_ips:
            del _ip_requests[ip]

        # Apply process-wide request limit.

        if (
            len(_global_requests)
            >= MAX_GLOBAL_REQUESTS
        ):
            return False

        timestamps = _ip_requests.get(client_ip)

        if timestamps is None:
            if len(_ip_requests) >= MAX_TRACKED_IPS:
                return False

            timestamps = deque()
            _ip_requests[client_ip] = timestamps

        if len(timestamps) >= MAX_REQUESTS_PER_IP:
            return False

        timestamps.append(now)
        _global_requests.append(now)

        return True


# ============================================================
# PUBLIC EMPLOYEE PASSWORD ASSISTANCE
# ============================================================

@router.post(
    "/employee-password-request",
    response_model=EmployeePasswordRequestResponse,
)
def request_employee_password(
    payload: EmployeePasswordRequest,
    request: Request,
):
    """
    Employee password assistance request.

    The server determines the actual user role
    and Owner relationship.

    Rate limiting does not depend on client-
    provided X-Forwarded-For headers.

    Excess requests return the same generic
    confirmation as regular requests.
    """

    client_ip = (
        request.client.host
        if request.client
        else "unknown"
    )

    allowed = _allow_request(
        client_ip
    )

    if not allowed:
        logger.warning(
            "Employee password assistance "
            "request rate limited."
        )

        return EmployeePasswordRequestResponse(
            status="success",
            message=GENERIC_MESSAGE,
        )

    result = request_employee_password_assistance(
        email=str(payload.email),
    )

    return EmployeePasswordRequestResponse(
        status=result["status"],
        message=result["message"],
    )
