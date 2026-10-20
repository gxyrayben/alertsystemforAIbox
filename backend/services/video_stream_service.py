"""订阅设备通道的视频流，作为 WS 代理把 MJPEG/JPEG 帧转发给浏览器。

为什么由后端代理（而不是浏览器直连设备）：
- 设备接口需要 `sessionID` Cookie，会话由服务端持有（challenge_login），不该暴露给前端；
- 设备可能是 HTTPS 自签证书，浏览器直连会被拒；后端复用 `DeviceService` 的证书策略；
- 退订要靠 `handle`，也必须由服务端在同一条会话链上完成。

协议（设备侧）：
1) `POST /media_video/subscribe_stream` body `{channel_id[, device_id]}` → `data.stream_id / data.handle`
2) WS `ws(s)://ip:port/media_video/stream?stream_id=..&session_id=..`
   - 首包为 8 字节二进制 ⇒ 错误码包：`total_length(4)=4 + error(4)`（大端）
   - 其余为媒体帧：16 字节报头 `type(4) seq(4) total_length(4) info_len(4)`（大端，total_length 含头）
     + `info[info_len]` + `data[total_length - info_len - 16]`
3) `DELETE /media_video/subscribe_stream` body `{handle}`

帧类型 type：0 传感器 / 1 视频 / 2 音频 / 3 图片 / 4 智能 / 256 结束
编码 codec：1 H264 / 2 H265 / 3 MJPEG

本模块只向下游转发「可直接显示的 JPEG」：
- MJPEG 视频帧（data 以 FF D8 开头）与图片流（data 内 `[data_len][data]` 多段）都能取出 JPEG；
- H264/H265 需要浏览器侧解码器（MSE/WebCodecs），不在本模块范围内，会向上报明确的 unsupported 状态。
"""
import asyncio
import ssl
import struct
from typing import Optional, Tuple

import httpx

from models.orm import DeviceORM
from services.device_service import DeviceService

SUBSCRIBE_PATH = "/media_video/subscribe_stream"
WS_PATH = "/media_video/stream"
HEADER_LEN = 16
# 订阅时必须显式带上的「本地设备 id」：实测缺省会被设备回 0x40000002 并断连
LOCAL_DEVICE_ID = 1

FRAME_TYPE = {0: "sensor", 1: "video", 2: "audio", 3: "image", 4: "smart", 256: "end"}
CODEC_NAME = {1: "H264", 2: "H265", 3: "MJPEG"}


# ── 协议解析 ────────────────────────────────────────────────────────────
def parse_error_packet(buf: bytes) -> Optional[int]:
    """识别 WS 首包的「订阅失败」通知：8 字节 = total_length(4)=4 + error(4)，大端。

    返回错误码；不是错误包则返回 None。
    """
    if len(buf) != 8:
        return None
    total_length, error = struct.unpack(">II", buf)
    if total_length != 4:
        return None
    return error


def parse_media_packet(buf: bytes) -> Optional[dict]:
    """解析 16 字节报头的媒体帧；长度不足或字段不自洽时返回 None（不抛异常，便于容错丢包）。"""
    if len(buf) < HEADER_LEN:
        return None
    ftype, seq, total_length, info_len = struct.unpack(">IIII", buf[:HEADER_LEN])
    if total_length < HEADER_LEN or total_length > len(buf):
        return None
    if HEADER_LEN + info_len > total_length:
        return None
    info = buf[HEADER_LEN:HEADER_LEN + info_len]
    data = buf[HEADER_LEN + info_len:total_length]
    out = {
        "type": FRAME_TYPE.get(ftype, str(ftype)),
        "type_id": ftype,
        "seq": seq,
        "total_length": total_length,
        "info_len": info_len,
        "channel_id": None,
        "codec": None,
        "codec_name": "",
        "width": None,
        "height": None,
        "data": data,
    }
    # 视频/音频 info 头：channel_id(4) codec(2) id(4) pts(8) ext_len(4) = 22 字节
    if ftype in (1, 2) and len(info) >= 6:
        out["channel_id"] = struct.unpack(">I", info[:4])[0]
        codec = struct.unpack(">H", info[4:6])[0]
        out["codec"] = codec
        out["codec_name"] = CODEC_NAME.get(codec, str(codec))
        # 视频专用 info 内容：width(2) height(2) frame_rate(4) idr(1)，紧跟 22 字节信息头之后
        if ftype == 1 and info_len >= 22 + 9:
            w, h, _fps, _idr = struct.unpack(">HHfB", info[22:31])
            out["width"], out["height"] = w, h
    elif ftype == 3 and len(info) >= 4:      # 图片流 info 头：channel_id(4) ext_len(4)
        out["channel_id"] = struct.unpack(">I", info[:4])[0]
    return out


