"""图文互搜（Chinese-CLIP 文搜图 / 以图搜图）接口。

- GET  /search/status  ：模型与索引进度（前端状态条轮询）
- POST /search/text    ：中文自然语言 → 相似图
- POST /search/image   ：上传图片 → 相似图（multipart，字段名 file）
- POST /search/reindex ：清空索引（后台任务随后重建）/ 手动触发一轮建索
"""
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from models.db import get_db
from models.schemas import ImageSearchRequest
from services import clip_service, image_index_service

router = APIRouter(prefix="/search", tags=["image-search"])

MAX_UPLOAD_BYTES = 12 * 1024 * 1024      # 上传以图搜图的图片上限（12MB）


def _parse_ts(value: Optional[str], end_of_day: bool = False) -> Optional[int]:
    """把前端传来的日期字符串（YYYY-MM-DD 或 ISO）转成毫秒时间戳；非法返回 None。"""
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    if end_of_day and len(value) <= 10:
        dt = dt.replace(hour=23, minute=59, second=59)
    return int(dt.timestamp() * 1000)


@router.get("/status")
async def search_status():
    """模型状态 + 索引进度 + 数据量（前端状态条与「重建索引」按钮的依据）。"""
    return await image_index_service.status()


@router.post("/text")
async def search_text(payload: ImageSearchRequest):
    """文搜图：用自然语言描述检索预警图片。"""
    filters = {
        "deviceName": payload.deviceName,
        "channelname": payload.channelname,
        "channelid": payload.channelid,
        "alertType": payload.alertType,
        "start_ts": _parse_ts(payload.startDate),
        "end_ts": _parse_ts(payload.endDate, end_of_day=True),
    }
    res = await image_index_service.search_by_text(
        payload.query, kind=payload.kind, top_k=payload.top_k, filters=filters)
    return res


@router.post("/image")
async def search_image(
    file: UploadFile = File(...),
    kind: str = Form("big"),
    top_k: int = Form(30),
    deviceName: Optional[str] = Form(None),
    channelname: Optional[str] = Form(None),
    alertType: Optional[str] = Form(None),
    startDate: Optional[str] = Form(None),
    endDate: Optional[str] = Form(None),
):
    """以图搜图：上传一张图，找预警库中最相似的图。"""
    content = await file.read()
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail=f"图片过大（上限 {MAX_UPLOAD_BYTES // 1048576}MB）")
    filters = {
        "deviceName": deviceName,
        "channelname": channelname,
        "alertType": alertType,
        "start_ts": _parse_ts(startDate),
        "end_ts": _parse_ts(endDate, end_of_day=True),
    }
    res = await image_index_service.search_by_image(
        content, kind=kind, top_k=top_k, filters=filters)
    return res


@router.post("/reindex")
async def reindex(kind: Optional[str] = None, run_now: bool = True):
    """重建索引：先清空（kind 为空=整帧+小图都清），可选立即跑一轮建索。

    清空后剩余部分由后台定时任务继续补齐，接口立即返回，不做长时间阻塞。
    """
    if kind not in (None, "", "big", "crop", "all"):
        raise HTTPException(status_code=400, detail="kind 只能是 big / crop / all")
    target = None if kind in (None, "", "all") else kind
    if not clip_service.is_configured():
        raise HTTPException(status_code=400, detail="图文互搜已在配置中关闭（config.json → image_search.enabled）")
    deleted = await image_index_service.reset_index(target)
    result = {"deleted": deleted, "indexed": 0, "skipped": 0}
    if run_now:
        # 立刻跑一轮，让用户马上看到进度变化（编码在线程池里跑，不阻塞事件循环）
        cycle = await image_index_service.run_index_cycle()
        result.update({k: cycle.get(k, 0) for k in ("indexed", "skipped")})
        if cycle.get("error"):
            result["error"] = cycle["error"]
    return result
