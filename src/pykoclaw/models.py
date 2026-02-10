from pydantic import BaseModel


class Conversation(BaseModel):
    name: str
    session_id: str | None = None
    cwd: str | None = None
    created_at: str


class ScheduledTask(BaseModel):
    id: str
    conversation: str
    prompt: str
    schedule_type: str
    schedule_value: str
    context_mode: str = "isolated"
    next_run: str | None = None
    last_run: str | None = None
    last_result: str | None = None
    status: str = "active"
    created_at: str
