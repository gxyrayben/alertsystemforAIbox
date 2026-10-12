<script>
    import { onMount } from 'svelte';
    import { apiGet, apiPost } from '../lib/api.js';

    let servicesConfig = {
        ws: { enabled: true, port: '8080', path: '/api/ws/alarms' },
        http: { enabled: true, port: '80', path: '/api/http/alarms' },
        // 服务端 TLS：主服务 :8000 与下面两个报警接收端口共用这一份开关（二选一：http 或 https）
        tls: { enabled: false, cert_file: 'certs/server.crt', key_file: 'certs/server.key' }
    };

    onMount(async () => {
        await fetchServicesConfig();
    });

    async function fetchServicesConfig() {
        try {
            const cfg = await apiGet('/services/config');
            servicesConfig = {
                ...servicesConfig, ...cfg,
                tls: { ...servicesConfig.tls, ...(cfg.tls || {}) },
            };
        } catch (e) { console.error(e); }
    }

    async function saveServicesConfig(type) {
        try {
            await apiPost('/services/config', servicesConfig);
            const extra = (type === 'tls' && servicesConfig.tls?.enabled)
                ? '\n注意：主服务(:8000)的协议切换需重启后端进程后生效；报警接收端口已即时重启。'
                : '';
            alert(`${type.toUpperCase()} 服务配置已保存${extra}`);
            await fetchServicesConfig();
        } catch (e) { console.error(e); }
    }
</script>

