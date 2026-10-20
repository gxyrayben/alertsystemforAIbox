<script>
    /**
     * 设备通道实时视频流播放组件。
     *
     * 数据来自本服务的 WS 代理 `/devices/{id}/stream?channel_id=..`：
     *   - 文本消息：`ready`（带 mode/codec/width/height）/ `error` / `closed`
     *   - 二进制消息：一帧数据。`mode='jpeg'` 时是完整 JPEG（用 <img> 直接显示）；
     *     `mode='video'` 时是 H.264/H.265 AnnexB 原始 NAL（用 WebCodecs 解码后画到 <canvas>）。
     *
     * 事件：
     *   - `status` {state:'connecting'|'live'|'error'|'idle', message}
     *   - `meta`   {width, height}   首帧尺寸，供父组件做 ROI 坐标对齐
     */
    import { onDestroy, createEventDispatcher, tick } from 'svelte';
    import { API_BASE } from '../lib/api.js';
    import { analyzeFrame, spsToCodecString, buildAvcC } from '../lib/h264.js';

    export let deviceId = '';
    export let channelId = '';
    export let active = false;

    const dispatch = createEventDispatcher();
    let lastState = '';
    const emitStatus = (state, message = '') => {
        lastState = state;
        if (state === 'error') clearWatchdog();   // 真实错误优先，别被超时消息盖掉
        dispatch('status', {
            state, message,
            info: { rx: rxFrames, live: liveFrames, codec: cfgKey, stage },
        });
    };
    const emitMeta = (w, h) => { if (w > 0 && h > 0) dispatch('meta', { width: w, height: h }); };

    let ws = null;
    let gen = 0;                 // 世代号：切换通道时丢弃旧连接的回调
    let mode = '';               // '' | 'jpeg' | 'video'
    let jpegUrl = '';
    let canvasEl = null;
    let decoder = null;
    let configured = false;
    let cfgKey = '';             // 已配置的 codec 字符串（SPS 变化时重新 configure）
    let tsCounter = 0;           // WebCodecs 要求时间戳单调递增
    let liveFrames = 0;
    let rxFrames = 0;            // 收到的二进制帧数（诊断用）
    let lastError = '';          // WebCodecs/解码器错误原文（诊断用）
    let watchdog = null;
    let wsOpened = false;      // 握手是否成功（区分「连不上」和「连上但没数据」）
    let stage = '';            // 后端进度：accepted / subscribed / waiting_frame
    let openTimer = null;
    const OPEN_TIMEOUT_MS = 4000;

    // 看门狗：收到 ready 但迟迟解不出第一帧时，**必须**给结论，不能永远停在「连接中」
    const WATCHDOG_MS = 22000;   // > 后端首帧超时(15s)，避免前端先于后端报假超时
    function armWatchdog() {
        clearTimeout(watchdog);
        watchdog = setTimeout(() => {
            if (liveFrames > 0 || lastState === 'error') return;
            const parts = [
                `WS=${wsOpened ? '已连接' : '未连接'}`,
                `阶段=${stage || '?'}`,
                `mode=${mode || '?'}`,
                `codec=${cfgKey || '-'}`,
                `收到帧=${rxFrames}`,
                `已解码=${liveFrames}`,
            ];
            if (lastError) parts.push(`错误=${lastError}`);
            dispatch('status', {
                state: 'error',
                message: `${WATCHDOG_MS / 1000}s 内未出画面（${parts.join('，')}）`,
            });
        }, WATCHDOG_MS);
    }
    function clearWatchdog() { clearTimeout(watchdog); watchdog = null; }

    function releaseJpeg() {
        if (jpegUrl) {
            const old = jpegUrl;
            setTimeout(() => { try { URL.revokeObjectURL(old); } catch (e) { /* 忽略 */ } }, 500);
            jpegUrl = '';
        }
    }

    function teardownDecoder() {
        configured = false;
        cfgKey = '';
        if (decoder) {
            try { decoder.close(); } catch (e) { /* 已关闭 */ }
            decoder = null;
        }
    }

    function reset() {
        releaseJpeg();
        teardownDecoder();
        mode = '';
        liveFrames = 0;
    }

    function wsUrl(id, ch) {
        const base = String(API_BASE || '').replace(/^http/, 'ws');
        return `${base}/devices/${id}/stream?channel_id=${encodeURIComponent(ch)}`;
    }

    function configureDecoder(codec, description) {
        if (typeof window === 'undefined' || typeof window.VideoDecoder === 'undefined') {
            emitStatus('error', '当前浏览器不支持 WebCodecs（请用 Chrome/Edge 新版本）');
            return false;
        }
        try {
            teardownDecoder();
            decoder = new VideoDecoder({
                output: (frame) => {
                    const c = canvasEl;
                    if (!c) { frame.close(); return; }
                    if (c.width !== frame.displayWidth || c.height !== frame.displayHeight) {
                        c.width = frame.displayWidth;
                        c.height = frame.displayHeight;
                    }
                    const ctx = c.getContext('2d');
                    if (ctx) ctx.drawImage(frame, 0, 0, c.width, c.height);
                    emitMeta(frame.displayWidth, frame.displayHeight);
                    frame.close();
                    liveFrames += 1;
                    if (liveFrames === 1) { clearWatchdog(); emitStatus('live'); }
                },
                error: (e) => {
                    lastError = String(e?.message || e);
                    emitStatus('error', '解码器错误：' + lastError);
                },
            });
            decoder.configure({ codec, description, optimizeForLatency: true });
            configured = true;
            cfgKey = codec;
            return true;
        } catch (e) {
            configured = false;
            emitStatus('error', '解码器初始化失败：' + (e?.message || e));
            return false;
        }
    }

    // H.264/H.265 AnnexB → WebCodecs
    function handleVideoFrame(buf) {
        const r = analyzeFrame(buf);
        if (r.sps && r.pps) {
            const codec = spsToCodecString(r.sps);
            if (codec && codec !== cfgKey) {
                if (!configureDecoder(codec, buildAvcC(r.sps, r.pps))) return;
            } else if (!configured) {
                // 之前配置失败/被清理过：用当前参数集重建一次
                if (!configureDecoder(codec, buildAvcC(r.sps, r.pps))) return;
            }
        }
        if (!decoder || !configured) return;     // 还没拿到参数集，等关键帧
        try {
            decoder.decode(new EncodedVideoChunk({
                type: r.idr ? 'key' : 'delta',
                timestamp: (tsCounter += 40000),   // 25fps 步进
                data: r.avcc,
            }));
        } catch (e) {
            emitStatus('error', '解码失败（' + (e?.message || e) + '），已解码 ' + liveFrames + ' 帧');
        }
    }

    function handleBinary(buf) {
        rxFrames += 1;
        const u8 = new Uint8Array(buf);
        // 防御性嗅探：万一 ready 消息缺失/字段不全，用首字节判断负载类型，
        // 避免把 H264 原始数据当成 JPEG 塞给 <img> 导致永远出不了画面。
        if (!mode && u8.length >= 2) {
            if (u8[0] === 0xff && u8[1] === 0xd8) mode = 'jpeg';
            else if (u8[0] === 0x00 && u8[1] === 0x00 && u8.length > 4) mode = 'video';
        }
        if (liveFrames === 0 && rxFrames % 10 === 1) emitStatus('connecting');
        if (mode === 'video') { handleVideoFrame(u8); return; }
        // JPEG / MJPEG：直接换成 blob URL 给 <img>
        const next = URL.createObjectURL(new Blob([buf], { type: 'image/jpeg' }));
        const prev = jpegUrl;
        jpegUrl = next;
        if (prev) setTimeout(() => { try { URL.revokeObjectURL(prev); } catch (e) { /* 忽略 */ } }, 800);
    }

    function disconnect() {
        if (ws) console.info('[live] disconnect (by client), gen ->', gen + 1);
        gen += 1;
        clearWatchdog();
        clearTimeout(openTimer);
        wsOpened = false;
        if (ws) {
            try { ws.close(); } catch (e) { /* 已断开 */ }
            ws = null;
        }
        reset();
        emitStatus('idle');
    }

    function connect() {
        console.info('[live] connect', { deviceId, channelId, active });
        disconnect();
        if (!deviceId || !channelId || !active) return;
        const my = ++gen;
        rxFrames = 0;
        lastError = '';
        stage = '';
        emitStatus('connecting');
        armWatchdog();
        let sock;
        try {
            sock = new WebSocket(wsUrl(deviceId, channelId));
            sock.binaryType = 'arraybuffer';
        } catch (e) {
            emitStatus('error', '无法建立视频流连接：' + (e?.message || e));
            return;
        }
        ws = sock;
        wsOpened = false;
        clearTimeout(openTimer);
        openTimer = setTimeout(() => {
            if (!wsOpened) {
                emitStatus('error', `无法建立视频流 WebSocket（${OPEN_TIMEOUT_MS / 1000}s 未握手成功）：`
                    + `请确认后端已重启、端口可达；若经 nginx 等反代需开启 WebSocket 升级。目标 ${wsUrl(deviceId, channelId)}`);
            }
        }, OPEN_TIMEOUT_MS);
        console.info('[live] socket created', wsUrl(deviceId, channelId), 'gen', my);
        sock.onopen = () => {
            if (my !== gen) return;
            wsOpened = true;
            clearTimeout(openTimer);
            emitStatus('connecting');   // 已连上后端，等 ready/帧
        };
        sock.onmessage = (ev) => {
            if (my !== gen) return;
            if (typeof ev.data === 'string') {
                let msg = {};
                try { msg = JSON.parse(ev.data); } catch (e) { msg = {}; }
                console.info('[live] recv', msg);
                if (msg.event === 'ready') {
                    mode = msg.mode === 'video' ? 'video' : 'jpeg';
                    armWatchdog();
                    if (msg.mode === 'video') {
                        if (msg.width && msg.height) emitMeta(msg.width, msg.height);
                        emitStatus('connecting');   // 等解码器出第一帧才算 live
                    } else {
                        emitStatus('connecting');   // 等第一张 JPEG
                    }
                } else if (msg.event === 'status') {
                    stage = msg.stage || '';
                    armWatchdog();            // 有进度就重置超时，不算卡住
                    emitStatus('connecting');
                } else if (msg.event === 'error') {
                    emitStatus('error', msg.message || '视频流异常');
                } else if (msg.event === 'closed') {
                    emitStatus('idle', '视频流已结束');
                }
                return;
            }
            handleBinary(ev.data);
            if (mode === 'jpeg') {
                liveFrames += 1;
                if (liveFrames === 1) { clearWatchdog(); emitStatus('live'); }
            }
        };
        sock.onerror = () => { if (my === gen) emitStatus('error', '视频流连接失败'); };
        sock.onclose = (e) => {
            console.info('[live] socket closed', { code: e?.code, reason: e?.reason, my, gen });
            if (my !== gen) return;
            ws = null;
            // 只在从未收到画面时判定为失败，避免正常结束覆盖已显示的画面
            if (liveFrames === 0) {
                emitStatus('error', wsOpened
                    ? 'WS 已连接但被后端关闭（后端订阅失败或流结束，请查看后端日志）'
                    : 'WS 握手未成功即关闭（后端未重启 / 路由不存在 / 反代不支持 WebSocket）');
            }
        };
    }

    // 通道/设备变化 或 active 切换时重连
    let lastKey = '';
    $: key = active ? `${deviceId}|${channelId}` : '';
    $: if (key !== lastKey) {
        lastKey = key;
        if (key) connect(); else disconnect();
    }
    onDestroy(disconnect);
</script>

<!-- canvas 常驻：首帧解码回调可能早于条件渲染完成，若按 mode 条件挂载会丢掉最早的几帧 -->
<canvas bind:this={canvasEl} class="absolute inset-0 w-full h-full" class:hidden={mode !== 'video'}></canvas>
{#if mode === 'jpeg' && jpegUrl}
    <img src={jpegUrl} alt="实时视频流" class="absolute inset-0 w-full h-full object-fill" />
{/if}
