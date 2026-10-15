"""报警上报入口的可复用小函数：表单解析 / 字段提取 / 存图 / 时间解析。
把原先 receive_http_alarm 的巨型函数拆分为可单测的步骤。"""
import os
import base64
import json
import re
import uuid
from datetime import datetime
from typing import Optional, Tuple

IMAGE_EXTS = (".jpg",".jpeg", ".png")
RAW_PAYLOAD_LIMIT = 8192      # 原始上报 JSON 落库上限（字节，超出截断并标注）


def _content_text(content) -> str:
    """从 alarmEvents[i].content 里取描述文本。

    设备历史上发过两种形态：字符串（直接就是描述）与对象（描述在 result 字段）。
    旧实现只按对象处理，收到字符串会抛 AttributeError 让整条告警入库 500，这里两种都兼容。
    """
    if isinstance(content, dict):
        for key in ("result", "text", "content", "desc"):
            value = content.get(key)
            if isinstance(value, str) and value:
                return value
            if value is not None and not isinstance(value, (dict, list)):
                return str(value)
        return ""
    if isinstance(content, str):
        return content
    if content is None:
        return ""
    return str(content)


def dump_raw_payload(alarm_json: Optional[dict], limit: int = RAW_PAYLOAD_LIMIT) -> str:
    """把原始上报 JSON 序列化后落库（超长截断，避免单条告警把库撑大）。"""
    if not alarm_json:
        return ""
    try:
        text = json.dumps(alarm_json, ensure_ascii=False)
    except Exception as e:  # noqa: BLE001
        return f'{{"error": "原始报文序列化失败: {e}"}}'
    if len(text) > limit:
        return text[:limit] + f'...（已截断，原始长度 {len(text)} 字符）'
    return text


def _maybe_alarm_json(raw: bytes) -> Optional[dict]:
    """尝试把原始内容解析成含 global_info 的报警 JSON，失败返回 None。"""
    try:
        parsed = json.loads(raw.decode("utf-8") if isinstance(raw, bytes) else raw)
        if "global_info" in parsed:
            return parsed
    except Exception:
        pass
    return None


async def parse_alarm_form(form) -> Tuple[Optional[dict], list]:
    """从上传表单中分离出报警 JSON 与图片二进制【有序列表】。

    返回 (alarm_json, image_parts)，其中 image_parts 形如
    `[{"field": 字段名, "filename": 文件名, "content": bytes}, ...]`，**严格保持 multipart 到达顺序**。

    为什么必须是列表而不是 dict：设备一次推两个二进制部件（约定【第一个=告警大图、第二个=送检小图】），
    而两个部件的文件名可能完全相同。旧实现用 `images[filename or field_name] = content` 做字典赋值，
    同名时后一张会把前一张覆盖掉 —— 结果大图被静默丢弃，库里只剩小图（imageUrlCrop 恒为空）。
    另外：凡是不解析为报警 JSON 的二进制部件，一律按图片处理（不做文件名启发式判断，避免误丢）。
    """
    alarm_json = None
    image_parts: list = []
    # multi_items() 会保留重复字段与到达顺序（items() 在部分实现里会去重/折叠）
    entries = form.multi_items() if hasattr(form, "multi_items") else form.items()
    for field_name, field_value in entries:
        if hasattr(field_value, "read"):  # UploadFile
            filename = getattr(field_value, "filename", "") or ""
            content = await field_value.read()
            parsed = _maybe_alarm_json(content)
            if parsed is not None:
                alarm_json = parsed
            else:
                image_parts.append({"field": field_name, "filename": filename, "content": content})
        elif isinstance(field_value, str):
            alarm_json = _maybe_alarm_json(field_value) or alarm_json
    if len(image_parts) != 2 and image_parts:
        # 只在"部件数不是约定的 2 个"时打一行日志（两路同名属设备正常行为，不刷日志）
        shape = "，".join(f"{p['field'] or '(无字段)'}/{p['filename'] or '(无文件名)'}={len(p['content'])}B"
                        for p in image_parts)
        print(f"[alarm_ingest] 本告警图片部件 {len(image_parts)} 个（按到达顺序）：{shape}")
    return alarm_json, image_parts


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
        # 通道号：真实通道号在 additional.device_id（与设备快照 channels[].device_id 对得上，实测 4=通道"36"）；
        # additional.channel_id 实测恒为 0（不是通道号），只在 device_id 缺失时兜底。
        "channel_id": _first_value(additional.get("device_id"), additional.get("channel_id")),
        "channel_name": additional.get("device_name", ""),
        "alarm_minor": additional.get("alarm_minor", ""),
        "agent_evname": agent_events.get("event_tag", ""),
        "agent_evid": agent_events.get("event_id", ""),
        # 描述信息：兼容 content 为字符串/对象两种形态（见 _content_text）
        "reslut": _content_text(content),
    }


