"""设备视频流代理：浏览器 ↔ 我们 ↔ 设备 WS。

前端只连本服务的 `WS /devices/{device_id}/stream?channel_id=..`，后端负责：
订阅（拿 stream_id/handle）→ 连设备 WS 收帧 → 只保留最新一帧转发 → 断开时退订。

客户端协议（JSON 文本消息用于状态，二进制消息就是 JPEG 帧）：
- `{"event":"ready","channel_id":N}`            已连上设备并开始出帧
- `{"event":"error","message":"..."}`           失败原因（订阅失败/无会话/编码不支持…）
- `{"event":"closed"}`                          结束
- 二进制帧                                       可直接 `new Blob([buf])` 给 <img> 播放
"""
import asyncio
import time

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect
from sqlalchemy.future import select

from models.db import AsyncSessionLocal
from models.orm import DeviceORM
from services import video_stream_service as vs

router = APIRouter(prefix="/devices", tags=["devices"])

# 单帧上限：JPEG 一般几十~几百 KB，H264 关键帧实测 300~450KB；超过 8MB 视为异常帧丢弃
_MAX_FRAME_BYTES = 8 * 1024 * 1024
# 等首帧的超时：订阅成功但设备迟迟不出帧时，给前端一个明确结论而不是无限转圈
_FIRST_FRAME_TIMEOUT = 15.0
# 帧队列深度：H264/H265 有帧间依赖需保序缓冲；JPEG 模式下泵只保留最新一帧，深度不影响延迟
_QUEUE_DEPTH = 32


async def _load_device(db, device_id: str):
    """解析设备：优先按主键 `id`，回退按业务 `device_id`。

    关键：其它 `/devices/{device_id}/...` 路由都用 `services.crud.get_or_404`，即**按主键 id**
    查询；而前端传的 `$selectedDevice.id` 正是主键（形如 `dev-6318d5db-...`）。
    早期本模块只按业务 `device_id`（形如 `M0141...`）匹配，导致浏览器连上来后
    判定「设备不存在」→ 订阅失败 → 前端只能看到兜底超时提示。
    """
    dev = (await db.execute(select(DeviceORM).where(DeviceORM.id == device_id))).scalars().first()
    if dev is None:
        dev = (await db.execute(
            select(DeviceORM).where(DeviceORM.device_id == device_id))).scalars().first()
    return dev


async def _safe_close(ws: WebSocket, code: int = 1000) -> None:
    """关闭连接；对端已断开时 starlette 会抛 WebSocketDisconnect(1006)，这里忽略以免刷错误日志。"""
    try:
        await ws.close(code=code)
    except Exception:  # noqa: BLE001
        pass


async def _safe_send_json(ws: WebSocket, payload: dict) -> None:
    """向前端发状态消息；连接已断时静默忽略（不掩盖后续清理逻辑）。"""
    try:
        await ws.send_json(payload)
    except Exception:  # noqa: BLE001
        pass


async def _next_frame_or_end(latest: asyncio.Queue, pump_task: asyncio.Task,
                             timeout: float):
    """等下一帧，同时监听上游泵是否提前结束。

    返回 (frame, phase)：frame 非空表示取到帧；否则 phase ∈ {"timeout", "ended"}。
    这样设备拒绝订阅/断流时能**立即**告知前端，而不是干等首帧超时（早期实现会白等 15s）。
    """
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while True:
        if pump_task.done():
            # 泵已结束但队列里可能还压着最后一帧，先取干净
            try:
                return latest.get_nowait(), "frame"
            except asyncio.QueueEmpty:
                return None, "ended"
        remaining = deadline - loop.time()
        if remaining <= 0:
            return None, "timeout"
        getter = asyncio.ensure_future(latest.get())
        try:
            done, _ = await asyncio.wait({getter, pump_task}, timeout=remaining,
                                         return_when=asyncio.FIRST_COMPLETED)
        except asyncio.CancelledError:
            getter.cancel()
            raise
        if getter in done:
            return getter.result(), "frame"
        getter.cancel()
        if pump_task in done:
            continue          # 回到循环顶部，把队列里剩下的帧取出来
        return None, "timeout"


