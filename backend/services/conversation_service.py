"""会话持久化服务：会话与消息的读写。"""
import uuid
import time
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession
from models.orm import ConversationORM, MessageORM


def _now() -> int:
    return int(time.time() * 1000)


async def ensure_conversation(db: AsyncSession, conversation_id: str, title_hint: str = "") -> ConversationORM:
    """按 id 获取会话，不存在则创建。title_hint 用于新会话自动命名（取前 20 字）。"""
    conv = None
    if conversation_id:
        conv = (await db.execute(
            select(ConversationORM).where(ConversationORM.id == conversation_id)
        )).scalar_one_or_none()

    if conv:
        return conv

    now = _now()
    title = (title_hint or "新会话").strip()[:20] or "新会话"
    conv = ConversationORM(
        id=conversation_id or f"conv-{uuid.uuid4()}",
        title=title,
        created_at=now,
        updated_at=now,
    )
    db.add(conv)
    await db.flush()
    return conv


async def add_message(db: AsyncSession, conversation_id: str, role: str, text: str, tables: str = "") -> MessageORM:
    msg = MessageORM(
        id=f"msg-{uuid.uuid4()}",
        conversation_id=conversation_id,
        role=role,
        text=text or "",
        tables=tables or "",
        created_at=_now(),
    )
    db.add(msg)
    return msg


async def touch_conversation(db: AsyncSession, conv: ConversationORM) -> None:
    conv.updated_at = _now()


async def update_summary(db: AsyncSession, conv: ConversationORM, summary: str) -> None:
    """更新会话的滚动记忆/总结。"""
    conv.summary = summary or ""


async def list_conversations(db: AsyncSession):
    return (await db.execute(
        select(ConversationORM).order_by(ConversationORM.updated_at.desc())
    )).scalars().all()


async def get_messages(db: AsyncSession, conversation_id: str):
    return (await db.execute(
        select(MessageORM)
        .where(MessageORM.conversation_id == conversation_id)
        .order_by(MessageORM.created_at.asc())
    )).scalars().all()


async def delete_conversation(db: AsyncSession, conversation_id: str) -> None:
    await db.execute(delete(MessageORM).where(MessageORM.conversation_id == conversation_id))
    await db.execute(delete(ConversationORM).where(ConversationORM.id == conversation_id))
    await db.commit()
