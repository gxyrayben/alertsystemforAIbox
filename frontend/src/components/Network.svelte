<script>
    import { onMount } from 'svelte';
    import { apiGet, apiPost } from '../lib/api.js';

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
            networkInterfaces = await apiGet('/network/interfaces');
        } catch (e) { console.error(e); }
    }

    async function fetchNetworkConfig() {
        try {
            const data = await apiGet('/network/config');
            backendNetworkId = data.backend_interface_id || 'eth0';
            frontendNetworkId = data.frontend_interface_id || 'eth0';
        } catch (e) { console.error(e); }
    }

    async function saveNetworkConfig() {
        try {
            await apiPost('/network/config', {
                backend_interface_id: backendNetworkId,
                frontend_interface_id: frontendNetworkId
            });
            if (backendNetwork && frontendNetwork) {
                alert(`配置已保存！\n\n后端服务将绑定至: ${backendNetwork.name} (${backendNetwork.ip})\n前端 UI 将绑定至: ${frontendNetwork.name} (${frontendNetwork.ip})\n\n请注意：前端绑定改变可能会导致服务重启，您可能需要手动刷新或访问新的前端 IP 地址。`);
            }
        } catch (e) { console.error(e); }
    }
</script>

<div class="grid grid-cols-1 xl:grid-cols-2 gap-6 h-full items-start">
    <!-- 后端网卡绑定 -->
    <div class="bg-slate-950 rounded-2xl border border-slate-800 overflow-hidden flex flex-col">
        <div class="px-6 py-4 border-b border-slate-800 bg-slate-900/40">
            <h3 class="text-lg text-white font-bold">后端数据服务网卡绑定</h3>
            <p class="text-xs text-slate-400 mt-1">选择后端数据接收服务所绑定的网卡。指定正确的网卡能确保设备报警数据成功上报被接收。</p>
        </div>

        <div class="p-6 space-y-6 flex-1">
            <div>
                <label class="block text-sm font-semibold text-slate-200 mb-2" for="backend-nic-select">选择网卡 (Network Interface)</label>
                <div class="relative">
                    <select
                        id="backend-nic-select"
                        bind:value={backendNetworkId}
                        class="w-full bg-slate-900 border border-slate-800 text-slate-100 rounded-xl px-4 py-3 text-sm placeholder-slate-500 outline-none focus:border-indigo-500 appearance-none cursor-pointer"
                    >
                        {#each networkInterfaces as nic}
                            <option value={nic.id}>{nic.name}</option>
                        {/each}
                    </select>
                    <div class="pointer-events-none absolute inset-y-0 right-0 flex items-center px-4 text-slate-500">
                        <svg class="fill-current h-4 w-4" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20"><path d="M9.293 12.95l.707.707L15.657 8l-1.414-1.414L10 10.828 5.757 6.586 4.343 8z"/></svg>
                    </div>
                </div>
            </div>

            {#if backendNetwork}
                <div class="bg-slate-900/60 rounded-xl p-5 border border-slate-800 space-y-4">
                    <div class="grid grid-cols-1 gap-y-3 text-sm">
                        <div class="flex justify-between">
                            <span class="text-slate-400">IPv4 地址:</span>
                            <span class="font-mono text-slate-200 bg-slate-900 border border-slate-800 rounded px-2">{backendNetwork.ip}</span>
                        </div>
                        <div class="flex justify-between">
                            <span class="text-slate-400">MAC 地址:</span>
                            <span class="font-mono text-slate-200">{backendNetwork.mac}</span>
                        </div>
                        <div class="flex justify-between">
                            <span class="text-slate-400">连接状态:</span>
                            <span class="inline-flex items-center text-xs font-medium {backendNetwork.status === 'connected' ? 'text-emerald-400' : 'text-rose-400'}">
                                {backendNetwork.status === 'connected' ? '● 已连接' : '○ 未连接'}
                            </span>
                        </div>
                    </div>
                </div>
            {/if}
        </div>
    </div>

    <!-- 前端 Web UI 网卡绑定 -->
    <div class="bg-slate-950 rounded-2xl border border-slate-800 overflow-hidden flex flex-col">
        <div class="px-6 py-4 border-b border-slate-800 bg-slate-900/40">
            <h3 class="text-lg text-white font-bold">前端 Web UI 访问网卡绑定</h3>
            <p class="text-xs text-slate-400 mt-1">选择 Web UI 页面所绑定的监听网卡。以便允许局域网内的其他电脑设备能够访问并管理本系统。</p>
        </div>

        <div class="p-6 space-y-6 flex-1">
            <div>
                <label class="block text-sm font-semibold text-slate-200 mb-2" for="frontend-nic-select">选择网卡 (Network Interface)</label>
                <div class="relative">
                    <select
                        id="frontend-nic-select"
                        bind:value={frontendNetworkId}
                        class="w-full bg-slate-900 border border-slate-800 text-slate-100 rounded-xl px-4 py-3 text-sm placeholder-slate-500 outline-none focus:border-indigo-500 appearance-none cursor-pointer"
                    >
                        {#each networkInterfaces as nic}
                            <option value={nic.id}>{nic.name}</option>
                        {/each}
                    </select>
                    <div class="pointer-events-none absolute inset-y-0 right-0 flex items-center px-4 text-slate-500">
                        <svg class="fill-current h-4 w-4" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20"><path d="M9.293 12.95l.707.707L15.657 8l-1.414-1.414L10 10.828 5.757 6.586 4.343 8z"/></svg>
                    </div>
                </div>
            </div>

            {#if frontendNetwork}
                <div class="bg-slate-900/60 rounded-xl p-5 border border-slate-800 space-y-4">
                    <div class="grid grid-cols-1 gap-y-3 text-sm">
                        <div class="flex justify-between">
                            <span class="text-slate-400">外部访问地址 (URL):</span>
                            <span class="font-mono text-indigo-400 font-bold bg-slate-900 border border-indigo-500/30 rounded px-2">http://{frontendNetwork.ip}:5173</span>
                        </div>
                        <div class="flex justify-between">
                            <span class="text-slate-400">MAC 地址:</span>
                            <span class="font-mono text-slate-200">{frontendNetwork.mac}</span>
                        </div>
                        <div class="flex justify-between">
                            <span class="text-slate-400">连接状态:</span>
                            <span class="inline-flex items-center text-xs font-medium {frontendNetwork.status === 'connected' ? 'text-emerald-400' : 'text-rose-400'}">
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
            class="px-8 py-3 bg-indigo-600 hover:bg-indigo-700 text-white rounded-xl shadow-lg shadow-indigo-500/20 text-sm font-bold transition-all active:scale-95"
        >
            保存所有网络配置
        </button>
    </div>
</div>
