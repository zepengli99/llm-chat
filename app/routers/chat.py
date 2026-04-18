import json
import logging
import uuid
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import AsyncSessionLocal, get_db
from app.dependencies import get_current_user
from app.models.conversation import Conversation
from app.models.message import Message
from app.models.user import User
from app.schemas.chat import ChatRequest, ConversationHistoryOut, ConversationOut, MessageOut
from app.services.llm_service import stream_chat

router = APIRouter(prefix="/chat", tags=["chat"])
logger = logging.getLogger(__name__)


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
    await db.commit()
    logger.info("created conversation %s for user %s", conversation.id, user.id)
    return conversation


async def _build_message_history(db: AsyncSession, conversation_id: uuid.UUID) -> list[dict]:
    result = await db.execute(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at)
    )
    return [{"role": m.role, "content": m.content} for m in result.scalars()]


async def _sse_generator(
    conversation: Conversation,
    user_message_text: str,
) -> AsyncIterator[str]:
    async with AsyncSessionLocal() as db:
        user_msg = Message(
            conversation_id=conversation.id,
            role="user",
            content=user_message_text,
        )
        db.add(user_msg)
        await db.flush()

        history = await _build_message_history(db, conversation.id)

        full_response: list[str] = []
        logger.info("llm stream started  conversation=%s", conversation.id)
        try:
            async for token in stream_chat(history):
                full_response.append(token)
                yield f"data: {json.dumps({'token': token})}\n\n"
        except Exception as exc:
            logger.exception("llm stream error  conversation=%s", conversation.id)
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
        logger.info("llm stream complete conversation=%s  tokens=%d", conversation.id, len(full_response))

    yield f"data: {json.dumps({'done': True, 'conversation_id': str(conversation.id)})}\n\n"


@router.post(
    "",
    summary="Send a message (streaming)",
    response_description="Server-Sent Events stream of token chunks followed by a `done` event.",
    responses={
        200: {
            "content": {
                "text/event-stream": {
                    "example": (
                        'data: {"token": "The"}\n\n'
                        'data: {"token": " capital of France is Paris."}\n\n'
                        'data: {"done": true, "conversation_id": "a1b2c3d4-..."}\n\n'
                    )
                }
            },
            "description": (
                "Token chunks streamed as SSE events. "
                "The final event contains `done: true` and the `conversation_id`."
            ),
        },
        401: {"description": "Missing or invalid JWT token."},
        404: {"description": "`conversation_id` not found or belongs to another user."},
    },
)
async def chat(
    body: ChatRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """
    Send a message and stream the LLM reply via **Server-Sent Events** (`text/event-stream`).

    **Authentication:** `Authorization: Bearer <token>` header is required.

    **Starting a new conversation:** omit `conversation_id` (or pass `null`). A new conversation
    is created automatically and its ID is returned in the final `done` event.

    **Continuing an existing conversation:** pass the `conversation_id` returned by a previous
    request. The full conversation history is sent to the LLM as context.

    **SSE event format:**

    While the LLM is generating, token chunks arrive one by one:
    ```
    data: {"token": "The"}
    data: {"token": " capital of France is Paris."}
    ```

    When generation is complete, a final event is sent:
    ```
    data: {"done": true, "conversation_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890"}
    ```

    If an error occurs mid-stream:
    ```
    data: {"error": "...error message..."}
    ```

    **Note:** Swagger UI's "Try it out" does not render SSE streams interactively.
    Use `curl -N` or `test_ui.html` to see tokens arrive in real time.
    """
    conversation = await _get_or_create_conversation(
        db, current_user, body.conversation_id, body.message
    )

    return StreamingResponse(
        _sse_generator(conversation, body.message),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.get(
    "/history",
    response_model=list[ConversationOut],
    summary="List all conversations",
    response_description="Conversations sorted by most recently updated, oldest-first within each page.",
    responses={
        401: {"description": "Missing or invalid JWT token."},
    },
)
async def list_conversations(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[ConversationOut]:
    """
    Return all conversations belonging to the authenticated user, sorted by **most recently
    updated** first.

    Each item includes the conversation `id` (use it in `POST /chat` to continue),
    the auto-generated `title`, and timestamps.

    Returns an empty list if the user has no conversations yet.
    """
    result = await db.execute(
        select(Conversation)
        .where(Conversation.user_id == current_user.id)
        .order_by(Conversation.updated_at.desc())
    )
    return result.scalars().all()


@router.get(
    "/history/{conversation_id}",
    response_model=ConversationHistoryOut,
    summary="Get conversation with full message history",
    response_description="Conversation metadata and all messages ordered oldest-first.",
    responses={
        401: {"description": "Missing or invalid JWT token."},
        404: {"description": "Conversation not found or belongs to another user."},
    },
)
async def get_conversation(
    conversation_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ConversationHistoryOut:
    """
    Fetch a single conversation and its complete message history.

    - **conversation_id**: UUID of the conversation (obtained from `GET /chat/history` or the
      `done` event of `POST /chat`).
    - Messages are ordered **oldest-first** so they can be rendered top-to-bottom directly.
    - Returns `404` if the conversation does not exist **or** belongs to a different user
      (no information leakage about other users' conversations).
    """
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
