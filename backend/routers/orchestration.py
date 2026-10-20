"""任务编排：编排任务的 CRUD、启停，以及编排产生的「业务预警」列表。"""
import json
import time
import uuid
from types import SimpleNamespace

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.db import get_db
from models.orm import DeviceORM, OrchestrationAlarmORM, OrchestrationTaskORM
from models.schemas import OrchestrationPayload, OrchestrationStatusUpdate
from services import orchestration_engine

router = APIRouter(prefix="/orchestration", tags=["orchestration"])


def _now_ms() -> int:
    return int(time.time() * 1000)


def _card(o: OrchestrationTaskORM) -> dict:
    try:
        nodes = json.loads(o.nodes or "[]")
        edges = json.loads(o.edges or "[]")
    except Exception:
        nodes, edges = [], []
    return {
        "id": o.id,
        "name": o.name,
        "status": o.status,
        "device_id": o.device_id or "",
        "node_count": len(nodes) if isinstance(nodes, list) else 0,
        "edge_count": len(edges) if isinstance(edges, list) else 0,
        "created_at": o.created_at,
        "updated_at": o.updated_at,
    }


@router.get("")
async def list_orchestrations(db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(
        select(OrchestrationTaskORM).order_by(desc(OrchestrationTaskORM.updated_at)))).scalars().all()
    cards = []
    # 设备快照按 device_id 缓存：多张卡片共用一个设备时只查一次库
    task_cache: dict = {}
    async def _tasks_of(device_id: str):
        if device_id not in task_cache:
            tasks = []
            if device_id:
                dev = (await db.execute(
                    select(DeviceORM).where(DeviceORM.device_id == device_id))).scalars().first()
                tasks = orchestration_engine._json(dev.device_tasks) if dev else []
            task_cache[device_id] = tasks if isinstance(tasks, list) else []
        return task_cache[device_id]

    for o in rows:
        card = _card(o)
        try:
            nodes = json.loads(o.nodes or "[]")
            edges = json.loads(o.edges or "[]")
        except Exception:
            nodes, edges = [], []
        issues = orchestration_engine.static_warnings(
            nodes if isinstance(nodes, list) else [],
            edges if isinstance(edges, list) else [],
            await _tasks_of(o.device_id or ""))
        card["issues"] = issues
        card["has_issue"] = bool(issues)
        cards.append(card)
    return {"items": cards, "total": len(cards)}


@router.post("")
async def create_orchestration(payload: OrchestrationPayload, db: AsyncSession = Depends(get_db)):
    if not payload.name or not payload.name.strip():
        raise HTTPException(status_code=400, detail="编排任务名称不能为空")
    now = _now_ms()
    o = OrchestrationTaskORM(
        id=f"orch-{uuid.uuid4()}",
        name=payload.name.strip(),
        # 默认开启：只有显式传 stopped 才停用（前端编辑器也默认勾选「启用」）
        status="stopped" if payload.status == "stopped" else "enabled",
        device_id=payload.device_id or "",
        nodes=json.dumps([n.dict() for n in payload.nodes], ensure_ascii=False),
        edges=json.dumps([e.dict() for e in payload.edges], ensure_ascii=False),
        created_at=now, updated_at=now,
    )
    db.add(o)
    await db.commit()
    await db.refresh(o)
    return _card(o)


@router.get("/alarms")
async def list_orchestration_alarms(
    orchestration_id: str = Query(""),
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
):
    q = select(OrchestrationAlarmORM).order_by(desc(OrchestrationAlarmORM.created_at)).limit(limit)
    if orchestration_id:
        q = q.where(OrchestrationAlarmORM.orchestration_id == orchestration_id)
    rows = (await db.execute(q)).scalars().all()

    def _imgs(o):
        try:
            return json.loads(o.images or "[]")
        except Exception:
            return []

    def _types(o):
        try:
            return json.loads(o.alert_types or "[]")
        except Exception:
            return []

    return {"items": [{
        "id": o.id,
        "orchestration_id": o.orchestration_id,
        "orchestration_name": o.orchestration_name,
        "output_id": o.output_id,
        "output_name": o.output_name,
        "device_name": o.device_name,
        "channelname": o.channelname,
        "alert_types": _types(o),
        "summary": o.summary,
        "images": _imgs(o),
        "created_at": o.created_at,
    } for o in rows], "total": len(rows)}