def extract_jpeg(data: bytes) -> Optional[bytes]:
    """从负载里取出最后一帧 JPEG。

    同时兼容三种常见封装，避免对报头细节过度依赖：
    - MJPEG 视频帧：data 本身就是 `FF D8 ... FF D9`
    - 图片流：data 是若干段 `[data_len(4)][jpeg]`
    - 其它：按 JPEG 魔数在 data 中扫描
    """
    if not data:
        return None
    if data[:2] == b"\xff\xd8":
        start = 0
    else:
        start = data.find(b"\xff\xd8")
        if start < 0:
            return None
    end = data.rfind(b"\xff\xd9")
    if end < start:
        return None
    return data[start:end + 2]


# ── WS 地址与 TLS ───────────────────────────────────────────────────────
def ws_url(device: DeviceORM, stream_id: str, session_id: str) -> str:
    """拼设备 WS 地址（scheme 跟随设备 protocol；session_id 取登录返回值）。"""
    https = (getattr(device, "protocol", None) or "http").lower().startswith("https")
    scheme = "wss" if https else "ws"
    q = f"stream_id={stream_id}&session_id={session_id}"
    return f"{scheme}://{device.ip}:{device.port}{WS_PATH}?{q}"


def ws_ssl_context(device: DeviceORM) -> Optional[ssl.SSLContext]:
    """wss 时的 SSL 上下文；设备 tls_verify=False（默认）则跳过证书校验，兼容自签证书。"""
    https = (getattr(device, "protocol", None) or "http").lower().startswith("https")
    if not https:
        return None
    ctx = ssl.create_default_context()
    if not bool(getattr(device, "tls_verify", False)):
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    return ctx


# ── 订阅 / 退订 ─────────────────────────────────────────────────────────
async def subscribe(client: httpx.AsyncClient, device: DeviceORM, db,
                    channel_id, device_id=LOCAL_DEVICE_ID) -> Tuple[bool, dict, str]:
    """订阅通道视频流。返回 (成功?, {stream_id, handle}, 错误消息)。

    ⚠ 实测（Dev01 / 固件现场验证）：`device_id` **必须显式传**，缺省时设备会回
    `0x40000002` 并直接断开 WS（虽然协议文档写的是"非必须，缺省代表本地设备"）。
    取值为「本地设备 id」，实测传 1 对多个通道均有效，与 channel_id 无关。
    """
    try:
        body = {"channel_id": int(channel_id)}
    except (TypeError, ValueError):
        return False, {}, f"channel_id 非法：{channel_id!r}"
    if device_id not in (None, ""):
        try:
            body["device_id"] = int(device_id)
        except (TypeError, ValueError):
            pass
    data = await DeviceService.authed_post(client, device, db, SUBSCRIBE_PATH, body)
    if data is None:
        return False, {}, f"设备「{device.name}」离线或不可达，无法订阅视频流"
    if data.get("code") != 0:
        return False, {}, data.get("message") or "订阅视频流失败"
    payload = data.get("data") or {}
    if not payload.get("stream_id"):
        return False, {}, "订阅成功但未返回 stream_id"
    return True, {"stream_id": str(payload["stream_id"]), "handle": payload.get("handle")}, ""


async def unsubscribe(client: httpx.AsyncClient, device: DeviceORM, db, handle) -> Tuple[bool, str]:
    """退订视频流（按 handle）。失败不抛异常，交给调用方记录。"""
    if handle in (None, ""):
        return False, "缺少 handle，无法退订"
    try:
        body = {"handle": int(handle)}
    except (TypeError, ValueError):
        return False, f"handle 非法：{handle!r}"
    data = await DeviceService.authed_request(
        client, device, db, "DELETE", SUBSCRIBE_PATH, body)
    if data is None:
        return False, "退订失败：设备不可达"
    if data.get("code") != 0:
        return False, f"退订失败：{data.get('message') or '设备返回失败'}"
    return True, "ok"


