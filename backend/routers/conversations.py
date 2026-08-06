from fastapi import APIRouter, Depends, HTTPException
import json
from typing import List
from sqlalchemy.ext.asyncio import AsyncSession
from models.db import get_db
from models.orm import ConversationORM
from models.schemas import ConversationResponse, ConversationDetail
from services import conversation_service as convo

router = APIRouter(prefix="/conversations", tags=["conversations"])


def _parse_tables(raw: str) -> list:
    try:
        data = json.loads(raw or "[]")
        return data if isinstance(data, list) else []
    except Exception:
        return []


@router.get("", response_model=List[ConversationResponse])
async def list_conversations(db: AsyncSession = Depends(get_db)):
    return await convo.list_conversations(db)


@router.get("/{conversation_id}", response_model=ConversationDetail)
async def get_conversation(conversation_id: str, db: AsyncSession = Depends(get_db)):
    conv = await db.get(ConversationORM, conversation_id)
    if not conv:
        raise HTTPException(status_code=404, detail="会话不存在")
    messages = await convo.get_messages(db, conversation_id)
    return {
        "id": conv.id,
        "title": conv.title,
        "summary": conv.summary or "",
        "created_at": conv.created_at,
        "updated_at": conv.updated_at,
        "messages": [
            {"id": m.id, "role": m.role, "text": m.text,
             "tables": _parse_tables(m.tables), "created_at": m.created_at}
            for m in messages
        ],
    }


@router.delete("/{conversation_id}")
async def delete_conversation(conversation_id: str, db: AsyncSession = Depends(get_db)):
    await convo.delete_conversation(db, conversation_id)
    return {"message": "Conversation deleted"}
