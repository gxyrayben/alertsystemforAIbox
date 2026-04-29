import os
import base64
import json
import httpx
from sqlalchemy.future import select
from models.orm import DeviceORM, AlertORM
from services.device_service import DeviceService
from services.llm_service import LLMService
from services.logging_service import add_operation_log

async def perform_auto_tune_workflow(db, task_obj, alert_limit=10):
    """
    Orchestrates the entire auto-tuning process: 
    1. Fetch device & alerts
    2. Encode images
    3. Get current prompt from device
    4. Call LLM for optimization
    5. Update device & log results
    """
    # 1. Fetch Device
    query = select(DeviceORM).where(DeviceORM.device_id == task_obj.device_id)
    result = await db.execute(query)
    device = result.scalars().first()
    if not device:
        return False, "关联设备不存在"

    # 2. Fetch Alerts
    try:
        algorithms = json.loads(task_obj.algorithms)
        target_agent_id = algorithms[0]
    except (json.JSONDecodeError, IndexError):
        return False, "任务算法配置无效"

    query = select(AlertORM).where(
        AlertORM.deviceName == device.name,
        AlertORM.alertType == target_agent_id,
        AlertORM.imageUrl != None
    )
    if task_obj.last_processed_time:
        query = query.where(AlertORM.timestamp > task_obj.last_processed_time)
    
    # Order by timestamp ASC to process chronologically
    result = await db.execute(query.order_by(AlertORM.timestamp.asc()).limit(alert_limit))
    alerts = result.scalars().all()
    
    # Requirement: Must have enough alerts for "Prompt调优" tasks
    if len(alerts) < (alert_limit if task_obj.task_type == "Prompt调优" else 1):
        return False, f"未收集到足够的告警数据 (当前: {len(alerts)}/{alert_limit})"

    # 3. Prepare Images
    encoded_images = []
    max_timestamp = task_obj.last_processed_time or 0
    for alert in alerts:
        max_timestamp = max(max_timestamp, alert.timestamp)
        img_path = alert.imageUrl[1:] if alert.imageUrl.startswith("/") else alert.imageUrl
        if os.path.exists(img_path):
            with open(img_path, "rb") as f:
                img_b64 = base64.b64encode(f.read()).decode('utf-8')
                mime_type = "image/png" if img_path.endswith(".png") else "image/jpeg"
                encoded_images.append(f"data:{mime_type};base64,{img_b64}")

    if not encoded_images:
        # Move cursor anyway if no images exist to avoid getting stuck
        task_obj.last_processed_time = max_timestamp
        await db.commit()
        return False, "告警图片在磁盘上丢失"

    # 4. Device Interaction
    async with httpx.AsyncClient(timeout=30.0) as client:
        tasks_data = await DeviceService.get_device_tasks(client, device, db)
        if not tasks_data:
            return False, "无法从设备获取任务列表"

        device_tasks_list = tasks_data.get("data", {}).get("list", [])
        target_device_task = next((dt for dt in device_tasks_list if dt.get("task_name") == task_obj.device_task), None)
        if not target_device_task:
            return False, f"未在设备上找到名称为 '{task_obj.device_task}' 的布控任务"

        agent_list = target_device_task.get("agent_list", [])
        target_agent = next((agent for agent in agent_list if agent.get("agent_id") == target_agent_id), None)
        if not target_agent:
            return False, f"未在设备任务中找到算法 '{target_agent_id}' 的配置"

        current_prompt = target_agent.get("agent_config", {}).get("prompt", "")

        # 5. LLM Optimization
        llm_result = await LLMService.optimize_prompt(target_agent_id, current_prompt, encoded_images)
        if not llm_result:
            return False, "大模型分析失败"

        is_false_positive = llm_result.get("is_false_positive", False)
        optimized_prompt = llm_result.get("optimized_prompt", current_prompt)
        reason = llm_result.get("reason", "")

        # 6. Apply Update
        if is_false_positive and optimized_prompt and optimized_prompt != current_prompt:
            target_agent["agent_config"]["prompt"] = optimized_prompt
            update_payload = DeviceService.build_task_payload(target_device_task)
            
            base_url = f"http://{device.ip}:{device.port}"
            put_res = await client.put(f"{base_url}/intelli_manager/task", json=update_payload)
            
            # Log the operation
            await add_operation_log(
                db=db,
                device_name=device.name,
                api_path="PUT /intelli_manager/task (Prompt Optimization)",
                parameters=optimized_prompt,
                result="成功" if put_res.status_code == 200 and put_res.json().get("code") == 0 else f"失败: {put_res.text}"
            )

        # 7. Update Task Cursor
        task_obj.last_processed_time = max_timestamp
        await db.commit()
        
        return True, {
            "is_false_positive": is_false_positive,
            "reason": reason,
            "optimized_prompt": optimized_prompt
        }