def _first_value(*candidates):
    """取第一个"非空"的值（None/空串跳过），用于字段兜底。"""
    for value in candidates:
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        return value
    return ""


def save_alarm_images(images: dict) -> Optional[str]:
    """保存全部图片，返回首张图片的访问 URL（向后兼容旧调用）。"""
    urls = save_alarm_images_all(images)
    return urls[0] if urls else None


# ── 图片文件名：{设备业务ID}_{通道id}_{通道名}_{报警子类型}_{图片ID}_{big|crop}.扩展名 ──
# 通道名等来自设备上报，必须清洗后才能进文件名：含 / \ : * ? " < > | 等字符会导致写盘失败，
# 含 .. / 绝对路径会导致路径穿越，Windows 还有保留名（CON/PRN/COM1…）与结尾点/空格限制。
_UNSAFE_CHARS = re.compile(r"[^0-9A-Za-z\u4e00-\u9fff_-]")
_WIN_RESERVED = {"CON", "PRN", "AUX", "NUL",
                 *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
# 各段长度上限（合计 ~100 字符，配合 uploads/日期/小时 目录远低于系统路径限制）
# 设备业务ID 实测 19 位（如 M014101762601000001），上限给 24 保证完整不截断
_SEG_LIMITS = {"device_id": 24, "channel_id": 8, "channel_name": 20, "alarm_type": 24}


def safe_segment(value, limit: int, default: str = "na") -> str:
    """把一段信息清洗成可安全用作文件名的片段（白名单字符 + 截断 + 保留名规避）。"""
    text = _UNSAFE_CHARS.sub("_", str(value if value is not None else "").strip())
    text = text.strip("._-")            # 去掉首尾分隔符：避免 ".."、结尾点/空格（Windows 不允许）
    text = text[:limit].strip("._-")
    if not text or text.upper() in _WIN_RESERVED:
        return default
    return text


def build_image_basename(naming: Optional[dict], role: str) -> str:
    """按 {设备}_{通道id}_{通道名}_{子类型}_{图片ID}_{角色} 生成图片文件名（不含扩展名）。

    图片ID 用本项目生成的 8 位短 uuid：保证每张图独立不覆盖（同一告警重推也不会互相顶掉，
    也就不会出现"7 天清理按旧告警路径把共享文件提前删掉"的问题）。
    """
    naming = naming or {}
    parts = [
        safe_segment(naming.get("device_id"), _SEG_LIMITS["device_id"]),
        safe_segment(naming.get("channel_id"), _SEG_LIMITS["channel_id"]),
        safe_segment(naming.get("channel_name"), _SEG_LIMITS["channel_name"]),
        safe_segment(naming.get("alarm_type"), _SEG_LIMITS["alarm_type"]),
        uuid.uuid4().hex[:8],
        safe_segment(role, 8, default="img"),
    ]
    return "_".join(parts)


def pick_image_ext(filename: str, content: bytes) -> str:
    """决定落盘扩展名：优先用原文件名扩展名，否则按文件头识别（PNG/JPEG）。"""
    ext = os.path.splitext(str(filename or ""))[1].lower()
    if ext in (".jpg", ".jpeg", ".png", ".bmp", ".webp"):
        return ext
    if content[:4] == b"\x89PNG":
        return ".png"
    return ".jpg"


def save_alarm_images_all(parts, naming: Optional[dict] = None) -> list:
    """保存 multipart 里的图片部件，返回访问 URL 列表（**严格保持到达顺序**）。

    parts 为 parse_alarm_form 产出的有序列表 `[{field, filename, content}]`；
    为兼容旧调用也接受 `{name: bytes}` 字典（此时按字典顺序）。
    naming 为命名上下文 `{device_id, channel_id, channel_name, alarm_type}`，用于按
    `{设备}_{通道id}_{通道名}_{子类型}_{图片ID}_{角色}` 生成可读且唯一的文件名（见 build_image_basename）。
    多级子目录可避免单一目录文件数过大撑爆文件系统。
    约定（设备侧）：**第 1 个二进制=告警大图（整帧），第 2 个=送检小图（目标裁切）**，
    故返回值的 [0]/[1] 分别就是大图/小图（文件名分别以 `_big` / `_crop` 结尾）。
    """
    if not parts:
        return []
    if isinstance(parts, dict):     # 向后兼容：老调用方传的是 {文件名: 字节}
        parts = [{"field": "", "filename": k, "content": v} for k, v in parts.items()]

    now = datetime.now()
    date_path, hour_path = now.strftime("%Y-%m-%d"), now.strftime("%H")
    save_dir = os.path.join("uploads", date_path, hour_path)
    os.makedirs(save_dir, exist_ok=True)

    urls = []
    for idx, part in enumerate(parts):
        img_data = part.get("content") or b""
        if not img_data:
            continue
        # 角色：第 1 张=big（整帧大图）、第 2 张=crop（目标小图），其余按序号
        role = {0: "big", 1: "crop"}.get(idx, f"img{idx + 1}")
        file_name = build_image_basename(naming, role) + pick_image_ext(part.get("filename"), img_data)
        with open(os.path.join(save_dir, file_name), "wb") as f:
            f.write(img_data)
        urls.append(f"/uploads/{date_path}/{hour_path}/{file_name}")
    return urls


def save_embedded_images(alarm_json: Optional[dict], naming: Optional[dict] = None) -> list:
    """保存【报文内嵌】的整帧大图（`full_images[].image_data.value` 的 base64），返回访问 URL 列表。

    背景：整帧大图优先走 multipart 第 1 个二进制；报文内嵌 `full_images` 作为兜底
    （设备端未开启时 value 为 "0"，此时返回空列表）。命名规则与 multipart 图一致，
    角色固定为 `big`（见 build_image_basename）。

    兼容三种取值形态：`{"image_data": {"value": "<b64>"}}` / `{"image_data": "<b64>"}` / 裸 base64；
    也兼容 `data:image/jpeg;base64,...` 前缀。解码失败/数据过小的跳过，绝不影响告警入库。
    """
    if not isinstance(alarm_json, dict):
        return []
    items = alarm_json.get("full_images")
    if isinstance(items, dict):
        items = [items]
    if not isinstance(items, list):
        return []

    now = datetime.now()
    date_path, hour_path = now.strftime("%Y-%m-%d"), now.strftime("%H")
    urls: list = []
    for item in items:
        if not isinstance(item, dict):
            continue
        node = item.get("image_data", item)
        if isinstance(node, dict):
            raw = node.get("value") or node.get("image_data") or ""
        else:
            raw = node or ""
        if not isinstance(raw, str):
            continue
        raw = raw.strip()
        if raw.startswith("data:"):                     # data URI 前缀
            raw = raw.split(",", 1)[-1]
        # 未上传整帧时 value 为 "0"/空；过短的一律不可能是图片
        if len(raw) < 256 or set(raw) <= {"0", "="}:
            continue
        try:
            blob = base64.b64decode(raw, validate=False)
        except Exception as e:  # noqa: BLE001
            print(f"[alarm_ingest] 内嵌大图 base64 解码失败：{e}")
            continue
        if len(blob) < 256:
            continue
        ext = ".png" if blob[:4] == b"\x89PNG" else ".jpg"
        save_dir = os.path.join("uploads", date_path, hour_path)
        os.makedirs(save_dir, exist_ok=True)
        file_name = build_image_basename(naming, "big") + ext
        try:
            with open(os.path.join(save_dir, file_name), "wb") as f:
                f.write(blob)
        except OSError as e:
            print(f"[alarm_ingest] 内嵌大图写盘失败：{e}")
            continue
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
