from secrets import token_hex

from fastapi import APIRouter, Depends, HTTPException

from app.core.security import get_current_user
from app.core.supabase import supabase_admin
from app.schemas.support import CreateSupportTicket, SupportReply


router = APIRouter(
    prefix="/support",
    tags=["Support"],
)


@router.post("/tickets")
def create_ticket(
    payload: CreateSupportTicket,
    current_user=Depends(get_current_user),
):
    customer_id = str(current_user.id)

    try:
        ticket_number = f"TKT-{token_hex(4).upper()}"

        ticket_result = (
            supabase_admin
            .table("support_tickets")
            .insert(
                {
                    "ticket_number": ticket_number,
                    "customer_id": customer_id,
                    "order_id": payload.order_id,
                    "subject": payload.subject,
                    "category": payload.category,
                    "priority": payload.priority,
                    "status": "open",
                }
            )
            .execute()
        )

        if not ticket_result.data:
            raise HTTPException(
                status_code=500,
                detail="Unable to create support ticket",
            )

        ticket = ticket_result.data[0]

        message_result = (
            supabase_admin
            .table("support_messages")
            .insert(
                {
                    "ticket_id": ticket["id"],
                    "sender_type": "customer",
                    "sender_id": customer_id,
                    "message": payload.message,
                }
            )
            .execute()
        )

        return {
            "ticket": ticket,
            "message": (
                message_result.data[0]
                if message_result.data
                else None
            ),
        }

    except HTTPException:
        raise

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="Unable to create support ticket",
        ) from exc


@router.get("/tickets")
def get_my_tickets(
    current_user=Depends(get_current_user),
):
    customer_id = str(current_user.id)

    try:
        result = (
            supabase_admin
            .table("support_tickets")
            .select("*")
            .eq("customer_id", customer_id)
            .order("created_at", desc=True)
            .execute()
        )

        return {
            "items": result.data or [],
        }

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="Unable to retrieve support tickets",
        ) from exc


@router.get("/tickets/{ticket_id}")
def get_my_ticket(
    ticket_id: str,
    current_user=Depends(get_current_user),
):
    customer_id = str(current_user.id)

    try:
        ticket_result = (
            supabase_admin
            .table("support_tickets")
            .select("*")
            .eq("id", ticket_id)
            .eq("customer_id", customer_id)
            .maybe_single()
            .execute()
        )

        if not ticket_result.data:
            raise HTTPException(
                status_code=404,
                detail="Support ticket not found",
            )

        messages_result = (
            supabase_admin
            .table("support_messages")
            .select("*")
            .eq("ticket_id", ticket_id)
            .order("created_at")
            .execute()
        )

        return {
            "ticket": ticket_result.data,
            "messages": messages_result.data or [],
        }

    except HTTPException:
        raise

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="Unable to retrieve support ticket",
        ) from exc


@router.post("/tickets/{ticket_id}/reply")
def reply_to_ticket(
    ticket_id: str,
    payload: SupportReply,
    current_user=Depends(get_current_user),
):
    customer_id = str(current_user.id)

    try:
        ticket_result = (
            supabase_admin
            .table("support_tickets")
            .select("id,status")
            .eq("id", ticket_id)
            .eq("customer_id", customer_id)
            .maybe_single()
            .execute()
        )

        if not ticket_result.data:
            raise HTTPException(
                status_code=404,
                detail="Support ticket not found",
            )

        if ticket_result.data["status"] == "closed":
            raise HTTPException(
                status_code=400,
                detail="This ticket is closed",
            )

        result = (
            supabase_admin
            .table("support_messages")
            .insert(
                {
                    "ticket_id": ticket_id,
                    "sender_type": "customer",
                    "sender_id": customer_id,
                    "message": payload.message,
                }
            )
            .execute()
        )

        if not result.data:
            raise HTTPException(
                status_code=500,
                detail="Unable to send reply",
            )

        return result.data[0]

    except HTTPException:
        raise

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="Unable to send support reply",
        ) from exc