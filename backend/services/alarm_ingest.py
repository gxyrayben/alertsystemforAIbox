"""报警上报入口的可复用小函数：表单解析 / 字段提取 / 存图 / 时间解析。
把原先 receive_http_alarm 的巨型函数拆分为可单测的步骤。"""
import os
import json
import uuid
from datetime import datetime
from typing import Optional, Tuple

IMAGE_EXTS = (".jpg",".jpeg", ".png")


def _looks_like_image(field_name: str, filename: str) -> bool:
    return (
        "picture" in field_name
        or "alarm_picture" in filename
        or "alarm_picture_0" in filename
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
    #warehouse = alarm_json.get("warehouseV20Events", {})
    agent_events = alarm_json.get("agent_events", {})
    alarm_events = agent_events.get("alarmEvents", [])
    first_event = alarm_events[0] if alarm_events else {}
    content = first_event.get("content",{})
 
    return {
        "version": global_info.get("version", ""),
        "pts": global_info.get("times_ms", ""),
        "device_id": global_info.get("device_id", ""),
        "channel_id": additional.get("channel_id", ""),
        "channel_name": additional.get("device_name", ""),
        "alarm_minor": additional.get("alarm_minor", ""),
        "agent_evname": agent_events.get("event_tag", ""),
        "agent_evid": agent_events.get("event_id", ""),
        "reslut": content.get("result", ""),
    }


def save_alarm_images(images: dict) -> Optional[str]:
    """保存全部图片，返回首张图片的访问 URL（向后兼容旧调用）。"""
    urls = save_alarm_images_all(images)
    return urls[0] if urls else None


def save_alarm_images_all(images: dict) -> list:
    """按 日期/小时 分级目录保存全部图片，返回所有图片的访问 URL 列表（保持传入顺序）。

    多级子目录可避免单一目录文件数过大撑爆文件系统。
    约定：列表首张为告警大图（整帧），次张（若有）为送检小图（目标裁切）。
    """
    if not images:
        return []

    now = datetime.now()
    date_path, hour_path = now.strftime("%Y-%m-%d"), now.strftime("%H")
    save_dir = os.path.join("uploads", date_path, hour_path)
    os.makedirs(save_dir, exist_ok=True)

    urls = []
    for img_name, img_data in images.items():
        # 上传文件名来自设备端 multipart 字段，可能含路径分隔符或 ../，
        # 仅取末段文件名（兼容 / 与 \），避免越权写入 uploads/ 目录之外（路径穿越）。
        safe_name = os.path.basename((img_name or "").replace("\\", "/"))
        file_name = f"{uuid.uuid4()}_{safe_name}"
        with open(os.path.join(save_dir, file_name), "wb") as f:
            f.write(img_data)
        urls.append(f"/uploads/{date_path}/{hour_path}/{file_name}")
    return urls


def image_pixel_size(path: str) -> Optional[Tuple[int, int]]:
    """仅用标准库读取图片文件头得到 (宽, 高) 像素，支持 PNG / JPEG；失败返回 None。

    供告警反馈闭环的小模型参数调优使用（从送检小图 imageUrlCrop 量目标大小），
    刻意不引入 Pillow 依赖，只解析文件头字节。
    """
    if not path:
        return None
    fs_path = path[1:] if path.startswith("/") else path
    try:
        with open(fs_path, "rb") as f:
            head = f.read(2)
            if head == b"\xff\xd8":  # JPEG：逐段扫描到 SOF marker 读宽高
                f.seek(2)
                while True:
                    b = f.read(1)
                    if not b:
                        return None
                    if b != b"\xff":
                        continue
                    marker = f.read(1)
                    while marker == b"\xff":  # 跳过填充 0xFF
                        marker = f.read(1)
                    if not marker:
                        return None
                    m = marker[0]
                    # SOF0..SOF15（不含 DHT/JPG/DAC 的 C4/C8/CC），含宽高
                    if 0xC0 <= m <= 0xCF and m not in (0xC4, 0xC8, 0xCC):
                        f.read(3)  # 段长(2) + 精度(1)
                        hw = f.read(4)
                        if len(hw) < 4:
                            return None
                        height = (hw[0] << 8) + hw[1]
                        width = (hw[2] << 8) + hw[3]
                        return width, height
                    seg_len = f.read(2)
                    if len(seg_len) < 2:
                        return None
                    f.seek(((seg_len[0] << 8) + seg_len[1]) - 2, os.SEEK_CUR)
            elif head == b"\x89P":  # PNG：IHDR 紧随 8 字节签名，前 8 字节为宽高
                f.seek(16)
                whb = f.read(8)
                if len(whb) < 8:
                    return None
                width = int.from_bytes(whb[0:4], "big")
                height = int.from_bytes(whb[4:8], "big")
                return width, height
    except Exception as e:
        print(f"image_pixel_size failed for {fs_path}: {e}")
    return None


def parse_alarm_time(pts) -> Tuple[str, int]:
    """把设备上报的 pts（毫秒）解析为 (可读时间字符串, 毫秒时间戳)。"""
    now = datetime.now()
    try:
        pts_ts = int(pts) / 1000 if pts else now.timestamp()
        return datetime.fromtimestamp(pts_ts).strftime("%Y-%m-%d %H:%M:%S"), int(pts_ts * 1000)
    except Exception:
        return now.strftime("%Y-%m-%d %H:%M:%S"), int(now.timestamp() * 1000)
