
from pydantic import BaseModel


class ProfileUpdate(BaseModel):
    name: str | None = None
    full_name: str | None = None
    phone: str | None = None
    avatar_url: str | None = None
