"""告警反馈闭环业务逻辑。

围绕 AlertORM 的标注字段（feedback_status / feedback_note / feedback_time /
feedback_submitted）实现：筛选项、待标注检索、已标注列表、写标注、提交优化。

约定：
- feedback_status == ''            → 待标注（左侧树/检索只返回这类）
- feedback_status == 'valid'       → 真实告警
- feedback_status == 'false_positive' → 误报
- 检索恒排除已标注项，天然满足需求「已标注不再被检索/展示在左侧」。
"""
import time
import json
from typing import Optional, List, Tuple
from sqlalchemy import select, desc, distinct, func
from sqlalchemy.ext.asyncio import AsyncSession

from models.orm import AlertORM, FeedbackTaskORM

VALID = "valid"
FALSE_POSITIVE = "false_positive"
_ALLOWED_STATUS = {VALID, FALSE_POSITIVE}

# 左/右列表一次性最大展示条数（需求：最大 10 条）
MAX_LIST = 10


def _now_ms() -> int:
    return int(time.time() * 1000)


def _apply_filters(query, device_name: Optional[str], channel: Optional[str], alert_type: Optional[str]):
    """按设备/通道/算法种类(alertType)追加过滤条件。"""
    if device_name:
        query = query.where(AlertORM.deviceName == device_name)
    if channel:
        query = query.where(AlertORM.channel == channel)
    if alert_type:
        query = query.where(AlertORM.alertType == alert_type)
    return query


async def filter_options(db: AsyncSession, device_name: Optional[str] = None) -> dict:
    """返回筛选下拉项：通道列表 + 算法种类(alertType)列表（可按设备限定）。"""
    ch_q = select(distinct(AlertORM.channel))
    ty_q = select(distinct(AlertORM.alertType))
    if device_name:
        ch_q = ch_q.where(AlertORM.deviceName == device_name)
        ty_q = ty_q.where(AlertORM.deviceName == device_name)
    channels = [c for c in (await db.execute(ch_q)).scalars().all() if c]
    alert_types = [t for t in (await db.execute(ty_q)).scalars().all() if t]
    return {"channels": sorted(channels), "alertTypes": sorted(alert_types)}


async def search_pending(
    db: AsyncSession,
    device_name: Optional[str] = None,
    channel: Optional[str] = None,
    alert_type: Optional[str] = None,
    limit: int = MAX_LIST,
) -> List[AlertORM]:
    """检索待标注告警（feedback_status==''），最多 limit 条，按时间倒序。

    已标注数据一律不返回 —— 满足「重新检索时已标注的不应被检索出来」。
    """
    query = select(AlertORM).where((AlertORM.feedback_status == "") | (AlertORM.feedback_status.is_(None)))
    query = _apply_filters(query, device_name, channel, alert_type)
    query = query.order_by(desc(AlertORM.timestamp)).limit(min(limit, MAX_LIST))
    return (await db.execute(query)).scalars().all()


async def list_annotated(
    db: AsyncSession,
    device_name: Optional[str] = None,
    channel: Optional[str] = None,
    alert_type: Optional[str] = None,
    limit: int = MAX_LIST,
) -> List[AlertORM]:
    """已标注告警列表（feedback_status 非空且未提交优化），最多 limit 条，按标注时间倒序。

    已提交优化的告警会从此列表移除 —— 满足「提交后端优化后，界面上的已标注数据清空不显示」。
    """
    query = select(AlertORM).where(
        AlertORM.feedback_status.in_(list(_ALLOWED_STATUS)),
        AlertORM.feedback_submitted == 0,
    )
    query = _apply_filters(query, device_name, channel, alert_type)
    query = query.order_by(desc(AlertORM.feedback_time), desc(AlertORM.timestamp)).limit(min(limit, MAX_LIST))
    return (await db.execute(query)).scalars().all()


async def set_feedback(db: AsyncSession, alert_id: str, status: str, note: str = "") -> Optional[AlertORM]:
    """写入/更新一条告警的标注（支持重新标注）。status 非法或告警不存在返回 None。

    重新标注会清空 feedback_submitted，使其可再次纳入优化提交。
    """
    if status not in _ALLOWED_STATUS:
        return None
    alert = await db.get(AlertORM, alert_id)
    if not alert:
        return None
    alert.feedback_status = status
    alert.feedback_note = note or ""
    alert.feedback_time = _now_ms()
    alert.feedback_submitted = 0  # 重新标注后允许再次提交优化
    await db.commit()
    await db.refresh(alert)
    return alert


async def submit_optimization(db: AsyncSession, alert_ids: Optional[List[str]] = None) -> dict:
    """提交已标注告警做后端分类调优（Case1/2/3）。

    委托 optimization_service.run_optimization：按设备/任务定位并分三类优化，
    成功下发后把对应告警置 feedback_submitted=1。返回结构化摘要（含向后兼容的
    submitted / by_type / alert_ids，供路由层拼提示语）。

    延迟导入 optimization_service，避免与 device_service/task_service 潜在循环依赖。
    """
    from services import optimization_service
    return await optimization_service.run_optimization(db, alert_ids)


# ── 调优下发运维记录（任务运维列表） ──────────────────────────────────────
async def list_feedback_tasks(
    db: AsyncSession, device_name: Optional[str] = None, page: int = 1, size: int = 10
) -> Tuple[int, List[FeedbackTaskORM]]:
    """分页返回调优下发运维记录，按创建时间倒序（可按设备限定）。"""
    base = select(FeedbackTaskORM)
    count_q = select(func.count()).select_from(FeedbackTaskORM)
    if device_name:
        base = base.where(FeedbackTaskORM.device_name == device_name)
        count_q = count_q.where(FeedbackTaskORM.device_name == device_name)
    total = (await db.execute(count_q)).scalar_one()
    q = base.order_by(desc(FeedbackTaskORM.created_at)).offset((page - 1) * size).limit(size)
    items = (await db.execute(q)).scalars().all()
    return total, items


async def get_feedback_task(db: AsyncSession, task_id: str) -> Optional[dict]:
    """单条运维记录详情，附带反序列化后的标注告警快照（供翻页查看）。不存在返回 None。"""
    rec = await db.get(FeedbackTaskORM, task_id)
    if not rec:
        return None
    try:
        alerts = json.loads(rec.alerts_snapshot or "[]")
    except (ValueError, TypeError):
        alerts = []
    return {
        "id": rec.id, "batch_id": rec.batch_id, "device_name": rec.device_name,
        "task_name": rec.task_name, "channel": rec.channel, "category": rec.category,
        "case_key": rec.case_key, "action": rec.action, "result": rec.result,
        "detail": rec.detail, "alert_count": rec.alert_count, "log_id": rec.log_id,
        "created_at": rec.created_at, "alerts": alerts,
    }
