"""告警反馈闭环 —— 后端分类调优编排（Case1/2/3）。

用户在「告警反馈闭环」页面标注真实/误报后点「提交后端做优化」，本模块负责：
1. 取出待优化的已标注告警（valid/false_positive 且未提交）；
2. 按设备分组，拉取设备任务列表 + monitor 列表，把每条告警定位到具体布控任务；
3. 用 categorize_task 分三类走不同优化策略：
   - Case1 大模型任务：仅误报 → LLMService.optimize_prompt → PUT /intelli_manager/task 改 agent_config.prompt；
   - Case2 小模型任务：正报+误报的小图尺寸 + 当前 monitor 参数 → analyze_smallmodel_params → create_monitor 覆盖下发；
   - Case3 小+大任务：小模型参数 + 二次大模型 Prompt（agentLLMParam.prompt）一起 create_monitor 覆盖下发；
4. 成功下发的告警置 feedback_submitted=1；全程写操作日志；返回结构化摘要。

设计约束（已与用户确认，见计划文件）：
- 告警回传无 bbox/置信度字段，故 Case2 目标大小取送检小图 imageUrlCrop 的真实像素；阈值取任务当前配置值；
- 设备无 monitor update 接口，故参数回写复用 create_monitor 覆盖下发；离线/失败降级为仅记日志并跳过。
"""
import os
import json
import time
import uuid
import httpx
from typing import Optional, List, Tuple
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.orm import DeviceORM, AlertORM, FeedbackTaskORM
from services.device_service import DeviceService, categorize_task, _index_monitors
from services.llm_service import LLMService
from services.logging_service import add_operation_log
from services import task_service, task_builders, alarm_ingest, algorithm_catalog

VALID = "valid"
FALSE_POSITIVE = "false_positive"


# ── 运维记录快照 & 落库 ────────────────────────────────────────────────────
def _snapshot_alerts(alerts: List[AlertORM]) -> List[dict]:
    """把一组告警量成详情翻页用的快照（脱离 AlertORM，避免 7 天清理/重标注后失效）。"""
    return [
        {
            "id": a.id,
            "alertType": a.alertType,
            "channel": a.channel or "",
            "time": a.time,
            "timestamp": a.timestamp,
            "imageUrl": a.imageUrl,
            "imageUrlCrop": a.imageUrlCrop,
            "feedback_status": a.feedback_status,
            "feedback_note": a.feedback_note or "",
        }
        for a in alerts
    ]


def _channels(alerts: List[AlertORM]) -> str:
    """组内去重通道，逗号连接。"""
    return ",".join(sorted({a.channel for a in alerts if a.channel}))


def _add_record(db: AsyncSession, batch_id: str, created_at: int, *, device_name: str,
                task_name: str, channel: str, category: str, case_key: str, action: str,
                result: str, detail: str, alerts: List[AlertORM], log_id: str = "") -> None:
    """新增一条调优下发运维记录（延后随所在设备批次一起 commit）。"""
    db.add(FeedbackTaskORM(
        id=str(uuid.uuid4()),
        batch_id=batch_id,
        device_name=device_name,
        task_name=task_name,
        channel=channel,
        category=category,
        case_key=case_key or "",
        action=action,
        result=result,
        detail=detail or "",
        alerts_snapshot=json.dumps(_snapshot_alerts(alerts), ensure_ascii=False),
        alert_count=len(alerts),
        log_id=log_id or "",
        created_at=created_at,
    ))


# ── 告警 → 设备任务 定位（best-effort） ────────────────────────────────────
def _alert_matches_task(alert_type: str, task: dict, mon: Optional[dict]) -> bool:
    """判断一条告警(alertType)是否归属某设备任务。

    大模型/小+大：匹配 agent_list 里的 event_id / event_tag；
    小模型：匹配对应 monitor 的 eventType 或其中文算法名。均为 best-effort。
    """
    if not alert_type:
        return False
    for a in task.get("agent_list") or []:
        if alert_type in (a.get("event_id"), a.get("event_tag")):
            return True
    rule = task_builders._first_rule(mon)
    if rule:
        event_type = rule.get("eventType") or ""
        if alert_type == event_type or alert_type == algorithm_catalog.event_name(event_type):
            return True
    return False


