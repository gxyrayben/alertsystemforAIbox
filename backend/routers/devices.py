from fastapi import APIRouter, Depends, HTTPException, Query
from typing import List
import uuid
import json
import httpx
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.exc import IntegrityError
from models.db import get_db
from models.schemas import Device, AgentCreate, AgentTaskDeploy, SmallModelTaskDeploy, CombinedTaskDeploy, WarehouseTaskDeploy
from models.orm import DeviceORM
from services.device_service import DeviceService, apply_device_snapshot, _parse_agents
from services import task_builders as tb
from services import task_validation
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

    # 插入前先查重：device_id 有唯一约束，重复会在 commit 时抛 IntegrityError（500）。
    # 提前快速失败，返回可读的 409，同时省掉无谓的设备登录/快照拉取。
    existing = await db.execute(select(DeviceORM).where(DeviceORM.device_id == device.device_id))
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail=f"设备业务 ID「{device.device_id}」已存在，请勿重复添加")

    snapshot = await DeviceService.fetch_device_data(device.ip, device.port, device.username, device.password)

    new_device = DeviceORM(id=f"dev-{uuid.uuid4()}", **device_data)
    apply_device_snapshot(new_device, *snapshot)
    db.add(new_device)
    try:
        await db.commit()
    except IntegrityError:
        # 并发场景下仍可能漏过上面的查重，兜底回滚并返回友好提示，避免 500
        await db.rollback()
        raise HTTPException(status_code=409, detail=f"设备业务 ID「{device.device_id}」已存在，请勿重复添加")
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


async def _resnapshot(device_obj: DeviceORM, db: AsyncSession) -> None:
    """下发成功后 best-effort 重新拉取设备快照（channels/tasks/algorithms/agents 回写 ORM）。

    复用 manual_fetch_device 的体，整块吞异常：快照刷新失败不应掩盖『下发已成功』这一事实。
    刷新后 device_tasks 里烘焙的查看回填 detail 立即与设备一致，供随后『查看/回填』使用。
    """
    try:
        snapshot = await DeviceService.fetch_device_data(
            device_obj.ip, device_obj.port, device_obj.username, device_obj.password, device_obj.session_id
        )
        apply_device_snapshot(device_obj, *snapshot)
        await db.commit()
    except Exception as e:
        print(f"_resnapshot skipped for {device_obj.name}: {e}")


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
        index = tb.index_agents(data)

        enriched = []
        for item in payload.agents:
            dev_agent = index.get(str(item.event_id))
            if dev_agent is None:
                raise HTTPException(
                    status_code=400,
                    detail=f"设备上不存在智能体算法「{item.event_tag or item.event_id}」，请先在『智能体资产库』新建。")
            alarm_type = item.alarm_type or dev_agent.get("alarm_type") or "freeform"
            is_attr = (alarm_type or "").lower() == "freeform"
            area = tb.roi_area(item.roiPoints)
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


@router.post("/{device_id}/deploy/smallmodel-task")
async def deploy_smallmodel_task(device_id: str, payload: SmallModelTaskDeploy, db: AsyncSession = Depends(get_db)):
    """下发【纯小模型算法仓任务】(single_point_task + monitor，无 agent_llm)。

    面板/对话共用；阈值/目标/时长/冷却/抽帧/ROI 等参数均由请求体针对性携带，经共享
    deploy_warehouse_task 两步下发；成功后 best-effort 重刷快照使查看回填即时一致。
    """
    device_obj = await get_or_404(db, DeviceORM, device_id, "Device")
    area = tb.roi_area(payload.roiPoints)
    async with httpx.AsyncClient(timeout=_AGENT_TIMEOUT) as client:
        ok, msg, task_id = await DeviceService.deploy_warehouse_task(
            client, device_obj, db,
            task_name=payload.task_name,
            channel_device_id=payload.channel_device_id,
            event_type=payload.event_type,
            algo_cabin_name=payload.algo_cabin_name,
            version=payload.version,
            monitor_name=payload.task_name,
            area=area,
            target_types=payload.target_types,
            threshold=payload.threshold,
            target_max=payload.target_max,
            target_min=payload.target_min,
            duration=payload.duration,
            cooldown=payload.cooldown,
            agent_llm=None,
            target_expand=None,
        )
    if not ok:
        raise HTTPException(status_code=502, detail=msg)
    await _resnapshot(device_obj, db)
    return {"success": True, "task_id": task_id, "message": msg}


