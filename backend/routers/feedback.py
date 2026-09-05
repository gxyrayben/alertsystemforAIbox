"""告警反馈闭环 —— 薄路由层（HTTP 关注点），业务逻辑在 services/feedback_service.py。"""
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from models.db import get_db
from models.schemas import (
    Alert, FeedbackRequest, OptimizationSubmit,
    FeedbackTaskListResponse, FeedbackTaskDetail,
)
from services import feedback_service as fb

router = APIRouter(prefix="/feedback", tags=["feedback"])


@router.get("/options")
async def get_options(deviceName: Optional[str] = None, db: AsyncSession = Depends(get_db)):
    """筛选下拉项：通道 + 算法种类（可按设备限定）。"""
    return await fb.filter_options(db, deviceName)


@router.get("/pending", response_model=List[Alert])
async def get_pending(
    deviceName: Optional[str] = None,
    channel: Optional[str] = None,
    alertType: Optional[str] = None,
    limit: int = Query(fb.MAX_LIST, ge=1, le=fb.MAX_LIST),
    db: AsyncSession = Depends(get_db),
):
    """待标注检索队列（左侧树），最多 10 条，已标注项不返回。"""
    return await fb.search_pending(db, deviceName, channel, alertType, limit)


@router.get("/annotated", response_model=List[Alert])
async def get_annotated(
    deviceName: Optional[str] = None,
    channel: Optional[str] = None,
    alertType: Optional[str] = None,
    limit: int = Query(fb.MAX_LIST, ge=1, le=fb.MAX_LIST),
    db: AsyncSession = Depends(get_db),
):
    """已标注列表（右侧），最多 10 条。"""
    return await fb.list_annotated(db, deviceName, channel, alertType, limit)


@router.get("/tasks", response_model=FeedbackTaskListResponse)
async def list_feedback_tasks(
    deviceName: Optional[str] = None,
    page: int = Query(1, ge=1),
    size: int = Query(10, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """调优下发运维记录列表（任务运维列表），分页，按创建时间倒序。"""
    total, items = await fb.list_feedback_tasks(db, deviceName, page, size)
    return {"items": items, "total": total}


@router.get("/tasks/{task_id}", response_model=FeedbackTaskDetail)
async def get_feedback_task(task_id: str, db: AsyncSession = Depends(get_db)):
    """单条运维记录详情，含标注告警快照供翻页查看。"""
    rec = await fb.get_feedback_task(db, task_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="运维记录不存在")
    return rec


@router.post("/alerts/{alert_id}", response_model=Alert)
async def annotate(alert_id: str, payload: FeedbackRequest, db: AsyncSession = Depends(get_db)):
    """标注/重新标注一条告警为真实告警或误报。"""
    alert = await fb.set_feedback(db, alert_id, payload.status, payload.note or "")
    if alert is None:
        raise HTTPException(status_code=400, detail="标注失败：告警不存在或状态非法（应为 valid / false_positive）")
    return alert


@router.post("/submit-optimization")
async def submit_optimization(payload: OptimizationSubmit, db: AsyncSession = Depends(get_db)):
    """提交已标注告警做后端分类调优（Case1 大模型 Prompt / Case2 小模型参数 / Case3 小+大）。"""
    result = await fb.submit_optimization(db, payload.alert_ids)
    deployed = result.get("deployed", 0)
    skipped = result.get("skipped", 0)
    if deployed == 0 and skipped == 0:
        return {**result, "message": "没有可优化的已标注数据（可能均已提交）。"}

    bc = result.get("by_case", {})
    parts = []
    if bc.get("Case1"):
        parts.append(f"大模型×{bc['Case1']} 下发 Prompt")
    if bc.get("Case2"):
        parts.append(f"小模型×{bc['Case2']} 调参数")
    if bc.get("Case3"):
        parts.append(f"小+大×{bc['Case3']} 调参数+Prompt")
    head = f"已优化下发 {deployed} 条（{'、'.join(parts)}）" if parts else "本轮无成功下发"
    tail = f"；跳过 {skipped} 条（离线/未定位/无需调整）" if skipped else ""
    return {**result, "message": head + tail + "。"}