def _locate_task(alert_type: str, tasks: List[dict], monitor_by_task: dict) -> Optional[dict]:
    """在设备任务列表里找到该告警归属的任务（首个命中）；找不到返回 None。"""
    for task in tasks:
        mon = (monitor_by_task.get(str(task.get("task_id"))) or {}).get("monitor")
        if _alert_matches_task(alert_type, task, mon):
            return task
    return None


def _crop_samples(alerts: List[AlertORM]) -> List[dict]:
    """把一组告警的送检小图量成尺寸样本：[{label, crop_w, crop_h, ratio}]。

    ratio = 小图面积 / 大图面积（大图不可读则省略）。无小图的告警跳过。
    """
    samples: List[dict] = []
    for a in alerts:
        if not a.imageUrlCrop:
            continue
        crop = alarm_ingest.image_pixel_size(a.imageUrlCrop)
        if not crop:
            continue
        cw, ch = crop
        sample = {"label": a.feedback_status, "crop_w": cw, "crop_h": ch}
        big = alarm_ingest.image_pixel_size(a.imageUrl) if a.imageUrl else None
        if big and big[0] and big[1]:
            sample["ratio"] = (cw * ch) / (big[0] * big[1])
        samples.append(sample)
    return samples


# ── 三类优化 ────────────────────────────────────────────────────────────
async def _optimize_case1(client, device, db, task: dict, alerts: List[AlertORM]) -> Tuple[bool, str, str]:
    """大模型任务：仅用误报大图调优 Prompt 并 PUT 下发。返回 (ok, msg, log_id)。"""
    fps = [a for a in alerts if a.feedback_status == FALSE_POSITIVE]
    if not fps:
        return False, "无误报样本，跳过", ""
    alert_type = fps[0].alertType
    target_agent = next(
        (a for a in task.get("agent_list") or [] if alert_type in (a.get("event_id"), a.get("event_tag"))),
        None,
    )
    if not target_agent:
        return False, "未在设备任务中定位到目标智能体", ""

    images, _ = task_service._encode_alert_images(fps)
    if not images:
        return False, "误报图片在磁盘丢失", ""

    current_prompt = target_agent.get("agent_config", {}).get("prompt", "")
    result = await LLMService.optimize_prompt(alert_type, current_prompt, images)
    if not result:
        return False, "大模型分析失败", ""
    if not result.get("is_false_positive"):
        return False, f"大模型判定非误报：{result.get('reason', '')}", ""
    new_prompt = result.get("optimized_prompt") or ""
    if not new_prompt or new_prompt == current_prompt:
        return False, "Prompt 无需调整", ""

    log_id = await task_service._apply_prompt_optimization(
        client, device, db, task, target_agent, new_prompt,
        task_name=task.get("task_name", ""),
    )
    return True, "已下发优化后 Prompt", log_id


