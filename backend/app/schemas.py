from datetime import datetime

from pydantic import BaseModel, EmailStr, Field, field_serializer


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=6)


class UserOut(BaseModel):
    id: int
    email: EmailStr
    created_at: datetime


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class ModelDownloadIn(BaseModel):
    hf_repo: str
    hf_filename: str


class ModelOut(BaseModel):
    id: int
    hf_repo: str
    hf_filename: str
    local_path: str | None
    size_bytes: int | None
    created_at: datetime


class ModelDownloadJobOut(BaseModel):
    id: int
    model_id: int
    status: str
    progress_bytes: int
    error: str | None
    started_at: datetime | None
    finished_at: datetime | None


class ModelCatalogItem(BaseModel):
    id: str
    label: str
    hf_repo: str
    hf_filename: str
    description: str | None = None


class HfModelSummary(BaseModel):
    repo_id: str
    likes: int | None = None
    downloads: int | None = None
    pipeline_tag: str | None = None
    tags: list[str] = []


class HfRepoFile(BaseModel):
    filename: str


class ChatCreateIn(BaseModel):
    model_id: int
    title: str | None = None


class ChatDeleteIn(BaseModel):
    chat_id: int


class ChatOut(BaseModel):
    id: int
    model_id: int
    title: str
    created_at: datetime

    @field_serializer("created_at")
    def serialize_created_at(self, dt: datetime) -> str:
        return dt.isoformat()


class MessageOut(BaseModel):
    id: int
    chat_id: int
    role: str
    content: str
    tokens_used: int | None = None
    created_at: datetime

    @field_serializer("created_at")
    def serialize_created_at(self, dt: datetime) -> str:
        return dt.isoformat()


class ChatDetailOut(BaseModel):
    chat: ChatOut
    messages: list[MessageOut]


class MessageCreateIn(BaseModel):
    content: str = Field(min_length=1)


class StreamParamsIn(BaseModel):
    after_message_id: int
    temperature: float = 0.7
    max_tokens: int = 512
    top_p: float = 0.95
    top_k: int = 40
    repeat_penalty: float = 1.1
    system_prompt: str | None = None