@router.post("/{device_id}/deploy/combined-task")
async def deploy_combined_task(device_id: str, payload: CombinedTaskDeploy, db: AsyncSession = Depends(get_db)):
    """下发【小+大任务】(single_point_task + monitor 带 agentLLMParam)。

    先校验/富化二次大模型智能体（镜像 deploy_agent_task 的索引与字段兜底；不存在报 400），
    再经共享 deploy_warehouse_task 两步下发（monitor 挂载 agent_llm + 扩图策略 target_expand）。
    """
    device_obj = await get_or_404(db, DeviceORM, device_id, "Device")
    area = tb.roi_area(payload.roiPoints)
    async with httpx.AsyncClient(timeout=_AGENT_TIMEOUT) as client:
        data = await DeviceService.list_agents(client, device_obj, db)
        if data is None:
            raise HTTPException(status_code=502, detail=f"设备「{device_obj.name}」离线或不可达，无法下发任务")
        if data.get("code") != 0:
            raise HTTPException(status_code=502, detail=data.get("message", "查询智能体算法失败"))
        # 按 event_id / agent_id 建索引，供二次大模型智能体的存在校验与字段兜底
        index = tb.index_agents(data)
        dev_agent = index.get(str(payload.agent_id))
        if dev_agent is None:
            raise HTTPException(
                status_code=400,
                detail=f"设备上不存在智能体算法「{payload.event_tag or payload.agent_id}」，请先在『智能体资产库』新建。")
        agent_llm = tb.build_agent_llm_param(
            {
                **dev_agent,
                "event_id": payload.agent_id,
                "event_tag": payload.event_tag or dev_agent.get("event_tag") or str(payload.agent_id),
                "alarm_type": payload.alarm_type or dev_agent.get("alarm_type") or "freeform",
            },
            prompt=payload.prompt or None,
            alarm_condition=payload.alarm_condition,
        )
        ok, msg, task_id = await DeviceService.deploy_warehouse_task(
            client, device_obj, db,
            task_name=payload.task_name,
            channel_device_id=payload.channel_device_id,
            event_type=payload.event_type,
            algo_cabin_name=payload.algo_cabin_name,
            version=payload.version,
            monitor_name=payload.task_name,
            area=area,
            target_types=payload.target_types,
            threshold=payload.threshold,
            target_max=payload.target_max,
            target_min=payload.target_min,
            duration=payload.duration,
            cooldown=payload.cooldown,
            agent_llm=agent_llm,
            target_expand=payload.target_expand,
        )
    if not ok:
        raise HTTPException(status_code=502, detail=msg)
    await _resnapshot(device_obj, db)
    return {"success": True, "task_id": task_id, "message": msg}


@router.post("/{device_id}/deploy/warehouse-task")
async def deploy_warehouse_task(device_id: str, payload: WarehouseTaskDeploy, db: AsyncSession = Depends(get_db)):
    """下发【算法仓多算法任务】(single_point_task + 多条 monitor，一次提交 N 条算法)。

    三条提交路径（界面手动 / 面板选模板 / 对话选模板）统一走此端点：
    先做按任务类型的参数校验(task_validation)→400；若含『小+大』算法则拉一次设备智能体列表富化
    agent_llm（不存在报 400）；逐算法解析 ROI（空=全画面）；再经 deploy_warehouse_task_multi 两步下发。
    成功后 best-effort 重刷快照，使查看回填即时一致。
    """
    device_obj = await get_or_404(db, DeviceORM, device_id, "Device")

    # ① 按任务类型的参数校验（三条路径共用的 choke point）
    errors = task_validation.validate_warehouse_deploy(payload)
    if errors:
        raise HTTPException(status_code=400, detail="；".join(errors))

    has_combined = any((a.kind or "small") == "combined" for a in payload.algorithms)
    async with httpx.AsyncClient(timeout=_AGENT_TIMEOUT) as client:
        # ② 仅当存在『小+大』算法时才拉设备智能体列表建索引（纯小模型无需触网）
        index = {}
        if has_combined:
            data = await DeviceService.list_agents(client, device_obj, db)
            if data is None:
                raise HTTPException(status_code=502, detail=f"设备「{device_obj.name}」离线或不可达，无法下发任务")
            if data.get("code") != 0:
                raise HTTPException(status_code=502, detail=data.get("message", "查询智能体算法失败"))
            index = tb.index_agents(data)

        # ③ 逐算法富化：解析 ROI（空=全画面）+ combined 的二次大模型 agent_llm
        enriched = []
        for item in payload.algorithms:
            area = tb.roi_area(item.roiPoints)
            agent_llm = None
            target_expand = None
            if (item.kind or "small") == "combined":
                dev_agent = index.get(str(item.agent_id))
                if dev_agent is None:
                    raise HTTPException(
                        status_code=400,
                        detail=f"设备上不存在智能体算法「{item.event_tag or item.agent_id}」，请先在『智能体资产库』新建。")
                agent_llm = tb.build_agent_llm_param(
                    {
                        **dev_agent,
                        "event_id": item.agent_id,
                        "event_tag": item.event_tag or dev_agent.get("event_tag") or str(item.agent_id),
                        "alarm_type": item.alarm_type or dev_agent.get("alarm_type") or "freeform",
                    },
                    prompt=item.prompt or None,
                    alarm_condition=item.alarm_condition,
                )
                target_expand = item.target_expand
            enriched.append({
                "event_type": item.event_type,
                "algo_cabin_name": item.algo_cabin_name,
                "version": item.version,
                "area": area,
                "target_types": item.target_types,
                "threshold": item.threshold,
                "target_max": item.target_max,
                "target_min": item.target_min,
                "duration": item.duration,
                "cooldown": item.cooldown,
                "agent_llm": agent_llm,
                "target_expand": target_expand,
            })

        ok, msg, task_id = await DeviceService.deploy_warehouse_task_multi(
            client, device_obj, db,
            task_name=payload.task_name,
            channel_device_id=payload.channel_device_id,
            algorithms=enriched,
        )
    if not ok:
        raise HTTPException(status_code=502, detail=msg)
    await _resnapshot(device_obj, db)
    return {"success": True, "task_id": task_id, "message": msg}


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
