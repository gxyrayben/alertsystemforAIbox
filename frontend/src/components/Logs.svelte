<script>
    import { onMount } from 'svelte';
    import { API_BASE } from '../lib/config.js';

    let logs = [];
    let total = 0;
    let page = 1;
    let size = 15;
    let isLoading = false;

    $: totalPages = Math.ceil(total / size) || 1;
    $: startItem = (page - 1) * size + 1;
    $: endItem = Math.min(page * size, total);

    onMount(() => {
        fetchLogs();
    });

    async function fetchLogs() {
        isLoading = true;
        try {
            const res = await fetch(`${API_BASE}/logs?page=${page}&size=${size}`);
            if (res.ok) {
                const data = await res.json();
                logs = data.items;
                total = data.total;
            }
        } catch (e) {
            console.error(e);
        } finally {
            isLoading = false;
        }
    }

    function prevPage() {
        if (page > 1) {
            page--;
            fetchLogs();
        }
    }

    function nextPage() {
        if (page < totalPages) {
            page++;
            fetchLogs();
        }
    }

    function exportToCsv() {
        if (logs.length === 0) return;

        const headers = ['日志ID', '操作设备', '调用接口', '核心参数', '调用时间', '调用结果'];
        const csvRows = [headers.join(',')];

        logs.forEach(log => {
            const row = [
                log.log_id,
                log.device_name,
                log.api_path,
                // Escape quotes for CSV
                `"${log.parameters.replace(/"/g, '""')}"`,
                formatDate(log.timestamp),
                log.result
            ];
            csvRows.push(row.join(','));
        });

        const csvContent = csvRows.join('\n');
        // Add BOM for Excel UTF-8 support
        const blob = new Blob(['\uFEFF' + csvContent], { type: 'text/csv;charset=utf-8;' });
        const url = URL.createObjectURL(blob);
        const link = document.createElement('a');
        link.setAttribute('href', url);
        link.setAttribute('download', `logs_page_${page}.csv`);
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
    }

    function formatDate(timestamp) {
        const d = new Date(timestamp);
        return `${d.getFullYear()}/${d.getMonth() + 1}/${d.getDate()} ${d.getHours().toString().padStart(2, '0')}:${d.getMinutes().toString().padStart(2, '0')}:${d.getSeconds().toString().padStart(2, '0')}`;
    }

    function truncateParams(params) {
        if (params.length > 50) {
            return params.substring(0, 47) + '...';
        }
        return params;
    }
</script>

<div class="h-full flex flex-col pt-8 items-center">
    <div class="w-full max-w-6xl bg-white rounded-xl shadow-sm border border-gray-200 flex flex-col h-full overflow-hidden">
        <!-- Header -->
        <div class="px-6 py-5 border-b border-gray-200 flex justify-between items-center bg-gray-50/50 shrink-0">
            <h3 class="text-sm text-gray-600">系统总共记录了 <span class="font-bold text-gray-900">{total}</span> 条操作日志</h3>
            <button on:click={exportToCsv} class="flex items-center px-4 py-2 bg-green-600 hover:bg-green-700 text-white rounded text-sm font-medium transition-colors shadow-sm active:scale-95">
                <svg class="w-4 h-4 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4"></path></svg>
                导出当前页数据
            </button>
        </div>

        <!-- Table -->
        <div class="flex-1 overflow-y-auto">
            <table class="min-w-full divide-y divide-gray-200">
                <thead class="bg-white sticky top-0 z-10 shadow-sm">
                    <tr>
                        <th class="px-6 py-4 text-left text-xs font-semibold text-gray-500 tracking-wider">日志ID</th>
                        <th class="px-6 py-4 text-left text-xs font-semibold text-gray-500 tracking-wider">操作设备</th>
                        <th class="px-6 py-4 text-left text-xs font-semibold text-gray-500 tracking-wider">调用接口</th>
                        <th class="px-6 py-4 text-left text-xs font-semibold text-gray-500 tracking-wider">核心参数</th>
                        <th class="px-6 py-4 text-left text-xs font-semibold text-gray-500 tracking-wider">调用时间</th>
                        <th class="px-6 py-4 text-left text-xs font-semibold text-gray-500 tracking-wider">调用结果</th>
                    </tr>
                </thead>
                <tbody class="bg-white divide-y divide-gray-100">
                    {#if isLoading}
                        <tr><td colspan="6" class="px-6 py-8 text-center text-sm text-gray-500">加载中...</td></tr>
                    {:else if logs.length === 0}
                        <tr><td colspan="6" class="px-6 py-12 text-center text-sm text-gray-500">暂无日志数据</td></tr>
                    {:else}
                        {#each logs as log}
                            <tr class="hover:bg-gray-50 transition-colors">
                                <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-500 font-mono">{log.log_id}</td>
                                <td class="px-6 py-4 whitespace-nowrap text-sm font-medium text-gray-900">{log.device_name}</td>
                                <td class="px-6 py-4 whitespace-nowrap text-sm text-blue-600 font-mono bg-blue-50/30 rounded">{log.api_path}</td>
                                <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-500 font-mono" title={log.parameters}>{truncateParams(log.parameters)}</td>
                                <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-500">{formatDate(log.timestamp)}</td>
                                <td class="px-6 py-4 whitespace-nowrap">
                                    <span class="px-2 inline-flex text-xs leading-5 font-semibold rounded-full {log.result === '成功' ? 'bg-green-100 text-green-800' : 'bg-red-100 text-red-800'}">
                                        {log.result}
                                    </span>
                                </td>
                            </tr>
                        {/each}
                    {/if}
                </tbody>
            </table>
        </div>

        <!-- Pagination -->
        <div class="px-6 py-4 border-t border-gray-200 bg-white flex items-center justify-between shrink-0">
            <div class="text-sm text-gray-500">
                显示第 {total === 0 ? 0 : startItem} 到 {endItem} 条，共 {total} 条
            </div>
            <div class="flex items-center space-x-2">
                <button 
                    on:click={prevPage} 
                    disabled={page === 1}
                    class="p-2 rounded border border-gray-300 text-gray-600 hover:bg-gray-50 disabled:opacity-50 disabled:cursor-not-allowed"
                >
                    <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 19l-7-7 7-7"></path></svg>
                </button>
                <span class="text-sm text-gray-700 px-2">第 {page} / {totalPages} 页</span>
                <button 
                    on:click={nextPage} 
                    disabled={page === totalPages || total === 0}
                    class="p-2 rounded border border-gray-300 text-gray-600 hover:bg-gray-50 disabled:opacity-50 disabled:cursor-not-allowed"
                >
                    <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7"></path></svg>
                </button>
            </div>
        </div>
    </div>
</div>
