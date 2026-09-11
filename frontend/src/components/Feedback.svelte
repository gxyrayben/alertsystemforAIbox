<script>
    import { onMount } from 'svelte';
    import { API_BASE, apiGet, apiPost } from '../lib/api.js';
    import { showToast, selectedDevice } from '../lib/controlStore.js';

    const PLACEHOLDER = 'https://placehold.co/800x500/1e293b/475569?text=No+Snapshot';

    // 筛选
    let filterChannel = '';
    let filterType = '';
    let options = { channels: [], alertTypes: [] };

    // 三区数据
    let pending = [];      // 左侧树：待标注（≤10）
    let annotated = [];    // 右侧列表：已标注（≤10）
    let selected = null;   // 中间：当前查看/标注的告警
    let note = '';
    let loading = false;
    let submitting = false;

    $: deviceName = $selectedDevice?.name || '';
    $: imgBig = selected?.imageUrl ? `${API_BASE}${selected.imageUrl}` : PLACEHOLDER;
    $: imgCrop = selected?.imageUrlCrop ? `${API_BASE}${selected.imageUrlCrop}` : '';

    function statusLabel(s) {
        if (s === 'valid') return { text: '真实告警', cls: 'bg-emerald-500/20 text-emerald-400 border-emerald-500/30' };
        if (s === 'false_positive') return { text: '误报', cls: 'bg-amber-500/20 text-amber-400 border-amber-500/30' };
        return { text: '待审核', cls: 'bg-rose-500/20 text-rose-400 border-rose-500/30' };
    }

    function qs() {
        const p = new URLSearchParams();
        if (deviceName) p.set('deviceName', deviceName);
        if (filterChannel) p.set('channel', filterChannel);
        if (filterType) p.set('alertType', filterType);
        return p.toString() ? `?${p.toString()}` : '';
    }

    async function loadOptions() {
        try {
            const p = deviceName ? `?deviceName=${encodeURIComponent(deviceName)}` : '';
            options = await apiGet(`/feedback/options${p}`);
        } catch (e) {
            options = { channels: [], alertTypes: [] };
        }
    }

    async function loadPending() {
        pending = await apiGet(`/feedback/pending${qs()}`);
    }
    async function loadAnnotated() {
        annotated = await apiGet(`/feedback/annotated${qs()}`);
    }

    async function search() {
        loading = true;
        try {
            await Promise.all([loadPending(), loadAnnotated()]);
            // 若当前选中项已不在任一列表（如已被标注移走），保留展示直到用户切换
            if (!selected && pending.length) selectAlert(pending[0]);
        } catch (e) {
            showToast(e?.detail || '检索失败,请检查后端服务。', 'error');
        } finally {
            loading = false;
        }
    }

    function selectAlert(a) {
        selected = a;
        note = a?.feedback_note || '';
    }

    async function annotate(status) {
        if (!selected) { showToast('请先在左侧队列选择一条告警。', 'warning'); return; }
        try {
            await apiPost(`/feedback/alerts/${selected.id}`, { status, note });
            const label = status === 'valid' ? '真实告警' : '误报';
            showToast(`已标注为「${label}」。`, 'success');
            const doneId = selected.id;
            // 重新拉取两侧：服务端已自动把已标注项移出 pending，并按需补足到 10 条
            await Promise.all([loadPending(), loadAnnotated()]);
            // 中间自动切到队列里的下一条（若还有）
            const next = pending.find((x) => x.id !== doneId) || pending[0] || null;
            selectAlert(next);
        } catch (e) {
            showToast(e?.detail || '标注失败。', 'error');
        }
    }

    async function submitOptimization() {
        submitting = true;
        try {
            const res = await apiPost('/feedback/submit-optimization', {});
            showToast(res?.message || '已提交优化。', res?.submitted ? 'success' : 'info');
            // 提交后：已标注数据已流转为运维记录 → 右侧列表清空（中间正在查看的图片保留不动）
            await Promise.all([loadPending(), loadAnnotated()]);
        } catch (e) {
            showToast(e?.detail || '提交优化失败。', 'error');
        } finally {
            submitting = false;
        }
    }

    // 右侧「已标注」项点击 → 载入中间重新标注
    function reannotate(a) {
        selectAlert(a);
    }

    // 已标注列表现已排除「已提交」项，只要有已标注数据即可提交优化（小模型 Case 也用真实样本）
    $: hasSubmittable = annotated.length > 0;

    onMount(async () => {
        await loadOptions();
        await search();
    });

    // 切换设备时刷新筛选项与数据
    let lastDevice = '';
    $: if (deviceName !== lastDevice) {
        lastDevice = deviceName;
        (async () => { await loadOptions(); await search(); })();
    }
