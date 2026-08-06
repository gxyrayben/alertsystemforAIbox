"""报警上报入口的可复用小函数：表单解析 / 字段提取 / 存图 / 时间解析。
把原先 receive_http_alarm 的巨型函数拆分为可单测的步骤。"""
import os
import json
import uuid
from datetime import datetime
from typing import Optional, Tuple

IMAGE_EXTS = (".jpg", ".png")


def _looks_like_image(field_name: str, filename: str) -> bool:
    return (
        "alarm_picture" in field_name
        or "alarm_picture" in filename
        or filename.endswith(IMAGE_EXTS)
    )


def _maybe_alarm_json(raw: bytes) -> Optional[dict]:
    """尝试把原始内容解析成含 global_info 的报警 JSON，失败返回 None。"""
    try:
        parsed = json.loads(raw.decode("utf-8") if isinstance(raw, bytes) else raw)
        if "global_info" in parsed:
            return parsed
    except Exception:
        pass
    return None


async def parse_alarm_form(form) -> Tuple[Optional[dict], dict]:
    """从上传表单中分离出报警 JSON 与图片二进制字典。"""
    alarm_json = None
    images = {}
    for field_name, field_value in form.items():
        if hasattr(field_value, "read"):  # UploadFile
            filename = getattr(field_value, "filename", "") or ""
            content = await field_value.read()
            if _looks_like_image(field_name, filename):
                images[filename or field_name] = content
            else:
                alarm_json = _maybe_alarm_json(content) or alarm_json
        elif isinstance(field_value, str):
            alarm_json = _maybe_alarm_json(field_value) or alarm_json
    return alarm_json, images


def extract_alarm_fields(alarm_json: dict) -> dict:
    """从报警 JSON 中提取落库所需的结构化字段。"""
    global_info = alarm_json.get("global_info", {})
    additional = alarm_json.get("additional", {})
    agent_events = alarm_json.get("agent_events", {})
    alarm_events = agent_events.get("alarmEvents", [])
    first_event = alarm_events[0] if alarm_events else {}
    return {
        "version": global_info.get("version", ""),
        "device_id": global_info.get("device_id", ""),
        "alarm_minor": additional.get("alarm_minor", ""),
        "agent_name": agent_events.get("agent_name", ""),
        "pts": agent_events.get("pts", ""),
        "agent_alias": first_event.get("agent_alias", ""),
        "content": first_event.get("content", ""),
    }


def save_alarm_images(images: dict) -> Optional[str]:
    """按 日期/小时 分级目录保存图片，返回首张图片的访问 URL。

    多级子目录可避免单一目录文件数过大撑爆文件系统。
    """
    if not images:
        return None

    now = datetime.now()
    date_path, hour_path = now.strftime("%Y-%m-%d"), now.strftime("%H")
    save_dir = os.path.join("uploads", date_path, hour_path)
    os.makedirs(save_dir, exist_ok=True)

    image_url = None
    for img_name, img_data in images.items():
        file_name = f"{uuid.uuid4()}_{img_name}"
        with open(os.path.join(save_dir, file_name), "wb") as f:
            f.write(img_data)
        if not image_url:
            image_url = f"/uploads/{date_path}/{hour_path}/{file_name}"
    return image_url


def parse_alarm_time(pts) -> Tuple[str, int]:
    """把设备上报的 pts（毫秒）解析为 (可读时间字符串, 毫秒时间戳)。"""
    now = datetime.now()
    try:
        pts_ts = int(pts) / 1000 if pts else now.timestamp()
        return datetime.fromtimestamp(pts_ts).strftime("%Y-%m-%d %H:%M:%S"), int(pts_ts * 1000)
    except Exception:
        return now.strftime("%Y-%m-%d %H:%M:%S"), int(now.timestamp() * 1000)
