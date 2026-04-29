from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import func
import uuid
import time

from models.db import get_db
from models.orm import TaskORM
from models.schemas import TaskCreate, TaskUpdate, TaskResponse
from services.task_service import perform_auto_tune_workflow

router = APIRouter(prefix="/api/tasks", tags=["tasks"])

@router.get("")
async def list_tasks(page: int = Query(1, ge=1), size: int = Query(10, ge=1), db: AsyncSession = Depends(get_db)):
    offset = (page - 1) * size
    
    total_query = select(func.count()).select_from(TaskORM)
    total_result = await db.execute(total_query)
    total = total_result.scalar()

    query = select(TaskORM).order_by(TaskORM.created_at.desc()).offset(offset).limit(size)
    result = await db.execute(query)
    tasks = result.scalars().all()
    
    return {"total": total, "tasks": [TaskResponse.model_validate(t) for t in tasks]}

@router.post("", response_model=TaskResponse)
async def create_task(task: TaskCreate, db: AsyncSession = Depends(get_db)):
    task_id = f"TASK-{str(uuid.uuid4())[:8].upper()}"
    current_time = int(time.time() * 1000)
    new_task = TaskORM(
        id=task_id,
        **task.model_dump(),
        created_at=current_time,
        last_processed_time=current_time
    )
    db.add(new_task)
    await db.commit()
    await db.refresh(new_task)
    return new_task

@router.put("/{task_id}", response_model=TaskResponse)
async def update_task(task_id: str, task_update: TaskUpdate, db: AsyncSession = Depends(get_db)):
    query = select(TaskORM).where(TaskORM.id == task_id)
    result = await db.execute(query)
    task_obj = result.scalars().first()
    if not task_obj:
        raise HTTPException(status_code=404, detail="Task not found")
        
    update_data = task_update.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(task_obj, key, value)
        
    await db.commit()
    await db.refresh(task_obj)
    return task_obj

@router.delete("/{task_id}")
async def delete_task(task_id: str, db: AsyncSession = Depends(get_db)):
    query = select(TaskORM).where(TaskORM.id == task_id)
    result = await db.execute(query)
    task_obj = result.scalars().first()
    if not task_obj:
        raise HTTPException(status_code=404, detail="Task not found")
        
    await db.delete(task_obj)
    await db.commit()
    return {"message": "Task deleted"}

@router.post("/{task_id}/auto_tune")
async def auto_tune_task(task_id: str, db: AsyncSession = Depends(get_db)):
    """
    Manually trigger the auto-tune workflow for a specific task.
    """
    query = select(TaskORM).where(TaskORM.id == task_id)
    result = await db.execute(query)
    task_obj = result.scalars().first()
    if not task_obj:
        raise HTTPException(status_code=404, detail="Task not found")

    # For manual trigger, we fetch up to 10 latest alerts (or 1 if it's not a tuning task)
    success, result_info = await perform_auto_tune_workflow(db, task_obj, alert_limit=10)
    
    if not success:
        raise HTTPException(status_code=400, detail=result_info)

    return result_info
