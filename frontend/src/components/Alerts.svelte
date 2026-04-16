<script>
    import { onMount } from 'svelte';
    import Icon from '../lib/Icon.svelte';
    import { API_BASE } from '../lib/config.js';

    function getStartOfDay() {
        const d = new Date();
        d.setHours(0, 0, 0, 0);
        // Format to YYYY-MM-DDTHH:mm:ss for datetime-local input
        return new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 19);
    }

    function getEndOfDay() {
        const d = new Date();
        d.setHours(23, 59, 59, 999);
        return new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 19);
    }

    let displayedAlerts = [];
    let alertFilters = { startDate: getStartOfDay(), endDate: getEndOfDay(), deviceName: '', alertType: '' };
    let aiLoadingIds = {};
    const alertTypes = ['区域入侵', '越界检测', '车辆违停', '人员聚集', '烟火检测'];

    // 分页状态
    let currentPage = 1;
    const itemsPerPage = 12;
    $: totalPages = Math.ceil(displayedAlerts.length / itemsPerPage);
    $: paginatedAlerts = displayedAlerts.slice((currentPage - 1) * itemsPerPage, currentPage * itemsPerPage);

    // 图片查看器状态
    let viewerImage = null;
    function openViewer(url) {
        viewerImage = url;
    }
    function closeViewer() {
        viewerImage = null;
    }

    onMount(async () => {
        await fetchAlerts();
    });

    async function fetchAlerts() {
        try {
            const params = new URLSearchParams();
            if (alertFilters.deviceName) params.append('deviceName', alertFilters.deviceName);
            if (alertFilters.alertType) params.append('alertType', alertFilters.alertType);
            if (alertFilters.startDate) params.append('startDate', alertFilters.startDate);
            if (alertFilters.endDate) params.append('endDate', alertFilters.endDate);

            const res = await fetch(`${API_BASE}/alerts?${params.toString()}`);
            if (res.ok) {
                displayedAlerts = await res.json();
                currentPage = 1;
            }
        } catch (e) { console.error(e); }
    }

    function handleResetAlertFilters() {
        alertFilters = { startDate: getStartOfDay(), endDate: getEndOfDay(), deviceName: '', alertType: '' };
        fetchAlerts();
    }

    async function handleAIAnalysis(alert) {
        aiLoadingIds[alert.id] = true;
        try {
            const res = await fetch(`${API_BASE}/ai/analyze`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ alert_id: alert.id })
            });
            const data = await res.json();
            alert.remark = data.remark;
            displayedAlerts = [...displayedAlerts];
        } finally {
            delete aiLoadingIds[alert.id];
            aiLoadingIds = { ...aiLoadingIds };
        }
    }

    function getAlertStyle(type) {
        switch (type) {
            case '烟火检测':
            case '区域入侵': return 'bg-red-100 text-red-700';
            case '越界检测': return 'bg-orange-100 text-orange-700';
            default: return 'bg-yellow-100 text-yellow-700';
        }
    }
</script>

