<script>
    import { onMount } from 'svelte';
    import { apiGet } from '../lib/api.js';
    import { formatDate } from '../lib/utils.js';

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
            const data = await apiGet(`/logs?page=${page}&size=${size}`);
            logs = data.items;
            total = data.total;
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
</script>

<div class="h-full flex flex-col pt-8 items-center">
    <div class="w-full max-w-6xl bg-slate-950 border border-slate-800 rounded-2xl flex flex-col h-full overflow-hidden">
        <!-- Header -->
        <div class="px-6 py-5 border-b border-slate-800 flex justify-between items-center bg-slate-900/40 shrink-0">
            <h3 class="text-sm text-slate-400">系统总共记录了 <span class="font-bold text-slate-100">{total}</span> 条操作日志</h3>
            <button on:click={exportToCsv} class="bg-emerald-600 hover:bg-emerald-700 text-white rounded-xl text-sm font-bold px-4 py-2 flex items-center shadow-sm active:scale-95">
                <i class="fa-solid fa-file-arrow-down mr-2 text-sm"></i>
                导出当前页数据
            </button>
        </div>

        <!-- Table -->
        <div class="flex-1 overflow-y-auto">
            <table class="w-full table-fixed divide-y divide-slate-800">
                <colgroup>
                    <col class="w-[9%]" />
                    <col class="w-[12%]" />
                    <col class="w-[20%]" />
                    <col class="w-[27%]" />
                    <col class="w-[16%]" />
                    <col class="w-[16%]" />
                </colgroup>
                <thead class="bg-slate-900/60 sticky top-0 z-10 shadow-sm">
                    <tr>
                        <th class="px-4 py-3.5 text-left text-[11px] font-semibold text-slate-500 uppercase tracking-wider">日志ID</th>
                        <th class="px-4 py-3.5 text-left text-[11px] font-semibold text-slate-500 uppercase tracking-wider">操作设备</th>
                        <th class="px-4 py-3.5 text-left text-[11px] font-semibold text-slate-500 uppercase tracking-wider">调用接口</th>
                        <th class="px-4 py-3.5 text-left text-[11px] font-semibold text-slate-500 uppercase tracking-wider">核心参数</th>
                        <th class="px-4 py-3.5 text-left text-[11px] font-semibold text-slate-500 uppercase tracking-wider">调用时间</th>
                        <th class="px-4 py-3.5 text-left text-[11px] font-semibold text-slate-500 uppercase tracking-wider">结果</th>
                    </tr>
                </thead>
                <tbody class="bg-slate-950 divide-y divide-slate-800">
                    {#if isLoading}
                        <tr><td colspan="6" class="px-4 py-8 text-center text-sm text-slate-500">加载中...</td></tr>
                    {:else if logs.length === 0}
                        <tr><td colspan="6" class="px-4 py-12 text-center text-sm text-slate-500">暂无日志数据</td></tr>
                    {:else}
                        {#each logs as log}
                            <tr class="hover:bg-slate-900/60 transition-colors align-top">
                                <td class="px-4 py-3.5 text-sm text-slate-400 font-mono truncate" title={log.log_id}>{log.log_id}</td>
                                <td class="px-4 py-3.5 text-sm font-medium text-slate-100 truncate" title={log.device_name}>{log.device_name}</td>
                                <td class="px-4 py-3.5 text-sm" title={log.api_path}>
                                    <span class="inline-block max-w-full truncate align-bottom text-indigo-400 font-mono text-xs bg-indigo-500/10 rounded px-1.5 py-0.5">{log.api_path}</span>
                                </td>
                                <td class="px-4 py-3.5 text-sm text-slate-400 truncate" title={log.parameters}>{log.parameters}</td>
                                <td class="px-4 py-3.5 text-sm text-slate-400 whitespace-nowrap">{formatDate(log.timestamp)}</td>
                                <td class="px-4 py-3.5" title={log.result}>
                                    <span class="max-w-full truncate inline-block px-2.5 py-1 text-xs leading-5 font-semibold rounded-full align-bottom {log.result === '成功' ? 'bg-emerald-500/10 text-emerald-400' : 'bg-rose-500/10 text-rose-400'}">
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
        <div class="px-6 py-4 border-t border-slate-800 bg-slate-900/40 flex items-center justify-between shrink-0">
            <div class="text-sm text-slate-400">
                显示第 {total === 0 ? 0 : startItem} 到 {endItem} 条，共 {total} 条
            </div>
            <div class="flex items-center space-x-2">
                <button
                    on:click={prevPage}
                    disabled={page === 1}
                    class="p-2 rounded-lg border border-slate-800 text-slate-400 hover:bg-slate-800 disabled:opacity-50 disabled:cursor-not-allowed"
                >
                    <i class="fa-solid fa-chevron-left text-sm"></i>
                </button>
                <span class="text-sm text-slate-200 px-2">第 {page} / {totalPages} 页</span>
                <button
                    on:click={nextPage}
                    disabled={page === totalPages || total === 0}
                    class="p-2 rounded-lg border border-slate-800 text-slate-400 hover:bg-slate-800 disabled:opacity-50 disabled:cursor-not-allowed"
                >
                    <i class="fa-solid fa-chevron-right text-sm"></i>
                </button>
            </div>
        </div>
    </div>
</div>
