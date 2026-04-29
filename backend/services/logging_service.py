import uuid
import time
from models.orm import LogORM
from sqlalchemy.ext.asyncio import AsyncSession

async def add_operation_log(
    db: AsyncSession, 
    device_name: str, 
    api_path: str, 
    parameters: str, 
    result: str
):
    log_id = f"LOG-{str(uuid.uuid4())[:8].upper()}"
    new_log = LogORM(
        id=str(uuid.uuid4()),
        log_id=log_id,
        device_name=device_name,
        api_path=api_path,
        parameters=parameters,
        result="成功" if "成功" in result else result,
        timestamp=int(time.time() * 1000)
    )
    db.add(new_log)
    await db.commit()