async def _optimize_monitor(client, device, db, task: dict, mon: dict,
                            alerts: List[AlertORM], with_prompt: bool) -> Tuple[bool, str, str]:
    """小模型 / 小+大任务：调小模型参数（并按需调二次 Prompt），create_monitor 覆盖下发。

    返回 (ok, msg, log_id)。
    """
    rule = task_builders._first_rule(mon)
    if not rule:
        return False, "无法获取 monitor 参数（monitor_list 不可用）", ""
    ep = rule.get("extendParams") or {}
    event_type = rule.get("eventType") or ""

    samples = _crop_samples(alerts)
    current = {
        "threshold": ep.get("threshold", 0.3),
        "target_max": ep.get("targetMax", 1),
        "target_min": ep.get("targetMin", 0),
    }
    new_params = await LLMService.analyze_smallmodel_params(event_type, current, samples)
    if not new_params:
        return False, "小模型参数分析失败", ""

    # 二次大模型 Prompt（仅小+大任务），源为 monitor 的 agentLLMParam
    agent_llm = None
    prompt_note = ""
    orig_agent_llm = (ep.get("aiotapCustom") or {}).get("agentLLMParam") or {}
    if with_prompt and orig_agent_llm:
        fps = [a for a in alerts if a.feedback_status == FALSE_POSITIVE]
        images, _ = task_service._encode_alert_images(fps) if fps else ([], 0)
        new_prompt = orig_agent_llm.get("prompt", "")
        if images:
            pres = await LLMService.optimize_prompt(event_type, orig_agent_llm.get("prompt", ""), images)
            if pres and pres.get("is_false_positive") and pres.get("optimized_prompt"):
                new_prompt = pres["optimized_prompt"]
                prompt_note = "，并更新二次大模型 Prompt"
        agent_llm = {**orig_agent_llm, "prompt": new_prompt}

    common = mon.get("common_param") or {}
    warehouse = common.get("warehouse_v20_param") or {}
    labels = warehouse.get("labels") or {}
    areas = rule.get("areas") or []
    payload = task_builders.build_monitor_payload(
        task_id=common.get("task_id"),
        channel_device_id=common.get("device_id"),
        event_type=event_type,
        algo_cabin_name=labels.get("algoCabinName", ""),
        version=labels.get("version", "V2.0.0"),
        monitor_id=common.get("monitor_id"),
        monitor_name=common.get("monitor_name"),
        area=areas[0] if areas else None,
        target_types=ep.get("targetTypes"),
        threshold=_num(new_params.get("threshold"), current["threshold"]),
        target_max=_num(new_params.get("target_max"), current["target_max"]),
        target_min=_num(new_params.get("target_min"), current["target_min"]),
        duration=ep.get("duration", 3),
        cooldown=ep.get("cooldownDuration", 600),
        agent_llm=agent_llm,
    )

    res = await DeviceService.create_monitor(client, device, db, payload)
    ok = bool(res) and res.get("code") == 0
    detail = (
        f"阈值 {current['threshold']}→{new_params.get('threshold')}, "
        f"目标 [{current['target_min']},{current['target_max']}]→"
        f"[{new_params.get('target_min')},{new_params.get('target_max')}]{prompt_note}"
    )
    log_id = await add_operation_log(
        db=db, device_name=device.name,
        api_path="POST /intelli_manager/monitor (Param Optimization)",
        parameters=detail,
        result="成功" if ok else f"失败: {res}",
        task_name=task.get("task_name", ""),
    )
    if not ok:
        return False, f"参数下发失败：{detail}", log_id
    return True, f"已覆盖下发小模型参数（{detail}）", log_id


def _num(v, fallback):
    """把大模型返回的数值安全转 float/int；非法则回退原值。"""
    try:
        if v is None:
            return fallback
        f = float(v)
        return int(f) if isinstance(fallback, int) and f == int(f) else f
    except (TypeError, ValueError):
        return fallback


