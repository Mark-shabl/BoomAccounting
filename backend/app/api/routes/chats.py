from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sse_starlette.sse import EventSourceResponse
from sqlalchemy import asc, desc, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.models import Chat, Message, Model, User
from app.db.session import get_db
from app.schemas import ChatCreateIn, ChatDeleteIn, ChatDetailOut, ChatOut, MessageCreateIn, MessageOut, StreamParamsIn
from app.services.llm_runner import llm_runner


router = APIRouter()


@router.post("/remove", status_code=status.HTTP_204_NO_CONTENT)
def delete_chat(payload: ChatDeleteIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    chat = db.get(Chat, payload.chat_id)
    if not chat or chat.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chat not found")
    db.delete(chat)
    db.commit()
    return None


@router.post("", response_model=ChatOut)
def create_chat(payload: ChatCreateIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    model = db.get(Model, payload.model_id)
    if not model or model.owner_user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Model not found")

    title = payload.title.strip() if payload.title else "New chat"
    chat = Chat(user_id=user.id, model_id=model.id, title=title)
    db.add(chat)
    db.commit()
    db.refresh(chat)
    return ChatOut(id=chat.id, model_id=chat.model_id, title=chat.title, created_at=chat.created_at)


@router.get("", response_model=list[ChatOut])
def list_chats(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    chats = db.scalars(select(Chat).where(Chat.user_id == user.id).order_by(desc(Chat.id))).all()
    return [ChatOut(id=c.id, model_id=c.model_id, title=c.title, created_at=c.created_at) for c in chats]


@router.get("/{chat_id}", response_model=ChatDetailOut)
def get_chat(chat_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    chat = db.get(Chat, chat_id)
    if not chat or chat.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chat not found")

    messages = db.scalars(select(Message).where(Message.chat_id == chat.id).order_by(asc(Message.id))).all()
    return ChatDetailOut(
        chat=ChatOut(id=chat.id, model_id=chat.model_id, title=chat.title, created_at=chat.created_at),
        messages=[
            MessageOut(
                id=m.id,
                chat_id=m.chat_id,
                role=m.role,
                content=m.content or "",
                tokens_used=m.tokens_used,
                created_at=m.created_at,
            )
            for m in messages
        ],
    )


@router.post("/{chat_id}/messages", response_model=MessageOut)
def add_user_message(
    chat_id: int, payload: MessageCreateIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    chat = db.get(Chat, chat_id)
    if not chat or chat.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chat not found")

    msg = Message(chat_id=chat.id, role="user", content=payload.content)
    db.add(msg)
    db.commit()
    db.refresh(msg)
    return MessageOut(id=msg.id, chat_id=msg.chat_id, role=msg.role, content=msg.content, tokens_used=msg.tokens_used, created_at=msg.created_at)


def _stream_assistant_impl(chat_id: int, payload: StreamParamsIn, user: User, db: Session):
    chat = db.get(Chat, chat_id)
    if not chat or chat.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chat not found")

    model = db.get(Model, chat.model_id)
    if not model or model.owner_user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Model not found")
    if not model.local_path:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Model is not downloaded yet")

    messages = db.scalars(
        select(Message).where(Message.chat_id == chat.id, Message.id <= payload.after_message_id).order_by(asc(Message.id))
    ).all()
    if not messages or messages[-1].id != payload.after_message_id or messages[-1].role != "user":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="after_message_id must be the last user message id")

    chat_messages = [{"role": m.role, "content": m.content} for m in messages]
    if payload.system_prompt and payload.system_prompt.strip():
        chat_messages.insert(0, {"role": "system", "content": payload.system_prompt.strip()})
    llama = llm_runner.get_llama(model)

    def event_gen():
        assistant_text_parts: list[str] = []
        tokens_used = 0
        try:
            yield {"event": "start", "data": ""}
            for chunk in llama.create_chat_completion(
                messages=chat_messages,
                stream=True,
                temperature=payload.temperature,
                max_tokens=payload.max_tokens,
                top_p=payload.top_p,
                top_k=payload.top_k,
                repeat_penalty=payload.repeat_penalty,
            ):
                delta = chunk["choices"][0]["delta"].get("content") or ""
                if delta:
                    assistant_text_parts.append(delta)
                    yield {"event": "token", "data": delta}
            final_text = "".join(assistant_text_parts).strip()
            if final_text:
                try:
                    token_ids = llama.tokenize(final_text.encode("utf-8"), add_bos=False)
                    tokens_used = len(token_ids)
                except Exception:
                    tokens_used = max(1, len(final_text) // 4)  # fallback approximation
                m = Message(chat_id=chat.id, role="assistant", content=final_text, tokens_used=tokens_used)
                db.add(m)
                db.commit()
            yield {"event": "done", "data": str(tokens_used)}
        except Exception as e:
            db.rollback()
            yield {"event": "error", "data": str(e)}

    return EventSourceResponse(event_gen())


@router.get("/{chat_id}/stream")
def stream_assistant_get(
    chat_id: int,
    after_message_id: int = Query(..., alias="after_message_id"),
    temperature: float = Query(0.7),
    max_tokens: int = Query(512),
    top_p: float = Query(0.95),
    top_k: int = Query(40),
    repeat_penalty: float = Query(1.1),
    system_prompt: str | None = Query(None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    payload = StreamParamsIn(
        after_message_id=after_message_id,
        temperature=temperature,
        max_tokens=max_tokens,
        top_p=top_p,
        top_k=top_k,
        repeat_penalty=repeat_penalty,
        system_prompt=system_prompt,
    )
    return _stream_assistant_impl(chat_id, payload, user, db)


@router.post("/{chat_id}/stream")
def stream_assistant_post(
    chat_id: int,
    payload: StreamParamsIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return _stream_assistant_impl(chat_id, payload, user, db)

