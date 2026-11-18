from typing import Literal

from pydantic import BaseModel


class VendorBrandingRequestResponse(BaseModel):
    id: str
    vendor_id: str
    request_type: Literal["logo", "banner"]
    current_url: str | None = None
    proposed_url: str
    status: Literal["pending", "approved", "rejected"]
    rejection_reason: str | None = None
    submitted_by: str | None = None
    reviewed_by: str | None = None
    submitted_at: str | None = None
    reviewed_at: str | None = None
    created_at: str | None = None
    updated_at: str | None = None