from fastapi import APIRouter, Depends, HTTPException, Query
from typing import List
import uuid
import json
import httpx
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.exc import IntegrityError
from models.db import get_db
from models.schemas import (Device, AgentCreate, AgentTaskDeploy, SmallModelTaskDeploy, CombinedTaskDeploy,
                            WarehouseTaskDeploy, TaskEnableUpdate)
from models.orm import DeviceORM
from services.device_service import (DeviceService, apply_device_snapshot, _parse_agents,
                                     algorithm_rows_from_ability)
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


@router.get("/{device_id}/algorithms")
async def list_device_algorithms(device_id: str, refresh: bool = Query(True), db: AsyncSession = Depends(get_db)):
    """小模型算法目录（算法仓 + 事件类型），供面板『新建/编辑布控任务』的算法下拉。

    refresh=True（默认）：实时拉设备算法仓 + 卡片能力，带真实 alg_version/目标类型；
    refresh=False 或设备不可达：退回快照 algorithms_ability 拍平（无版本/目标类型，离线可用）。
    注意不要用 device.available_algorithms —— 那里存的是任务里已用到的算法ID字符串，不是能力目录。
    """
    device_obj = await get_or_404(db, DeviceORM, device_id, "Device")
    rows, err = [], ""
    if refresh:
        async with httpx.AsyncClient(timeout=_AGENT_TIMEOUT) as client:
            rows, err = await DeviceService.list_algorithm_rows(client, device_obj, db)
    fallback = False
    if not rows:  # 离线/未刷新 → 快照兜底，保证面板下拉不空
        rows = algorithm_rows_from_ability(json.loads(device_obj.algorithms_ability or "[]"))
        fallback = True
    return {"count": len(rows), "algorithms": rows, "fallback": fallback, "message": err or ""}


def _raise_device_error(msg: str) -> None:
    """设备侧失败消息 → HTTP 状态码：任务不存在按 404，其余（不可达/返回错误）按 502。"""
    raise HTTPException(status_code=404 if "未找到任务" in msg else 502, detail=msg)


async def _index_device_agents(client: httpx.AsyncClient, device_obj: DeviceORM, db: AsyncSession) -> dict:
    """实时拉取设备智能体列表并按 event_id/agent_id 建索引，供存在校验与字段兜底；离线/失败报 502。"""
    data = await DeviceService.list_agents(client, device_obj, db)
    if data is None:
        raise HTTPException(status_code=502, detail=f"设备「{device_obj.name}」离线或不可达，无法下发任务")
    if data.get("code") != 0:
        raise HTTPException(status_code=502, detail=data.get("message", "查询智能体算法失败"))
    return tb.index_agents(data)


def _enrich_agent_items(index: dict, items) -> List[dict]:
    """智能体任务逐项富化（创建/编辑共用）。

    缺省 prompt/alarm_type 用设备端该智能体自身配置兜底；非描述型强制关闭关键词过滤；
    空 ROI 用全画面。检测区的 areaId/areaName/areaType 取面板 ROI 池的用户配置，
    最后按任务整体去重 areaId（同一块 ROI 共享一个号，不同 ROI 撞号则顺延）。
    设备上不存在该智能体时报 400。
    """
    enriched = []
    for item in items:
        dev_agent = index.get(str(item.event_id))
        if dev_agent is None:
            raise HTTPException(
                status_code=400,
                detail=f"设备上不存在智能体算法「{item.event_tag or item.event_id}」，请先在『智能体资产库』新建。")
        alarm_type = item.alarm_type or dev_agent.get("alarm_type") or "freeform"
        is_attr = (alarm_type or "").lower() == "freeform"
        enriched.append({
            "event_id": item.event_id,
            "event_tag": item.event_tag or dev_agent.get("event_tag") or str(item.event_id),
            "alarm_type": alarm_type,
            "prompt": item.prompt if item.prompt else dev_agent.get("prompt", ""),
            "alarm_condition": item.alarm_condition,
            "filter_enable": bool(item.filter_enable) if is_attr else False,
            "filter_keywords": item.filter_keywords if is_attr else "",
            "area": tb.roi_area(item.roiPoints, item.areaId or 1,
                                item.areaName or "检测区", item.areaType or "POLYGON"),
        })
    tb.dedupe_area_ids([e["area"] for e in enriched])
    return enriched


