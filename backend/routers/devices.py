from fastapi import APIRouter, Depends, HTTPException, Query
from typing import List
import uuid
import json
import httpx
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from models.db import get_db
from models.schemas import Device, AgentCreate, AgentTaskDeploy
from models.orm import DeviceORM
from services.device_service import DeviceService, apply_device_snapshot, _parse_agents
from services import task_builders as tb
from services.crud import get_or_404

router = APIRouter(prefix="/devices", tags=["devices"])

# 由客户端提交、但由系统内部管理（不可直接写入）的字段
_MANAGED_FIELDS = {"id", "channels", "device_tasks", "available_algorithms", "algorithms_ability","status", "session_id", "agents"}

_AGENT_TIMEOUT = 15.0


@router.get("", response_model=List[Device])
async def get_devices(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(DeviceORM))
    return result.scalars().all()


@router.post("", response_model=Device)
async def create_device(device: Device, db: AsyncSession = Depends(get_db)):
    device_data = device.dict(exclude=_MANAGED_FIELDS)
    snapshot = await DeviceService.fetch_device_data(device.ip, device.port, device.username, device.password)

    new_device = DeviceORM(id=f"dev-{uuid.uuid4()}", **device_data)
    apply_device_snapshot(new_device, *snapshot)
    db.add(new_device)
    await db.commit()
    await db.refresh(new_device)
    return new_device


@router.post("/{device_id}/fetch", response_model=Device)
async def manual_fetch_device(device_id: str, db: AsyncSession = Depends(get_db)):
    device_obj = await get_or_404(db, DeviceORM, device_id, "Device")
    snapshot = await DeviceService.fetch_device_data(
        device_obj.ip, device_obj.port, device_obj.username, device_obj.password, device_obj.session_id
    )
    apply_device_snapshot(device_obj, *snapshot)
    await db.commit()
    await db.refresh(device_obj)
    return device_obj


async def _refresh_agents(device_obj: DeviceORM, db: AsyncSession) -> List[dict]:
    """实时从设备拉取智能体算法列表并持久化到 device.agents。设备离线/失败抛 HTTPException。"""
    async with httpx.AsyncClient(timeout=_AGENT_TIMEOUT) as client:
        data = await DeviceService.list_agents(client, device_obj, db)
    if data is None:
        raise HTTPException(status_code=502, detail=f"设备「{device_obj.name}」离线或不可达")
    if data.get("code") != 0:
        raise HTTPException(status_code=502, detail=data.get("message", "查询智能体算法失败"))
    agents = _parse_agents(data.get("data", {}).get("list", []))
    device_obj.agents = json.dumps(agents, ensure_ascii=False)
    await db.commit()
    return agents


@router.get("/{device_id}/agents")
async def list_device_agents(device_id: str, refresh: bool = Query(True), db: AsyncSession = Depends(get_db)):
    """智能体算法列表。

    refresh=True（默认，刷新按钮）：实时从设备拉取并回写快照，返回最新列表；
    refresh=False（面板下拉兜底）：直接返回本地快照 device.agents，离线也可用、不触网。
    """
    device_obj = await get_or_404(db, DeviceORM, device_id, "Device")
    if not refresh:
        agents = json.loads(device_obj.agents or "[]")
        return {"count": len(agents), "agents": agents}
    agents = await _refresh_agents(device_obj, db)
    return {"count": len(agents), "agents": agents}


