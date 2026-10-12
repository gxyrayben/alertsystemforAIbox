<script>
    // 图文互搜：中文自然语言 → 搜预警图（文搜图），也支持上传图搜相似图（以图搜图）。
    // 后端用本地 Chinese-CLIP(ViT-B/16) 提取特征，非实时建模：后台定时批量建索，页面只看进度。
    import { onMount, onDestroy } from 'svelte';
    import { API_BASE, apiGet, apiPost, apiUpload } from '../lib/api.js';
    import { devices, selectedDevice, showToast } from '../lib/controlStore.js';

    let status = null;             // /search/status 返回（模型 + 索引进度 + 数据量）
    let statusErr = '';
    let timer = null;

    // 检索条件
    let kind = 'big';              // big=告警整帧 / crop=送检小图
    let mode = 'text';             // text=文搜图 / image=以图搜图
    let query = '';
    let topK = 24;
    let filters = { deviceName: '', channelname: '', alertType: '', startDate: '', endDate: '' };

    let searching = false;
    let reindexing = false;
    let hits = [];
    let searchErr = '';
    let lastQueryLabel = '';
    let uploadFile = null;
    let uploadPreview = '';

    let viewerImage = null;

    onMount(async () => {
        await fetchStatus();
        // 建索是后台异步的：状态条轮询刷新（有待处理/正在跑时更密）
        timer = setInterval(fetchStatus, 5000);
    });
    onDestroy(() => timer && clearInterval(timer));

    async function fetchStatus() {
        try {
            status = await apiGet('/search/status');
            statusErr = '';
        } catch (e) {
            statusErr = e?.detail || '无法获取建索状态（后端不可达？）';
        }
    }

    // 通道下拉：复用「预警管理」同一套健壮解析（device_id 可能是数字）
    $: channelOptions = parseChannels($selectedDevice);
    function parseChannels(dev) {
        try {
            const raw = JSON.parse(dev?.channels || '[]');
            if (!Array.isArray(raw)) return [];
            const seen = new Set();
            const out = [];
            for (const item of raw) {
                const cid = String(item?.device_id ?? '').trim();
                const name = String(item?.device_name ?? '').trim();
                if (!cid || !name || seen.has(cid)) continue;
                seen.add(cid);
                out.push({ id: cid, name });
            }
            return out;
        } catch (e) {
            return [];
        }
    }

    // 设备选择：默认跟随顶栏当前设备
    $: if (status !== null && !filters.deviceName && $selectedDevice?.name) {
        filters.deviceName = $selectedDevice.name;
    }

    function fmtTime(ts) {
        if (!ts) return '';
        const d = new Date(Number(ts));
        const p = (n) => String(n).padStart(2, '0');
        return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
    }

    async function doTextSearch() {
        const q = query.trim();
        if (!q) { showToast('请输入要搜索的画面描述。', 'warning'); return; }
        searching = true; searchErr = ''; hits = [];
        try {
            const res = await apiPost('/search/text', {
                query: q, kind, top_k: Number(topK),
                deviceName: filters.deviceName || null,
                channelname: filters.channelname || null,
                alertType: filters.alertType || null,
                startDate: filters.startDate || null,
                endDate: filters.endDate || null,
            });
            hits = res?.hits || [];
            searchErr = res?.error || '';
            lastQueryLabel = `「${q}」 · ${kind === 'big' ? '整帧' : '送检小图'} · 索引 ${res?.pool_size ?? 0} 张`;
        } catch (e) {
            searchErr = e?.detail || '检索失败';
        } finally {
            searching = false;
        }
    }

    function onUploadPick(ev) {
        const f = ev.target.files?.[0];
        if (!f) return;
        uploadFile = f;
        if (uploadPreview) URL.revokeObjectURL(uploadPreview);
        uploadPreview = URL.createObjectURL(f);
    }

    async function doImageSearch() {
        if (!uploadFile) { showToast('请先选择一张图片。', 'warning'); return; }
        searching = true; searchErr = ''; hits = [];
        try {
            const fd = new FormData();
            fd.append('file', uploadFile);
            fd.append('kind', kind);
            fd.append('top_k', String(Number(topK)));
            if (filters.deviceName) fd.append('deviceName', filters.deviceName);
            if (filters.channelname) fd.append('channelname', filters.channelname);
            if (filters.alertType) fd.append('alertType', filters.alertType);
            if (filters.startDate) fd.append('startDate', filters.startDate);
            if (filters.endDate) fd.append('endDate', filters.endDate);
            const res = await apiUpload('/search/image', fd);
            hits = res?.hits || [];
            searchErr = res?.error || '';
            lastQueryLabel = `上传图 · ${kind === 'big' ? '整帧' : '送检小图'} · 索引 ${res?.pool_size ?? 0} 张`;
        } catch (e) {
            searchErr = e?.detail || '检索失败';
        } finally {
            searching = false;
        }
    }

    async function doReindex(scope) {
        if (!confirm(scope === 'all' ? '确定清空全部图片索引并重新建索？（后台会逐轮补齐，期间检索结果可能暂时变少）'
            : `确定只重建「${scope === 'big' ? '整帧' : '送检小图'}」索引？`)) return;
        reindexing = true;
        try {
            const res = await apiPost(`/search/reindex?kind=${scope}&run_now=true`, {});
            showToast(`已清空 ${res?.deleted ?? 0} 条索引，本轮新建 ${res?.indexed ?? 0} 张${res?.skipped ? `，跳过 ${res.skipped} 张` : ''}。`, 'success');
            await fetchStatus();
            hits = [];
        } catch (e) {
            showToast(e?.detail || '重建索引失败', 'error');
        } finally {
            reindexing = false;
        }
    }

    function resetFilters() {
        filters = {
            deviceName: $selectedDevice?.name || '',
            channelname: '', alertType: '', startDate: '', endDate: '',
        };
    }

    $: big = status?.index?.by_kind?.big || { indexed: 0, usable: 0, failed: 0 };
    $: crop = status?.index?.by_kind?.crop || { indexed: 0, usable: 0, failed: 0 };
    $: model = status?.model || {};
    $: idxCfg = status?.config || {};
    $: modelReady = !!model.model_ready;
