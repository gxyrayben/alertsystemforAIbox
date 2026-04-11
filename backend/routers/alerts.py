from fastapi import APIRouter, HTTPException, Query, Request, UploadFile, Depends
from typing import List, Optional
from datetime import datetime
import json
import uuid
import os
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import desc
from models.db import get_db
from models.schemas import Alert, AIAnalyzeRequest
from models.orm import AlertORM

router = APIRouter(tags=["alerts"])

async def receive_http_alarm(request: Request, db: AsyncSession = Depends(get_db)):
    try:
        form = await request.form()
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid form data: {e}")
        
    alarm_json = None
    images = {}

    for field_name, field_value in form.items():
        if hasattr(field_value, "read"):
            filename = getattr(field_value, "filename", "") or ""
            if "alarm_picture" in field_name or "alarm_picture" in filename or filename.endswith(".jpg") or filename.endswith(".png"):
                content = await field_value.read()
                images[filename or field_name] = content
            else:
                try:
                    content = await field_value.read()
                    parsed = json.loads(content.decode("utf-8"))
                    if "global_info" in parsed:
                        alarm_json = parsed
                except Exception:
                    pass
        elif isinstance(field_value, str):
            try:
                parsed = json.loads(field_value)
                if "global_info" in parsed:
                    alarm_json = parsed
            except Exception:
                pass

    if not alarm_json:
        raise HTTPException(status_code=400, detail="Missing or invalid JSON info")

    global_info = alarm_json.get("global_info", {})
    version = global_info.get("version", "")
    device_id = global_info.get("device_id", "")

    # **安全增强：设备白名单校验**
    if not device_id:
        raise HTTPException(status_code=403, detail="Forbidden: Missing device_id in protocol")
    
    from models.orm import DeviceORM
    device_check = await db.execute(select(DeviceORM).where(DeviceORM.device_id == str(device_id)))
    matched_device = device_check.scalar()
    if not matched_device:
        raise HTTPException(status_code=403, detail=f"Forbidden: Device ID '{device_id}' is not registered in this system")

    additional = alarm_json.get("additional", {})
    alarm_minor = additional.get("alarm_minor", "")
    device_name = matched_device.name # 优先使用系统中录入的设备名称，更准确

    agent_events = alarm_json.get("agent_events", {})
    agent_name = agent_events.get("agent_name", "")
    pts = agent_events.get("pts", "")
    
    alarm_events_list = agent_events.get("alarmEvents", [])
    agent_alias = ""
    content = ""
    if alarm_events_list:
        agent_alias = alarm_events_list[0].get("agent_alias", "")
        content = alarm_events_list[0].get("content", "")

    # **性能优化点：按日期和小时构建多级子目录，防止单一目录文件数超大撑爆文件系统树**
    image_url = None
    now = datetime.now()
    date_path = now.strftime("%Y-%m-%d")
    hour_path = now.strftime("%H")
    save_dir = os.path.join("uploads", date_path, hour_path)
    os.makedirs(save_dir, exist_ok=True)
    
    if images:
        for img_name, img_data in images.items():
            file_name = f"{uuid.uuid4()}_{img_name}"
            file_path = os.path.join(save_dir, file_name)
            with open(file_path, "wb") as f:
                f.write(img_data)
            if not image_url:
                image_url = f"/uploads/{date_path}/{hour_path}/{file_name}"

    try:
        pts_ts = int(pts) / 1000 if pts else now.timestamp()
        alarm_time = datetime.fromtimestamp(pts_ts).strftime('%Y-%m-%d %H:%M:%S')
        timestamp_val = int(pts_ts * 1000)
    except:
        alarm_time = now.strftime('%Y-%m-%d %H:%M:%S')
        timestamp_val = int(now.timestamp() * 1000)

    new_id = f"alert-{uuid.uuid4()}"
    new_alert = AlertORM(
        id=new_id,
        deviceName=device_name or f"设备 {device_id}" or "未知设备",
        alertType=agent_alias or alarm_minor or "未知类型",
        time=alarm_time,
        timestamp=timestamp_val,
        imageUrl=image_url,
        remark=f"版本: {version}, 规则: {agent_name} ({content})"
    )
    db.add(new_alert)
    await db.commit()

    return {"message": "Success", "alert_id": new_id}

@router.get("/alerts", response_model=List[Alert])
async def get_alerts(
    deviceName: Optional[str] = None,
    alertType: Optional[str] = None,
    startDate: Optional[str] = None,
    endDate: Optional[str] = None,
    db: AsyncSession = Depends(get_db)
):
    query = select(AlertORM)
    if deviceName:
        query = query.where(AlertORM.deviceName.like(f"%{deviceName}%"))
    if alertType:
        query = query.where(AlertORM.alertType == alertType)
    if startDate:
        try:
            start_ts = int(datetime.fromisoformat(startDate).timestamp() * 1000)
            query = query.where(AlertORM.timestamp >= start_ts)
        except ValueError:
            pass
    if endDate:
        try:
            end_dt = datetime.fromisoformat(endDate)
            if len(endDate) <= 10:  # e.g., "YYYY-MM-DD"
                end_dt = end_dt.replace(hour=23, minute=59, second=59)
            end_ts = int(end_dt.timestamp() * 1000)
            query = query.where(AlertORM.timestamp <= end_ts)
        except ValueError:
            pass
    
    # 限制前端只拉取最新的100条展示，减轻渲染压力
    query = query.order_by(desc(AlertORM.timestamp)).limit(100)
    result = await db.execute(query)
    return result.scalars().all()

@router.post("/ai/analyze")
async def analyze_alert(request: AIAnalyzeRequest, db: AsyncSession = Depends(get_db)):
    alert = await db.get(AlertORM, request.alert_id)
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    
    import asyncio
    await asyncio.sleep(1)
    
    ai_text = f"AI 建议：已确认 {alert.alertType}，建议通知巡逻人员前往核实。"
    alert.remark = ai_text
    await db.commit()
    
    return {"remark": ai_text}
