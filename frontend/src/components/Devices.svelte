<script>
    import { onMount } from 'svelte';
    import Icon from '../lib/Icon.svelte';
    import { API_BASE } from '../lib/config.js';

    let devices = [];
    let isDeviceModalOpen = false;
    let editingDeviceId = null;
    let deviceFormData = { device_id: '', name: '', ip: '', port: '', username: '', password: '' };
    let devicePage = 1;
    const itemsPerPage = 15;

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

    function openDeviceModal(device = null) {
        if (device) {
            deviceFormData = { ...device };
            editingDeviceId = device.id;
        } else {
            deviceFormData = { device_id: '', name: '', ip: '', port: '', username: '', password: '' };
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
                        <td class="px-6 py-4 whitespace-nowrap text-sm font-medium text-center">
                            <button on:click={() => openDeviceModal(device)} class="text-blue-600 hover:text-blue-900 mx-2 p-1 rounded hover:bg-blue-100 transition-colors" title="编辑"><Icon name="Edit" className="w-4 h-4" /></button>
                            <button on:click={() => handleDeviceDelete(device.id)} class="text-red-600 hover:text-red-900 mx-2 p-1 rounded hover:bg-red-100 transition-colors" title="删除"><Icon name="Trash2" className="w-4 h-4" /></button>
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
                <button on:click={() => isDeviceModalOpen = false} class="px-4 py-2 border rounded-lg">取消</button>
                <button on:click={handleDeviceSave} class="px-4 py-2 bg-blue-600 text-white rounded-lg">确定</button>
            </div>
        </div>
    </div>
{/if}
