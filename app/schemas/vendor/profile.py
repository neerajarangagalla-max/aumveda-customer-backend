from pydantic import BaseModel, EmailStr


class VendorProfileUpdateRequest(BaseModel):
    business_name: str | None = None
    legal_name: str | None = None
    description: str | None = None

    email: EmailStr | None = None
    phone: str | None = None

    logo_url: str | None = None
    banner_url: str | None = None

    address_line1: str | None = None
    address_line2: str | None = None

    city: str | None = None
    state: str | None = None
    postal_code: str | None = None
    country: str | None = None

    tax_id: str | None = None