# E2E Simulation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create an automated simulation script that acts as both a mock camera device and a client, pushing data and interacting with the backend to verify the full prompt-tuning workflow.

**Architecture:** A standalone Python script `tests/simulate_e2e.py`. It uses `threading` to run a lightweight FastAPI mock camera device on port `8080`. Then it runs a sequence of `httpx` API calls to the main backend (port `8000`) to register the device, create the task, push mock alarms with dummy images, and poll the logs to verify successful LLM auto-tuning.

**Tech Stack:** Python, FastAPI, Uvicorn, httpx, asyncio, threading

---

### Task 1: Create the Mock Device Server

**Files:**
- Create: `tests/simulate_e2e.py`

- [ ] **Step 1: Setup script structure and mock device**

```python
import asyncio
import threading
import time
import httpx
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import base64
import os

mock_app = FastAPI(title="Mock Camera Device")
received_prompts = []

@mock_app.get("/auth/login/challenge")
async def get_challenge(username: str = ""):
    return JSONResponse({
        "code": 0,
        "data": {
            "session_id": "mock_session_123",
            "salt": "mocksalt",
            "challenge": "mockchallenge"
        }
    })

@mock_app.post("/auth/login")
async def login(request: Request):
    return JSONResponse({"code": 0, "msg": "success"})

@mock_app.post("/intelli_manager/task_list")
async def task_list(request: Request):
    # Mocking a task list response expected by the backend
    return JSONResponse({
        "code": 0,
        "data": {
            "list": [
                {
                    "task_id": "MOCK-TASK-01",
                    "task_name": "测试区域抓拍",
                    "device_name": "channel_1",
                    "agent_list": [
                        {
                            "agent_id": "人脸抓拍",
                            "agent_config": {
                                "prompt": "发现任何人脸都抓拍"
                            }
                        }
                    ]
                }
            ]
        }
    })

@mock_app.put("/intelli_manager/task")
async def update_task(request: Request):
    data = await request.json()
    try:
        new_prompt = data["agent_list"][0]["agent_config"]["prompt"]
        received_prompts.append(new_prompt)
        print(f"[Mock Device] Received new prompt update: {new_prompt}")
    except Exception as e:
        print(f"[Mock Device] Error parsing updated task: {e}")
        
    return JSONResponse({"code": 0, "msg": "success"})

def run_mock_server():
    uvicorn.run(mock_app, host="0.0.0.0", port=8080, log_level="warning")

def start_mock_server():
    t = threading.Thread(target=run_mock_server, daemon=True)
    t.start()
    time.sleep(2) # Wait for server to start
```

---

### Task 2: Implement the Simulation Flow

**Files:**
- Modify: `tests/simulate_e2e.py:65-150`

- [ ] **Step 1: Write the main simulation logic**

```python
# Append to the end of tests/simulate_e2e.py

BACKEND_URL = "http://localhost:8000"

# A minimal 1x1 valid PNG image in base64
TINY_PNG_B64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII="

async def run_simulation():
    print("=== 开始全链路仿真测试 ===")
    
    start_mock_server()
    print("1. 模拟设备服务已启动 (Port: 8080)")

    async with httpx.AsyncClient() as client:
        # 1. 检查后端是否存活
        try:
            await client.get(f"{BACKEND_URL}/docs")
        except Exception:
            print("❌ 后端服务未启动，请先在 backend 目录运行: python main.py")
            return

        # 2. 注册设备
        device_payload = {
            "device_id": "SIM-DEV-001",
            "name": "仿真测试摄像头",
            "ip": "127.0.0.1",
            "port": "8080",
            "username": "admin",
            "password": "password",
            "channels": '[{"device_name": "channel_1"}]',
            "device_tasks": '[{"task_name": "测试区域抓拍", "device_name": "channel_1", "agent_id": "人脸抓拍"}]'
        }
        res = await client.post(f"{BACKEND_URL}/devices", json=device_payload)
        print(f"2. 注册仿真设备: {res.status_code}")

        # 3. 创建 Prompt调优 任务
        task_payload = {
            "name": "E2E仿真调优任务",
            "task_type": "Prompt调优",
            "device_id": "SIM-DEV-001",
            "device_task": "测试区域抓拍",
            "channel": "channel_1",
            "algorithms": '["人脸抓拍"]',
            "status": "布控中"
        }
        res = await client.post(f"{BACKEND_URL}/api/tasks", json=task_payload)
        print(f"3. 创建调优任务: {res.status_code}")

        # 4. 推送 5 条告警数据
        print("4. 开始推送 5 条模拟告警数据...")
        img_bytes = base64.b64decode(TINY_PNG_B64)
        
        for i in range(5):
            alarm_json = {
                "global_info": {
                    "version": "1.0",
                    "device_id": "SIM-DEV-001"
                },
                "agent_events": {
                    "agent_name": "人脸抓拍",
                    "alarmEvents": [{"agent_alias": "人脸抓拍", "content": "发现可疑人脸"}]
                }
            }
            
            files = {
                "global_info": (None, json.dumps(alarm_json), "application/json"),
                "alarm_picture_1.png": ("test_alarm.png", img_bytes, "image/png")
            }
            
            res = await client.post(f"{BACKEND_URL}/api/http/alarms", files=files)
            print(f"  - 推送第 {i+1} 条告警: {res.status_code}")
            await asyncio.sleep(1)

        # 5. 轮询日志等待结果
        print("\n5. 开始轮询系统日志，等待后台自动调优触发 (最长等待 90 秒)...")
        print("   (注意：如果您未在系统配置真实的大模型 API Key，任务将会在请求 LLM 时失败并中止)")
        
        for attempt in range(18):
            res = await client.get(f"{BACKEND_URL}/api/logs?page=1&size=5")
            if res.status_code == 200:
                logs = res.json().get("items", [])
                for log in logs:
                    if "Prompt Optimization" in log["api_path"] and "SIM-DEV-001" in log["device_name"]:
                        print("\n✅ 成功！检测到调优下发日志：")
                        print(f"   执行结果: {log['result']}")
                        print(f"   下发新提示词: {log['parameters']}")
                        return
            
            await asyncio.sleep(5)
            print(f"   等待中... ({attempt * 5}s)")
            
        print("\n⚠️ 轮询超时。可能是大模型配置错误或网络原因，请检查后端运行终端中的报错信息。")

if __name__ == "__main__":
    os.makedirs("tests", exist_ok=True)
    asyncio.run(run_simulation())
```

- [ ] **Step 2: Commit**

```bash
git add tests/simulate_e2e.py
git commit -m "test: add E2E simulation script for auto-tuning workflow"
```
