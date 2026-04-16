from fastapi import APIRouter, HTTPException, Depends
from typing import List
import uuid
import httpx
import json
import hashlib
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from models.db import get_db
from models.schemas import Device
from models.orm import DeviceORM

router = APIRouter(prefix="/devices", tags=["devices"])

async def fetch_device_data(ip: str, port: str, username: str = "", password: str = "", existing_session_id: str = ""):
    channels = []
    device_tasks = []
    algorithms = set()
    status = "离线"
    session_id = existing_session_id
    
    try:
        base_url = f"http://{ip}:{port}"
        # Set a slightly longer timeout to accommodate login and multiple requests
        async with httpx.AsyncClient(timeout=5.0) as client:
            if session_id:
                client.cookies.set("sessionID", session_id)
            
            async def do_login():
                nonlocal status, session_id
                if not username or not password:
                    status = "密码错误"
                    return False
                    
                try:
                    challenge_res = await client.get(f"{base_url}/auth/login/challenge", params={"username": username})
                    if challenge_res.status_code == 200:
                        c_data = challenge_res.json()
                        if c_data.get("code") == 0:
                            data = c_data.get("data", {})
                            new_session_id = data.get("session_id", "")
                            challenge = data.get("challenge", "")
                            salt = data.get("salt", "")
                            
                            # Calculate password hash: sha256(pwd+salt+challenge)
                            pwd_str = f"{password}{salt}{challenge}"
                            hashed_pwd = hashlib.sha256(pwd_str.encode('utf-8')).hexdigest()
                            
                            login_payload = {
                                "session_id": new_session_id,
                                "username": username,
                                "password": hashed_pwd,
                                "aiotap_flag": 1
                            }
                            
                            login_res = await client.post(f"{base_url}/auth/login", json=login_payload)
                            if login_res.status_code == 200:
                                l_data = login_res.json()
                                if l_data.get("code") == 0:
                                    print(f"Successfully logged into device {ip}")
                                    session_id = new_session_id
                                    client.cookies.set("sessionID", session_id)
                                    status = "在线"
                                    return True
                                else:
                                    print(f"Device {ip} login failed: {l_data.get('message')}")
                                    status = "密码错误"
                            else:
                                print(f"Device {ip} login request returned status {login_res.status_code}")
                                status = "异常"
                        else:
                            print(f"Device {ip} challenge failed: {c_data.get('message')}")
                            status = "异常"
                    else:
                        print(f"Device {ip} challenge request returned status {challenge_res.status_code}")
                        status = "离线"
                except Exception as e:
                    print(f"Error during login process for {ip}: {e}")
                    status = "离线"
                return False

            # If we don't have a session, login immediately
            if not session_id:
                await do_login()
            else:
                # We have a session, let's verify if it's still valid
                try:
                    res = await client.post(f"{base_url}/device_access/device_config", json={"offset": 0, "size": 1})
                    if res.status_code == 200:
                        data = res.json()
                        if data.get("code") == 0:
                            status = "在线"
                        else:
                            # Might be expired or invalid
                            await do_login()
                    else:
                        await do_login()
                except Exception:
                    # network error or similar -> offline
                    status = "离线"
            
            # Fetch channels and tasks if online
            if status == "在线":
                try:
                    res = await client.post(f"{base_url}/device_access/device_config", json={"offset": 0, "size": 100})
                    if res.status_code == 200:
                        data = res.json()
                        if data.get("code") == 0:
                            for item in data.get("data", []):
                                channels.append({
                                    "device_id": str(item.get("device_id")),
                                    "device_name": item.get("device_name"),
                                    "proto": item.get("proto"),
                                    "rtsp": item.get("rtsp_param", {}).get("url")
                                })
                except Exception as e:
                    print(f"Error fetching channels from {ip}: {e}")

                try:
                    res = await client.post(f"{base_url}/intelli_manager/task_list", json={"offset": 0, "size": 100, "condition": {}})
                    if res.status_code == 200:
                        data = res.json()
                        if data.get("code") == 0:
                            task_list = data.get("data", {}).get("list", [])
                            for task in task_list:
                                agent_ids = []
                                for agent in task.get("agent_list", []):
                                    aid = agent.get('agent_id', '')
                                    if aid:
                                        agent_ids.append(aid)
                                        algorithms.add(aid)
                                
                                device_names = [d.get("device_name") for d in task.get("device_list", [])]
                                
                                device_tasks.append({
                                    "task_id": str(task.get("task_id")),
                                    "task_name": task.get("task_name"),
                                    "device_name": ", ".join(device_names),
                                    "agent_id": ", ".join(agent_ids)
                                })
                except Exception as e:
                    print(f"Error fetching tasks from {ip}: {e}")

    except Exception as global_e:
        print(f"Global error in fetch_device_data for {ip}: {global_e}")
        status = "离线"
            
    return channels, device_tasks, list(algorithms), status, session_id

@router.get("", response_model=List[Device])
async def get_devices(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(DeviceORM))
    return result.scalars().all()

@router.post("", response_model=Device)
async def create_device(device: Device, db: AsyncSession = Depends(get_db)):
    new_id = f"dev-{uuid.uuid4()}"
    device_data = device.dict(exclude={"id", "channels", "device_tasks", "available_algorithms", "status", "session_id"})
    
    # Try fetching initial data with auth
    channels, dtasks, algs, status, session_id = await fetch_device_data(device.ip, device.port, device.username, device.password)
    
    new_device = DeviceORM(
        id=new_id, 
        **device_data,
        status=status,
        session_id=session_id,
        channels=json.dumps(channels),
        device_tasks=json.dumps(dtasks),
        available_algorithms=json.dumps(algs)
    )
    db.add(new_device)
    await db.commit()
    await db.refresh(new_device)
    return new_device

@router.post("/{device_id}/fetch", response_model=Device)
async def manual_fetch_device(device_id: str, db: AsyncSession = Depends(get_db)):
    device_obj = await db.get(DeviceORM, device_id)
    if not device_obj:
        raise HTTPException(status_code=404, detail="Device not found")
    
    channels, dtasks, algs, status, session_id = await fetch_device_data(
        device_obj.ip, device_obj.port, device_obj.username, device_obj.password, device_obj.session_id
    )
    
    device_obj.status = status
    device_obj.session_id = session_id
    device_obj.channels = json.dumps(channels)
    device_obj.device_tasks = json.dumps(dtasks)
    device_obj.available_algorithms = json.dumps(algs)
    
    await db.commit()
    await db.refresh(device_obj)
    return device_obj

@router.put("/{device_id}", response_model=Device)
async def update_device(device_id: str, updated_device: Device, db: AsyncSession = Depends(get_db)):
    device_obj = await db.get(DeviceORM, device_id)
    if not device_obj:
        raise HTTPException(status_code=404, detail="Device not found")
    
    update_data = updated_device.dict(exclude={"id", "channels", "device_tasks", "available_algorithms", "status", "session_id"})
    
    # Check if critical auth/network parameters changed, if so re-fetch and re-login
    if (update_data.get("ip") != device_obj.ip or 
        update_data.get("port") != device_obj.port or 
        update_data.get("username") != device_obj.username or 
        update_data.get("password") != device_obj.password):
        
        channels, dtasks, algs, status, session_id = await fetch_device_data(
            update_data.get("ip"), update_data.get("port"), update_data.get("username"), update_data.get("password")
        )
        device_obj.status = status
        device_obj.session_id = session_id
        device_obj.channels = json.dumps(channels)
        device_obj.device_tasks = json.dumps(dtasks)
        device_obj.available_algorithms = json.dumps(algs)

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