<div class="space-y-6">
    <!-- 全局 TLS（HTTPS/WSS）开关：主服务 + 报警接收端口共用 -->
    <div class="bg-slate-950 rounded-2xl border border-slate-800 overflow-hidden">
        <div class="px-6 py-4 border-b border-slate-800 bg-slate-900/40 flex justify-between items-center">
            <div>
                <h3 class="text-white font-bold">服务协议：HTTPS / WSS</h3>
                <p class="text-[11px] text-slate-500 mt-0.5">主服务 :8000 与下面两个报警接收端口共用此开关（二选一：HTTP 或 HTTPS）</p>
            </div>
            <label class="relative inline-flex items-center cursor-pointer">
                <input type="checkbox" bind:checked={servicesConfig.tls.enabled} class="sr-only peer">
                <div class="w-11 h-6 bg-slate-700 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-slate-200 after:border-slate-400 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-emerald-600"></div>
            </label>
        </div>
        <div class="p-6 space-y-4">
            <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div class="flex flex-col space-y-1">
                    <label class="text-xs font-medium text-slate-400" for="tls-cert">证书文件 (cert)</label>
                    <input id="tls-cert" type="text" bind:value={servicesConfig.tls.cert_file} placeholder="certs/server.crt"
                           class="bg-slate-900 border border-slate-800 text-slate-100 rounded-xl px-4 py-3 text-sm placeholder-slate-500 outline-none focus:border-indigo-500 font-mono" />
                </div>
                <div class="flex flex-col space-y-1">
                    <label class="text-xs font-medium text-slate-400" for="tls-key">私钥文件 (key)</label>
                    <input id="tls-key" type="text" bind:value={servicesConfig.tls.key_file} placeholder="certs/server.key"
                           class="bg-slate-900 border border-slate-800 text-slate-100 rounded-xl px-4 py-3 text-sm placeholder-slate-500 outline-none focus:border-indigo-500 font-mono" />
                </div>
            </div>
            <p class="text-[11px] text-slate-500 leading-relaxed">
                路径相对 backend/ 目录（也可写绝对路径）。没有证书时先执行
                <code class="text-indigo-300 bg-slate-900 px-1.5 py-0.5 rounded">python tools/gen_self_signed_cert.py</code>
                生成自签证书；证书缺失会自动回落 HTTP 并在后端日志告警。
                <span class="text-amber-400/90">主服务(:8000) 的协议切换需重启后端进程生效，报警接收端口保存后即时重启。</span>
            </p>
        </div>
        <div class="px-6 py-4 border-t border-slate-800 bg-slate-900/40 flex justify-end">
            <button on:click={() => saveServicesConfig('tls')} class="bg-emerald-600 hover:bg-emerald-700 text-white rounded-xl text-xs font-bold px-4 py-2">保存协议配置</button>
        </div>
    </div>

    <div class="grid grid-cols-1 md:grid-cols-2 gap-6">
    <!-- WebSocket 服务 -->
    <div class="bg-slate-950 rounded-2xl border border-slate-800 overflow-hidden flex flex-col">
        <div class="px-6 py-4 border-b border-slate-800 bg-slate-900/40 flex justify-between items-center">
            <h3 class="text-white font-bold">WebSocket 报警接收服务</h3>
            <label class="relative inline-flex items-center cursor-pointer">
                <input type="checkbox" bind:checked={servicesConfig.ws.enabled} class="sr-only peer">
                <div class="w-11 h-6 bg-slate-700 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-slate-200 after:border-slate-400 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-indigo-600"></div>
            </label>
        </div>
        <div class="p-6 space-y-4">
            <div class="flex flex-col space-y-1">
                <label class="text-xs font-medium text-slate-400" for="ws-port">服务端口</label>
                <input id="ws-port" type="text" bind:value={servicesConfig.ws.port} class="bg-slate-900 border border-slate-800 text-slate-100 rounded-xl px-4 py-3 text-sm placeholder-slate-500 outline-none focus:border-indigo-500" />
            </div>
            <div class="flex flex-col space-y-1">
                <label class="text-xs font-medium text-slate-400" for="ws-path">订阅路径</label>
                <input id="ws-path" type="text" bind:value={servicesConfig.ws.path} class="bg-slate-900 border border-slate-800 text-slate-100 rounded-xl px-4 py-3 text-sm placeholder-slate-500 outline-none focus:border-indigo-500" />
            </div>

            <!-- 认证配置 -->
            <div class="pt-2 border-t border-slate-800 space-y-3">
                <div class="flex items-center justify-between">
                    <span class="text-xs font-semibold text-slate-400">访问认证 (Token/Auth)</span>
                    <label class="relative inline-flex items-center cursor-pointer scale-75">
                        <input type="checkbox" bind:checked={servicesConfig.ws.auth_enabled} class="sr-only peer">
                        <div class="w-11 h-6 bg-slate-700 rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-slate-200 after:border-slate-400 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-indigo-500"></div>
                    </label>
                </div>
                {#if servicesConfig.ws.auth_enabled}
                    <div class="grid grid-cols-2 gap-3 animate-in fade-in duration-300">
                        <input type="text" placeholder="用户名" bind:value={servicesConfig.ws.username} class="bg-slate-900 border border-slate-800 text-slate-100 rounded-xl px-3 py-2 text-xs placeholder-slate-500 outline-none focus:border-indigo-500" />
                        <input type="password" placeholder="Token/密码" bind:value={servicesConfig.ws.password} class="bg-slate-900 border border-slate-800 text-slate-100 rounded-xl px-3 py-2 text-xs placeholder-slate-500 outline-none focus:border-indigo-500" />
                    </div>
                {/if}
            </div>
        </div>

        <div class="px-6 py-4 border-t border-slate-800 bg-slate-900/40 flex justify-end">
            <button on:click={() => saveServicesConfig('ws')} class="bg-indigo-600 hover:bg-indigo-700 text-white rounded-xl text-xs font-bold px-4 py-2">保存 WS 配置</button>
        </div>
    </div>

    <!-- HTTP 服务 -->
    <div class="bg-slate-950 rounded-2xl border border-slate-800 overflow-hidden flex flex-col">
        <div class="px-6 py-4 border-b border-slate-800 bg-slate-900/40 flex justify-between items-center">
            <h3 class="text-white font-bold">HTTP 报警推送服务</h3>
            <label class="relative inline-flex items-center cursor-pointer">
                <input type="checkbox" bind:checked={servicesConfig.http.enabled} class="sr-only peer">
                <div class="w-11 h-6 bg-slate-700 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-slate-200 after:border-slate-400 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-indigo-600"></div>
            </label>
        </div>
        <div class="p-6 space-y-4">
            <div class="flex flex-col space-y-1">
                <label class="text-xs font-medium text-slate-400" for="http-port">监听端口</label>
                <input id="http-port" type="text" bind:value={servicesConfig.http.port} class="bg-slate-900 border border-slate-800 text-slate-100 rounded-xl px-4 py-3 text-sm placeholder-slate-500 outline-none focus:border-indigo-500" />
            </div>
            <div class="flex flex-col space-y-1">
                <label class="text-xs font-medium text-slate-400" for="http-path">推送路径</label>
                <input id="http-path" type="text" bind:value={servicesConfig.http.path} class="bg-slate-900 border border-slate-800 text-slate-100 rounded-xl px-4 py-3 text-sm placeholder-slate-500 outline-none focus:border-indigo-500" />
            </div>

            <!-- 认证配置 -->
            <div class="pt-2 border-t border-slate-800 space-y-3">
                <div class="flex items-center justify-between">
                    <span class="text-xs font-semibold text-slate-400">访问认证 (Token/Auth)</span>
                    <label class="relative inline-flex items-center cursor-pointer scale-75">
                        <input type="checkbox" bind:checked={servicesConfig.http.auth_enabled} class="sr-only peer">
                        <div class="w-11 h-6 bg-slate-700 rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-slate-200 after:border-slate-400 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-indigo-500"></div>
                    </label>
                </div>
                {#if servicesConfig.http.auth_enabled}
                    <div class="grid grid-cols-2 gap-3 animate-in fade-in duration-300">
                        <input type="text" placeholder="用户名" bind:value={servicesConfig.http.username} class="bg-slate-900 border border-slate-800 text-slate-100 rounded-xl px-3 py-2 text-xs placeholder-slate-500 outline-none focus:border-indigo-500" />
                        <input type="password" placeholder="Token/密码" bind:value={servicesConfig.http.password} class="bg-slate-900 border border-slate-800 text-slate-100 rounded-xl px-3 py-2 text-xs placeholder-slate-500 outline-none focus:border-indigo-500" />
                    </div>
                {/if}
            </div>
        </div>

        <div class="px-6 py-4 border-t border-slate-800 bg-slate-900/40 flex justify-end">
            <button on:click={() => saveServicesConfig('http')} class="bg-indigo-600 hover:bg-indigo-700 text-white rounded-xl text-xs font-bold px-4 py-2">保存 HTTP 配置</button>
        </div>
    </div>
    </div>
</div>
