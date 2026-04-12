<script>
    import { onMount } from 'svelte';
    import Icon from '../lib/Icon.svelte';
    import { API_BASE } from '../lib/config.js';

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

    onMount(async () => {
        await fetchDevices();
    });

    async function fetchDevices() {
        try {
            const res = await fetch(`${API_BASE}/devices`);
            if (res.ok) devices = await res.json();
        } catch (e) { console.error(e); }
    }

    async function handleDeviceSave() {
        if (!deviceFormData.device_id || !deviceFormData.name || !deviceFormData.ip) return alert('设备ID、名称和IP不能为空！');
        
        let url = `${API_BASE}/devices`;
        let method = 'POST';
        
        if (editingDeviceId) {
            url = `${API_BASE}/devices/${editingDeviceId}`;
            method = 'PUT';
        }

        try {
            const res = await fetch(url, {
                method,
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(deviceFormData)
            });

            if (res.ok) {
                await fetchDevices();
                isDeviceModalOpen = false;
            } else {
                const err = await res.json();
                alert(`保存失败: ${err.detail || '未知错误'}`);
            }
        } catch (e) { console.error(e); }
    }

    async function handleDeviceDelete(id) {
        if (confirm('确定删除该设备吗？')) {
            try {
                const res = await fetch(`${API_BASE}/devices/${id}`, { method: 'DELETE' });
                if (res.ok) await fetchDevices();
            } catch (e) { console.error(e); }
        }
    }

    async function handleFetchDetail(device) {
        isFetching = true;
        currentDetailDevice = device;
        isFetchDetailModalOpen = true;
        
        try {
            const res = await fetch(`${API_BASE}/devices/${device.id}/fetch`, { method: 'POST' });
            if (res.ok) {
                const updatedDevice = await res.json();
                currentDetailDevice = updatedDevice;
                // Update in list too
                const idx = devices.findIndex(d => d.id === device.id);
                if (idx !== -1) devices[idx] = updatedDevice;
            } else {
                alert("获取设备信息失败，请检查设备连通性。");
            }
        } catch (e) {
            console.error(e);
            alert("请求网络错误");
        } finally {
            isFetching = false;
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
            case '在线': return 'bg-green-100 text-green-700 border-green-200';
            case '异常': return 'bg-red-100 text-red-700 border-red-200';
            case '离线': default: return 'bg-gray-100 text-gray-700 border-gray-200';
        }
    }

    function parseJson(str) {
        try { return JSON.parse(str || '[]'); } catch(e) { return []; }
    }
</script>

