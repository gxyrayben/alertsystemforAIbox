<script>
    import { onMount } from 'svelte';
    import { apiGet, apiPost, apiPut, apiDelete } from '../lib/api.js';
    import { parseJson } from '../lib/utils.js';
    import { setDevices } from '../lib/controlStore.js';

    let devices = [];
    let isDeviceModalOpen = false;
    let editingDeviceId = null;
    let deviceFormData = { device_id: '', name: '', ip: '', port: '80', username: '', password: '' };
    let devicePage = 1;
    const itemsPerPage = 15;

    // Fetch Details Modal
    let isFetchDetailModalOpen = false;
    let currentDetailDevice = null;
    let isFetching = false;
    let isRefreshingAll = false;   // 新增：一键刷新所有设备状态

    onMount(async () => {
        await fetchDevices();
    });

    async function fetchDevices() {
        try {
            devices = await apiGet('/devices');
            setDevices(devices); // 同步全局“当前设备”下拉
        } catch (e) { console.error(e); }
    }

    async function handleDeviceSave() {
        if (!deviceFormData.device_id || !deviceFormData.name || !deviceFormData.ip) return alert('设备ID、名称和IP不能为空！');

        try {
            if (editingDeviceId) {
                await apiPut(`/devices/${editingDeviceId}`, deviceFormData);
            } else {
                await apiPost('/devices', deviceFormData);
            }
            await fetchDevices();
            isDeviceModalOpen = false;
        } catch (e) {
            console.error(e);
            alert(`保存失败: ${e.detail || '未知错误'}`);
        }
    }

    async function handleDeviceDelete(id) {
        if (confirm('确定删除该设备吗？')) {
            try {
                await apiDelete(`/devices/${id}`);
                await fetchDevices();
            } catch (e) { console.error(e); }
        }
    }

    async function handleFetchDetail(device) {
        isFetching = true;
        currentDetailDevice = device;
        isFetchDetailModalOpen = true;

        try {
            const updatedDevice = await apiPost(`/devices/${device.id}/fetch`);
            currentDetailDevice = updatedDevice;
            // 同步更新列表中的该设备
            const idx = devices.findIndex(d => d.id === device.id);
            if (idx !== -1) devices[idx] = updatedDevice;
        } catch (e) {
            console.error(e);
            alert("获取设备信息失败，请检查设备连通性。");
        } finally {
            isFetching = false;
        }
    }

    // 刷新列表：对每台设备重新联系设备端拉取最新状态（复用 /fetch），再刷新列表
    async function handleRefreshAll() {
        if (isRefreshingAll || devices.length === 0) return;
        isRefreshingAll = true;
        try {
            const results = await Promise.allSettled(
                devices.map(d => apiPost(`/devices/${d.id}/fetch`))
            );
            const failed = results.filter(r => r.status === 'rejected').length;
            await fetchDevices();
            if (failed > 0) alert(`${failed} 台设备刷新失败（可能离线或不可达）。`);
        } catch (e) {
            console.error(e);
            alert('刷新列表失败，请稍后重试。');
        } finally {
            isRefreshingAll = false;
        }
    }

    function openDeviceModal(device = null) {
        if (device) {
            deviceFormData = { ...device };
            editingDeviceId = device.id;
        } else {
            deviceFormData = { device_id: '', name: '', ip: '', port: '80', username: '', password: '' };
            editingDeviceId = null;
        }
        isDeviceModalOpen = true;
    }

    $: totalDevicePages = Math.ceil(devices.length / itemsPerPage);
    $: currentDevices = devices.slice((devicePage - 1) * itemsPerPage, devicePage * itemsPerPage);

    function getStatusStyle(status) {
        switch (status) {
            case '在线': return 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20';
            case '异常': return 'bg-rose-500/10 text-rose-400 border-rose-500/20';
            case '离线': default: return 'bg-slate-800 text-slate-400 border-slate-700';
        }
    }
</script>