<div class="flex flex-col h-full space-y-6">
    <div class="bg-white rounded-xl shadow-sm border border-gray-200 p-5 shrink-0">
        <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-5 gap-4 items-end">
            <div class="flex flex-col space-y-1">
                <label class="text-xs text-gray-500 font-medium" for="start">开始时间</label>
                <input type="datetime-local" step="1" id="start" bind:value={alertFilters.startDate} class="px-3 h-[38px] border border-gray-300 rounded-lg text-sm outline-none focus:ring-2 focus:ring-blue-500 w-full box-border" />
            </div>
            <div class="flex flex-col space-y-1">
                <label class="text-xs text-gray-500 font-medium" for="end">结束时间</label>
                <input type="datetime-local" step="1" id="end" bind:value={alertFilters.endDate} class="px-3 h-[38px] border border-gray-300 rounded-lg text-sm outline-none focus:ring-2 focus:ring-blue-500 w-full box-border" />
            </div>
            <div class="flex flex-col space-y-1">
                <label class="text-xs text-gray-500 font-medium" for="devName">设备名称</label>
                <input type="text" id="devName" placeholder="输入设备名称" bind:value={alertFilters.deviceName} class="px-3 h-[38px] border border-gray-300 rounded-lg text-sm outline-none focus:ring-2 focus:ring-blue-500 w-full box-border" />
            </div>
            <div class="flex flex-col space-y-1">
                <label class="text-xs text-gray-500 font-medium" for="type">预警类型</label>
                <select id="type" bind:value={alertFilters.alertType} class="px-3 h-[38px] border border-gray-300 rounded-lg text-sm outline-none focus:ring-2 focus:ring-blue-500 bg-white w-full box-border">
                    <option value="">全部类型</option>
                    {#each alertTypes as t}<option value={t}>{t}</option>{/each}
                </select>
            </div>
            <div class="flex space-x-3 lg:justify-end">
                <button on:click={handleResetAlertFilters} class="flex items-center justify-center px-4 h-[38px] bg-gray-100 hover:bg-gray-200 text-gray-700 rounded-lg text-sm font-medium transition-colors flex-1 lg:flex-none box-border">
                    <Icon name="RefreshCcw" className="w-4 h-4 mr-2" /> 重置
                </button>
                <button on:click={fetchAlerts} class="flex items-center justify-center px-4 h-[38px] bg-blue-600 hover:bg-blue-700 text-white rounded-lg shadow-sm text-sm font-medium transition-colors flex-1 lg:flex-none box-border">
                    <Icon name="Search" className="w-4 h-4 mr-2" /> 检索
                </button>
            </div>
        </div>
    </div>

    <div class="flex-1 overflow-auto pb-4">
        {#if displayedAlerts.length > 0}
            <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-6">
                {#each paginatedAlerts as alert}
                    <div class="bg-white rounded-xl overflow-hidden shadow-sm border flex flex-col">
                        <div class="relative aspect-video bg-gray-100 flex items-center justify-center border-b overflow-hidden group">
                            {#if alert.imageUrl}
                                <img src="{API_BASE}{alert.imageUrl}" alt="抓拍图片" class="w-full h-full object-cover object-center cursor-zoom-in transition-transform duration-300 group-hover:scale-105" on:dblclick={() => openViewer(`${API_BASE}${alert.imageUrl}`)} title="双击查看大图" />
                            {:else}
                                <div class="flex flex-col items-center text-gray-400">
                                    <Icon name="Camera" className="w-10 h-10 mb-2 opacity-50" />
                                    <span class="text-xs">无实时抓拍图像</span>
                                </div>
                            {/if}
                            <div class="absolute top-3 right-3 px-2 py-1 rounded text-xs font-bold {getAlertStyle(alert.alertType)}">{alert.alertType}</div>
                        </div>
                        <div class="p-4 flex flex-col flex-1">
                            <h3 class="text-sm font-bold text-gray-800 mb-2 truncate" title={alert.deviceName}>{alert.deviceName}</h3>
                            <div class="flex items-center text-xs text-gray-500 mb-3"><Icon name="Clock" className="w-3.5 h-3.5 mr-1.5" />{alert.time}</div>
                            <div class="mt-auto pt-3 border-t">
                                <div class="flex justify-between items-start mb-1">
                                    <span class="text-xs font-medium text-gray-500">备注与建议：</span>
                                    <button on:click={() => handleAIAnalysis(alert)} disabled={aiLoadingIds[alert.id]} class="text-xs flex items-center text-blue-600 bg-blue-50 px-2 py-1 rounded-md disabled:opacity-50">
                                        <Icon name={aiLoadingIds[alert.id] ? "RefreshCcw" : "Sparkles"} className="w-3 h-3 mr-1 {aiLoadingIds[alert.id] ? 'animate-spin' : ''}" />
                                        {aiLoadingIds[alert.id] ? 'AI思考中' : 'AI 分析'}
                                    </button>
                                </div>
                                <p class="text-sm text-gray-700 min-h-[40px] bg-gray-50 p-2 rounded-md cursor-default" title={alert.remark || ''}>
                                    {alert.remark ? (alert.remark.length > 24 ? alert.remark.slice(0, 24) + '...' : alert.remark) : ''}
                                </p>
                            </div>
                        </div>
                    </div>
                {/each}
            </div>
            
            {#if totalPages > 1}
            <div class="flex justify-center items-center space-x-4 mt-8 pb-4">
                <button 
                    disabled={currentPage === 1} 
                    on:click={() => currentPage--} 
                    class="px-4 py-2 rounded-lg border bg-white hover:bg-gray-50 disabled:opacity-50 disabled:cursor-not-allowed transition-colors text-sm font-medium text-gray-700 flex items-center shadow-sm"
                >
                    <Icon name="ChevronLeft" className="w-4 h-4 mr-1" /> 上一页
                </button>
                <span class="text-sm font-medium text-gray-600">第 {currentPage} 页 / 共 {totalPages} 页</span>
                <button 
                    disabled={currentPage === totalPages} 
                    on:click={() => currentPage++} 
                    class="px-4 py-2 rounded-lg border bg-white hover:bg-gray-50 disabled:opacity-50 disabled:cursor-not-allowed transition-colors text-sm font-medium text-gray-700 flex items-center shadow-sm"
                >
                    下一页 <Icon name="ChevronRight" className="w-4 h-4 ml-1" />
                </button>
            </div>
            {/if}
        {:else}
            <div class="h-full flex flex-col items-center justify-center text-gray-400"><Icon name="Search" className="w-16 h-16 mb-4 opacity-30" /><p>未检索到相关的预警抓拍数据</p></div>
        {/if}
    </div>
</div>

{#if viewerImage}
<!-- svelte-ignore a11y-click-events-have-key-events -->
<!-- svelte-ignore a11y-no-static-element-interactions -->
<div class="fixed inset-0 z-[100] flex items-center justify-center bg-black bg-opacity-80 backdrop-blur-sm" on:click={closeViewer}>
    <div class="relative max-w-[90vw] max-h-[90vh]">
        <img src={viewerImage} alt="大图" class="max-w-full max-h-[90vh] object-contain rounded-lg shadow-2xl" on:click|stopPropagation />
        <button class="absolute -top-12 right-0 text-white/70 hover:text-white transition-colors" on:click={closeViewer} title="关闭">
            <Icon name="X" className="w-8 h-8" />
        </button>
    </div>
</div>
{/if}