@router.get("/{device_id}/stream/probe")
async def device_stream_probe(device_id: str, channel_id: str = Query(""),
                              seconds: float = Query(8.0, ge=1, le=30)):
    """诊断接口：在服务端跑一遍「订阅 → 连设备 WS → 收帧 → 退订」，返回摘要。

    浏览器直接打开即可判断问题出在**后端链路**还是**前端解码**：
    - `ok=true` 且 `frames>0`：后端能拿到帧 → 问题在前端播放/解码；
    - `ok=false`：后端就失败了，`error` 会给出原因（离线/拒绝订阅/H264 不支持等）。
    """
    if not channel_id:
        return {"ok": False, "error": "缺少 channel_id"}
    summary = {"ok": False, "device_id": device_id, "channel_id": channel_id,
               "subscribe": {}, "ws_opened": False, "frames": 0, "mode": "", "codec": "",
               "width": 0, "height": 0, "first_frame_head": "", "error": ""}
    async with AsyncSessionLocal() as db:
        device = await _load_device(db, device_id)
        if device is None:
            summary["error"] = f"设备 {device_id} 不存在"
            return summary
        async with vs.DeviceService.new_client(device, timeout=15.0) as client:
            _t0 = time.time()
            ok, info, err = await vs.subscribe(client, device, db, channel_id)
            _t_sub = time.time() - _t0
            if not ok:
                print(f"[video] subscribe FAILED device={device_id} ch={channel_id} {err} elapsed={_t_sub:.2f}s")
            summary["subscribe"] = {"ok": ok, "stream_id": info.get("stream_id"), "handle": info.get("handle")}
            if not ok:
                summary["error"] = err
                return summary
            state = {"error": "", "closed": False}
            latest: asyncio.Queue = asyncio.Queue(maxsize=_QUEUE_DEPTH)
            pump = asyncio.create_task(
                vs.pump_frames(device, info["stream_id"], device.session_id or "", latest, state))
            try:
                deadline = asyncio.get_running_loop().time() + float(seconds)
                while asyncio.get_running_loop().time() < deadline:
                    frame, phase = await _next_frame_or_end(latest, pump, 3.0)
                    if frame is not None:
                        summary["frames"] += 1
                        if summary["frames"] == 1:
                            summary["first_frame_head"] = frame[:12].hex()
                        continue
                    if phase == "ended":
                        break
                summary["ws_opened"] = True
                summary["mode"] = state.get("mode") or ""
                summary["codec"] = state.get("codec") or ""
                summary["width"] = state.get("width") or 0
                summary["height"] = state.get("height") or 0
                summary["error"] = state.get("error") or ""
                summary["ok"] = summary["frames"] > 0
                if summary["ok"] is False and not summary["error"]:
                    summary["error"] = f"{seconds:g}s 内未收到任何可播放帧"
            finally:
                pump.cancel()
                try:
                    await pump
                except (asyncio.CancelledError, Exception):  # noqa: BLE001
                    pass
                try:
                    await vs.unsubscribe(client, device, db, info.get("handle"))
                except Exception:  # noqa: BLE001
                    pass
    return summary


