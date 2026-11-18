from pydantic import BaseModel, EmailStr, Field


class VendorRegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)

    full_name: str
    phone: str | None = None

    business_name: str
    legal_name: str | None = None

    business_email: EmailStr | None = None
    business_phone: str | None = None

    city: str | None = None
    state: str | None = None
    country: str = "India"


class VendorLoginRequest(BaseModel):
    email: EmailStr
    password: str