<div class="bg-white rounded-xl shadow-sm border border-gray-200 flex flex-col h-full">
    <div class="px-6 py-5 border-b border-gray-200 flex justify-between items-center">
        <div class="text-sm text-gray-500">共找到 <span class="font-bold text-gray-900">{devices.length}</span> 个设备</div>
        <button on:click={() => openDeviceModal()} class="flex items-center px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-lg shadow-sm text-sm font-medium transition-colors">
            <Icon name="Plus" className="w-4 h-4 mr-2" /> 添加设备
        </button>
    </div>
    <div class="flex-1 overflow-auto">
        <table class="w-full text-left border-collapse">
            <thead class="bg-gray-50 sticky top-0 z-10">
                <tr>
                    <th class="px-6 py-4 text-xs font-semibold text-gray-500 uppercase tracking-wider border-b border-gray-200">业务 ID (匹配协议)</th>
                    <th class="px-6 py-4 text-xs font-semibold text-gray-500 uppercase tracking-wider border-b border-gray-200">设备名称</th>
                    <th class="px-6 py-4 text-xs font-semibold text-gray-500 uppercase tracking-wider border-b border-gray-200">IP地址/端口</th>
                    <th class="px-6 py-4 text-xs font-semibold text-gray-500 uppercase tracking-wider border-b border-gray-200">状态</th>
                    <th class="px-6 py-4 text-xs font-semibold text-gray-500 uppercase tracking-wider border-b border-gray-200 text-center">操作</th>
                </tr>
            </thead>
            <tbody class="divide-y divide-gray-200 bg-white">
                {#each currentDevices as device}
                    <tr class="hover:bg-blue-50/50 transition-colors">
                        <td class="px-6 py-4 whitespace-nowrap text-sm font-mono text-blue-600">{device.device_id}</td>
                        <td class="px-6 py-4 whitespace-nowrap text-sm font-medium text-gray-900">{device.name}</td>
                        <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-600 font-mono">{device.ip}:{device.port}</td>
                        <td class="px-6 py-4 whitespace-nowrap text-sm">
                            <span class="px-2.5 py-1 inline-flex text-xs leading-5 font-semibold rounded-full border {getStatusStyle(device.status)}">{device.status}</span>
                        </td>
                        <td class="px-6 py-4 whitespace-nowrap text-sm font-medium text-center flex items-center justify-center space-x-1">
                            <button on:click={() => handleFetchDetail(device)} class="text-green-600 hover:text-green-900 p-1 rounded hover:bg-green-100 transition-colors" title="获取详情">
                                <Icon name="RefreshCcw" className="w-4 h-4" />
                            </button>
                            <button on:click={() => openDeviceModal(device)} class="text-blue-600 hover:text-blue-900 p-1 rounded hover:bg-blue-100 transition-colors" title="编辑">
                                <Icon name="Edit" className="w-4 h-4" />
                            </button>
                            <button on:click={() => handleDeviceDelete(device.id)} class="text-red-600 hover:text-red-900 p-1 rounded hover:bg-red-100 transition-colors" title="删除">
                                <Icon name="Trash2" className="w-4 h-4" />
                            </button>
                        </td>
                    </tr>
                {/each}
            </tbody>
        </table>
    </div>
    <div class="px-6 py-4 border-t border-gray-200 bg-gray-50 flex items-center justify-between rounded-b-xl">
        <span class="text-sm text-gray-500">第 <span class="font-medium text-gray-900">{devicePage}</span> 页 / 共 <span class="font-medium text-gray-900">{totalDevicePages || 1}</span> 页</span>
        <div class="flex space-x-2">
            <button on:click={() => devicePage = Math.max(1, devicePage - 1)} disabled={devicePage === 1} class="p-2 border rounded-md bg-white disabled:opacity-50 transition-colors hover:bg-gray-100"><Icon name="ChevronLeft" className="w-4 h-4" /></button>
            <button on:click={() => devicePage = Math.min(totalDevicePages, devicePage + 1)} disabled={devicePage === totalDevicePages} class="p-2 border rounded-md bg-white disabled:opacity-50 transition-colors hover:bg-gray-100"><Icon name="ChevronRight" className="w-4 h-4" /></button>
        </div>
    </div>
</div>

<!-- Add/Edit Device Modal -->
{#if isDeviceModalOpen}
    <div class="fixed inset-0 z-50 flex items-center justify-center bg-black bg-opacity-40 backdrop-blur-sm">
        <div class="bg-white rounded-xl shadow-2xl w-full max-w-md">
            <div class="px-6 py-4 border-b flex justify-between items-center">
                <h3 class="text-lg font-semibold">{editingDeviceId ? '编辑设备' : '添加设备'}</h3>
                <button on:click={() => isDeviceModalOpen = false} class="text-gray-400 hover:text-gray-600"><Icon name="X" className="w-5 h-5" /></button>
            </div>
            <div class="px-6 py-5 space-y-4">
                <div>
                    <label class="block text-sm font-medium text-gray-700 mb-1">设备业务 ID <span class="text-red-500">*</span></label>
                    <input type="text" placeholder="例如：DEV-001" bind:value={deviceFormData.device_id} class="w-full px-4 py-2 border rounded-lg outline-none focus:ring-2 focus:ring-blue-500" />
                </div>
                <div>
                    <label class="block text-sm font-medium text-gray-700 mb-1">设备名称 <span class="text-red-500">*</span></label>
                    <input type="text" placeholder="例如：东大门摄像头" bind:value={deviceFormData.name} class="w-full px-4 py-2 border rounded-lg outline-none focus:ring-2 focus:ring-blue-500" />
                </div>
                <div class="flex space-x-4">
                    <div class="flex-1">
                        <label class="block text-sm font-medium text-gray-700 mb-1">IP 地址 <span class="text-red-500">*</span></label>
                        <input type="text" placeholder="192.168.1.10" bind:value={deviceFormData.ip} class="w-full px-4 py-2 border rounded-lg outline-none focus:ring-2 focus:ring-blue-500" />
                    </div>
                    <div class="w-32">
                        <label class="block text-sm font-medium text-gray-700 mb-1">端口</label>
                        <input type="text" placeholder="80" bind:value={deviceFormData.port} class="w-full px-4 py-2 border rounded-lg outline-none focus:ring-2 focus:ring-blue-500" />
                    </div>
                </div>
                <div>
                    <label class="block text-sm font-medium text-gray-700 mb-1">用户名</label>
                    <input type="text" placeholder="admin" bind:value={deviceFormData.username} class="w-full px-4 py-2 border rounded-lg outline-none focus:ring-2 focus:ring-blue-500" />
                </div>
                <div>
                    <label class="block text-sm font-medium text-gray-700 mb-1">密码</label>
                    <input type="password" placeholder="请输入密码" bind:value={deviceFormData.password} class="w-full px-4 py-2 border rounded-lg outline-none focus:ring-2 focus:ring-blue-500" />
                </div>
            </div>
            <div class="px-6 py-4 border-t flex justify-end space-x-3 bg-gray-50">
                <button on:click={() => isDeviceModalOpen = false} class="px-4 py-2 border rounded-lg bg-white">取消</button>
                <button on:click={handleDeviceSave} class="px-4 py-2 bg-blue-600 text-white rounded-lg shadow-sm hover:bg-blue-700">确定</button>
            </div>
        </div>
    </div>
{/if}

<!-- Fetch Details Modal -->
{#if isFetchDetailModalOpen && currentDetailDevice}
    <div class="fixed inset-0 z-50 flex items-center justify-center bg-black bg-opacity-40 backdrop-blur-sm p-4">
        <div class="bg-white rounded-2xl shadow-2xl w-full max-w-5xl max-h-[90vh] flex flex-col overflow-hidden">
            <div class="px-8 py-5 border-b flex justify-between items-center bg-slate-50">
                <h3 class="text-xl font-bold text-slate-800">设备详情获取 - {currentDetailDevice.name}</h3>
                <button on:click={() => isFetchDetailModalOpen = false} class="text-slate-400 hover:text-slate-600 p-1 rounded-full hover:bg-slate-200 transition-colors">
                    <Icon name="X" className="w-6 h-6" />
                </button>
            </div>
            
            <div class="flex-1 overflow-y-auto p-8 space-y-10">
                <!-- Channel Table -->
                <section>
                    <div class="flex items-center mb-4">
                        <div class="p-2 bg-blue-100 text-blue-600 rounded-lg mr-3"><Icon name="Camera" className="w-5 h-5" /></div>
                        <h4 class="text-lg font-semibold text-slate-800">设备通道列表 ({parseJson(currentDetailDevice.channels).length})</h4>
                    </div>
                    <div class="border rounded-xl overflow-hidden shadow-sm">
                        <table class="w-full text-left border-collapse">
                            <thead>
                                <tr class="bg-slate-50 border-b text-slate-500 text-xs font-bold uppercase">
                                    <th class="px-6 py-3">设备ID (device_id)</th>
                                    <th class="px-6 py-3">设备名称 (device_name)</th>
                                    <th class="px-6 py-3">协议类型 (proto)</th>
                                    <th class="px-6 py-3">取流地址 (rtsp)</th>
                                </tr>
                            </thead>
                            <tbody class="divide-y text-sm">
                                {#each parseJson(currentDetailDevice.channels) as ch}
                                    <tr class="hover:bg-slate-50 transition-colors">
                                        <td class="px-6 py-4 font-mono text-slate-500">{ch.device_id}</td>
                                        <td class="px-6 py-4 font-bold text-slate-800">{ch.device_name}</td>
                                        <td class="px-6 py-4">
                                            <span class="px-2 py-0.5 bg-blue-100 text-blue-700 rounded text-[10px] font-bold">{ch.proto}</span>
                                        </td>
                                        <td class="px-6 py-4 font-mono text-xs text-slate-500 break-all">{ch.rtsp}</td>
                                    </tr>
                                {:else}
                                    <tr><td colspan="4" class="px-6 py-10 text-center text-slate-400">暂无通道数据</td></tr>
                                {/each}
                            </tbody>
                        </table>
                    </div>
                </section>

                <!-- Task Table -->
                <section>
                    <div class="flex items-center mb-4">
                        <div class="p-2 bg-green-100 text-green-600 rounded-lg mr-3"><Icon name="ClipboardList" className="w-5 h-5" /></div>
                        <h4 class="text-lg font-semibold text-slate-800">任务布控列表 ({parseJson(currentDetailDevice.device_tasks).length})</h4>
                    </div>
                    <div class="border rounded-xl overflow-hidden shadow-sm">
                        <table class="w-full text-left border-collapse">
                            <thead>
                                <tr class="bg-slate-50 border-b text-slate-500 text-xs font-bold uppercase">
                                    <th class="px-6 py-3">任务ID (task_id)</th>
                                    <th class="px-6 py-3">任务名称 (task_name)</th>
                                    <th class="px-6 py-3">关联通道 (device_name)</th>
                                    <th class="px-6 py-3">智能体算法 (agent_id)</th>
                                </tr>
                            </thead>
                            <tbody class="divide-y text-sm">
                                {#each parseJson(currentDetailDevice.device_tasks) as t}
                                    <tr class="hover:bg-slate-50 transition-colors">
                                        <td class="px-6 py-4 font-mono text-slate-500">{t.task_id}</td>
                                        <td class="px-6 py-4 font-bold text-slate-800">{t.task_name}</td>
                                        <td class="px-6 py-4 text-slate-600">{t.device_name}</td>
                                        <td class="px-6 py-4 font-mono text-purple-600 uppercase text-xs">{t.agent_id}</td>
                                    </tr>
                                {:else}
                                    <tr><td colspan="4" class="px-6 py-10 text-center text-slate-400">暂无布控任务数据</td></tr>
                                {/each}
                            </tbody>
                        </table>
                    </div>
                </section>
            </div>
            
            <div class="px-8 py-5 border-t bg-slate-50 flex justify-end items-center space-x-4">
                {#if isFetching}
                    <div class="flex items-center text-blue-600 text-sm font-medium animate-pulse">
                        <Icon name="Loader2" className="w-4 h-4 mr-2 animate-spin" /> 正在从设备同步最新数据...
                    </div>
                {/if}
                <button on:click={() => isFetchDetailModalOpen = false} class="px-8 py-2.5 bg-blue-600 hover:bg-blue-700 text-white rounded-xl font-bold shadow-lg shadow-blue-200 transition-all active:scale-95">完成</button>
            </div>
        </div>
    </div>
{/if}
