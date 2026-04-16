# Automated Prompt Tuning Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Automate the AI prompt tuning process by creating a continuous background job that batches recent alerts and optimizes device algorithm prompts dynamically.

**Architecture:** We will extend the existing `TaskORM` to track the processing cursor (`last_processed_time`). A new background worker module (`auto_tune_worker.py`) will be scheduled via the existing `APScheduler` in `main.py` to run every 60 seconds. It will process 5 new alerts at a time for each active tuning task.

**Tech Stack:** FastAPI, SQLAlchemy, SQLite, APScheduler, httpx

---

### Task 1: Database Schema Updates

**Files:**
- Modify: `backend/models/orm.py`
- Modify: `backend/models/schemas.py`
- Modify: `backend/routers/tasks.py`
- Create: `backend/scripts/migrate_tasks.py`

- [ ] **Step 1: Update ORM Model**
Modify `backend/models/orm.py` to add `last_processed_time` to `TaskORM`.

```python
# In TaskORM class:
    last_processed_time = Column(BigInteger, default=0)
```

- [ ] **Step 2: Update Pydantic Schemas**
Modify `backend/models/schemas.py` to include `last_processed_time` in `TaskBase` and `TaskResponse`.

```python
# In TaskBase class:
    last_processed_time: Optional[int] = 0

# In TaskUpdate class (optional, but good for completeness):
    last_processed_time: Optional[int] = None
```

- [ ] **Step 3: Update Task Creation Logic**
Modify `backend/routers/tasks.py` inside `create_task` to initialize `last_processed_time` to the current timestamp.

```python
    current_time = int(time.time() * 1000)
    new_task = TaskORM(
        id=task_id,
        **task.model_dump(),
        created_at=current_time,
        last_processed_time=current_time  # Start tracking from creation time
    )
```

- [ ] **Step 4: Create and Run Migration Script**
Since SQLite is used without Alembic, create a quick migration script to alter the table.
Create `backend/scripts/migrate_tasks.py`:

```python
import asyncio
from sqlalchemy import text
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from models.db import engine

async def migrate():
    async with engine.begin() as conn:
        try:
            await conn.execute(text("ALTER TABLE tasks ADD COLUMN last_processed_time BIGINT DEFAULT 0;"))
            print("Migration successful: added last_processed_time")
        except Exception as e:
            if "duplicate column name" in str(e):
                print("Column already exists, skipping.")
            else:
                print(f"Error during migration: {e}")

if __name__ == "__main__":
    asyncio.run(migrate())
```

- [ ] **Step 5: Run the migration**
```bash
cd backend && python scripts/migrate_tasks.py
```
Expected: "Migration successful..." or "Column already exists..."

---

### Task 2: Implement Auto Tune Worker

**Files:**
- Create: `backend/services/auto_tune_worker.py`

- [ ] **Step 1: Create Auto Tune Worker Module**
Create `backend/services/auto_tune_worker.py` with the background cycle logic. Note that it needs to handle batching 5 images and sending a modified prompt to the LLM.

