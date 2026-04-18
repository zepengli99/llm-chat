import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str = Field(
        ...,
        description="User message text to send to the LLM.",
        examples=["What is the capital of France?"],
    )
    conversation_id: uuid.UUID | None = Field(
        default=None,
        description=(
            "ID of an existing conversation to continue. "
            "Omit or pass `null` to start a new conversation automatically. "
            "The `conversation_id` is returned in the final SSE `done` event."
        ),
        examples=[None],
    )


class MessageOut(BaseModel):
    id: uuid.UUID = Field(..., description="Unique message ID.")
    role: str = Field(
        ...,
        description="`user` — message you sent; `assistant` — LLM reply.",
        examples=["user"],
    )
    content: str = Field(..., description="Full text of the message.")
    created_at: datetime = Field(..., description="UTC timestamp when the message was stored.")

    model_config = {"from_attributes": True}


class ConversationOut(BaseModel):
    id: uuid.UUID = Field(
        ...,
        description="Unique conversation ID. Pass this as `conversation_id` in `POST /chat` to continue the conversation.",
    )
    title: str | None = Field(
        ...,
        description="Auto-derived from the first 50 characters of the opening message.",
    )
    created_at: datetime = Field(..., description="UTC timestamp when the conversation was created.")
    updated_at: datetime = Field(..., description="UTC timestamp of the most recent message.")

    model_config = {"from_attributes": True}


class ConversationHistoryOut(BaseModel):
    conversation: ConversationOut = Field(..., description="Conversation metadata.")
    messages: list[MessageOut] = Field(
        ...,
        description="All messages in this conversation, ordered oldest-first.",
    )
