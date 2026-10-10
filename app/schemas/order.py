from pydantic import BaseModel


class CreateOrder(BaseModel):
    shipping_address: dict
    payment_method: str = "cod"
