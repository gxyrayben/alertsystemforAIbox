from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
import uuid
import time

from models.db import get_db
from models.orm import TaskORM
from models.schemas import TaskCreate, TaskUpdate, TaskResponse
from services.task_service import perform_auto_tune_workflow
from services.crud import get_or_404, paginate

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


@router.get("")
async def list_tasks(page: int = Query(1, ge=1), size: int = Query(10, ge=1), db: AsyncSession = Depends(get_db)):
    total, tasks = await paginate(db, TaskORM, page, size, TaskORM.created_at.desc())
    return {"total": total, "tasks": [TaskResponse.model_validate(t) for t in tasks]}


@router.post("", response_model=TaskResponse)
async def create_task(task: TaskCreate, db: AsyncSession = Depends(get_db)):
    task_id = f"TASK-{str(uuid.uuid4())[:8].upper()}"
    current_time = int(time.time() * 1000)
    new_task = TaskORM(
        id=task_id,
        **task.model_dump(),
        created_at=current_time,
        last_processed_time=current_time,
    )
    db.add(new_task)
    await db.commit()
    await db.refresh(new_task)
    return new_task


@router.put("/{task_id}", response_model=TaskResponse)
async def update_task(task_id: str, task_update: TaskUpdate, db: AsyncSession = Depends(get_db)):
    task_obj = await get_or_404(db, TaskORM, task_id, "Task")
    for key, value in task_update.model_dump(exclude_unset=True).items():
        setattr(task_obj, key, value)
    await db.commit()
    await db.refresh(task_obj)
    return task_obj


@router.delete("/{task_id}")
async def delete_task(task_id: str, db: AsyncSession = Depends(get_db)):
    task_obj = await get_or_404(db, TaskORM, task_id, "Task")
    await db.delete(task_obj)
    await db.commit()
    return {"message": "Task deleted"}


@router.post("/{task_id}/auto_tune")
async def auto_tune_task(task_id: str, db: AsyncSession = Depends(get_db)):
    """手动触发某任务的自动调优流程。"""
    task_obj = await get_or_404(db, TaskORM, task_id, "Task")

    # 手动触发时最多取最近 10 条告警（非调优任务取 1 条）
    success, result_info = await perform_auto_tune_workflow(db, task_obj, alert_limit=10)
    if not success:
        raise HTTPException(status_code=400, detail=result_info)
    return result_info
