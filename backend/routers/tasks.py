from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import func
from typing import List
import uuid
import time
import json
import base64
import os
import httpx
import hashlib

from models.db import get_db
from models.orm import TaskORM, DeviceORM, AlertORM, LogORM
from models.schemas import TaskCreate, TaskUpdate, TaskResponse
import database


def build_intelli_manager_task_update_payload(task_obj: dict) -> dict:
    """Build a minimal update payload for PUT /intelli_manager/task."""
    allowed_fields = [
        "task_id",
        "task_name",
        "task_type",
        "device_list",
        "enable",
        "schedule_plan_id",
        "analysis_interval",
        "agent_list",
    ]
    payload = {k: task_obj[k] for k in allowed_fields if k in task_obj}
    
    # 修复物理设备的特定约束（从设备拉取可能是 0，但下发必须在 1~10 之间）
    if "device_list" in payload:
        for dev in payload["device_list"]:
            if "image_extract_frame_interval" in dev:
                if dev["image_extract_frame_interval"] < 1:
                    dev["image_extract_frame_interval"] = 1
                elif dev["image_extract_frame_interval"] > 10:
                    dev["image_extract_frame_interval"] = 10
                    
    return payload


router = APIRouter(prefix="/api/tasks", tags=["tasks"])

@router.get("")
async def list_tasks(page: int = Query(1, ge=1), size: int = Query(10, ge=1), db: AsyncSession = Depends(get_db)):
    offset = (page - 1) * size
    
    total_query = select(func.count()).select_from(TaskORM)
    total_result = await db.execute(total_query)
    total = total_result.scalar()

    query = select(TaskORM).order_by(TaskORM.created_at.desc()).offset(offset).limit(size)
    result = await db.execute(query)
    tasks = result.scalars().all()
    
    return {"total": total, "tasks": [TaskResponse.model_validate(t) for t in tasks]}

@router.post("", response_model=TaskResponse)
async def create_task(task: TaskCreate, db: AsyncSession = Depends(get_db)):
    task_id = f"TASK-{str(uuid.uuid4())[:8].upper()}"
    current_time = int(time.time() * 1000)
    new_task = TaskORM(
        id=task_id,
        **task.model_dump(),
        created_at=current_time,
        last_processed_time=current_time
    )
    db.add(new_task)
    await db.commit()
    await db.refresh(new_task)
    return new_task

@router.put("/{task_id}", response_model=TaskResponse)
async def update_task(task_id: str, task_update: TaskUpdate, db: AsyncSession = Depends(get_db)):
    query = select(TaskORM).where(TaskORM.id == task_id)
    result = await db.execute(query)
    task_obj = result.scalars().first()
    if not task_obj:
        raise HTTPException(status_code=404, detail="Task not found")
        
    update_data = task_update.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(task_obj, key, value)
        
    await db.commit()
    await db.refresh(task_obj)
    return task_obj

@router.delete("/{task_id}")
async def delete_task(task_id: str, db: AsyncSession = Depends(get_db)):
    query = select(TaskORM).where(TaskORM.id == task_id)
    result = await db.execute(query)
    task_obj = result.scalars().first()
    if not task_obj:
        raise HTTPException(status_code=404, detail="Task not found")
        
    await db.delete(task_obj)
    await db.commit()
    return {"message": "Task deleted"}

