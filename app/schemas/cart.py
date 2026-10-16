from pydantic import BaseModel, Field


class AddCartItem(BaseModel):
    product_id: str
    variant_id: str
    quantity: int = Field(default=1, ge=1)


class UpdateCartItem(BaseModel):
    quantity: int = Field(default=1, ge=1)
