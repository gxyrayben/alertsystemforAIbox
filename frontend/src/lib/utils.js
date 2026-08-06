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
