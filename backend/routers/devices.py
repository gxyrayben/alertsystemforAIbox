from fastapi import APIRouter, HTTPException, Depends
from typing import List
import uuid
import httpx
import json
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from models.db import get_db
from models.schemas import Device
from models.orm import DeviceORM

router = APIRouter(prefix="/devices", tags=["devices"])

async def fetch_device_data(ip: str, port: str):
    channels = []
    device_tasks = []
    algorithms = set()
    
    base_url = f"http://{ip}:{port}"
    
    async with httpx.AsyncClient(timeout=5.0) as client:
        # 1. Fetch channels
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

        # 2. Fetch tasks
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
            
    # If no algorithms found from tasks, add some default ones
    if not algorithms:
        algorithms = {"区域入侵", "越界检测", "车辆违停", "人员聚集", "烟火检测", "异常离岗"}
            
    return channels, device_tasks, list(algorithms)

@router.get("", response_model=List[Device])
async def get_devices(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(DeviceORM))
    return result.scalars().all()

@router.post("", response_model=Device)
async def create_device(device: Device, db: AsyncSession = Depends(get_db)):
    new_id = f"dev-{uuid.uuid4()}"
    device_data = device.dict(exclude={"id", "channels", "device_tasks", "available_algorithms"})
    
    # Try fetching initial data
    channels, dtasks, algs = await fetch_device_data(device.ip, device.port)
    
    new_device = DeviceORM(
        id=new_id, 
        **device_data,
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
    
    channels, dtasks, algs = await fetch_device_data(device_obj.ip, device_obj.port)
    
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
    
    update_data = updated_device.dict(exclude={"id", "channels", "device_tasks", "available_algorithms"})
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
