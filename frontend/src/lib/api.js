// 后端地址跟随当前访问页面的主机名，端口固定 8000。
// 这样本机用 localhost、其他电脑用服务器局域网 IP 访问时，都能正确指向后端，
// 不用写死 IP（原来写死 localhost 会让其他电脑请求打到它自己本机，导致取不到数据）。
//
// 协议跟随当前页面（页面 https → 请求 https），与后端 config.json 的 tls 开关对齐，
// 避免 https 页面去请求 http 接口被浏览器按混合内容拦掉。
// 特殊部署（页面与后端协议不一致）可用 window.__API_BASE__ 显式覆盖（在 index.html 里赋值）。
export const API_BASE = window.__API_BASE__ || `${window.location.protocol}//${window.location.hostname}:8000`;

async function apiFetch(path, options = {}) {
    const res = await fetch(`${API_BASE}${path}`, options);
    if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw { status: res.status, ...err };
    }
    return res.json();
}

export const apiGet = (path) => apiFetch(path);

export const apiPost = (path, body, opts = {}) =>
    apiFetch(path, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
        signal: opts.signal   // 传入 AbortController.signal 可中途取消请求（如「停止任务」）
    });

export const apiPut = (path, body) =>
    apiFetch(path, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body)
    });

export const apiDelete = (path) => apiFetch(path, { method: 'DELETE' });

// 上传文件（multipart/form-data）：不要手写 Content-Type，交给浏览器带 boundary。
// 目前用于「图文互搜」的以图搜图（POST /search/image）。
export const apiUpload = (path, formData) =>
    apiFetch(path, { method: 'POST', body: formData });
