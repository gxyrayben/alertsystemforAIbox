"""通用数据库助手，消除各 router 中重复的『按 id 查询否则 404』与分页逻辑。"""
from typing import Tuple, Type, List, Any
from fastapi import HTTPException
from sqlalchemy.future import select
from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncSession


async def get_or_404(db: AsyncSession, model: Type[Any], obj_id: str, name: str = "Resource"):
    """按主键获取对象，不存在时抛出 404。"""
    obj = await db.get(model, obj_id)
    if not obj:
        raise HTTPException(status_code=404, detail=f"{name} not found")
    return obj


async def paginate(
    db: AsyncSession,
    model: Type[Any],
    page: int,
    size: int,
    order_by,
) -> Tuple[int, List[Any]]:
    """通用分页：返回 (总数, 当前页对象列表)。"""
    total = (await db.execute(select(func.count()).select_from(model))).scalar_one()

    query = select(model).order_by(order_by).offset((page - 1) * size).limit(size)
    items = (await db.execute(query)).scalars().all()
    return total, items
