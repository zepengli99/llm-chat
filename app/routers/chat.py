import json
import uuid
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.dependencies import get_current_user
from app.models.conversation import Conversation
from app.models.message import Message
from app.models.user import User
from app.schemas.chat import ChatRequest, ConversationHistoryOut, ConversationOut, MessageOut
from app.services.llm_service import stream_chat

router = APIRouter(prefix="/chat", tags=["chat"])


async def _get_or_create_conversation(
    db: AsyncSession,
    user: User,
    conversation_id: uuid.UUID | None,
    first_user_message: str,
) -> Conversation:
    if conversation_id is not None:
        result = await db.execute(
            select(Conversation).where(
                Conversation.id == conversation_id,
                Conversation.user_id == user.id,
            )
        )
        conversation = result.scalar_one_or_none()
        if conversation is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Conversation not found",
            )
        return conversation

    title = first_user_message[:50]
    conversation = Conversation(user_id=user.id, title=title)
    db.add(conversation)
    await db.flush()
    return conversation


async def _build_message_history(db: AsyncSession, conversation_id: uuid.UUID) -> list[dict]:
    result = await db.execute(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at)
    )
    return [{"role": m.role, "content": m.content} for m in result.scalars()]


async def _sse_generator(
    db: AsyncSession,
    conversation: Conversation,
    user_message_text: str,
) -> AsyncIterator[str]:
    user_msg = Message(
        conversation_id=conversation.id,
        role="user",
        content=user_message_text,
    )
    db.add(user_msg)
    await db.flush()

    history = await _build_message_history(db, conversation.id)

    full_response: list[str] = []
    try:
        async for token in stream_chat(history):
            full_response.append(token)
            yield f"data: {json.dumps({'token': token})}\n\n"
    except Exception as exc:
        yield f"data: {json.dumps({'error': str(exc)})}\n\n"
        await db.rollback()
        return

    assistant_msg = Message(
        conversation_id=conversation.id,
        role="assistant",
        content="".join(full_response),
    )
    db.add(assistant_msg)
    await db.commit()

    yield f"data: {json.dumps({'done': True, 'conversation_id': str(conversation.id)})}\n\n"


@router.post("")
async def chat(
    body: ChatRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """Send a message and stream back the LLM response via Server-Sent Events."""
    conversation = await _get_or_create_conversation(
        db, current_user, body.conversation_id, body.message
    )

    return StreamingResponse(
        _sse_generator(db, conversation, body.message),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/history", response_model=list[ConversationOut])
async def list_conversations(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[ConversationOut]:
    """List all conversations for the authenticated user."""
    result = await db.execute(
        select(Conversation)
        .where(Conversation.user_id == current_user.id)
        .order_by(Conversation.updated_at.desc())
    )
    return result.scalars().all()


@router.get("/history/{conversation_id}", response_model=ConversationHistoryOut)
async def get_conversation(
    conversation_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ConversationHistoryOut:
    """Get a single conversation with all its messages."""
    result = await db.execute(
        select(Conversation)
        .where(
            Conversation.id == conversation_id,
            Conversation.user_id == current_user.id,
        )
        .options(selectinload(Conversation.messages))
    )
    conversation = result.scalar_one_or_none()
    if conversation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")

    return ConversationHistoryOut(
        conversation=ConversationOut.model_validate(conversation),
        messages=[MessageOut.model_validate(m) for m in conversation.messages],
    )
