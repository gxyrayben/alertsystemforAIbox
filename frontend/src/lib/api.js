export const API_BASE = 'http://localhost:8000';

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
