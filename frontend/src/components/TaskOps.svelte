<script>
    import { onMount } from 'svelte';
    import { API_BASE, apiGet } from '../lib/api.js';
    import { showToast, switchTab, selectedDevice } from '../lib/controlStore.js';
    import { formatDate } from '../lib/utils.js';

    const PLACEHOLDER = 'https://placehold.co/800x500/1e293b/475569?text=No+Snapshot';

    let records = [];
    let total = 0;
    let page = 1;
    const size = 8;
    let loading = false;

    // 详情翻页弹层
    let detail = null;        // { ...record, alerts: [] }
    let detailIdx = 0;
    let detailLoading = false;

    $: deviceName = $selectedDevice?.name || '';
    $: totalPages = Math.ceil(total / size) || 1;
    $: cur = detail?.alerts?.[detailIdx] || null;
    $: curBig = cur?.imageUrl ? `${API_BASE}${cur.imageUrl}` : PLACEHOLDER;
    $: curCrop = cur?.imageUrlCrop ? `${API_BASE}${cur.imageUrlCrop}` : '';

    function statusLabel(s) {
        if (s === 'valid') return { text: '真实告警', cls: 'bg-emerald-500/20 text-emerald-400 border-emerald-500/30' };
        if (s === 'false_positive') return { text: '误报', cls: 'bg-amber-500/20 text-amber-400 border-amber-500/30' };
        return { text: '待审核', cls: 'bg-rose-500/20 text-rose-400 border-rose-500/30' };
    }

    // Case 徽章：大模型 / 小模型 / 小+大
    function caseBadge(rec) {
        const map = {
            Case1: { text: '大模型 · Prompt', cls: 'bg-indigo-500/15 text-indigo-300 border-indigo-500/30' },
            Case2: { text: '小模型 · 参数', cls: 'bg-amber-500/15 text-amber-300 border-amber-500/30' },
            Case3: { text: '小+大 · 参数+Prompt', cls: 'bg-fuchsia-500/15 text-fuchsia-300 border-fuchsia-500/30' },
        };
        return map[rec.case_key] || { text: rec.category || '—', cls: 'bg-slate-700/30 text-slate-400 border-slate-700' };
    }

    async function load() {
        loading = true;
        try {
            const p = new URLSearchParams();
            p.set('page', page);
            p.set('size', size);
            if (deviceName) p.set('deviceName', deviceName);
            const data = await apiGet(`/feedback/tasks?${p.toString()}`);
            records = data.items || [];
            total = data.total || 0;
        } catch (e) {
            showToast(e?.detail || '加载运维记录失败，请检查后端服务。', 'error');
            records = [];
            total = 0;
        } finally {
            loading = false;
        }
    }

    function prevPage() { if (page > 1) { page--; load(); } }
    function nextPage() { if (page < totalPages) { page++; load(); } }

    async function openDetail(rec) {
        detailLoading = true;
        detail = null;
        detailIdx = 0;
        try {
            detail = await apiGet(`/feedback/tasks/${rec.id}`);
        } catch (e) {
            showToast(e?.detail || '加载标注详情失败。', 'error');
            detail = null;
        } finally {
            detailLoading = false;
        }
    }

    function closeDetail() { detail = null; detailIdx = 0; }
    function prevAlert() { if (detailIdx > 0) detailIdx--; }
    function nextAlert() { if (detail && detailIdx < detail.alerts.length - 1) detailIdx++; }

    onMount(load);

    // 切换设备时回到第一页重新拉取
    let lastDevice = '';
    $: if (deviceName !== lastDevice) {
        lastDevice = deviceName;
        page = 1;
        load();
    }
</script>

