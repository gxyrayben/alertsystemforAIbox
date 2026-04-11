<script>
    import { onMount } from 'svelte';
    import { API_BASE } from '../lib/config.js';

    let servicesConfig = {
        ws: { enabled: true, port: '8080', path: '/api/ws/alarms' },
        http: { enabled: true, port: '80', path: '/api/http/alarms' }
    };

    onMount(async () => {
        await fetchServicesConfig();
    });

    async function fetchServicesConfig() {
        try {
            const res = await fetch(`${API_BASE}/services/config`);
            if (res.ok) servicesConfig = await res.json();
        } catch (e) { console.error(e); }
    }

    async function saveServicesConfig(type) {
        try {
            const res = await fetch(`${API_BASE}/services/config`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(servicesConfig)
            });
            if (res.ok) {
                alert(`${type.toUpperCase()} 服务配置已保存`);
            }
        } catch (e) { console.error(e); }
    }
</script>

<div class="grid grid-cols-1 md:grid-cols-2 gap-6">
    <!-- WebSocket 服务 -->
    <div class="bg-white rounded-xl shadow-sm border border-gray-200 overflow-hidden flex flex-col">
        <div class="px-6 py-4 border-b border-gray-200 bg-gray-50 flex justify-between items-center">
            <h3 class="font-semibold text-gray-800">WebSocket 报警接收服务</h3>
            <label class="relative inline-flex items-center cursor-pointer">
                <input type="checkbox" bind:checked={servicesConfig.ws.enabled} class="sr-only peer">
                <div class="w-11 h-6 bg-gray-200 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-blue-600"></div>
            </label>
        </div>
        <div class="p-6 space-y-4">
            <div class="flex flex-col space-y-1">
                <label class="text-xs text-gray-500" for="ws-port">服务端口</label>
                <input id="ws-port" type="text" bind:value={servicesConfig.ws.port} class="px-3 py-2 border rounded-lg text-sm outline-none focus:ring-2 focus:ring-blue-500" />
            </div>
            <div class="flex flex-col space-y-1">
                <label class="text-xs text-gray-500" for="ws-path">订阅路径</label>
                <input id="ws-path" type="text" bind:value={servicesConfig.ws.path} class="px-3 py-2 border rounded-lg text-sm outline-none focus:ring-2 focus:ring-blue-500" />
            </div>

            <!-- 认证配置 -->
            <div class="pt-2 border-t space-y-3">
                <div class="flex items-center justify-between">
                    <span class="text-xs font-semibold text-gray-600">访问认证 (Token/Auth)</span>
                    <label class="relative inline-flex items-center cursor-pointer scale-75">
                        <input type="checkbox" bind:checked={servicesConfig.ws.auth_enabled} class="sr-only peer">
                        <div class="w-11 h-6 bg-gray-200 rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-indigo-500"></div>
                    </label>
                </div>
                {#if servicesConfig.ws.auth_enabled}
                    <div class="grid grid-cols-2 gap-3 animate-in fade-in duration-300">
                        <input type="text" placeholder="用户名" bind:value={servicesConfig.ws.username} class="px-3 py-1.5 border rounded text-xs outline-none" />
                        <input type="password" placeholder="Token/密码" bind:value={servicesConfig.ws.password} class="px-3 py-1.5 border rounded text-xs outline-none" />
                    </div>
                {/if}
            </div>
        </div>

        <div class="px-6 py-4 border-t border-gray-200 bg-gray-50 flex justify-end">
            <button on:click={() => saveServicesConfig('ws')} class="px-4 py-2 bg-blue-600 text-white rounded-lg text-sm font-medium">保存 WS 配置</button>
        </div>
    </div>

    <!-- HTTP 服务 -->
    <div class="bg-white rounded-xl shadow-sm border border-gray-200 overflow-hidden flex flex-col">
        <div class="px-6 py-4 border-b border-gray-200 bg-gray-50 flex justify-between items-center">
            <h3 class="font-semibold text-gray-800">HTTP 报警推送服务</h3>
            <label class="relative inline-flex items-center cursor-pointer">
                <input type="checkbox" bind:checked={servicesConfig.http.enabled} class="sr-only peer">
                <div class="w-11 h-6 bg-gray-200 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-blue-600"></div>
            </label>
        </div>
        <div class="p-6 space-y-4">
            <div class="flex flex-col space-y-1">
                <label class="text-xs text-gray-500" for="http-port">监听端口</label>
                <input id="http-port" type="text" bind:value={servicesConfig.http.port} class="px-3 py-2 border rounded-lg text-sm outline-none focus:ring-2 focus:ring-blue-500" />
            </div>
            <div class="flex flex-col space-y-1">
                <label class="text-xs text-gray-500" for="http-path">推送路径</label>
                <input id="http-path" type="text" bind:value={servicesConfig.http.path} class="px-3 py-2 border rounded-lg text-sm outline-none focus:ring-2 focus:ring-blue-500" />
            </div>

            <!-- 认证配置 -->
            <div class="pt-2 border-t space-y-3">
                <div class="flex items-center justify-between">
                    <span class="text-xs font-semibold text-gray-600">访问认证 (Token/Auth)</span>
                    <label class="relative inline-flex items-center cursor-pointer scale-75">
                        <input type="checkbox" bind:checked={servicesConfig.http.auth_enabled} class="sr-only peer">
                        <div class="w-11 h-6 bg-gray-200 rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-indigo-500"></div>
                    </label>
                </div>
                {#if servicesConfig.http.auth_enabled}
                    <div class="grid grid-cols-2 gap-3 animate-in fade-in duration-300">
                        <input type="text" placeholder="用户名" bind:value={servicesConfig.http.username} class="px-3 py-1.5 border rounded text-xs outline-none" />
                        <input type="password" placeholder="Token/密码" bind:value={servicesConfig.http.password} class="px-3 py-1.5 border rounded text-xs outline-none" />
                    </div>
                {/if}
            </div>
        </div>

        <div class="px-6 py-4 border-t border-gray-200 bg-gray-50 flex justify-end">
            <button on:click={() => saveServicesConfig('http')} class="px-4 py-2 bg-blue-600 text-white rounded-lg text-sm font-medium">保存 HTTP 配置</button>
        </div>
    </div>
</div>
