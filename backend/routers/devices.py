from fastapi import APIRouter, Depends, HTTPException
from typing import List
import uuid
import json
import httpx
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from models.db import get_db
from models.schemas import Device, AgentCreate
from models.orm import DeviceORM
from services.device_service import DeviceService, apply_device_snapshot, _parse_agents
from services import task_builders as tb
from services.crud import get_or_404

router = APIRouter(prefix="/devices", tags=["devices"])

# 由客户端提交、但由系统内部管理（不可直接写入）的字段
_MANAGED_FIELDS = {"id", "channels", "device_tasks", "available_algorithms", "status", "session_id", "agents"}

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
async def list_device_agents(device_id: str, db: AsyncSession = Depends(get_db)):
    """刷新按钮：实时从设备拉取智能体算法并回写快照，返回最新列表。"""
    device_obj = await get_or_404(db, DeviceORM, device_id, "Device")
    agents = await _refresh_agents(device_obj, db)
    return {"count": len(agents), "agents": agents}


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
