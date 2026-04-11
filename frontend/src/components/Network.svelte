<script>
    import { onMount } from 'svelte';
    import { API_BASE } from '../lib/config.js';

    let networkInterfaces = [];
    let backendNetworkId = 'eth0';
    let frontendNetworkId = 'eth0';
    
    $: backendNetwork = Array.isArray(networkInterfaces) ? networkInterfaces.find(n => n.id === backendNetworkId) : null;
    $: frontendNetwork = Array.isArray(networkInterfaces) ? networkInterfaces.find(n => n.id === frontendNetworkId) : null;

    onMount(async () => {
        await fetchNetworkInterfaces();
        await fetchNetworkConfig();
    });

    async function fetchNetworkInterfaces() {
        try {
            const res = await fetch(`${API_BASE}/network/interfaces`);
            if (res.ok) networkInterfaces = await res.json();
        } catch (e) { console.error(e); }
    }

    async function fetchNetworkConfig() {
        try {
            const res = await fetch(`${API_BASE}/network/config`);
            if (res.ok) {
                const data = await res.json();
                backendNetworkId = data.backend_interface_id || 'eth0';
                frontendNetworkId = data.frontend_interface_id || 'eth0';
            }
        } catch (e) { console.error(e); }
    }

    async function saveNetworkConfig() {
        try {
            const res = await fetch(`${API_BASE}/network/config`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ 
                    backend_interface_id: backendNetworkId,
                    frontend_interface_id: frontendNetworkId
                })
            });
            if (res.ok && backendNetwork && frontendNetwork) {
                alert(`配置已保存！\n\n后端服务将绑定至: ${backendNetwork.name} (${backendNetwork.ip})\n前端 UI 将绑定至: ${frontendNetwork.name} (${frontendNetwork.ip})\n\n请注意：前端绑定改变可能会导致服务重启，您可能需要手动刷新或访问新的前端 IP 地址。`);
            }
        } catch (e) { console.error(e); }
    }
</script>

<div class="grid grid-cols-1 xl:grid-cols-2 gap-6 h-full items-start">
    <!-- 后端网卡绑定 -->
    <div class="bg-white rounded-xl shadow-sm border border-gray-200 overflow-hidden flex flex-col">
        <div class="px-6 py-4 border-b border-gray-200 bg-gray-50">
            <h3 class="text-lg font-semibold text-gray-800">后端数据服务网卡绑定</h3>
            <p class="text-xs text-gray-500 mt-1">选择后端数据接收服务所绑定的网卡。指定正确的网卡能确保设备报警数据成功上报被接收。</p>
        </div>
        
        <div class="p-6 space-y-6 flex-1">
            <div>
                <label class="block text-sm font-medium text-gray-700 mb-2" for="backend-nic-select">选择网卡 (Network Interface)</label>
                <div class="relative">
                    <select 
                        id="backend-nic-select"
                        bind:value={backendNetworkId} 
                        class="w-full px-4 py-3 border border-gray-300 rounded-lg outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500 text-sm bg-white appearance-none cursor-pointer"
                    >
                        {#each networkInterfaces as nic}
                            <option value={nic.id}>{nic.name}</option>
                        {/each}
                    </select>
                    <div class="pointer-events-none absolute inset-y-0 right-0 flex items-center px-4 text-gray-500">
                        <svg class="fill-current h-4 w-4" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20"><path d="M9.293 12.95l.707.707L15.657 8l-1.414-1.414L10 10.828 5.757 6.586 4.343 8z"/></svg>
                    </div>
                </div>
            </div>

            {#if backendNetwork}
                <div class="bg-gray-50 rounded-lg p-5 border border-gray-200 space-y-4">
                    <div class="grid grid-cols-1 gap-y-3 text-sm">
                        <div class="flex justify-between">
                            <span class="text-gray-500">IPv4 地址:</span>
                            <span class="font-mono text-gray-900 bg-white px-2 border rounded">{backendNetwork.ip}</span>
                        </div>
                        <div class="flex justify-between">
                            <span class="text-gray-500">MAC 地址:</span>
                            <span class="font-mono text-gray-900">{backendNetwork.mac}</span>
                        </div>
                        <div class="flex justify-between">
                            <span class="text-gray-500">连接状态:</span>
                            <span class="inline-flex items-center text-xs font-medium {backendNetwork.status === 'connected' ? 'text-green-600' : 'text-red-600'}">
                                {backendNetwork.status === 'connected' ? '● 已连接' : '○ 未连接'}
                            </span>
                        </div>
                    </div>
                </div>
            {/if}
        </div>
    </div>

    <!-- 前端 Web UI 网卡绑定 -->
    <div class="bg-white rounded-xl shadow-sm border border-gray-200 overflow-hidden flex flex-col">
        <div class="px-6 py-4 border-b border-gray-200 bg-blue-50/50">
            <h3 class="text-lg font-semibold text-blue-900">前端 Web UI 访问网卡绑定</h3>
            <p class="text-xs text-blue-600/70 mt-1">选择 Web UI 页面所绑定的监听网卡。以便允许局域网内的其他电脑设备能够访问并管理本系统。</p>
        </div>
        
        <div class="p-6 space-y-6 flex-1">
            <div>
                <label class="block text-sm font-medium text-gray-700 mb-2" for="frontend-nic-select">选择网卡 (Network Interface)</label>
                <div class="relative">
                    <select 
                        id="frontend-nic-select"
                        bind:value={frontendNetworkId} 
                        class="w-full px-4 py-3 border border-gray-300 rounded-lg outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500 text-sm bg-white appearance-none cursor-pointer"
                    >
                        {#each networkInterfaces as nic}
                            <option value={nic.id}>{nic.name}</option>
                        {/each}
                    </select>
                    <div class="pointer-events-none absolute inset-y-0 right-0 flex items-center px-4 text-gray-500">
                        <svg class="fill-current h-4 w-4" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20"><path d="M9.293 12.95l.707.707L15.657 8l-1.414-1.414L10 10.828 5.757 6.586 4.343 8z"/></svg>
                    </div>
                </div>
            </div>

            {#if frontendNetwork}
                <div class="bg-blue-50/30 rounded-lg p-5 border border-blue-100 space-y-4">
                    <div class="grid grid-cols-1 gap-y-3 text-sm">
                        <div class="flex justify-between">
                            <span class="text-gray-500">外部访问地址 (URL):</span>
                            <span class="font-mono text-blue-700 font-bold bg-white px-2 border border-blue-200 rounded">http://{frontendNetwork.ip}:5173</span>
                        </div>
                        <div class="flex justify-between">
                            <span class="text-gray-500">MAC 地址:</span>
                            <span class="font-mono text-gray-900">{frontendNetwork.mac}</span>
                        </div>
                        <div class="flex justify-between">
                            <span class="text-gray-500">连接状态:</span>
                            <span class="inline-flex items-center text-xs font-medium {frontendNetwork.status === 'connected' ? 'text-green-600' : 'text-red-600'}">
                                {frontendNetwork.status === 'connected' ? '● 已连接' : '○ 未连接'}
                            </span>
                        </div>
                    </div>
                </div>
            {/if}
        </div>
    </div>
    
    <!-- 统一保存按钮 -->
    <div class="xl:col-span-2 flex justify-end">
        <button 
            on:click={saveNetworkConfig}
            class="px-8 py-3 bg-blue-600 hover:bg-blue-700 text-white rounded-xl shadow-lg shadow-blue-200 text-sm font-bold transition-all active:scale-95"
        >
            保存所有网络配置
        </button>
    </div>
</div>