@router.websocket("/{device_id}/stream")
async def device_stream(ws: WebSocket, device_id: str, channel_id: str = Query("")):
    """把某设备某通道的视频流（MJPEG/JPEG）实时转发给浏览器。"""
    await ws.accept()
    print(f"[video] WS open device={device_id} channel={channel_id}")
    # 握手成功立刻回一条进度：订阅设备接口（可能触发重登）可能要几秒，
    # 期间不能一片静默，否则前端只能靠超时猜「卡住了」。
    await _safe_send_json(ws, {"event": "status", "stage": "accepted"})

    if not channel_id:
        await _safe_send_json(ws, {"event": "error", "message": "缺少 channel_id"})
        await _safe_close(ws, 1008)
        return

    # 每次连接独立会话：WS 生命周期里不能依赖 HTTP 请求的 Depends 会话
    async with AsyncSessionLocal() as db:
        device = await _load_device(db, device_id)
        if device is None:
            await _safe_send_json(ws, {"event": "error", "message": f"设备 {device_id} 不存在"})
            await _safe_close(ws, 1008)
            return

        latest: asyncio.Queue = asyncio.Queue(maxsize=_QUEUE_DEPTH)
        state: dict = {"error": "", "closed": False, "codec": ""}
        pump_task = None
        handle = None
        async with vs.DeviceService.new_client(device, timeout=15.0) as client:
            _t0 = time.time()
            ok, info, err = await vs.subscribe(client, device, db, channel_id)
            _t_sub = time.time() - _t0
            if not ok:
                print(f"[video] subscribe FAILED device={device_id} ch={channel_id} {err} elapsed={_t_sub:.2f}s")
                await _safe_send_json(ws, {"event": "error", "message": err})
                await _safe_close(ws, 1011)
                return
            handle = info.get("handle")
            print(f"[video] subscribed device={device_id} stream={info.get('stream_id')} handle={handle} elapsed={_t_sub:.2f}s")
            await _safe_send_json(ws, {"event": "status", "stage": "subscribed",
                                       "stream_id": info.get("stream_id") or ""})
            session_id = device.session_id or ""
            if not session_id:
                await _safe_send_json(ws, {"event": "error", "message": "设备会话为空，请重新同步设备"})
                await _safe_close(ws, 1011)
                return

            pump_task = asyncio.create_task(
                vs.pump_frames(device, info["stream_id"], session_id, latest, state))
            await _safe_send_json(ws, {"event": "status", "stage": "waiting_frame"})
            try:
                # 首帧：取到帧就 ready；泵提前结束（订阅被拒/断流）则立即报错
                first, phase = await _next_frame_or_end(latest, pump_task, _FIRST_FRAME_TIMEOUT)
                if first is None:
                    msg = state.get("error") or (
                        f"设备 {int(_FIRST_FRAME_TIMEOUT)}s 内未出帧" if phase == "timeout" else "视频流已结束")
                    await _safe_send_json(ws, {"event": "error", "message": msg})
                    return
                print(f"[video] first frame device={device_id} ch={channel_id} mode={state.get('mode')} "
                      f"codec={state.get('codec')} bytes={len(first)}")
                await _safe_send_json(ws, {
                    "event": "ready",
                    "channel_id": channel_id,
                    # 前端据此选择播放方式：jpeg → <img>；video → WebCodecs 解码
                    "mode": state.get("mode") or "jpeg",
                    "codec": state.get("codec") or "",
                    "width": state.get("width") or 0,
                    "height": state.get("height") or 0,
                })
                if len(first) <= _MAX_FRAME_BYTES:
                    await ws.send_bytes(first)

                # 持续转发：只发最新帧（队列 maxsize=1，旧帧自然被覆盖）
                while True:
                    frame, phase = await _next_frame_or_end(latest, pump_task, 10.0)
                    if frame is not None:
                        if len(frame) <= _MAX_FRAME_BYTES:
                            await ws.send_bytes(frame)
                        continue
                    if phase == "timeout":
                        continue          # 长时间无帧：继续等（设备可能只是画面静止），不主动断开
                    # 泵已结束：有错误就报错，正常结束则 closed
                    if state.get("error"):
                        await _safe_send_json(ws, {"event": "error", "message": state["error"]})
                    else:
                        await _safe_send_json(ws, {"event": "closed"})
                    return
            except WebSocketDisconnect:
                pass
            finally:
                if pump_task is not None:
                    pump_task.cancel()
                    try:
                        await pump_task
                    except (asyncio.CancelledError, Exception):  # noqa: BLE001
                        pass
                # 退订：用同一条设备会话把 handle 还回去，避免设备侧资源泄漏
                try:
                    await vs.unsubscribe(client, device, db, handle)
                except Exception as e:  # noqa: BLE001
                    print(f"[video] 退订失败 device={device_id} handle={handle}: {e}")