# ── 帧泵：上游 WS → 只保留最新一帧 ──────────────────────────────────────
async def pump_frames(device: DeviceORM, stream_id: str, session_id: str,
                      latest: "asyncio.Queue[bytes]", state: dict) -> None:
    """连设备 WS 收帧，把可播放的负载放进 latest。

    两种负载分别处理：
    - **JPEG/MJPEG/图片流**：直接推 JPEG 字节；队列 maxsize=1 覆盖式入队（天然丢旧帧，低延迟）。
    - **H264/H265（实测该设备的通道就是 H264 1920×1080）**：推**原始 AnnexB 数据**，
      由前端 WebCodecs 解码。视频帧有依赖关系，不能随便覆盖丢弃：
      队列有界（PUMP_QUEUE_VIDEO），满了以后丢弃新帧，直到遇到下一个关键帧再重新同步，
      避免花屏/解码器报错。

    state 字段：error（失败原因）、closed、codec（H264/H265）、width/height、类型 mode。
    """
    import websockets

    url = ws_url(device, stream_id, session_id)
    try:
        async with websockets.connect(url, ssl=ws_ssl_context(device),
                                      max_size=None, open_timeout=10) as up:
            first = True
            while True:
                msg = await up.recv()
                if isinstance(msg, str):
                    continue          # 设备若发文本心跳，忽略
                if first:
                    first = False
                    err = parse_error_packet(msg)
                    if err is not None:
                        state["error"] = f"订阅失败，设备返回错误码 0x{err:08x}({err})"
                        return
                pkt = parse_media_packet(msg)
                if pkt is None:
                    continue
                if pkt["type_id"] == 256:          # 结束帧
                    state["error"] = "设备已结束该路视频流"
                    return
                if pkt["type_id"] in (2, 4):       # 音频 / 智能负载不用于画面
                    continue

                # 按【type + codec】判定负载性质，**不要靠扫 JPEG 魔数**：
                # 实测 H264 关键帧的 NAL 负载里会恰好出现 FF D8/FF D9 字节序列，
                # 用魔数扫描会把关键帧误判成 JPEG 而丢弃原始视频数据（真机踩到过）。
                codec = pkt.get("codec")
                is_image_stream = pkt["type_id"] == 3
                is_mjpeg = pkt["type_id"] == 1 and codec == 3
                if is_image_stream or is_mjpeg:
                    jpeg = extract_jpeg(pkt["data"])
                    if jpeg is None:
                        continue
                    state.setdefault("mode", "jpeg")
                    state["codec"] = "MJPEG" if is_mjpeg else "JPEG"
                    # 只保留最新一帧（清空后再入队，保证低延迟）
                    while not latest.empty():
                        try:
                            latest.get_nowait()
                        except asyncio.QueueEmpty:
                            break
                    latest.put_nowait(jpeg)
                    continue

                # 非 JPEG ⇒ H264/H265：透传 AnnexB 原始数据
                if not pkt["data"]:
                    continue
                state["mode"] = "video"
                state["codec"] = pkt["codec_name"] or "H264"
                if pkt.get("width") and pkt.get("height"):
                    state["width"], state["height"] = pkt["width"], pkt["height"]
                is_key = bool(pkt.get("idr"))
                if latest.full():
                    if not is_key:
                        state["dropped"] = state.get("dropped", 0) + 1
                        continue          # 积压时丢弃非关键帧
                    # 遇到关键帧：清空积压后重新同步，保证解码器能恢复
                    while not latest.empty():
                        try:
                            latest.get_nowait()
                        except asyncio.QueueEmpty:
                            break
                latest.put_nowait(pkt["data"])
    except asyncio.CancelledError:
        raise
    except Exception as e:  # noqa: BLE001
        state["error"] = f"视频流连接中断：{type(e).__name__}: {e}"
    finally:
        state["closed"] = True
