import uuid
import time
from models.orm import LogORM
from sqlalchemy.ext.asyncio import AsyncSession


async def add_operation_log(db: AsyncSession, device_name: str, api_path: str, parameters: str, result: str, task_name: str = "") -> str:
    """写入一条操作日志，返回其 log_id（便于调用方回链，如反馈调优运维记录）。"""
    log_id = f"LOG-{str(uuid.uuid4())[:8].upper()}"
    new_log = LogORM(
        id=str(uuid.uuid4()),
        log_id=log_id,
        device_name=device_name,
        api_path=api_path,
        parameters=parameters,
        result=result,
        timestamp=int(time.time() * 1000),
        task_name=task_name or "",
    )
    db.add(new_log)
    await db.commit()
    return log_id
