from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from models.db import get_db
from models.orm import LogORM
from models.schemas import LogResponse, LogCreate, LogListResponse
from services.crud import paginate
import uuid

router = APIRouter(prefix="/logs", tags=["logs"])


@router.get("", response_model=LogListResponse)
async def get_logs(page: int = Query(1, ge=1), size: int = Query(15, ge=1, le=100), db: AsyncSession = Depends(get_db)):
    total, logs = await paginate(db, LogORM, page, size, LogORM.timestamp.desc())
    return {"items": logs, "total": total}


@router.post("", response_model=LogResponse)
async def create_log(log: LogCreate, db: AsyncSession = Depends(get_db)):
    db_log = LogORM(id=str(uuid.uuid4()), **log.model_dump())
    db.add(db_log)
    await db.commit()
    await db.refresh(db_log)
    return db_log