</script>

<div class="space-y-5">
    <!-- 模型与索引进度：非实时建模，这里只做状态展示与手动重建入口 -->
    <div class="bg-slate-950 rounded-2xl border border-slate-800 overflow-hidden">
        <div class="px-6 py-4 border-b border-slate-800 bg-slate-900/40 flex flex-wrap items-center justify-between gap-3">
            <div class="flex items-center gap-3">
                <h3 class="text-white font-bold flex items-center"><i class="fa-solid fa-magnifying-glass-chart mr-2 text-indigo-400"></i>图文互搜 · 索引状态</h3>
                <span class="text-[11px] px-2 py-0.5 rounded-full border {modelReady ? 'text-emerald-300 border-emerald-700/60 bg-emerald-950/50' : 'text-amber-300 border-amber-700/60 bg-amber-950/40'}">
                    {modelReady ? '模型就绪' : '模型未就绪'}
                </span>
                {#if status?.index?.running}
                    <span class="text-[11px] text-indigo-300 flex items-center"><i class="fa-solid fa-arrows-rotate animate-spin mr-1.5"></i>后台建索中…</span>
                {/if}
            </div>
            <div class="flex items-center gap-2">
                <button on:click={() => doReindex('big')} disabled={reindexing}
                        class="text-[11px] text-slate-300 border border-slate-700 hover:border-indigo-500/60 rounded-lg px-2.5 py-1.5 disabled:opacity-50 transition">
                    <i class="fa-solid fa-rotate-left mr-1"></i>重建整帧索引
                </button>
                <button on:click={() => doReindex('crop')} disabled={reindexing}
                        class="text-[11px] text-slate-300 border border-slate-700 hover:border-indigo-500/60 rounded-lg px-2.5 py-1.5 disabled:opacity-50 transition">
                    <i class="fa-solid fa-rotate-left mr-1"></i>重建小图索引
                </button>
                <button on:click={() => doReindex('all')} disabled={reindexing}
                        class="text-[11px] text-white bg-indigo-600 hover:bg-indigo-700 rounded-lg px-2.5 py-1.5 disabled:opacity-50 transition">
                    <i class="fa-solid fa-database mr-1"></i>全部重建
                </button>
            </div>
        </div>

        <div class="p-6 grid grid-cols-2 md:grid-cols-3 xl:grid-cols-6 gap-4">
            <div class="bg-slate-900/60 border border-slate-800 rounded-xl p-3">
                <p class="text-[11px] text-slate-500">整帧已建索</p>
                <p class="text-xl font-bold text-slate-100 mt-1">{big.usable}<span class="text-xs text-slate-500 font-normal"> / {big.indexed}</span></p>
                <p class="text-[10px] text-slate-500 mt-0.5">失败 {big.failed}</p>
            </div>
            <div class="bg-slate-900/60 border border-slate-800 rounded-xl p-3">
                <p class="text-[11px] text-slate-500">送检小图已建索</p>
                <p class="text-xl font-bold text-slate-100 mt-1">{crop.usable}<span class="text-xs text-slate-500 font-normal"> / {crop.indexed}</span></p>
                <p class="text-[10px] text-slate-500 mt-0.5">失败 {crop.failed}</p>
            </div>
            <div class="bg-slate-900/60 border border-slate-800 rounded-xl p-3">
                <p class="text-[11px] text-slate-500">待处理</p>
                <p class="text-xl font-bold {status?.index?.pending ? 'text-amber-300' : 'text-slate-100'} mt-1">{status?.index?.pending ?? '—'}</p>
                <p class="text-[10px] text-slate-500 mt-0.5">后台每 {idxCfg.interval_seconds || 60}s 处理 {idxCfg.per_cycle || 120} 张</p>
            </div>
            <div class="bg-slate-900/60 border border-slate-800 rounded-xl p-3">
                <p class="text-[11px] text-slate-500">预警总数 / 有图</p>
                <p class="text-xl font-bold text-slate-100 mt-1">{status?.data?.alerts ?? '—'}<span class="text-xs text-slate-500 font-normal"> / {status?.data?.alerts_with_image ?? '—'}</span></p>
                <p class="text-[10px] text-slate-500 mt-0.5">图片随预警 7 天后清理</p>
            </div>
            <div class="bg-slate-900/60 border border-slate-800 rounded-xl p-3">
                <p class="text-[11px] text-slate-500">推理设备</p>
                <p class="text-xl font-bold text-slate-100 mt-1 uppercase">{model.device || '—'}</p>
                <p class="text-[10px] text-slate-500 mt-0.5 truncate" title={model.model}>{model.model || ''}</p>
            </div>
            <div class="bg-slate-900/60 border border-slate-800 rounded-xl p-3">
                <p class="text-[11px] text-slate-500">最近一轮</p>
                <p class="text-xl font-bold text-slate-100 mt-1">{status?.index?.last_indexed ?? 0}<span class="text-xs text-slate-500 font-normal"> 张</span></p>
                <p class="text-[10px] text-slate-500 mt-0.5">{status?.index?.last_run_ts ? fmtTime(status.index.last_run_ts) : '尚未运行'}</p>
            </div>
        </div>

        {#if !modelReady || statusErr || status?.index?.last_error}
            <div class="px-6 pb-5 -mt-1 space-y-1.5">
                {#if statusErr}
                    <p class="text-[11px] text-rose-400"><i class="fa-solid fa-triangle-exclamation mr-1.5"></i>{statusErr}</p>
                {/if}
                {#if !modelReady}
                    <p class="text-[11px] text-amber-400/90">
                        <i class="fa-solid fa-circle-info mr-1.5"></i>本地模型未就绪：{model.error || `请先执行 python tools/download_clip_model.py 下载 Chinese-CLIP 到 ${model.model_dir || 'models/'}`}
                    </p>
                {/if}
                {#if status?.index?.last_error}
                    <p class="text-[11px] text-rose-400"><i class="fa-solid fa-bug mr-1.5"></i>建索失败：{status.index.last_error}</p>
                {/if}
            </div>
        {/if}
    </div>

    <!-- 检索区 -->
    <div class="bg-slate-950 rounded-2xl border border-slate-800 p-5 space-y-4">
        <div class="flex flex-wrap items-center gap-3">
            <div class="flex rounded-xl border border-slate-800 overflow-hidden">
                <button on:click={() => mode = 'text'}
                        class="px-3.5 py-2 text-xs font-bold transition {mode === 'text' ? 'bg-indigo-600 text-white' : 'bg-slate-900 text-slate-400 hover:text-slate-200'}">
                    <i class="fa-solid fa-font mr-1.5"></i>文搜图
                </button>
                <button on:click={() => mode = 'image'}
                        class="px-3.5 py-2 text-xs font-bold transition {mode === 'image' ? 'bg-indigo-600 text-white' : 'bg-slate-900 text-slate-400 hover:text-slate-200'}">
                    <i class="fa-solid fa-image mr-1.5"></i>以图搜图
                </button>
            </div>

            <div class="flex items-center gap-2">
                <span class="text-[11px] text-slate-500">检索目标</span>
                <select bind:value={kind} class="bg-slate-900 border border-slate-800 text-slate-200 rounded-xl px-3 py-2 text-xs outline-none focus:border-indigo-500">
                    <option value="big">告警整帧（大图）</option>
                    <option value="crop">送检小图（目标裁切）</option>
                </select>
            </div>

            <div class="flex items-center gap-2">
                <span class="text-[11px] text-slate-500">返回条数</span>
                <select bind:value={topK} class="bg-slate-900 border border-slate-800 text-slate-200 rounded-xl px-3 py-2 text-xs outline-none focus:border-indigo-500">
                    <option value={12}>12</option>
                    <option value={24}>24</option>
                    <option value={48}>48</option>
                    <option value={100}>100</option>
                </select>
            </div>
        </div>

        {#if mode === 'text'}
            <div class="space-y-2">
                <textarea bind:value={query} rows="2" on:keydown={(e) => { if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) doTextSearch(); }}
                          placeholder="用中文描述你要找的画面，例如：穿红色上衣的人 / 没戴安全帽的工人 / 电动车进入电梯 / 画面里有一只狗"
                          class="w-full bg-slate-900 border border-slate-800 text-slate-100 rounded-xl px-4 py-3 text-sm placeholder-slate-500 outline-none focus:border-indigo-500 resize-none"></textarea>
                <div class="flex flex-wrap gap-2">
                    {#each ['穿红色上衣的人', '未戴安全帽', '电动车进入电梯', '有人翻越围墙', '画面中有烟雾', '夜间有人员徘徊'] as s}
                        <button on:click={() => (query = s)} class="text-[11px] text-slate-400 bg-slate-900 border border-slate-800 hover:border-indigo-500/60 hover:text-slate-200 rounded-full px-3 py-1 transition">{s}</button>
                    {/each}
                </div>
            </div>
        {:else}
            <div class="flex flex-wrap items-center gap-4">
                <label class="flex items-center gap-3 cursor-pointer">
                    <span class="text-xs text-slate-300 bg-slate-900 border border-slate-800 hover:border-indigo-500/60 rounded-xl px-4 py-2.5 transition">
                        <i class="fa-solid fa-upload mr-2"></i>选择图片
                    </span>
                    <input type="file" accept="image/*" on:change={onUploadPick} class="hidden" />
                    <span class="text-[11px] text-slate-500">{uploadFile ? uploadFile.name : '未选择文件'}</span>
                </label>
                {#if uploadPreview}
                    <img src={uploadPreview} alt="待检索图" class="h-16 w-24 object-cover rounded-lg border border-slate-800" />
                {/if}
            </div>
        {/if}

        <div class="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-5 gap-3 pt-1 border-t border-slate-800">
            <div class="flex flex-col space-y-1">
                <label class="text-[11px] text-slate-500" for="is-dev">设备</label>
                <select id="is-dev" bind:value={filters.deviceName} class="bg-slate-900 border border-slate-800 text-slate-200 rounded-xl px-3 py-2 text-xs outline-none focus:border-indigo-500">
                    <option value="">全部设备</option>
                    {#each $devices as d}<option value={d.name}>{d.name}</option>{/each}
                </select>
            </div>
            <div class="flex flex-col space-y-1">
                <label class="text-[11px] text-slate-500" for="is-chan">通道</label>
                <select id="is-chan" bind:value={filters.channelname} class="bg-slate-900 border border-slate-800 text-slate-200 rounded-xl px-3 py-2 text-xs outline-none focus:border-indigo-500">
                    <option value="">全部通道</option>
                    {#each channelOptions as c}<option value={c.name}>{c.name}</option>{/each}
                </select>
            </div>
            <div class="flex flex-col space-y-1">
                <label class="text-[11px] text-slate-500" for="is-type">预警类型</label>
                <input id="is-type" type="text" bind:value={filters.alertType} placeholder="如 INTRUSION（可留空）"
                       class="bg-slate-900 border border-slate-800 text-slate-200 rounded-xl px-3 py-2 text-xs placeholder-slate-500 outline-none focus:border-indigo-500" />
            </div>
            <div class="flex flex-col space-y-1">
                <label class="text-[11px] text-slate-500" for="is-start">开始时间</label>
                <input id="is-start" type="datetime-local" step="1" bind:value={filters.startDate}
                       class="bg-slate-900 border border-slate-800 text-slate-200 rounded-xl px-3 py-2 text-xs outline-none focus:border-indigo-500" />
            </div>
            <div class="flex flex-col space-y-1">
                <label class="text-[11px] text-slate-500" for="is-end">结束时间</label>
                <input id="is-end" type="datetime-local" step="1" bind:value={filters.endDate}
                       class="bg-slate-900 border border-slate-800 text-slate-200 rounded-xl px-3 py-2 text-xs outline-none focus:border-indigo-500" />
            </div>
        </div>

        <div class="flex flex-wrap items-center gap-3">
            <button on:click={mode === 'text' ? doTextSearch : doImageSearch} disabled={searching}
                    class="bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50 text-white rounded-xl px-5 py-2.5 text-sm font-bold shadow-sm flex items-center">
                <i class="fa-solid {searching ? 'fa-arrows-rotate animate-spin' : 'fa-magnifying-glass'} mr-2"></i>{searching ? '检索中' : '开始检索'}
            </button>
            <button on:click={resetFilters} class="text-xs text-slate-400 hover:text-slate-200 border border-slate-800 rounded-xl px-3 py-2.5 transition">重置筛选</button>
            {#if lastQueryLabel}<span class="text-[11px] text-slate-500">{lastQueryLabel} · 命中 {hits.length} 条</span>{/if}
        </div>

        {#if searchErr}
            <p class="text-[11px] text-amber-400/90"><i class="fa-solid fa-circle-info mr-1.5"></i>{searchErr}</p>
        {/if}
    </div>

    <!-- 结果图片墙 -->
    <div class="pb-6">
        {#if hits.length}
            <div class="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-6 gap-4">
                {#each hits as hit}
                    <div class="bg-slate-950 border border-slate-800 rounded-2xl overflow-hidden flex flex-col group">
                        <div class="relative aspect-video bg-slate-900 border-b border-slate-800 overflow-hidden">
                            {#if hit.imageUrl}
                                <img src="{API_BASE}{hit.imageUrl}" alt={hit.alertType} loading="lazy"
                                     class="w-full h-full object-cover cursor-zoom-in transition-transform duration-300 group-hover:scale-105"
                                     on:dblclick={() => (viewerImage = `${API_BASE}${hit.imageUrl}`)} title="双击查看大图" />
                            {:else}
                                <div class="flex items-center justify-center h-full text-slate-600 text-xs">无图</div>
                            {/if}
                            <div class="absolute top-2 right-2 px-1.5 py-0.5 rounded text-[10px] font-bold bg-indigo-600/90 text-white">
                                相似 {(hit.score * 100).toFixed(1)}%
                            </div>
                        </div>
                        <div class="p-3 space-y-1">
                            <p class="text-xs font-bold text-slate-200 truncate" title={hit.deviceName}>{hit.deviceName || '—'}</p>
                            <p class="text-[11px] text-slate-500 truncate" title={hit.alertType}>{hit.alertType || '—'}{hit.channelname ? ` · ${hit.channelname}` : ''}</p>
                            <p class="text-[10px] text-slate-600">{hit.time || fmtTime(hit.timestamp)}</p>
                        </div>
                    </div>
                {/each}
            </div>
        {:else if !searching}
            <div class="bg-slate-950 border border-slate-800 rounded-2xl p-10 text-center">
                <i class="fa-solid fa-images text-3xl text-slate-700 mb-3"></i>
                <p class="text-sm text-slate-400">还没有检索结果</p>
                <p class="text-[11px] text-slate-600 mt-1.5">
                    {#if (status?.index?.pending ?? 0) > 0 && (big.usable + crop.usable) === 0}
                        首次建索进行中：后台每 {idxCfg.interval_seconds || 60}s 处理 {idxCfg.per_cycle || 120} 张，可稍后再试（本页状态每 5s 自动刷新）。
                    {:else}
                        输入中文画面描述后点「开始检索」；结果按相似度排序，双击图片可看大图。
                    {/if}
                </p>
            </div>
        {/if}
    </div>
</div>

<!-- 大图查看 -->
{#if viewerImage}
    <div class="fixed inset-0 z-50 flex items-center justify-center bg-black/80 p-6" on:click|self={() => (viewerImage = null)}>
        <div class="relative max-w-6xl max-h-full">
            <img src={viewerImage} alt="大图" class="max-h-[85vh] rounded-xl border border-slate-700" />
            <button on:click={() => (viewerImage = null)} class="absolute -top-3 -right-3 w-8 h-8 rounded-full bg-slate-900 border border-slate-700 text-slate-300 hover:text-white">
                <i class="fa-solid fa-xmark"></i>
            </button>
        </div>
    </div>
{/if}
