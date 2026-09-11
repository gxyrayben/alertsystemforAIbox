/** 前端公共小工具，集中存放跨组件复用的纯函数。 */

/** 安全解析后端返回的 JSON 字符串字段（如 channels/device_tasks），失败返回空数组。 */
export function parseJson(str) {
    try {
        return JSON.parse(str || '[]');
    } catch (_) {
        return [];
    }
}

/** 毫秒时间戳格式化为 本地 年/月/日 时:分:秒。 */
export function formatDate(timestamp) {
    const d = new Date(timestamp);
    const pad = (n) => n.toString().padStart(2, '0');
    return `${d.getFullYear()}/${d.getMonth() + 1}/${d.getDate()} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
}

/**
 * 从 apiFetch 抛出的错误对象里提取可读文案。
 * 后端 HTTPException 的 detail 是字符串（如「设备业务 ID 已存在」），直接展示；
 * Pydantic 校验错误(422) 的 detail 是数组，逐条取 msg 拼接，避免弹出 [object Object]。
 */
export function extractError(e, fallback = '未知错误') {
    if (!e) return fallback;
    const d = e.detail;
    if (typeof d === 'string' && d) return d;
    if (Array.isArray(d)) {
        const msgs = d.map((x) => (x && x.msg) || '').filter(Boolean);
        if (msgs.length) return msgs.join('；');
    }
    return e.message || fallback;
}

