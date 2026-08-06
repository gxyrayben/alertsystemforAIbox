import os
import base64
import json
import httpx
from typing import List, Optional, Tuple
from sqlalchemy.future import select
from models.orm import DeviceORM, AlertORM, TaskORM
from services.device_service import DeviceService
from services.llm_service import LLMService
from services.logging_service import add_operation_log


async def _get_task_device(db, task_obj: TaskORM) -> Optional[DeviceORM]:
    result = await db.execute(select(DeviceORM).where(DeviceORM.device_id == task_obj.device_id))
    return result.scalars().first()


def _resolve_target_agent_id(task_obj: TaskORM) -> Optional[str]:
    """任务算法配置里的首个算法 id，即本次调优的目标算法；配置无效返回 None。"""
    try:
        return json.loads(task_obj.algorithms)[0]
    except (json.JSONDecodeError, IndexError, TypeError):
        return None


async def _collect_unprocessed_alerts(db, device: DeviceORM, task_obj: TaskORM,
                                      target_agent_id: str, alert_limit: int) -> List[AlertORM]:
    """按时间升序取该设备/算法下、游标之后、带图片的告警（最多 alert_limit 条）。"""
    query = select(AlertORM).where(
        AlertORM.deviceName == device.name,
        AlertORM.alertType == target_agent_id,
        AlertORM.imageUrl != None,
    )
    if task_obj.last_processed_time:
        query = query.where(AlertORM.timestamp > task_obj.last_processed_time)
    result = await db.execute(query.order_by(AlertORM.timestamp.asc()).limit(alert_limit))
    return result.scalars().all()


def _encode_alert_images(alerts: List[AlertORM]) -> Tuple[List[str], int]:
    """把告警图片读成 data URL 列表，并返回这批告警的最大时间戳（用于推进游标）。"""
    encoded_images: List[str] = []
    max_timestamp = 0
    for alert in alerts:
        max_timestamp = max(max_timestamp, alert.timestamp)
        img_path = alert.imageUrl[1:] if alert.imageUrl.startswith("/") else alert.imageUrl
        if os.path.exists(img_path):
            with open(img_path, "rb") as f:
                img_b64 = base64.b64encode(f.read()).decode("utf-8")
            mime_type = "image/png" if img_path.endswith(".png") else "image/jpeg"
            encoded_images.append(f"data:{mime_type};base64,{img_b64}")
    return encoded_images, max_timestamp


def _locate_device_agent(tasks_data: dict, task_obj: TaskORM, target_agent_id: str):
    """在设备任务列表中定位目标布控任务及其算法配置。

    返回 (target_device_task, target_agent, current_prompt) 或 (None, 错误信息)。
    """
    device_tasks_list = tasks_data.get("data", {}).get("list", [])
    target_device_task = next(
        (dt for dt in device_tasks_list if dt.get("task_name") == task_obj.device_task), None
    )
    if not target_device_task:
        return None, f"未在设备上找到名称为 '{task_obj.device_task}' 的布控任务"

    target_agent = next(
        (a for a in target_device_task.get("agent_list", []) if a.get("agent_id") == target_agent_id), None
    )
    if not target_agent:
        return None, f"未在设备任务中找到算法 '{target_agent_id}' 的配置"

    current_prompt = target_agent.get("agent_config", {}).get("prompt", "")
    return (target_device_task, target_agent, current_prompt), None


async def _apply_prompt_optimization(client, device, db, target_device_task,
                                     target_agent, optimized_prompt) -> None:
    """把优化后的 Prompt 下发到设备并记录操作日志。"""
    target_agent["agent_config"]["prompt"] = optimized_prompt
    update_payload = DeviceService.build_task_payload(target_device_task)

    base_url = f"http://{device.ip}:{device.port}"
    put_res = await client.put(f"{base_url}/intelli_manager/task", json=update_payload)

    ok = put_res.status_code == 200 and put_res.json().get("code") == 0
    await add_operation_log(
        db=db,
        device_name=device.name,
        api_path="PUT /intelli_manager/task (Prompt Optimization)",
        parameters=optimized_prompt,
        result="成功" if ok else f"失败: {put_res.text}",
    )


async def perform_auto_tune_workflow(db, task_obj, alert_limit=10):
    """自动调优编排：取设备与告警 → 编码图片 → 读取设备当前 Prompt →
    调大模型分析 → 命中误报则下发新 Prompt → 推进处理游标。"""
    device = await _get_task_device(db, task_obj)
    if not device:
        return False, "关联设备不存在"

    target_agent_id = _resolve_target_agent_id(task_obj)
    if target_agent_id is None:
        return False, "任务算法配置无效"

    alerts = await _collect_unprocessed_alerts(db, device, task_obj, target_agent_id, alert_limit)
    required = alert_limit if task_obj.task_type == "Prompt调优" else 1
    if len(alerts) < required:
        return False, f"未收集到足够的告警数据 (当前: {len(alerts)}/{alert_limit})"

    encoded_images, max_timestamp = _encode_alert_images(alerts)
    if not encoded_images:
        # 图片已在磁盘丢失：仍推进游标，避免卡在同一批告警上
        task_obj.last_processed_time = max_timestamp
        await db.commit()
        return False, "告警图片在磁盘上丢失"

    async with httpx.AsyncClient(timeout=30.0) as client:
        tasks_data = await DeviceService.get_device_tasks(client, device, db)
        if not tasks_data:
            return False, "无法从设备获取任务列表"

        located, error = _locate_device_agent(tasks_data, task_obj, target_agent_id)
        if error:
            return False, error
        target_device_task, target_agent, current_prompt = located

        llm_result = await LLMService.optimize_prompt(target_agent_id, current_prompt, encoded_images)
        if not llm_result:
            return False, "大模型分析失败"

        is_false_positive = llm_result.get("is_false_positive", False)
        optimized_prompt = llm_result.get("optimized_prompt", current_prompt)
        reason = llm_result.get("reason", "")

        if is_false_positive and optimized_prompt and optimized_prompt != current_prompt:
            await _apply_prompt_optimization(
                client, device, db, target_device_task, target_agent, optimized_prompt
            )

        task_obj.last_processed_time = max_timestamp
        await db.commit()

        return True, {
            "is_false_positive": is_false_positive,
            "reason": reason,
            "optimized_prompt": optimized_prompt,
        }
