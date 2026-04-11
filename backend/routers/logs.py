from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import func
from models.db import get_db
from models.orm import LogORM
from models.schemas import LogResponse, LogCreate, LogListResponse
import uuid

router = APIRouter(prefix="/logs", tags=["logs"])

@router.get("", response_model=LogListResponse)
async def get_logs(page: int = Query(1, ge=1), size: int = Query(15, ge=1, le=100), db: AsyncSession = Depends(get_db)):
    skip = (page - 1) * size
    
    # Get total count
    count_query = select(func.count()).select_from(LogORM)
    total_result = await db.execute(count_query)
    total = total_result.scalar_one()
    
    # Get logs
    logs_query = select(LogORM).order_by(LogORM.timestamp.desc()).offset(skip).limit(size)
    logs_result = await db.execute(logs_query)
    logs = logs_result.scalars().all()
    
    return {"items": logs, "total": total}

@router.post("", response_model=LogResponse)
async def create_log(log: LogCreate, db: AsyncSession = Depends(get_db)):
    db_log = LogORM(
        id=str(uuid.uuid4()),
        log_id=log.log_id,
        device_name=log.device_name,
        api_path=log.api_path,
        parameters=log.parameters,
        result=log.result,
        timestamp=log.timestamp
    )
    db.add(db_log)
    await db.commit()
    await db.refresh(db_log)
    return db_log