async def _enrich_warehouse_algorithms(
    client: httpx.AsyncClient, device_obj: DeviceORM, db: AsyncSession, algorithms
) -> List[dict]:
    """算法仓多算法逐项富化（创建/编辑共用）：解析 ROI（空=全画面）+ combined 的二次大模型 agent_llm。

    检测区的 areaId/areaName/areaType 取面板 ROI 池的用户配置，最后按任务整体去重 areaId
    （多条算法共用同一块 ROI 时共享同一号，不同 ROI 撞号则顺延，避免设备侧区域互相覆盖）。
    仅当存在『小+大』算法时才拉设备智能体列表（纯小模型无需触网）；智能体不存在报 400。
    combined 的关键词过滤沿用 _enrich_agent_items 语义：仅描述型(freeform)生效，其余强制关闭。
    """
    has_combined = any((a.kind or "small") == "combined" for a in algorithms)
    index = await _index_device_agents(client, device_obj, db) if has_combined else {}

    enriched = []
    for item in algorithms:
        agent_llm = None
        target_expand = None
        if (item.kind or "small") == "combined":
            dev_agent = index.get(str(item.agent_id))
            if dev_agent is None:
                raise HTTPException(
                    status_code=400,
                    detail=f"设备上不存在智能体算法「{item.event_tag or item.agent_id}」，请先在『智能体资产库』新建。")
            alarm_type = item.alarm_type or dev_agent.get("alarm_type") or "freeform"
            is_attr = (alarm_type or "").lower() == "freeform"
            agent_llm = tb.build_agent_llm_param(
                {
                    **dev_agent,
                    "event_id": item.agent_id,
                    "event_tag": item.event_tag or dev_agent.get("event_tag") or str(item.agent_id),
                    "alarm_type": alarm_type,
                    "filter_enable": bool(item.filter_enable) if is_attr else False,
                    "filter_keywords": item.filter_keywords if is_attr else "",
                },
                prompt=item.prompt or None,
                alarm_condition=item.alarm_condition,
            )
            target_expand = item.target_expand
        enriched.append({
            "event_type": item.event_type,
            "algo_cabin_name": item.algo_cabin_name,
            "version": item.version,
            "area": tb.roi_area(item.roiPoints, item.areaId or 1,
                                item.areaName or "检测区", item.areaType or "POLYGON"),
            "target_types": item.target_types,
            "threshold": item.threshold,
            "target_max": item.target_max,
            "target_min": item.target_min,
            "duration": item.duration,
            "cooldown": item.cooldown,
            "agent_llm": agent_llm,
            "target_expand": target_expand,
        })
    tb.dedupe_area_ids([e["area"] for e in enriched])
    return enriched


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
        index = await _index_device_agents(client, device_obj, db)
        enriched = _enrich_agent_items(index, payload.agents)

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
    area = tb.roi_area(payload.roiPoints, payload.areaId or 1,
                       payload.areaName or "检测区", payload.areaType or "POLYGON")
    async with httpx.AsyncClient(timeout=_AGENT_TIMEOUT) as client:
        ok, msg, task_id = await DeviceService.deploy_warehouse_task(
            client, device_obj, db,
            task_name=payload.task_name,
            channel_device_id=payload.channel_device_id,
            event_type=payload.event_type,
            algo_cabin_name=payload.algo_cabin_name,
            version=payload.version,
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
    area = tb.roi_area(payload.roiPoints, payload.areaId or 1,
                       payload.areaName or "检测区", payload.areaType or "POLYGON")
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
        alarm_type = payload.alarm_type or dev_agent.get("alarm_type") or "freeform"
        is_attr = (alarm_type or "").lower() == "freeform"
        agent_llm = tb.build_agent_llm_param(
            {
                **dev_agent,
                "event_id": payload.agent_id,
                "event_tag": payload.event_tag or dev_agent.get("event_tag") or str(payload.agent_id),
                "alarm_type": alarm_type,
                "filter_enable": bool(payload.filter_enable) if is_attr else False,
                "filter_keywords": payload.filter_keywords if is_attr else "",
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

    async with httpx.AsyncClient(timeout=_AGENT_TIMEOUT) as client:
        # ② 逐算法富化：解析 ROI（空=全画面）+ combined 的二次大模型 agent_llm（与编辑保存共用）
        enriched = await _enrich_warehouse_algorithms(client, device_obj, db, payload.algorithms)

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


@router.put("/{device_id}/tasks/{task_id}/agent-task")
async def update_agent_task(device_id: str, task_id: str, payload: AgentTaskDeploy,
                            db: AsyncSession = Depends(get_db)):
    """就地更新【纯大模型智能体任务】(agent_real_task)：任务列表『编辑』保存走此端点。

    与创建同一套校验/富化(_index_device_agents + _enrich_agent_items)，区别是带上原 task_id
    走 PUT /intelli_manager/task 覆盖更新（不会新建出重复任务）。
    enable 使能位保持不变（启用/停用请用 enable 端点）。成功后 best-effort 重刷快照，使列表与回填即时一致。
    """
    device_obj = await get_or_404(db, DeviceORM, device_id, "Device")
    if not (1 <= len(payload.agents) <= 4):
        raise HTTPException(status_code=400, detail="智能体任务需关联 1~4 个智能体算法")

    async with httpx.AsyncClient(timeout=_AGENT_TIMEOUT) as client:
        index = await _index_device_agents(client, device_obj, db)
        enriched = _enrich_agent_items(index, payload.agents)
        ok, msg = await DeviceService.update_agent_real_task(
            client, device_obj, db,
            task_id=task_id,
            task_name=payload.task_name,
            channel_device_id=payload.channel_device_id,
            agents=enriched,
            analysis_interval=payload.analysis_interval,
        )
    if not ok:
        _raise_device_error(msg)
    await _resnapshot(device_obj, db)
    return {"success": True, "task_id": task_id, "message": msg}


@router.put("/{device_id}/tasks/{task_id}/warehouse-task")
async def update_warehouse_task(device_id: str, task_id: str, payload: WarehouseTaskDeploy,
                                db: AsyncSession = Depends(get_db)):
    """就地更新【算法仓多算法任务】(single_point_task + N 条 monitor)：任务列表『编辑』保存走此端点。

    与创建共用参数校验(task_validation)与富化(_enrich_warehouse_algorithms)；保存时按算法仓
    用原 monitor_id 覆盖重下规则，编辑中被移除的算法仓降级停用（设备无删除接口）。
    """
    device_obj = await get_or_404(db, DeviceORM, device_id, "Device")

    errors = task_validation.validate_warehouse_deploy(payload)
    if errors:
        raise HTTPException(status_code=400, detail="；".join(errors))

    async with httpx.AsyncClient(timeout=_AGENT_TIMEOUT) as client:
        enriched = await _enrich_warehouse_algorithms(client, device_obj, db, payload.algorithms)
        ok, msg = await DeviceService.update_warehouse_task_multi(
            client, device_obj, db,
            task_id=task_id,
            task_name=payload.task_name,
            channel_device_id=payload.channel_device_id,
            algorithms=enriched,
        )
    if not ok:
        _raise_device_error(msg)
    await _resnapshot(device_obj, db)
    return {"success": True, "task_id": task_id, "message": msg}


@router.put("/{device_id}/tasks/{task_id}/enable")
async def set_device_task_enable(device_id: str, task_id: str, payload: TaskEnableUpdate,
                                 db: AsyncSession = Depends(get_db)):
    """任务列表『是否启用』开关：切换设备任务 enable，并同步其名下各算法仓 monitor 的使能位。"""
    device_obj = await get_or_404(db, DeviceORM, device_id, "Device")
    async with httpx.AsyncClient(timeout=_AGENT_TIMEOUT) as client:
        ok, msg = await DeviceService.set_task_enable(
            client, device_obj, db, task_id=task_id, enable=payload.enable)
    if not ok:
        _raise_device_error(msg)
    await _resnapshot(device_obj, db)
    return {"success": True, "task_id": task_id, "enable": payload.enable, "message": msg}


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
