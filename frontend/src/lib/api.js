// 后端地址跟随当前访问页面的主机名，端口固定 8000。
// 这样本机用 localhost、其他电脑用服务器局域网 IP 访问时，都能正确指向后端，
// 不用写死 IP（原来写死 localhost 会让其他电脑请求打到它自己本机，导致取不到数据）。
export const API_BASE = `http://${window.location.hostname}:8000`;

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
