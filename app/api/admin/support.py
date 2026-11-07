from fastapi import APIRouter, Depends, HTTPException, Query

from app.core.security import get_current_admin
from app.core.supabase import supabase_admin
from app.schemas.support import SupportReply, SupportTicketUpdate


router = APIRouter(
    prefix="/admin/support",
    tags=["Admin Support"],
    dependencies=[Depends(get_current_admin)],
)


@router.get("/summary")
def get_support_summary():
    result = (
        supabase_admin
        .table("support_tickets")
        .select("status")
        .execute()
    )

    rows = result.data or []

    return {
        "total": len(rows),
        "open": sum(1 for row in rows if row.get("status") == "open"),
        "in_progress": sum(
            1 for row in rows if row.get("status") == "in_progress"
        ),
        "resolved": sum(
            1 for row in rows if row.get("status") == "resolved"
        ),
        "closed": sum(
            1 for row in rows if row.get("status") == "closed"
        ),
    }


@router.get("/tickets")
def get_support_tickets(
    search: str | None = None,
    status: str | None = None,
    priority: str | None = None,
    category: str | None = None,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    query = (
        supabase_admin
        .table("support_tickets")
        .select("*", count="exact")
    )

    if status:
        query = query.eq("status", status)

    if priority:
        query = query.eq("priority", priority)

    if category:
        query = query.eq("category", category)

    if search:
        query = query.or_(
            f"ticket_number.ilike.%{search}%,"
            f"subject.ilike.%{search}%"
        )

    result = (
        query
        .order("created_at", desc=True)
        .range(offset, offset + limit - 1)
        .execute()
    )

    return {
        "items": result.data or [],
        "total": result.count or 0,
        "limit": limit,
        "offset": offset,
    }


@router.get("/tickets/{ticket_id}")
def get_support_ticket(ticket_id: str):
    ticket = (
        supabase_admin
        .table("support_tickets")
        .select("*")
        .eq("id", ticket_id)
        .maybe_single()
        .execute()
    )

    if not ticket.data:
        raise HTTPException(
            status_code=404,
            detail="Support ticket not found",
        )

    messages = (
        supabase_admin
        .table("support_messages")
        .select("*")
        .eq("ticket_id", ticket_id)
        .order("created_at")
        .execute()
    )

    customer = (
        supabase_admin
        .table("profiles")
        .select("*")
        .eq("id", ticket.data["customer_id"])
        .maybe_single()
        .execute()
    )

    return {
        "ticket": ticket.data,
        "customer": customer.data,
        "messages": messages.data or [],
    }


@router.patch("/tickets/{ticket_id}")
def update_support_ticket(
    ticket_id: str,
    payload: SupportTicketUpdate,
):
    update_data = {}

    if payload.status is not None:
        if payload.status not in {
            "open",
            "in_progress",
            "resolved",
            "closed",
        }:
            raise HTTPException(
                status_code=400,
                detail="Invalid ticket status",
            )

        update_data["status"] = payload.status

    if payload.priority is not None:
        if payload.priority not in {
            "low",
            "medium",
            "high",
            "urgent",
        }:
            raise HTTPException(
                status_code=400,
                detail="Invalid ticket priority",
            )

        update_data["priority"] = payload.priority

    if not update_data:
        raise HTTPException(
            status_code=400,
            detail="No changes provided",
        )

    result = (
        supabase_admin
        .table("support_tickets")
        .update(update_data)
        .eq("id", ticket_id)
        .execute()
    )

    if not result.data:
        raise HTTPException(
            status_code=404,
            detail="Support ticket not found",
        )

    return result.data[0]


@router.post("/tickets/{ticket_id}/reply")
def admin_reply(
    ticket_id: str,
    payload: SupportReply,
    current_admin=Depends(get_current_admin),
):
    ticket = (
        supabase_admin
        .table("support_tickets")
        .select("id,status")
        .eq("id", ticket_id)
        .maybe_single()
        .execute()
    )

    if not ticket.data:
        raise HTTPException(
            status_code=404,
            detail="Support ticket not found",
        )

    if ticket.data["status"] == "closed":
        raise HTTPException(
            status_code=400,
            detail="This ticket is closed",
        )

    result = (
        supabase_admin
        .table("support_messages")
        .insert({
            "ticket_id": ticket_id,
            "sender_type": "admin",
            "sender_id": str(current_admin.id),
            "message": payload.message,
        })
        .execute()
    )

    if not result.data:
        raise HTTPException(
            status_code=500,
            detail="Unable to send admin reply",
        )

    if ticket.data["status"] == "open":
        (
            supabase_admin
            .table("support_tickets")
            .update({"status": "in_progress"})
            .eq("id", ticket_id)
            .execute()
        )

    return result.data[0]