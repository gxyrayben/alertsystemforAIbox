<script>
    import { onMount } from 'svelte';
    import { API_BASE, apiGet, apiPost } from '../lib/api.js';

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

            displayedAlerts = await apiGet(`/alerts?${params.toString()}`);
            currentPage = 1;
        } catch (e) { console.error(e); }
    }

    function handleResetAlertFilters() {
        alertFilters = { startDate: getStartOfDay(), endDate: getEndOfDay(), deviceName: '', alertType: '' };
        fetchAlerts();
    }

    async function handleAIAnalysis(alert) {
        aiLoadingIds[alert.id] = true;
        try {
            const data = await apiPost('/ai/analyze', { alert_id: alert.id });
            alert.remark = data.remark;
            displayedAlerts = [...displayedAlerts];
        } catch (e) {
            console.error(e);
        } finally {
            delete aiLoadingIds[alert.id];
            aiLoadingIds = { ...aiLoadingIds };
        }
    }

    function getAlertStyle(type) {
        switch (type) {
            case '烟火检测':
            case '区域入侵': return 'bg-rose-500/10 text-rose-400';
            case '越界检测': return 'bg-amber-500/10 text-amber-400';
            default: return 'bg-amber-500/10 text-amber-400';
        }
    }
</script>

<div class="flex flex-col h-full space-y-6">
    <div class="bg-slate-950 border border-slate-800 rounded-2xl p-5 shrink-0">
        <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-5 gap-4 items-end">
            <div class="flex flex-col space-y-1">
                <label class="text-xs text-slate-400 font-medium" for="start">开始时间</label>
                <input type="datetime-local" step="1" id="start" bind:value={alertFilters.startDate} class="bg-slate-900 border border-slate-800 text-slate-100 rounded-xl px-3 h-[38px] text-sm placeholder-slate-500 outline-none focus:border-indigo-500 w-full box-border" />
            </div>
            <div class="flex flex-col space-y-1">
                <label class="text-xs text-slate-400 font-medium" for="end">结束时间</label>
                <input type="datetime-local" step="1" id="end" bind:value={alertFilters.endDate} class="bg-slate-900 border border-slate-800 text-slate-100 rounded-xl px-3 h-[38px] text-sm placeholder-slate-500 outline-none focus:border-indigo-500 w-full box-border" />
            </div>
            <div class="flex flex-col space-y-1">
                <label class="text-xs text-slate-400 font-medium" for="devName">设备名称</label>
                <input type="text" id="devName" placeholder="输入设备名称" bind:value={alertFilters.deviceName} class="bg-slate-900 border border-slate-800 text-slate-100 rounded-xl px-3 h-[38px] text-sm placeholder-slate-500 outline-none focus:border-indigo-500 w-full box-border" />
            </div>
            <div class="flex flex-col space-y-1">
                <label class="text-xs text-slate-400 font-medium" for="type">预警类型</label>
                <select id="type" bind:value={alertFilters.alertType} class="bg-slate-900 border border-slate-800 text-slate-100 rounded-xl px-3 h-[38px] text-sm placeholder-slate-500 outline-none focus:border-indigo-500 w-full box-border">
                    <option value="">全部类型</option>
                    {#each alertTypes as t}<option value={t}>{t}</option>{/each}
                </select>
            </div>
            <div class="flex space-x-3 lg:justify-end">
                <button on:click={handleResetAlertFilters} class="bg-slate-900 hover:bg-slate-800 text-slate-300 border border-slate-800 rounded-xl h-[38px] px-4 text-sm font-medium flex items-center justify-center flex-1 lg:flex-none box-border">
                    <i class="fa-solid fa-arrows-rotate text-sm mr-2"></i> 重置
                </button>
                <button on:click={fetchAlerts} class="bg-indigo-600 hover:bg-indigo-700 text-white rounded-xl h-[38px] px-4 text-sm font-bold shadow-sm flex items-center justify-center flex-1 lg:flex-none box-border">
                    <i class="fa-solid fa-magnifying-glass text-sm mr-2"></i> 检索
                </button>
            </div>
        </div>
    </div>

    <div class="flex-1 overflow-auto pb-4">
        {#if displayedAlerts.length > 0}
            <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-6">
                {#each paginatedAlerts as alert}
                    <div class="bg-slate-950 border border-slate-800 rounded-2xl overflow-hidden flex flex-col">
                        <div class="relative aspect-video bg-slate-900 flex items-center justify-center border-b border-slate-800 overflow-hidden group">
                            {#if alert.imageUrl}
                                <img src="{API_BASE}{alert.imageUrl}" alt="抓拍图片" class="w-full h-full object-cover object-center cursor-zoom-in transition-transform duration-300 group-hover:scale-105" on:dblclick={() => openViewer(`${API_BASE}${alert.imageUrl}`)} title="双击查看大图" />
                            {:else}
                                <div class="flex flex-col items-center text-slate-500">
                                    <i class="fa-solid fa-camera text-3xl mb-2 opacity-50"></i>
                                    <span class="text-xs">无实时抓拍图像</span>
                                </div>
                            {/if}
                            <div class="absolute top-3 right-3 px-2 py-1 rounded text-xs font-bold {getAlertStyle(alert.alertType)}">{alert.alertType}</div>
                        </div>
                        <div class="p-4 flex flex-col flex-1">
                            <h3 class="text-sm font-bold text-slate-100 mb-2 truncate" title={alert.deviceName}>{alert.deviceName}</h3>
                            <div class="flex items-center text-xs text-slate-500 mb-3"><i class="fa-solid fa-clock text-xs mr-1.5"></i>{alert.time}</div>
                            <div class="mt-auto pt-3 border-t border-slate-800">
                                <div class="flex justify-between items-start mb-1">
                                    <span class="text-xs font-medium text-slate-500">备注与建议：</span>
                                    <button on:click={() => handleAIAnalysis(alert)} disabled={aiLoadingIds[alert.id]} class="text-xs flex items-center text-indigo-400 bg-indigo-500/10 hover:bg-indigo-500/20 px-2 py-1 rounded-lg disabled:opacity-50">
                                        <i class="fa-solid {aiLoadingIds[alert.id] ? 'fa-arrows-rotate animate-spin' : 'fa-wand-magic-sparkles'} text-[10px] mr-1"></i>
                                        {aiLoadingIds[alert.id] ? 'AI思考中' : 'AI 分析'}
                                    </button>
                                </div>
                                <p class="text-sm text-slate-300 min-h-[40px] bg-slate-900 border border-slate-800 p-2 rounded-lg cursor-default" title={alert.remark || ''}>
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
                    class="bg-slate-900 hover:bg-slate-800 border border-slate-800 text-slate-300 rounded-xl px-4 py-2 text-sm font-medium disabled:opacity-50 disabled:cursor-not-allowed flex items-center"
                >
                    <i class="fa-solid fa-chevron-left text-sm mr-1"></i> 上一页
                </button>
                <span class="text-sm font-medium text-slate-400">第 {currentPage} 页 / 共 {totalPages} 页</span>
                <button
                    disabled={currentPage === totalPages}
                    on:click={() => currentPage++}
                    class="bg-slate-900 hover:bg-slate-800 border border-slate-800 text-slate-300 rounded-xl px-4 py-2 text-sm font-medium disabled:opacity-50 disabled:cursor-not-allowed flex items-center"
                >
                    下一页 <i class="fa-solid fa-chevron-right text-sm ml-1"></i>
                </button>
            </div>
            {/if}
        {:else}
            <div class="h-full flex flex-col items-center justify-center text-slate-500"><i class="fa-solid fa-magnifying-glass text-5xl mb-4 opacity-30"></i><p>未检索到相关的预警抓拍数据</p></div>
        {/if}
    </div>
</div>

{#if viewerImage}
<!-- svelte-ignore a11y-click-events-have-key-events -->
<!-- svelte-ignore a11y-no-static-element-interactions -->
<div class="fixed inset-0 z-[100] flex items-center justify-center bg-black/80 backdrop-blur-sm" on:click={closeViewer}>
    <div class="relative max-w-[90vw] max-h-[90vh]">
        <img src={viewerImage} alt="大图" class="max-w-full max-h-[90vh] object-contain rounded-lg shadow-2xl" on:click|stopPropagation />
        <button class="absolute -top-12 right-0 text-white/70 hover:text-white transition-colors" on:click={closeViewer} title="关闭">
            <i class="fa-solid fa-xmark text-2xl"></i>
        </button>
    </div>
</div>
{/if}
