from fastapi import APIRouter, HTTPException, Depends
from typing import List
import uuid
import json
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from models.db import get_db
from models.schemas import Device
from models.orm import DeviceORM
from services.device_service import DeviceService

router = APIRouter(prefix="/devices", tags=["devices"])

@router.get("", response_model=List[Device])
async def get_devices(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(DeviceORM))
    return result.scalars().all()

@router.post("", response_model=Device)
async def create_device(device: Device, db: AsyncSession = Depends(get_db)):
    new_id = f"dev-{uuid.uuid4()}"
    device_data = device.dict(exclude={"id", "channels", "device_tasks", "available_algorithms", "status", "session_id"})
    
    # Try fetching initial data with auth via Service
    channels, dtasks, algs, status, session_id = await DeviceService.fetch_device_data(device.ip, device.port, device.username, device.password)
    
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
    
    channels, dtasks, algs, status, session_id = await DeviceService.fetch_device_data(
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
    
    # Check if critical parameters changed
    if (update_data.get("ip") != device_obj.ip or 
        update_data.get("port") != device_obj.port or 
        update_data.get("username") != device_obj.username or 
        update_data.get("password") != device_obj.password):
        
        channels, dtasks, algs, status, session_id = await DeviceService.fetch_device_data(
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