# ── 编排入口 ────────────────────────────────────────────────────────────
async def run_optimization(db: AsyncSession, alert_ids: Optional[List[str]] = None) -> dict:
    """分类调优主流程。返回结构化摘要（含向后兼容的 submitted/by_type/alert_ids）。

    同时把每个设备任务的下发结果（成功/跳过）持久化为 FeedbackTaskORM 运维记录，
    同一次提交共享 batch_id，供「任务运维列表」展示与详情翻页。
    """
    query = select(AlertORM).where(
        AlertORM.feedback_status.in_([VALID, FALSE_POSITIVE]),
        AlertORM.feedback_submitted == 0,
    )
    if alert_ids:
        query = query.where(AlertORM.id.in_(alert_ids))
    alerts = (await db.execute(query)).scalars().all()

    summary = {
        "submitted": 0, "deployed": 0, "skipped": 0,
        "by_case": {"Case1": 0, "Case2": 0, "Case3": 0},
        "by_type": {}, "alert_ids": [], "details": [],
    }
    if not alerts:
        return summary

    batch_id = str(uuid.uuid4())
    created_at = int(time.time() * 1000)

    # 按设备名分组
    by_device: dict = {}
    for a in alerts:
        by_device.setdefault(a.deviceName, []).append(a)

    for device_name, dev_alerts in by_device.items():
        dev_res = await db.execute(select(DeviceORM).where(DeviceORM.name == device_name))
        device = dev_res.scalars().first()
        if not device:
            _skip(db, batch_id, created_at, summary, dev_alerts, device_name, "关联设备不存在")
            await db.commit()
            continue

        async with httpx.AsyncClient(timeout=30.0) as client:
            tasks_data = await DeviceService.get_device_tasks(client, device, db)
            if not tasks_data:
                _skip(db, batch_id, created_at, summary, dev_alerts, device_name, "设备离线或无法获取任务列表")
                await db.commit()
                continue
            tasks = tasks_data.get("data", {}).get("list", []) or []
            monitors = await DeviceService.list_monitors(client, device, db)
            monitor_by_task = _index_monitors((monitors or {}).get("data", {}).get("list", [])) if monitors else {}

            # 告警 → 任务 定位并按 task_id 聚合；未定位到的按算法名聚合后统一落跳过记录
            groups: dict = {}
            unlocated: dict = {}
            for a in dev_alerts:
                task = _locate_task(a.alertType, tasks, monitor_by_task)
                if not task:
                    unlocated.setdefault(a.alertType, []).append(a)
                    continue
                groups.setdefault(str(task.get("task_id")), (task, []))[1].append(a)
            for alert_type, grp in unlocated.items():
                _skip(db, batch_id, created_at, summary, grp, device_name, f"未定位到算法「{alert_type}」所属任务")

            for task_id, (task, grp_alerts) in groups.items():
                category = categorize_task(task)
                mon = (monitor_by_task.get(task_id) or {}).get("monitor")
                task_name = task.get("task_name") or task_id
                log_id = ""
                try:
                    if category == "大模型任务":
                        ok, msg, log_id = await _optimize_case1(client, device, db, task, grp_alerts)
                        case_key = "Case1"
                    elif category == "小模型任务":
                        ok, msg, log_id = await _optimize_monitor(client, device, db, task, mon, grp_alerts, with_prompt=False)
                        case_key = "Case2"
                    elif category == "小+大任务":
                        ok, msg, log_id = await _optimize_monitor(client, device, db, task, mon, grp_alerts, with_prompt=True)
                        case_key = "Case3"
                    else:
                        ok, msg, case_key = False, f"不支持的任务类型：{category}", None
                except Exception as e:
                    ok, msg, case_key = False, f"优化异常：{e}", None

                _add_record(
                    db, batch_id, created_at,
                    device_name=device_name, task_name=task_name, channel=_channels(grp_alerts),
                    category=category, case_key=case_key or "",
                    action="deployed" if ok else "skipped", result=msg, detail=msg,
                    alerts=grp_alerts, log_id=log_id,
                )
                summary["details"].append({
                    "task_name": task_name, "category": category,
                    "action": "deployed" if ok else "skipped", "result": msg,
                })
                if ok:
                    if case_key:
                        summary["by_case"][case_key] += 1
                    for a in grp_alerts:
                        a.feedback_submitted = 1
                        summary["deployed"] += 1
                        summary["alert_ids"].append(a.id)
                        summary["by_type"][a.alertType] = summary["by_type"].get(a.alertType, 0) + 1
                else:
                    summary["skipped"] += len(grp_alerts)
            await db.commit()

    summary["submitted"] = summary["deployed"]
    return summary


def _skip(db: AsyncSession, batch_id: str, created_at: int, summary: dict,
          alerts: List[AlertORM], device_name: str, reason: str) -> None:
    """记跳过：累加摘要 + 落一条 skipped 运维记录（含这批告警快照）。"""
    summary["skipped"] += len(alerts)
    summary["details"].append({
        "task_name": device_name, "category": "-", "action": "skipped", "result": reason,
    })
    _add_record(
        db, batch_id, created_at,
        device_name=device_name, task_name=device_name, channel=_channels(alerts),
        category="-", case_key="", action="skipped", result=reason, detail=reason,
        alerts=alerts,
    )
