"""布控任务【参数模板库】CRUD 路由（内联实现，风格对齐 routers/tasks.py）。

模板 config 在 API 层是 dict、在 ORM 层存 JSON 字符串，序列化/反序列化都在本路由内完成。
模板仅存参数快照，不下发设备；套用（灌面板 → 用户确认 → 部署）由前端与 agent_tools.apply_task_template 承担。
"""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from typing import List
import uuid
import time
import json

from models.db import get_db
from models.orm import TaskTemplateORM
from models.schemas import TaskTemplateCreate, TaskTemplateUpdate, TaskTemplateResponse
from services.crud import get_or_404

router = APIRouter(prefix="/task-templates", tags=["task_templates"])


def _serialize(tpl: TaskTemplateORM) -> dict:
    """ORM → API：config 字段由 JSON 字符串反序列化为 dict（坏数据兜底为空对象）。"""
    try:
        cfg = json.loads(tpl.config or "{}")
    except Exception:
        cfg = {}
    return {
        "id": tpl.id, "name": tpl.name, "task_mode": tpl.task_mode,
        "event_type": tpl.event_type, "config": cfg, "description": tpl.description,
        "created_at": tpl.created_at, "updated_at": tpl.updated_at,
    }


@router.get("", response_model=List[TaskTemplateResponse])
async def list_task_templates(db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(
        select(TaskTemplateORM).order_by(TaskTemplateORM.updated_at.desc())
    )).scalars().all()
    return [_serialize(t) for t in rows]


@router.post("", response_model=TaskTemplateResponse)
async def create_task_template(tpl: TaskTemplateCreate, db: AsyncSession = Depends(get_db)):
    now = int(time.time() * 1000)
    obj = TaskTemplateORM(
        id=f"tpl-{uuid.uuid4()}",
        name=tpl.name, task_mode=tpl.task_mode, event_type=tpl.event_type,
        config=json.dumps(tpl.config or {}, ensure_ascii=False),
        description=tpl.description, created_at=now, updated_at=now,
    )
    db.add(obj)
    await db.commit()
    await db.refresh(obj)
    return _serialize(obj)


@router.get("/{tpl_id}", response_model=TaskTemplateResponse)
async def get_task_template(tpl_id: str, db: AsyncSession = Depends(get_db)):
    obj = await get_or_404(db, TaskTemplateORM, tpl_id, "TaskTemplate")
    return _serialize(obj)


@router.put("/{tpl_id}", response_model=TaskTemplateResponse)
async def update_task_template(tpl_id: str, upd: TaskTemplateUpdate, db: AsyncSession = Depends(get_db)):
    obj = await get_or_404(db, TaskTemplateORM, tpl_id, "TaskTemplate")
    data = upd.model_dump(exclude_unset=True)
    if data.get("config") is not None:
        data["config"] = json.dumps(data["config"], ensure_ascii=False)
    for key, value in data.items():
        setattr(obj, key, value)
    obj.updated_at = int(time.time() * 1000)
    await db.commit()
    await db.refresh(obj)
    return _serialize(obj)


@router.delete("/{tpl_id}")
async def delete_task_template(tpl_id: str, db: AsyncSession = Depends(get_db)):
    obj = await get_or_404(db, TaskTemplateORM, tpl_id, "TaskTemplate")
    await db.delete(obj)
    await db.commit()
    return {"message": "TaskTemplate deleted"}