<div class="bg-slate-950 border border-slate-800 rounded-2xl flex flex-col h-full">
    <div class="px-6 py-5 border-b border-slate-800 bg-slate-900/40 flex justify-between items-center">
        <div class="text-sm text-slate-400">共找到 <span class="font-bold text-slate-100">{devices.length}</span> 个设备</div>
        <div class="flex items-center space-x-3">
            <button on:click={handleRefreshAll} disabled={isRefreshingAll || devices.length === 0} class="flex items-center px-4 py-2 bg-slate-900 hover:bg-slate-800 text-slate-200 border border-slate-800 rounded-xl shadow-sm text-sm font-bold disabled:opacity-50 disabled:cursor-not-allowed">
                <i class="fa-solid fa-arrows-rotate text-sm mr-2 {isRefreshingAll ? 'animate-spin' : ''}"></i>
                {isRefreshingAll ? '刷新中...' : '刷新列表'}
            </button>
            <button on:click={() => openDeviceModal()} class="flex items-center px-4 py-2 bg-indigo-600 hover:bg-indigo-700 text-white rounded-xl shadow-sm text-sm font-bold">
                <i class="fa-solid fa-plus text-sm mr-2"></i> 添加设备
            </button>
        </div>
    </div>
    <div class="flex-1 overflow-auto">
        <table class="w-full text-left border-collapse">
            <thead class="bg-slate-900/60 sticky top-0 z-10">
                <tr>
                    <th class="px-6 py-4 text-[11px] font-semibold text-slate-500 uppercase tracking-wider border-b border-slate-800">业务 ID (匹配协议)</th>
                    <th class="px-6 py-4 text-[11px] font-semibold text-slate-500 uppercase tracking-wider border-b border-slate-800">设备名称</th>
                    <th class="px-6 py-4 text-[11px] font-semibold text-slate-500 uppercase tracking-wider border-b border-slate-800">IP地址/端口</th>
                    <th class="px-6 py-4 text-[11px] font-semibold text-slate-500 uppercase tracking-wider border-b border-slate-800">状态</th>
                    <th class="px-6 py-4 text-[11px] font-semibold text-slate-500 uppercase tracking-wider border-b border-slate-800 text-center">操作</th>
                </tr>
            </thead>
            <tbody class="divide-y divide-slate-800 bg-slate-950">
                {#each currentDevices as device}
                    <tr class="hover:bg-slate-900/60 transition-colors">
                        <td class="px-6 py-4 whitespace-nowrap text-sm font-mono text-indigo-400">{device.device_id}</td>
                        <td class="px-6 py-4 whitespace-nowrap text-sm font-medium text-slate-100">{device.name}</td>
                        <td class="px-6 py-4 whitespace-nowrap text-sm text-slate-400 font-mono">{device.ip}:{device.port}</td>
                        <td class="px-6 py-4 whitespace-nowrap text-sm">
                            <span class="px-2.5 py-1 inline-flex text-xs leading-5 font-semibold rounded-full border {getStatusStyle(device.status)}">{device.status}</span>
                        </td>
                        <td class="px-6 py-4 whitespace-nowrap text-sm font-medium text-center flex items-center justify-center space-x-1">
                            <button on:click={() => handleFetchDetail(device)} class="text-emerald-400 hover:bg-emerald-500/10 p-1.5 rounded-lg transition-colors" title="获取详情">
                                <i class="fa-solid fa-arrows-rotate text-sm"></i>
                            </button>
                            <button on:click={() => openDeviceModal(device)} class="text-indigo-400 hover:bg-indigo-500/10 p-1.5 rounded-lg transition-colors" title="编辑">
                                <i class="fa-solid fa-pen-to-square text-sm"></i>
                            </button>
                            <button on:click={() => handleDeviceDelete(device.id)} class="text-rose-400 hover:bg-rose-500/10 p-1.5 rounded-lg transition-colors" title="删除">
                                <i class="fa-solid fa-trash text-sm"></i>
                            </button>
                        </td>
                    </tr>
                {/each}
            </tbody>
        </table>
    </div>
    <div class="px-6 py-4 border-t border-slate-800 bg-slate-900/40 flex items-center justify-between rounded-b-2xl">
        <span class="text-sm text-slate-400">第 <span class="font-medium text-slate-100">{devicePage}</span> 页 / 共 <span class="font-medium text-slate-100">{totalDevicePages || 1}</span> 页</span>
        <div class="flex space-x-2">
            <button on:click={() => devicePage = Math.max(1, devicePage - 1)} disabled={devicePage === 1} class="p-2 rounded-lg border border-slate-800 bg-slate-900 text-slate-400 hover:bg-slate-800 disabled:opacity-50"><i class="fa-solid fa-chevron-left text-sm"></i></button>
            <button on:click={() => devicePage = Math.min(totalDevicePages, devicePage + 1)} disabled={devicePage === totalDevicePages} class="p-2 rounded-lg border border-slate-800 bg-slate-900 text-slate-400 hover:bg-slate-800 disabled:opacity-50"><i class="fa-solid fa-chevron-right text-sm"></i></button>
        </div>
    </div>
</div>

<!-- Add/Edit Device Modal -->
{#if isDeviceModalOpen}
    <div class="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
        <div class="bg-slate-950 border border-slate-800 rounded-2xl shadow-2xl w-full max-w-md">
            <div class="px-6 py-4 border-b border-slate-800 flex justify-between items-center">
                <h3 class="text-lg text-white font-bold">{editingDeviceId ? '编辑设备' : '添加设备'}</h3>
                <button on:click={() => isDeviceModalOpen = false} class="text-slate-400 hover:text-slate-200"><i class="fa-solid fa-xmark text-base"></i></button>
            </div>
            <div class="px-6 py-5 space-y-4">
                <div>
                    <label class="block text-sm font-medium text-slate-300 mb-1">设备业务 ID <span class="text-rose-400">*</span></label>
                    <input type="text" placeholder="例如：DEV-001" bind:value={deviceFormData.device_id} class="w-full bg-slate-900 border border-slate-800 text-slate-100 rounded-xl px-4 py-2 text-sm placeholder-slate-500 outline-none focus:border-indigo-500" />
                </div>
                <div>
                    <label class="block text-sm font-medium text-slate-300 mb-1">设备名称 <span class="text-rose-400">*</span></label>
                    <input type="text" placeholder="例如：东大门摄像头" bind:value={deviceFormData.name} class="w-full bg-slate-900 border border-slate-800 text-slate-100 rounded-xl px-4 py-2 text-sm placeholder-slate-500 outline-none focus:border-indigo-500" />
                </div>
                <div class="flex space-x-4">
                    <div class="flex-1">
                        <label class="block text-sm font-medium text-slate-300 mb-1">IP 地址 <span class="text-rose-400">*</span></label>
                        <input type="text" placeholder="192.168.1.10" bind:value={deviceFormData.ip} class="w-full bg-slate-900 border border-slate-800 text-slate-100 rounded-xl px-4 py-2 text-sm placeholder-slate-500 outline-none focus:border-indigo-500" />
                    </div>
                    <div class="w-32">
                        <label class="block text-sm font-medium text-slate-300 mb-1">端口</label>
                        <input type="text" placeholder="80" bind:value={deviceFormData.port} class="w-full bg-slate-900 border border-slate-800 text-slate-100 rounded-xl px-4 py-2 text-sm placeholder-slate-500 outline-none focus:border-indigo-500" />
                    </div>
                </div>
                <div>
                    <label class="block text-sm font-medium text-slate-300 mb-1">用户名</label>
                    <input type="text" placeholder="admin" bind:value={deviceFormData.username} class="w-full bg-slate-900 border border-slate-800 text-slate-100 rounded-xl px-4 py-2 text-sm placeholder-slate-500 outline-none focus:border-indigo-500" />
                </div>
                <div>
                    <label class="block text-sm font-medium text-slate-300 mb-1">密码</label>
                    <input type="password" placeholder="请输入密码" bind:value={deviceFormData.password} class="w-full bg-slate-900 border border-slate-800 text-slate-100 rounded-xl px-4 py-2 text-sm placeholder-slate-500 outline-none focus:border-indigo-500" />
                </div>
            </div>
            <div class="px-6 py-4 border-t border-slate-800 flex justify-end space-x-3 bg-slate-900/40">
                <button on:click={() => isDeviceModalOpen = false} class="bg-slate-900 border border-slate-800 text-slate-300 hover:bg-slate-800 rounded-xl px-4 py-2">取消</button>
                <button on:click={handleDeviceSave} class="bg-indigo-600 hover:bg-indigo-700 text-white rounded-xl px-4 py-2 font-bold">确定</button>
            </div>
        </div>
    </div>
{/if}

<!-- Fetch Details Modal -->
{#if isFetchDetailModalOpen && currentDetailDevice}
    <div class="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4">
        <div class="bg-slate-950 border border-slate-800 rounded-2xl shadow-2xl w-full max-w-5xl max-h-[90vh] flex flex-col overflow-hidden">
            <div class="px-8 py-5 border-b border-slate-800 flex justify-between items-center bg-slate-900/40">
                <h3 class="text-xl font-bold text-white">设备详情获取 - {currentDetailDevice.name}</h3>
                <button on:click={() => isFetchDetailModalOpen = false} class="text-slate-400 hover:text-slate-200 p-1 rounded-full transition-colors">
                    <i class="fa-solid fa-xmark text-lg"></i>
                </button>
            </div>

            <div class="flex-1 overflow-y-auto p-8 space-y-10">
                <!-- Channel Table -->
                <section>
                    <div class="flex items-center mb-4">
                        <div class="p-2 bg-indigo-500/10 text-indigo-400 rounded-lg mr-3"><i class="fa-solid fa-camera text-base"></i></div>
                        <h4 class="text-lg font-semibold text-slate-100">设备通道列表 ({parseJson(currentDetailDevice.channels).length})</h4>
                    </div>
                    <div class="bg-slate-950 border border-slate-800 rounded-xl overflow-hidden">
                        <table class="w-full text-left border-collapse">
                            <thead>
                                <tr class="bg-slate-900/60 border-b border-slate-800 text-slate-500 text-[11px] font-semibold uppercase tracking-wider">
                                    <th class="px-6 py-3">设备ID (device_id)</th>
                                    <th class="px-6 py-3">设备名称 (device_name)</th>
                                    <th class="px-6 py-3">协议类型 (proto)</th>
                                    <th class="px-6 py-3">取流地址 (rtsp)</th>
                                </tr>
                            </thead>
                            <tbody class="divide-y divide-slate-800 text-sm">
                                {#each parseJson(currentDetailDevice.channels) as ch}
                                    <tr class="hover:bg-slate-900/60 transition-colors">
                                        <td class="px-6 py-4 font-mono text-slate-400">{ch.device_id}</td>
                                        <td class="px-6 py-4 font-medium text-slate-100">{ch.device_name}</td>
                                        <td class="px-6 py-4">
                                            <span class="px-2 py-0.5 bg-indigo-500/10 text-indigo-400 rounded text-[10px] font-bold">{ch.proto}</span>
                                        </td>
                                        <td class="px-6 py-4 font-mono text-xs text-slate-400 break-all">{ch.rtsp}</td>
                                    </tr>
                                {:else}
                                    <tr><td colspan="4" class="px-6 py-10 text-center text-slate-500">暂无通道数据</td></tr>
                                {/each}
                            </tbody>
                        </table>
                    </div>
                </section>

                <!-- Task Table -->
                <section>
                    <div class="flex items-center mb-4">
                        <div class="p-2 bg-emerald-500/10 text-emerald-400 rounded-lg mr-3"><i class="fa-solid fa-clipboard-list text-base"></i></div>
                        <h4 class="text-lg font-semibold text-slate-100">任务布控列表 ({parseJson(currentDetailDevice.device_tasks).length})</h4>
                    </div>
                    <div class="bg-slate-950 border border-slate-800 rounded-xl overflow-hidden">
                        <table class="w-full text-left border-collapse">
                            <thead>
                                <tr class="bg-slate-900/60 border-b border-slate-800 text-slate-500 text-[11px] font-semibold uppercase tracking-wider">
                                    <th class="px-6 py-3">任务ID (task_id)</th>
                                    <th class="px-6 py-3">任务名称 (task_name)</th>
                                    <th class="px-6 py-3">关联通道 (device_name)</th>
                                    <th class="px-6 py-3">智能体算法 (agent_id)</th>
                                </tr>
                            </thead>
                            <tbody class="divide-y divide-slate-800 text-sm">
                                {#each parseJson(currentDetailDevice.device_tasks) as t}
                                    <tr class="hover:bg-slate-900/60 transition-colors">
                                        <td class="px-6 py-4 font-mono text-slate-400">{t.task_id}</td>
                                        <td class="px-6 py-4 font-medium text-slate-100">{t.task_name}</td>
                                        <td class="px-6 py-4 text-slate-400">{t.device_name}</td>
                                        <td class="px-6 py-4 font-mono text-indigo-400 uppercase text-xs">{t.agent_id}</td>
                                    </tr>
                                {:else}
                                    <tr><td colspan="4" class="px-6 py-10 text-center text-slate-500">暂无布控任务数据</td></tr>
                                {/each}
                            </tbody>
                        </table>
                    </div>
                </section>
            </div>

            <div class="px-8 py-5 border-t border-slate-800 bg-slate-900/40 flex justify-end items-center space-x-4">
                {#if isFetching}
                    <div class="flex items-center text-indigo-400 text-sm font-medium animate-pulse">
                        <i class="fa-solid fa-spinner text-sm mr-2 animate-spin"></i> 正在从设备同步最新数据...
                    </div>
                {/if}
                <button on:click={() => isFetchDetailModalOpen = false} class="bg-indigo-600 hover:bg-indigo-700 text-white rounded-xl font-bold px-8 py-2.5 shadow-lg shadow-indigo-500/20">完成</button>
            </div>
        </div>
    </div>
{/if}
