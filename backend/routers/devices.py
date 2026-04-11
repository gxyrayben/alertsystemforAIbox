from fastapi import APIRouter, HTTPException, Depends
from typing import List
import uuid
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from models.db import get_db
from models.schemas import Device
from models.orm import DeviceORM

router = APIRouter(prefix="/devices", tags=["devices"])

@router.get("", response_model=List[Device])
async def get_devices(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(DeviceORM))
    return result.scalars().all()

@router.post("", response_model=Device)
async def create_device(device: Device, db: AsyncSession = Depends(get_db)):
    new_id = f"dev-{uuid.uuid4()}"
    device_data = device.dict(exclude={"id"})
    new_device = DeviceORM(id=new_id, **device_data)
    db.add(new_device)
    await db.commit()
    await db.refresh(new_device)
    return new_device

@router.put("/{device_id}", response_model=Device)
async def update_device(device_id: str, updated_device: Device, db: AsyncSession = Depends(get_db)):
    device_obj = await db.get(DeviceORM, device_id)
    if not device_obj:
        raise HTTPException(status_code=404, detail="Device not found")
    
    update_data = updated_device.dict(exclude={"id"})
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
