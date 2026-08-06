from fastapi import APIRouter, HTTPException, Request, Depends
from typing import List, Optional
from datetime import datetime
import asyncio
import uuid
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import desc
from models.db import get_db
from models.schemas import Alert, AIAnalyzeRequest
from models.orm import AlertORM, DeviceORM
from services import alarm_ingest

router = APIRouter(tags=["alerts"])


async def receive_http_alarm(request: Request, db: AsyncSession = Depends(get_db)):
    try:
        form = await request.form()
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid form data: {e}")

    alarm_json, images = await alarm_ingest.parse_alarm_form(form)
    if not alarm_json:
        raise HTTPException(status_code=400, detail="Missing or invalid JSON info")

    fields = alarm_ingest.extract_alarm_fields(alarm_json)
    device_id = fields["device_id"]

    # 安全增强：设备白名单校验
    if not device_id:
        raise HTTPException(status_code=403, detail="Forbidden: Missing device_id in protocol")
    result = await db.execute(select(DeviceORM).where(DeviceORM.device_id == str(device_id)))
    matched_device = result.scalar()
    if not matched_device:
        raise HTTPException(status_code=403, detail=f"Forbidden: Device ID '{device_id}' is not registered in this system")

    image_url = alarm_ingest.save_alarm_images(images)
    alarm_time, timestamp_val = alarm_ingest.parse_alarm_time(fields["pts"])

    new_id = f"alert-{uuid.uuid4()}"
    new_alert = AlertORM(
        id=new_id,
        deviceName=matched_device.name or f"设备 {device_id}",  # 优先使用系统录入的名称
        alertType=fields["agent_alias"] or fields["alarm_minor"] or "未知类型",
        time=alarm_time,
        timestamp=timestamp_val,
        imageUrl=image_url,
        remark=f"版本: {fields['version']}, 规则: {fields['agent_name']} ({fields['content']})",
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
    db: AsyncSession = Depends(get_db),
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
            if len(endDate) <= 10:  # 形如 "YYYY-MM-DD"，补到当天 23:59:59
                end_dt = end_dt.replace(hour=23, minute=59, second=59)
            query = query.where(AlertORM.timestamp <= int(end_dt.timestamp() * 1000))
        except ValueError:
            pass

    # 只拉取最新 100 条展示，减轻渲染压力
    query = query.order_by(desc(AlertORM.timestamp)).limit(100)
    result = await db.execute(query)
    return result.scalars().all()


@router.post("/ai/analyze")
async def analyze_alert(request: AIAnalyzeRequest, db: AsyncSession = Depends(get_db)):
    alert = await db.get(AlertORM, request.alert_id)
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")

    await asyncio.sleep(1)
    ai_text = f"AI 建议：已确认 {alert.alertType}，建议通知巡逻人员前往核实。"
    alert.remark = ai_text
    await db.commit()
    return {"remark": ai_text}