@router.get("/alert-types")
async def alert_types(hours: int = Query(24, ge=1, le=720), device_name: str = Query("")):
    """近 N 小时各算法告警类型条数：元件库标注 + 校验诊断上下文。

    注意：必须注册在 GET /{orch_id} 之前，否则会被当成 orch_id 抢先匹配。
    """
    return {"items": await orchestration_engine.alert_type_stats(hours=hours, device_name=device_name), "hours": hours}


@router.get("/{orch_id}")
async def get_orchestration(orch_id: str, db: AsyncSession = Depends(get_db)):
    o = await db.get(OrchestrationTaskORM, orch_id)
    if not o:
        raise HTTPException(status_code=404, detail="编排任务不存在")
    try:
        nodes = json.loads(o.nodes or "[]")
        edges = json.loads(o.edges or "[]")
    except Exception:
        nodes, edges = [], []
    return {**_card(o), "nodes": nodes, "edges": edges}


@router.put("/{orch_id}")
async def update_orchestration(orch_id: str, payload: OrchestrationPayload, db: AsyncSession = Depends(get_db)):
    o = await db.get(OrchestrationTaskORM, orch_id)
    if not o:
        raise HTTPException(status_code=404, detail="编排任务不存在")
    if not payload.name or not payload.name.strip():
        raise HTTPException(status_code=400, detail="编排任务名称不能为空")
    o.name = payload.name.strip()
    o.device_id = payload.device_id or ""
    # 编辑保存时默认开启：仅当显式传 stopped 才停用
    o.status = "stopped" if payload.status == "stopped" else "enabled"
    o.nodes = json.dumps([n.dict() for n in payload.nodes], ensure_ascii=False)
    o.edges = json.dumps([e.dict() for e in payload.edges], ensure_ascii=False)
    o.updated_at = _now_ms()
    await db.commit()
    await db.refresh(o)
    return _card(o)


@router.put("/{orch_id}/status")
async def set_orchestration_status(orch_id: str, payload: OrchestrationStatusUpdate, db: AsyncSession = Depends(get_db)):
    o = await db.get(OrchestrationTaskORM, orch_id)
    if not o:
        raise HTTPException(status_code=404, detail="编排任务不存在")
    if payload.status not in ("enabled", "stopped"):
        raise HTTPException(status_code=400, detail="status 只能是 enabled / stopped")
    o.status = payload.status
    o.updated_at = _now_ms()
    await db.commit()
    await db.refresh(o)
    return _card(o)


@router.delete("/{orch_id}")
async def delete_orchestration(orch_id: str, db: AsyncSession = Depends(get_db)):
    o = await db.get(OrchestrationTaskORM, orch_id)
    if not o:
        raise HTTPException(status_code=404, detail="编排任务不存在")
    await db.delete(o)
    await db.commit()
    return {"message": "编排任务已删除"}


@router.post("/diagnose")
async def diagnose_draft(payload: OrchestrationPayload, hours: int = Query(24, ge=1, le=720)):
    """「校验」未保存的草稿：直接按当前画布内容求值（无需先保存）。"""
    draft = SimpleNamespace(id="(draft)", name=payload.name or "(未命名)",
                            status=payload.status or "stopped", device_id=payload.device_id or "",
                            nodes=json.dumps([n.dict() for n in payload.nodes], ensure_ascii=False),
                            edges=json.dumps([e.dict() for e in payload.edges], ensure_ascii=False))
    return await orchestration_engine.diagnose_orchestration(draft, hours=hours)


@router.post("/{orch_id}/diagnose")
async def diagnose_orchestration(orch_id: str, hours: int = Query(24, ge=1, le=720),
                                 db: AsyncSession = Depends(get_db)):
    """「校验」：按编排图逐节点求值，回显命中数与未命中原因（含设备实际告警类型）。"""
    o = await db.get(OrchestrationTaskORM, orch_id)
    if not o:
        raise HTTPException(status_code=404, detail="编排任务不存在")
    return await orchestration_engine.diagnose_orchestration(o, hours=hours)


@router.post("/run")
async def run_orchestrations():
    """手动触发一次全量评估（对所有启用的编排，回看最近时间窗的告警）。用于测试与补算。"""
    result = await orchestration_engine.run_all_enabled()
    return {"result": result, "total": sum(result.values())}