@router.post("/{device_id}/deploy/agent-task")
async def deploy_agent_task(device_id: str, payload: AgentTaskDeploy, db: AsyncSession = Depends(get_db)):
    """下发【纯大模型智能体任务】(agent_real_task)，最多关联 4 个智能体，每个智能体单 ROI。

    流程：实时拉取设备智能体列表建索引（离线报 502）→ 校验数量(1~4)与逐个存在 →
    逐个富化(缺省 prompt/alarm_type 用设备值兜底；非描述型强制关闭 filter；空 ROI 用全画面) →
    build_agent_real_task_payload → create_task。
    """
    device_obj = await get_or_404(db, DeviceORM, device_id, "Device")
    if not (1 <= len(payload.agents) <= 4):
        raise HTTPException(status_code=400, detail="智能体任务需关联 1~4 个智能体算法")

    async with httpx.AsyncClient(timeout=_AGENT_TIMEOUT) as client:
        data = await DeviceService.list_agents(client, device_obj, db)
        if data is None:
            raise HTTPException(status_code=502, detail=f"设备「{device_obj.name}」离线或不可达，无法下发任务")
        if data.get("code") != 0:
            raise HTTPException(status_code=502, detail=data.get("message", "查询智能体算法失败"))
        # 按 event_id / agent_id 建索引，供存在校验与字段兜底
        index = {}
        for a in data.get("data", {}).get("list", []):
            for key in (a.get("event_id"), a.get("agent_id")):
                if key is not None:
                    index[str(key)] = a

        enriched = []
        for item in payload.agents:
            dev_agent = index.get(str(item.event_id))
            if dev_agent is None:
                raise HTTPException(
                    status_code=400,
                    detail=f"设备上不存在智能体算法「{item.event_tag or item.event_id}」，请先在『智能体资产库』新建。")
            alarm_type = item.alarm_type or dev_agent.get("alarm_type") or "freeform"
            is_attr = (alarm_type or "").lower() == "freeform"
            area = tb.full_frame_area() if not item.roiPoints else {
                "areaId": 1, "areaName": "检测区", "areaType": "POLYGON", "points": item.roiPoints,
            }
            enriched.append({
                "event_id": item.event_id,
                "event_tag": item.event_tag or dev_agent.get("event_tag") or str(item.event_id),
                "alarm_type": alarm_type,
                "prompt": item.prompt if item.prompt else dev_agent.get("prompt", ""),
                "alarm_condition": item.alarm_condition,
                "filter_enable": bool(item.filter_enable) if is_attr else False,
                "filter_keywords": item.filter_keywords if is_attr else "",
                "area": area,
            })

        task_payload = tb.build_agent_real_task_payload(
            payload.task_name, payload.channel_device_id, enriched,
            analysis_interval=payload.analysis_interval)
        result = await DeviceService.create_task(client, device_obj, db, task_payload)

    if result is None:
        raise HTTPException(status_code=502, detail=f"设备「{device_obj.name}」离线或不可达，任务下发失败")
    if result.get("code") != 0:
        raise HTTPException(status_code=502, detail=result.get("message", "任务下发失败"))
    task_id = result.get("data", {}).get("task_id")
    return {"success": True, "task_id": task_id,
            "message": f"智能体任务「{payload.task_name}」已下发（关联 {len(enriched)} 个智能体）"}


@router.post("/{device_id}/agents")
async def create_device_agent(device_id: str, agent: AgentCreate, db: AsyncSession = Depends(get_db)):
    """新增智能体：构造 agent_item 下发到设备，成功后重新拉取并回写快照，返回最新列表。"""
    device_obj = await get_or_404(db, DeviceORM, device_id, "Device")
    body = tb.build_agent_item_payload(
        agent.event_id, agent.event_tag, agent.prompt, agent.alarm_type, agent.alarm_condition
    )
    async with httpx.AsyncClient(timeout=_AGENT_TIMEOUT) as client:
        data = await DeviceService.create_agent(client, device_obj, db, body)
    if data is None:
        raise HTTPException(status_code=502, detail=f"设备「{device_obj.name}」离线或不可达，无法新建智能体算法")
    if data.get("code") != 0:
        raise HTTPException(status_code=502, detail=data.get("message", "新建智能体算法失败"))
    agents = await _refresh_agents(device_obj, db)
    return {"count": len(agents), "agents": agents,
            "message": f"智能体算法「{agent.event_tag}」已下发到设备"}


@router.put("/{device_id}", response_model=Device)
async def update_device(device_id: str, updated_device: Device, db: AsyncSession = Depends(get_db)):
    device_obj = await get_or_404(db, DeviceORM, device_id, "Device")
    update_data = updated_device.dict(exclude=_MANAGED_FIELDS)

    # 连接关键参数变化时才重新拉取设备数据
    connection_fields = ("ip", "port", "username", "password")
    if any(update_data.get(f) != getattr(device_obj, f) for f in connection_fields):
        snapshot = await DeviceService.fetch_device_data(
            update_data.get("ip"), update_data.get("port"), update_data.get("username"), update_data.get("password")
        )
        apply_device_snapshot(device_obj, *snapshot)

    for key, value in update_data.items():
        setattr(device_obj, key, value)
    await db.commit()
    await db.refresh(device_obj)
    return device_obj


@router.delete("/{device_id}")
async def delete_device(device_id: str, db: AsyncSession = Depends(get_db)):
    device_obj = await db.get(DeviceORM, device_id)
    if device_obj:
        await db.delete(device_obj)
        await db.commit()
    return {"message": "Device deleted"}