</script>

<div class="max-w-[1600px] mx-auto space-y-5">
    <div>
        <h2 class="text-lg font-bold text-white">告警反馈闭环：历史抓拍标注与优化飞轮</h2>
        <p class="text-xs text-slate-400 mt-1">按通道 / 算法种类检索历史高疑告警,逐条标注真实/误报;已标注数据自动流转至右侧,并从左侧队列移除、补足新数据。已标注的数据不会再被检索。</p>
    </div>

    <!-- 筛选栏 -->
    <div class="bg-slate-950 p-3.5 rounded-2xl border border-slate-800 flex flex-wrap items-end gap-3">
        <div class="flex flex-col">
            <label class="text-[10px] text-slate-500 mb-1">当前设备</label>
            <div class="h-9 px-3 flex items-center bg-slate-900 border border-slate-800 rounded-lg text-[11px] text-slate-300">
                <i class="fa-solid fa-video text-[10px] mr-1.5 text-indigo-400"></i>{deviceName || '未选择'}
            </div>
        </div>
        <div class="flex flex-col">
            <label class="text-[10px] text-slate-500 mb-1">通道</label>
            <select bind:value={filterChannel} class="h-9 bg-slate-900 border border-slate-800 text-slate-200 rounded-lg px-3 text-[11px] focus:border-indigo-500 min-w-[140px]">
                <option value="">全部通道</option>
                {#each options.channels as c}<option value={c}>{c}</option>{/each}
            </select>
        </div>
        <div class="flex flex-col">
            <label class="text-[10px] text-slate-500 mb-1">算法种类</label>
            <select bind:value={filterType} class="h-9 bg-slate-900 border border-slate-800 text-slate-200 rounded-lg px-3 text-[11px] focus:border-indigo-500 min-w-[160px]">
                <option value="">全部算法</option>
                {#each options.alertTypes as t}<option value={t}>{t}</option>{/each}
            </select>
        </div>
        <button on:click={search} disabled={loading} class="h-9 px-4 bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50 text-white rounded-lg text-[11px] font-bold flex items-center">
            <i class="fa-solid fa-magnifying-glass mr-1.5 {loading ? 'animate-spin' : ''}"></i>{loading ? '检索中' : '检索'}
        </button>
    </div>

    <div class="grid grid-cols-1 lg:grid-cols-12 gap-5 items-start">
        <!-- 左：待标注队列 -->
        <div class="lg:col-span-3 bg-slate-950 p-3.5 rounded-2xl border border-slate-800 space-y-2.5">
            <div class="flex items-center justify-between">
                <p class="text-[10px] font-bold text-slate-500 uppercase tracking-wider">🚨 级联触发的高疑告警快照</p>
                <span class="text-[9px] text-slate-500 font-mono">{pending.length}/10</span>
            </div>
            {#if !pending.length}
                <div class="py-10 text-center text-[11px] text-slate-600"><i class="fa-solid fa-inbox text-2xl mb-2 block"></i>暂无待标注数据</div>
            {/if}
            {#each pending as a (a.id)}
                <div on:click={() => selectAlert(a)}
                    class="p-2.5 rounded-xl border cursor-pointer transition-all flex items-center space-x-2.5 {selected?.id === a.id ? 'border-indigo-500/60 bg-indigo-500/10' : 'border-slate-800 bg-slate-950/40 hover:border-indigo-500/30'}">
                    <div class="relative w-14 h-14 rounded-lg overflow-hidden border border-slate-800 shrink-0 bg-slate-900">
                        <img src={a.imageUrl ? `${API_BASE}${a.imageUrl}` : PLACEHOLDER} alt="" class="w-full h-full object-cover" />
                        <div class="absolute inset-0 bg-rose-500/10"></div>
                    </div>
                    <div class="flex-1 min-w-0">
                        <div class="flex items-center justify-between">
                            <span class="text-[9px] bg-rose-500/20 text-rose-400 font-bold px-1.5 py-0.5 rounded border border-rose-500/30">待审核</span>
                            <span class="text-[9px] text-slate-500 font-mono">{a.channelid || '—'}</span>
                        </div>
                        <h4 class="text-[11px] font-bold text-slate-200 mt-1 truncate">{a.alertType}</h4>
                        <p class="text-[9px] text-slate-500 mt-0.5 truncate">{a.time}</p>
                    </div>
                </div>
            {/each}
        </div>

        <!-- 中：大图 + 小图 + 标注 -->
        <div class="lg:col-span-6 bg-slate-950 p-4 rounded-2xl border border-slate-800 space-y-4">
            {#if !selected}
                <div class="py-24 text-center text-slate-600"><i class="fa-solid fa-hand-pointer text-3xl mb-3 block"></i><p class="text-xs">请从左侧队列选择一条告警进行标注</p></div>
            {:else}
                <div class="flex justify-between items-start pb-3 border-b border-slate-800">
                    <div>
                        <span class="text-[10px] bg-slate-900 text-slate-400 px-2 py-1 rounded font-mono border border-slate-800">{selected.id}</span>
                        <h3 class="font-bold text-white mt-1.5 text-xs">{selected.deviceName} · {selected.alertType}</h3>
                    </div>
                    <div class="text-right">
                        <p class="text-[10px] text-slate-500">通道 {selected.channelid || '—'}</p>
                        <p class="text-xs font-semibold text-indigo-400 font-mono">{selected.time}</p>
                        {#if selected.feedback_status}
                            {@const lb = statusLabel(selected.feedback_status)}
                            <span class="inline-block mt-1 text-[9px] font-bold px-1.5 py-0.5 rounded border {lb.cls}">已标注 · {lb.text}</span>
                        {/if}
                    </div>
                </div>

                <div class="grid grid-cols-3 gap-4">
                    <div class="col-span-2 relative rounded-xl overflow-hidden bg-slate-900 aspect-[16/10] border border-slate-800">
                        <img src={imgBig} alt="告警大图" class="w-full h-full object-cover" />
                        <span class="absolute top-2 left-2 bg-slate-950/80 text-slate-300 text-[9px] font-bold px-2 py-0.5 rounded">告警大图（整帧）</span>
                    </div>
                    <div class="col-span-1 flex flex-col bg-slate-900 p-3 rounded-xl border border-slate-800">
                        <p class="text-[9px] text-slate-500 font-bold mb-1.5 uppercase text-center">送检小图</p>
                        <div class="flex-1 flex items-center justify-center border-2 border-indigo-500/30 rounded-lg bg-slate-950 overflow-hidden">
                            {#if imgCrop}
                                <img src={imgCrop} alt="送检小图" class="max-h-40 object-contain rounded" />
                            {:else}
                                <span class="text-[9px] text-slate-600 p-3 text-center">该告警无独立送检小图</span>
                            {/if}
                        </div>
                    </div>
                </div>

                <div class="bg-slate-900/60 p-4 rounded-xl border border-slate-800 space-y-3">
                    <p class="text-xs font-bold text-slate-300">💡 标注该告警：</p>
                    <textarea bind:value={note} rows="2" placeholder="可选：标注备注 / 误报原因…" class="w-full text-[11px] text-slate-300 bg-slate-950 border border-slate-800 focus:border-indigo-500 rounded-lg p-2.5"></textarea>
                    <div class="grid grid-cols-2 gap-3">
                        <button on:click={() => annotate('valid')} class="bg-slate-950 hover:bg-emerald-500/10 text-slate-200 border border-slate-800 hover:border-emerald-500/50 py-3 rounded-xl text-[12px] font-bold transition-all flex items-center justify-center">
                            <i class="fa-solid fa-circle-check text-emerald-400 mr-2"></i>真实报警
                        </button>
                        <button on:click={() => annotate('false_positive')} class="bg-slate-950 hover:bg-amber-500/10 text-slate-200 border border-slate-800 hover:border-amber-500/50 py-3 rounded-xl text-[12px] font-bold transition-all flex items-center justify-center">
                            <i class="fa-solid fa-triangle-exclamation text-amber-400 mr-2"></i>误报
                        </button>
                    </div>
                    {#if selected.feedback_status}
                        <p class="text-[10px] text-slate-500 text-center">该告警已标注,重新点击上方按钮即可修改标注结果。</p>
                    {/if}
                </div>
            {/if}
        </div>

        <!-- 右：已标注列表 -->
        <div class="lg:col-span-3 bg-slate-950 p-3.5 rounded-2xl border border-slate-800 space-y-2.5">
            <div class="flex items-center justify-between">
                <p class="text-[10px] font-bold text-slate-500 uppercase tracking-wider">✅ 已标注数据</p>
                <span class="text-[9px] text-slate-500 font-mono">{annotated.length}/10</span>
            </div>
            <button on:click={submitOptimization} disabled={submitting || !hasSubmittable}
                class="w-full py-2 rounded-lg text-[11px] font-bold flex items-center justify-center transition-all {hasSubmittable ? 'bg-indigo-600 hover:bg-indigo-700 text-white' : 'bg-slate-900 text-slate-600 border border-slate-800 cursor-not-allowed'}">
                <i class="fa-solid fa-arrows-spin mr-1.5 {submitting ? 'animate-spin' : ''}"></i>{submitting ? '提交中' : '提交后端做优化'}
            </button>

            {#if !annotated.length}
                <div class="py-10 text-center text-[11px] text-slate-600"><i class="fa-solid fa-clipboard-check text-2xl mb-2 block"></i>暂无已标注数据</div>
            {/if}
            {#each annotated as a (a.id)}
                {@const lb = statusLabel(a.feedback_status)}
                <div on:click={() => reannotate(a)}
                    class="p-2.5 rounded-xl border cursor-pointer transition-all flex items-center space-x-2.5 {selected?.id === a.id ? 'border-indigo-500/60 bg-indigo-500/10' : 'border-slate-800 bg-slate-950/40 hover:border-indigo-500/30'}">
                    <div class="w-14 h-14 rounded-lg overflow-hidden border border-slate-800 shrink-0 bg-slate-900">
                        <img src={a.imageUrl ? `${API_BASE}${a.imageUrl}` : PLACEHOLDER} alt="" class="w-full h-full object-cover" />
                    </div>
                    <div class="flex-1 min-w-0">
                        <div class="flex items-center justify-between gap-1">
                            <span class="text-[9px] font-bold px-1.5 py-0.5 rounded border {lb.cls}">{lb.text}</span>
                        </div>
                        <h4 class="text-[11px] font-semibold text-slate-300 mt-1 truncate">{a.alertType}</h4>
                        <p class="text-[9px] text-slate-500 mt-0.5 truncate">{a.channelid || '—'} · 点击重新标注</p>
                    </div>
                </div>
            {/each}
        </div>
    </div>
</div>
