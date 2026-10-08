"""Typed boundary models: raw Telegram JSON never crosses into the core."""

from pydantic import BaseModel, ConfigDict


class Chat(BaseModel):
    """A Telegram conversation. `id` is the only identity this project uses."""

    model_config = ConfigDict(extra="ignore")

    id: int
    type: str | None = None


class Message(BaseModel):
    """An inbound message. `text` is absent for photos, stickers, voice notes."""

    model_config = ConfigDict(extra="ignore")

    message_id: int
    chat: Chat
    date: int | None = None
    text: str | None = None


class Update(BaseModel):
    """One unit of work from `getUpdates`. Only `message` is in scope for now."""

    model_config = ConfigDict(extra="ignore")

    update_id: int
    message: Message | None = None
