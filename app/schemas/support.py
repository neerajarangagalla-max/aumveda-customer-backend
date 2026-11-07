from pydantic import BaseModel, Field


class CreateSupportTicket(BaseModel):
    subject: str = Field(min_length=3, max_length=200)
    category: str = "general"
    priority: str = "medium"
    order_id: str | None = None
    message: str = Field(min_length=1, max_length=5000)


class SupportReply(BaseModel):
    message: str = Field(min_length=1, max_length=5000)


class SupportTicketUpdate(BaseModel):
    status: str | None = None
    priority: str | None = None