<div class="max-w-6xl mx-auto space-y-6">
    <!-- 头部 -->
    <div class="flex flex-col sm:flex-row justify-between items-start sm:items-center bg-slate-950 p-5 rounded-2xl border border-slate-800 gap-4">
        <div>
            <h2 class="text-base font-bold text-white">调优下发运维记录</h2>
            <p class="text-xs text-slate-400 mt-0.5">「告警反馈闭环」每次提交后端优化产生的按通道任务下发结果。一次提交可含多条记录（不同通道 / Case）。</p>
            <span class="inline-flex items-center gap-1.5 mt-2 text-[11px] bg-emerald-500/10 text-emerald-300 border border-emerald-500/30 px-2.5 py-1 rounded-lg">
                <i class="fa-solid fa-video text-[10px]"></i> 当前设备：<strong>{deviceName || '全部'}</strong>
            </span>
        </div>
        <div class="flex items-center space-x-2 w-full sm:w-auto">
            <button on:click={load} disabled={loading} class="bg-slate-800 hover:bg-slate-700 disabled:opacity-50 text-slate-200 px-3.5 py-1.5 rounded-xl text-xs font-bold flex items-center transition-all shrink-0">
                <i class="fa-solid fa-rotate mr-1.5 {loading ? 'animate-spin' : ''}"></i> 刷新
            </button>
            <button on:click={() => switchTab('feedback')} class="bg-indigo-600 hover:bg-indigo-700 text-white px-3.5 py-1.5 rounded-xl text-xs font-bold flex items-center transition-all shadow-sm shrink-0">
                <i class="fa-solid fa-arrows-spin mr-1.5"></i> 去标注/提交优化
            </button>
        </div>
    </div>

    <!-- 记录列表 -->
    <div class="grid grid-cols-1 gap-4">
        {#each records as rec (rec.id)}
            {@const cb = caseBadge(rec)}
            <div class="bg-slate-950 p-5 rounded-2xl border border-slate-800 flex flex-col md:flex-row md:items-center justify-between gap-4 hover:border-slate-700 transition-all">
                <div class="space-y-2 flex-1 min-w-0">
                    <div class="flex flex-wrap items-center gap-2">
                        {#if rec.action === 'deployed'}
                            <span class="text-[10px] bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 font-semibold px-2 py-0.5 rounded flex items-center"><span class="w-1.5 h-1.5 bg-emerald-500 rounded-full mr-1"></span> 已下发</span>
                        {:else}
                            <span class="text-[10px] bg-slate-700/30 text-slate-400 border border-slate-700 font-semibold px-2 py-0.5 rounded flex items-center"><span class="w-1.5 h-1.5 bg-slate-500 rounded-full mr-1"></span> 已跳过</span>
                        {/if}
                        <span class="text-[10px] font-bold px-2 py-0.5 rounded border {cb.cls}">{cb.text}</span>
                        <span class="text-[10px] bg-slate-900 text-slate-400 border border-slate-800 font-mono px-2 py-0.5 rounded" title="提交批次">批次 {rec.batch_id.slice(0, 8)}</span>
                    </div>
                    <h3 class="font-bold text-slate-100 text-sm truncate">下发任务：{rec.task_name || '—'}</h3>
                    <p class="text-[11px] text-slate-400 bg-slate-900 p-2 rounded border border-slate-800 line-clamp-2"><strong class="text-slate-300">结果：</strong>{rec.result || '—'}</p>
                    <div class="flex flex-wrap gap-4 text-[11px] text-slate-500 pt-0.5">
                        <span><i class="fa-solid fa-video mr-1"></i> 设备: <strong>{rec.device_name || '—'}</strong></span>
                        <span><i class="fa-solid fa-diagram-project mr-1"></i> 通道: <strong>{rec.channel || '—'}</strong></span>
                        <span><i class="fa-solid fa-tags mr-1"></i> 标注数据: <strong class="text-slate-300">{rec.alert_count} 条</strong></span>
                        <span><i class="fa-solid fa-clock mr-1"></i> {formatDate(rec.created_at)}</span>
                        {#if rec.log_id}<span><i class="fa-solid fa-file-lines mr-1"></i> 日志: <strong class="font-mono text-slate-400">{rec.log_id}</strong></span>{/if}
                    </div>
                </div>
                <div class="flex items-center gap-2 shrink-0">
                    <button on:click={() => openDetail(rec)} disabled={!rec.alert_count} class="bg-indigo-500/10 hover:bg-indigo-500/25 disabled:opacity-40 disabled:cursor-not-allowed text-indigo-400 border border-indigo-500/30 px-4 py-2 rounded-xl text-xs font-bold transition-all flex items-center justify-center"><i class="fa-solid fa-images mr-1.5"></i> 详情</button>
                </div>
            </div>
        {:else}
            <div class="bg-slate-950 p-12 text-center rounded-2xl border border-slate-800 text-slate-500">
                <i class="fa-solid fa-rectangle-list text-4xl mb-3 text-slate-700"></i>
                <p class="text-xs">{loading ? '加载中…' : '暂无调优下发记录，请在「告警反馈闭环」标注并提交优化。'}</p>
            </div>
        {/each}
    </div>

    <!-- 分页 -->
    {#if total > 0}
        <div class="flex items-center justify-between bg-slate-950 border border-slate-800 rounded-2xl px-5 py-3">
            <div class="text-xs text-slate-400">共 {total} 条记录</div>
            <div class="flex items-center space-x-2">
                <button on:click={prevPage} disabled={page === 1} class="p-2 rounded-lg border border-slate-800 text-slate-400 hover:bg-slate-800 disabled:opacity-50 disabled:cursor-not-allowed"><i class="fa-solid fa-chevron-left text-sm"></i></button>
                <span class="text-xs text-slate-200 px-2">第 {page} / {totalPages} 页</span>
                <button on:click={nextPage} disabled={page === totalPages} class="p-2 rounded-lg border border-slate-800 text-slate-400 hover:bg-slate-800 disabled:opacity-50 disabled:cursor-not-allowed"><i class="fa-solid fa-chevron-right text-sm"></i></button>
            </div>
        </div>
    {/if}
</div>

<!-- 详情翻页弹层 -->
{#if detailLoading || detail}
    <div class="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/80 p-4" on:click|self={closeDetail}>
        <div class="w-full max-w-3xl bg-slate-950 border border-slate-800 rounded-2xl shadow-2xl overflow-hidden">
            <div class="px-5 py-4 border-b border-slate-800 flex justify-between items-center bg-slate-900/40">
                <div class="min-w-0">
                    <h3 class="text-sm font-bold text-white truncate">标注数据详情 · {detail?.task_name || ''}</h3>
                    <p class="text-[11px] text-slate-400 mt-0.5">{detail?.device_name || ''} · 通道 {detail?.channel || '—'}</p>
                </div>
                <button on:click={closeDetail} class="text-slate-400 hover:text-white p-2"><i class="fa-solid fa-xmark text-lg"></i></button>
            </div>

            <div class="p-5">
                {#if detailLoading}
                    <div class="py-20 text-center text-slate-500 text-sm"><i class="fa-solid fa-spinner animate-spin text-2xl mb-3 block"></i>加载中…</div>
                {:else if !detail?.alerts?.length}
                    <div class="py-20 text-center text-slate-500 text-sm"><i class="fa-solid fa-inbox text-2xl mb-3 block"></i>该记录无标注数据快照</div>
                {:else if cur}
                    {@const lb = statusLabel(cur.feedback_status)}
                    <div class="flex justify-between items-start pb-3 border-b border-slate-800 mb-4">
                        <div>
                            <span class="text-[10px] bg-slate-900 text-slate-400 px-2 py-1 rounded font-mono border border-slate-800">{cur.id}</span>
                            <h4 class="font-bold text-white mt-1.5 text-xs">{cur.alertType}</h4>
                        </div>
                        <div class="text-right">
                            <p class="text-[10px] text-slate-500">通道 {cur.channel || '—'}</p>
                            <p class="text-xs font-semibold text-indigo-400 font-mono">{cur.time}</p>
                            <span class="inline-block mt-1 text-[9px] font-bold px-1.5 py-0.5 rounded border {lb.cls}">{lb.text}</span>
                        </div>
                    </div>

                    <div class="grid grid-cols-3 gap-4">
                        <div class="col-span-2 relative rounded-xl overflow-hidden bg-slate-900 aspect-[16/10] border border-slate-800">
                            <img src={curBig} alt="告警大图" class="w-full h-full object-cover" />
                            <span class="absolute top-2 left-2 bg-slate-950/80 text-slate-300 text-[9px] font-bold px-2 py-0.5 rounded">告警大图（整帧）</span>
                        </div>
                        <div class="col-span-1 flex flex-col bg-slate-900 p-3 rounded-xl border border-slate-800">
                            <p class="text-[9px] text-slate-500 font-bold mb-1.5 uppercase text-center">送检小图</p>
                            <div class="flex-1 flex items-center justify-center border-2 border-indigo-500/30 rounded-lg bg-slate-950 overflow-hidden">
                                {#if curCrop}
                                    <img src={curCrop} alt="送检小图" class="max-h-40 object-contain rounded" />
                                {:else}
                                    <span class="text-[9px] text-slate-600 p-3 text-center">该告警无独立送检小图</span>
                                {/if}
                            </div>
                        </div>
                    </div>

                    {#if cur.feedback_note}
                        <div class="mt-4 bg-slate-900/60 p-3 rounded-xl border border-slate-800">
                            <p class="text-[10px] text-slate-500 font-bold mb-1">标注备注</p>
                            <p class="text-[11px] text-slate-300">{cur.feedback_note}</p>
                        </div>
                    {/if}
                {/if}
            </div>

            {#if detail?.alerts?.length}
                <div class="px-5 py-3 border-t border-slate-800 bg-slate-900/40 flex items-center justify-between">
                    <div class="text-xs text-slate-400">第 {detailIdx + 1} / {detail.alerts.length} 条标注</div>
                    <div class="flex items-center space-x-2">
                        <button on:click={prevAlert} disabled={detailIdx === 0} class="p-2 rounded-lg border border-slate-800 text-slate-400 hover:bg-slate-800 disabled:opacity-50 disabled:cursor-not-allowed"><i class="fa-solid fa-chevron-left text-sm"></i></button>
                        <button on:click={nextAlert} disabled={detailIdx === detail.alerts.length - 1} class="p-2 rounded-lg border border-slate-800 text-slate-400 hover:bg-slate-800 disabled:opacity-50 disabled:cursor-not-allowed"><i class="fa-solid fa-chevron-right text-sm"></i></button>
                    </div>
                </div>
            {/if}
        </div>
    </div>
{/if}