```python
import asyncio
import time
import base64
import os
import json
import httpx
import hashlib
from sqlalchemy.future import select

from models.db import AsyncSessionLocal
from models.orm import TaskORM, DeviceORM, AlertORM
import database

async def do_login(client, base_url, device_obj, db_session):
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
            await db_session.commit()
            return True
    return False

async def process_tuning_task(task_obj, db_session):
    if not task_obj.algorithms or task_obj.algorithms == "[]":
        return

    algorithms = json.loads(task_obj.algorithms)
    target_agent_id = algorithms[0]

    # Get device
    query = select(DeviceORM).where(DeviceORM.device_id == task_obj.device_id)
    result = await db_session.execute(query)
    device_obj = result.scalars().first()
    if not device_obj:
        return

    # Get 5 newest alerts after last_processed_time
    query = select(AlertORM).where(
        AlertORM.deviceName == device_obj.name,
        AlertORM.alertType == target_agent_id,
        AlertORM.imageUrl != None,
        AlertORM.timestamp > (task_obj.last_processed_time or 0)
    ).order_by(AlertORM.timestamp.asc()).limit(5)
    
    result = await db_session.execute(query)
    alerts = result.scalars().all()

    if len(alerts) < 5:
        return  # Wait until we have 5 alerts

    # Read images
    encoded_images = []
    max_timestamp = 0
    for alert in alerts:
        if alert.timestamp > max_timestamp:
            max_timestamp = alert.timestamp
            
        img_path = alert.imageUrl
        if img_path.startswith("/"):
            img_path = img_path[1:]
        
        if os.path.exists(img_path):
            with open(img_path, "rb") as f:
                img_b64 = base64.b64encode(f.read()).decode('utf-8')
                mime_type = "image/png" if img_path.endswith(".png") else "image/jpeg"
                encoded_images.append({"url": f"data:{mime_type};base64,{img_b64}"})

    if len(encoded_images) == 0:
        # No valid images, just update timestamp to skip these broken alerts
        task_obj.last_processed_time = max_timestamp
        await db_session.commit()
        return

    llm_config = database.llm_config
    if not llm_config:
        return

    base_url = f"http://{device_obj.ip}:{device_obj.port}"
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        if device_obj.session_id:
            client.cookies.set("sessionID", device_obj.session_id)
            
        # Get task list from device
        tasks_res = await client.post(f"{base_url}/intelli_manager/task_list", json={"offset": 0, "size": 100, "condition": {}})
        if tasks_res.status_code != 200 or tasks_res.json().get("code") != 0:
            success = await do_login(client, base_url, device_obj, db_session)
            if not success:
                return
            tasks_res = await client.post(f"{base_url}/intelli_manager/task_list", json={"offset": 0, "size": 100, "condition": {}})
            
        tasks_data = tasks_res.json()
        if tasks_data.get("code") != 0:
            return

        device_tasks_list = tasks_data.get("data", {}).get("list", [])
        target_device_task = None
        for dt in device_tasks_list:
            if dt.get("task_name") == task_obj.device_task:
                target_device_task = dt
                break
        
        if not target_device_task:
            return

        current_prompt = ""
        agent_list = target_device_task.get("agent_list", [])
        target_agent = None
        for agent in agent_list:
            if agent.get("agent_id") == target_agent_id:
                target_agent = agent
                current_prompt = agent.get("agent_config", {}).get("prompt", "")
                break
        
        if not target_agent:
            return

        # Prepare LLM request
        prompt_instruction = f"""你现在是一个智能安防摄像头的提示词调优专家。
当前设备的任务是识别：{target_agent_id}。
设备目前使用的识别提示词(Prompt)是：
{current_prompt}

请观察用户提供的最新 {len(encoded_images)} 张『告警抓拍图』。
1. 综合判断这些图中是否存在**误报**（False Positive）？
2. 如果存在误报，请分析原因（如反光、形状相似等），并输出一段**全新优化后的 Prompt**，在原基础上增加排除这些干扰项的描述。如果不希望修改或者并非误报，请在optimized_prompt保持原样。

请严格以 JSON 格式返回：
{{
    "is_false_positive": true/false,
    "reason": "分析原因...",
    "optimized_prompt": "新的提示词内容..."
}}"""
        content_array = [{"type": "text", "text": prompt_instruction}]
        for img in encoded_images:
            content_array.append({"type": "image_url", "image_url": img})

        messages = [{"role": "user", "content": content_array}]

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
            if llm_res.status_code == 200:
                llm_data = llm_res.json()
                content_str = llm_data["choices"][0]["message"]["content"].strip()
                if content_str.startswith("```json"):
                    content_str = content_str[7:-3].strip()
                elif content_str.startswith("```"):
                    content_str = content_str[3:-3].strip()
                
                tuning_result = json.loads(content_str)
                is_false_positive = tuning_result.get("is_false_positive", False)
                optimized_prompt = tuning_result.get("optimized_prompt", current_prompt)

                if is_false_positive and optimized_prompt and optimized_prompt != current_prompt:
                    target_agent["agent_config"]["prompt"] = optimized_prompt
                    put_res = await client.put(f"{base_url}/intelli_manager/task", json=target_device_task)
                    if put_res.status_code == 200 and put_res.json().get("code") == 0:
                        pass # Successfully updated

                # Always update timestamp if LLM succeeded
                task_obj.last_processed_time = max_timestamp
                await db_session.commit()
                print(f"Auto-tune completed for task {task_obj.id}, new cursor: {max_timestamp}")
        except Exception as e:
            print(f"Auto-tune LLM failed for task {task_obj.id}: {e}")
            pass # Do not update timestamp, retry next time

async def run_auto_tune_cycle():
    async with AsyncSessionLocal() as session:
        # Find all active "Prompt调优" tasks
        query = select(TaskORM).where(
            TaskORM.task_type == "Prompt调优",
            TaskORM.status.in_(["布控中", "运行中", "未布控"]) # Let's process "未布控" too, as UI might default to it, but realistically it should be "布控中". Let's handle all.
        )
        result = await session.execute(query)
        tasks = result.scalars().all()

        for task in tasks:
            try:
                await process_tuning_task(task, session)
            except Exception as e:
                print(f"Error processing auto-tune for task {task.id}: {e}")
```

---

### Task 3: Schedule the Background Worker

**Files:**
- Modify: `backend/main.py`

- [ ] **Step 1: Register the Job in main.py**
Open `backend/main.py` and add the import and job scheduling inside `lifespan`.

```python
# Add this import near the top:
from services.auto_tune_worker import run_auto_tune_cycle

# Inside @asynccontextmanager async def lifespan(app: FastAPI):
    # Below scheduler.add_job(clean_old_alerts, ...)
    scheduler.add_job(run_auto_tune_cycle, IntervalTrigger(seconds=60), id="run_auto_tune_cycle")
```

- [ ] **Step 2: Commit**

```bash
git add backend/models/orm.py backend/models/schemas.py backend/routers/tasks.py backend/scripts/migrate_tasks.py backend/services/auto_tune_worker.py backend/main.py
git commit -m "feat: add continuous background auto-tune worker"
```
