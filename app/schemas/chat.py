import uuid
from datetime import datetime

from pydantic import BaseModel


class ChatRequest(BaseModel):
    message: str
    conversation_id: uuid.UUID | None = None


class MessageOut(BaseModel):
    id: uuid.UUID
    role: str
    content: str
    created_at: datetime

    model_config = {"from_attributes": True}


class ConversationOut(BaseModel):
    id: uuid.UUID
    title: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ConversationHistoryOut(BaseModel):
    conversation: ConversationOut
    messages: list[MessageOut]
