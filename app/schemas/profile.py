
from datetime import date

from pydantic import BaseModel


class ProfileUpdate(BaseModel):
    name: str | None = None
    full_name: str | None = None
    phone: str | None = None
    avatar_url: str | None = None
    date_of_birth: date | None = None
    gender: str | None = None
    marketing_opt_in: bool | None = None
