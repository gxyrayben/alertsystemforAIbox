from fastapi import APIRouter, HTTPException, Request, Depends
from typing import List, Optional
from datetime import datetime
import asyncio
import json
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

    alarm_json, image_parts = await alarm_ingest.parse_alarm_form(form)
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

    # 图片落位：设备一次推两个二进制部件，约定【第 1 个=告警大图（整帧）、第 2 个=送检小图（目标裁切）】，
    # 故按 multipart 到达顺序取 [0]/[1]。若报文里还内嵌了整帧图（full_images 非空）则兜底使用。
    # 文件名按 {设备业务ID}_{通道id}_{通道名}_{子类型}_{图片ID}_{big|crop} 生成（见 build_image_basename）。
    naming = {
        "device_id": fields["device_id"],
        "channel_id": fields["channel_id"],
        "channel_name": fields["channel_name"],
        "alarm_type": fields["alarm_minor"] or fields["agent_evid"] or "unknown",
    }
    multipart_urls = alarm_ingest.save_alarm_images_all(image_parts, naming)
    full_urls = alarm_ingest.save_embedded_images(alarm_json, naming)
    if multipart_urls:
        image_url = multipart_urls[0]
        image_url_crop = multipart_urls[1] if len(multipart_urls) > 1 else None
    elif full_urls:
        image_url = full_urls[0]
        image_url_crop = None
    else:
        image_url = image_url_crop = None
    alarm_time, timestamp_val = alarm_ingest.parse_alarm_time(fields["pts"])

    new_id = f"alert-{uuid.uuid4()}"
    new_alert = AlertORM(
        id=new_id,
        deviceName=matched_device.name or device_id,  # 优先使用系统录入的名称
        alertType=fields["alarm_minor"] or fields["agent_evid"] or "unknown",
        time=alarm_time,
        timestamp=timestamp_val,
        imageUrl=image_url,
        imageUrlCrop=image_url_crop,
        channelid=fields["channel_id"], 
        channelname=fields["channel_name"],  # 触发通道名（= 设备通道快照里的 device_name），供预警管理按通道检索
        remark=fields["reslut"],
        ### //remark=f"版本: {fields['version']}, 规则: {fields['agent_name']} ({fields['content']})",
        # 原始上报报文：详情页可展开核对，后续新增字段（如目标 TrackID）也有据可查
        rawPayload=alarm_ingest.dump_raw_payload(alarm_json),
    )
    db.add(new_alert)
    await db.commit()
    return {"message": "Success", "alert_id": new_id}


@router.get("/alerts", response_model=List[Alert])
async def get_alerts(
    deviceName: Optional[str] = None,
    channelid: Optional[str] = None,
    channelname: Optional[str] = None,
    alertType: Optional[str] = None,
    startDate: Optional[str] = None,
    endDate: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    query = select(AlertORM)
    if deviceName:
        query = query.where(AlertORM.deviceName == deviceName)
    if channelid:
            query = query.where(AlertORM.channelid == channelid)
    if channelname:
        query = query.where(AlertORM.channelname == channelname)
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


@router.get("/alerts/{alert_id}")
async def get_alert_detail(alert_id: str, db: AsyncSession = Depends(get_db)):
    """单条预警的详情（只读）：告警全字段 + 设备信息 + 触发通道信息 + 原始上报报文。

    - 设备信息：按 alerts.deviceName（= 系统录入的设备名）关联 devices 表，取业务ID/IP/端口/协议/在线状态；
    - 通道信息：从该设备 channels 快照里按 alerts.channelid 匹配（快照 device_id 可能是数字，按字符串比），
      取通道名/在线状态/RTSP 地址；匹配不到时只带通道名（channelname 字段）；
    - 原始报文：rawPayload（历史告警可能为空，前端显示"历史数据未采集"）。
    """
    alert = await db.get(AlertORM, alert_id)
    if not alert:
        raise HTTPException(status_code=404, detail="预警记录不存在")

    device_info, channel_info = None, None
    if alert.deviceName:
        dev = (await db.execute(
            select(DeviceORM).where(DeviceORM.name == alert.deviceName))).scalars().first()
        if dev:
            device_info = {
                "id": dev.id,
                "device_id": dev.device_id,
                "name": dev.name,
                "ip": dev.ip,
                "port": dev.port,
                "protocol": dev.protocol or "http",
                "status": dev.status,
                "address": f"{(dev.protocol or 'http')}://{dev.ip}:{dev.port}",
            }
            try:
                channels = json.loads(dev.channels or "[]")
            except (TypeError, ValueError) as e:
                # 只吞"内容不是合法 JSON"这类数据问题；编程错误（如漏 import）要让它冒出来，
                # 否则会静默退化成"永远匹配不到通道"，排查成本极高
                print(f"[alerts] 解析设备「{dev.name}」通道快照失败：{e}")
                channels = []
            ch_list = [ch for ch in (channels if isinstance(channels, list) else []) if isinstance(ch, dict)]
            # 主匹配：通道号（与设备快照 device_id 一致）；设备重新接入后通道号可能变化，
            # 故再按【通道名】兜底匹配一次（名字通常保留），并在 matched_by 里标明依据。
            hit, matched_by = None, ""
            if alert.channelid:
                hit = next((c for c in ch_list if str(c.get("device_id")) == str(alert.channelid)), None)
                matched_by = "id" if hit else ""
            if hit is None and alert.channelname:
                hit = next((c for c in ch_list if str(c.get("device_name")) == str(alert.channelname)), None)
                matched_by = "name" if hit else ""
            if hit is not None:
                channel_info = {
                    "device_id": str(hit.get("device_id") or ""),
                    "name": hit.get("device_name") or alert.channelname or "",
                    "proto": hit.get("proto") or "",
                    "rtsp": hit.get("rtsp") or "",
                    "gbid": hit.get("gbid") or "",
                    "onlinestatus": hit.get("onlinestatus") or "",
                    # 命中标记：False 表示只是回落展示上报里的通道名（快照里找不到该通道）
                    "matched": True,
                    "matched_by": matched_by,   # id=按通道号命中 / name=按通道名兜底命中
                }
    if channel_info is None:
        # 快照里找不到（老告警 / 通道已删 / 设备刚接入快照为空）时，至少把入库时记下的通道名带回去；
        # matched=False 让前端能明确提示"来自上报记录，非设备快照"，避免与命中混淆
        channel_info = {
            "device_id": alert.channelid or "",
            "name": alert.channelname or "",
            "proto": "", "rtsp": "", "gbid": "", "onlinestatus": "",
            "matched": False,
            "matched_by": "",
        }

    return {
        "id": alert.id,
        "deviceName": alert.deviceName,
        "alertType": alert.alertType,
        "time": alert.time,
        "timestamp": alert.timestamp,
        "imageUrl": alert.imageUrl,          # 告警大图（整帧）
        "imageUrlCrop": alert.imageUrlCrop,  # 送检小图（目标裁切），可能为空
        "channelid": alert.channelid,
        "channelname": alert.channelname,
        "remark": alert.remark or "",        # 描述信息（上报 content.result）
        "feedback_status": alert.feedback_status or "",
        "feedback_note": alert.feedback_note or "",
        "feedback_time": alert.feedback_time,
        "feedback_submitted": alert.feedback_submitted or 0,
        "rawPayload": alert.rawPayload or "",
        "device": device_info,
        "channel": channel_info,
    }


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