@router.post("/{task_id}/auto_tune")
async def auto_tune_task(task_id: str, db: AsyncSession = Depends(get_db)):
    query = select(TaskORM).where(TaskORM.id == task_id)
    result = await db.execute(query)
    task_obj = result.scalars().first()
    if not task_obj:
        raise HTTPException(status_code=404, detail="Task not found")

    if not task_obj.algorithms or task_obj.algorithms == "[]":
        raise HTTPException(status_code=400, detail="任务未配置智能体算法，无法进行调优")

    algorithms = json.loads(task_obj.algorithms)

    query = select(DeviceORM).where(DeviceORM.device_id == task_obj.device_id)
    result = await db.execute(query)
    device_obj = result.scalars().first()
    if not device_obj:
        raise HTTPException(status_code=404, detail="关联设备不存在")

    query = select(AlertORM).where(AlertORM.deviceName == device_obj.name).where(AlertORM.imageUrl != None).order_by(AlertORM.timestamp.desc()).limit(1)
    result = await db.execute(query)
    alert_obj = result.scalars().first()
    if not alert_obj:
        raise HTTPException(status_code=404, detail="未找到该设备相关的含有图片的告警记录")

    img_path = alert_obj.imageUrl
    if img_path.startswith("/"):
        img_path = img_path[1:]
    
    if not os.path.exists(img_path):
        raise HTTPException(status_code=404, detail="告警图片文件在磁盘上丢失")

    with open(img_path, "rb") as f:
        img_b64 = base64.b64encode(f.read()).decode('utf-8')

    mime_type = "image/jpeg"
    if img_path.endswith(".png"):
        mime_type = "image/png"

    base_url = f"http://{device_obj.ip}:{device_obj.port}"
    session_id = device_obj.session_id

    async with httpx.AsyncClient(timeout=15.0) as client:
        if session_id:
            client.cookies.set("sessionID", session_id)
            
        async def do_login():
            challenge_res = await client.get(f"{base_url}/auth/login/challenge", params={"username": device_obj.username})
            if challenge_res.status_code == 200 and challenge_res.json().get("code") == 0:
                c_data = challenge_res.json().get("data", {})
                new_session_id = c_data.get("session_id", "")
                salt = c_data.get("salt", "")
                challenge = c_data.get("challenge", "")
                
                pwd_str = f"{device_obj.password}{salt}{challenge}"
                hashed_pwd = hashlib.sha256(pwd_str.encode('utf-8')).hexdigest()
                
                login_payload = {
                    "session_id": new_session_id,
                    "username": device_obj.username,
                    "password": hashed_pwd,
                    "aiotap_flag": 1
                }
                
                login_res = await client.post(f"{base_url}/auth/login", json=login_payload)
                if login_res.status_code == 200 and login_res.json().get("code") == 0:
                    client.cookies.set("sessionID", new_session_id)
                    device_obj.session_id = new_session_id
                    device_obj.status = "在线"
                    await db.commit()
                    return True
            return False

        tasks_res = await client.post(f"{base_url}/intelli_manager/task_list", json={"offset": 0, "size": 100, "condition": {}})
        if tasks_res.status_code != 200 or tasks_res.json().get("code") != 0:
            success = await do_login()
            if not success:
                raise HTTPException(status_code=500, detail="设备登录鉴权失败")
            tasks_res = await client.post(f"{base_url}/intelli_manager/task_list", json={"offset": 0, "size": 100, "condition": {}})
            
        tasks_data = tasks_res.json()
        if tasks_data.get("code") != 0:
            raise HTTPException(status_code=500, detail="从设备获取任务列表失败")

        device_tasks_list = tasks_data.get("data", {}).get("list", [])
        target_device_task = None
        for dt in device_tasks_list:
            if dt.get("task_name") == task_obj.device_task:
                target_device_task = dt
                break
        
        if not target_device_task:
            raise HTTPException(status_code=404, detail=f"未在设备上找到名称为 '{task_obj.device_task}' 的布控任务")

        target_agent_id = algorithms[0]
        current_prompt = ""
        agent_list = target_device_task.get("agent_list", [])
        target_agent = None
        for agent in agent_list:
            if agent.get("agent_id") == target_agent_id:
                target_agent = agent
                current_prompt = agent.get("agent_config", {}).get("prompt", "")
                break
        
        if not target_agent:
            raise HTTPException(status_code=404, detail=f"未在设备任务中找到算法 '{target_agent_id}' 的配置")

        llm_config = database.llm_config
        if not llm_config:
            raise HTTPException(status_code=500, detail="系统未配置大语言模型")

        prompt_instruction = f"""你现在是一个智能安防摄像头的提示词调优专家。
当前设备的任务是识别：{target_agent_id}。
设备目前使用的识别提示词(Prompt)是：
{current_prompt}

请观察用户提供的最新『告警抓拍图』。
1. 判断这张图是否是**误报**（False Positive）？
2. 如果是误报，请分析原因（如反光、形状相似等），并输出一段**全新优化后的 Prompt**，在原基础上增加排除这些干扰项的描述。如果不希望修改或者并非误报，请在optimized_prompt保持原样。

请严格以 JSON 格式返回：
{{
    "is_false_positive": true/false,
    "reason": "分析原因...",
    "optimized_prompt": "新的提示词内容..."
}}
"""
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt_instruction},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{mime_type};base64,{img_b64}"}
                    }
                ]
            }
        ]

        llm_payload = {
            "model": llm_config["model_name"],
            "messages": messages,
            "response_format": {"type": "json_object"} if ("gpt" in llm_config["model_name"].lower() or "moonshot" in llm_config["model_name"].lower()) else None
        }
        
        if llm_payload["response_format"] is None:
            del llm_payload["response_format"]

        headers = {"Authorization": f"Bearer {llm_config['api_key']}"}
        llm_url = f"{llm_config['base_url'].rstrip('/')}/chat/completions"

        try:
            llm_res = await client.post(llm_url, headers=headers, json=llm_payload, timeout=60.0)
            if llm_res.status_code != 200:
                error_msg = llm_res.text
                try:
                    error_json = llm_res.json()
                    error_msg = error_json.get("error", {}).get("message", llm_res.text)
                except Exception:
                    pass
                raise HTTPException(status_code=400, detail=f"大模型接口报错 ({llm_res.status_code}): {error_msg}")
            
            llm_res.raise_for_status()
            llm_data = llm_res.json()
            content_str = llm_data["choices"][0]["message"]["content"]
            
            content_str = content_str.strip()
            if content_str.startswith("```json"):
                content_str = content_str[7:-3].strip()
            elif content_str.startswith("```"):
                content_str = content_str[3:-3].strip()
                
            tuning_result = json.loads(content_str)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"LLM 推理失败: {str(e)}")

        is_false_positive = tuning_result.get("is_false_positive", False)
        optimized_prompt = tuning_result.get("optimized_prompt", current_prompt)
        reason = tuning_result.get("reason", "")

        updated = False
        if is_false_positive and optimized_prompt and optimized_prompt != current_prompt:
            target_agent["agent_config"]["prompt"] = optimized_prompt
            
            update_payload = build_intelli_manager_task_update_payload(target_device_task)
            
            put_res = await client.put(f"{base_url}/intelli_manager/task", json=update_payload)
            
            log_id = f"LOG-{str(uuid.uuid4())[:8].upper()}"
            new_log = LogORM(
                id=str(uuid.uuid4()),
                log_id=log_id,
                device_name=device_obj.name,
                api_path="PUT /intelli_manager/task (Prompt Optimization)",
                parameters=optimized_prompt,
                result="成功" if put_res.status_code == 200 and put_res.json().get("code") == 0 else f"失败: {put_res.text}",
                timestamp=int(time.time() * 1000)
            )
            db.add(new_log)
            await db.commit()

            if put_res.status_code == 200 and put_res.json().get("code") == 0:
                updated = True
            else:
                raise HTTPException(status_code=500, detail=f"下发新 Prompt 至设备失败: {put_res.text}")

        return {
            "is_false_positive": is_false_positive,
            "reason": reason,
            "old_prompt": current_prompt,
            "new_prompt": optimized_prompt,
            "updated_device": updated,
            "alert_image": img_path
        }