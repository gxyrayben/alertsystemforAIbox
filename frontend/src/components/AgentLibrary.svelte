<script>
    import { onMount } from 'svelte';
    import { switchTab, requestChat, selectedDevice, loadDevices, showToast } from '../lib/controlStore.js';
    import { apiGet, apiPost } from '../lib/api.js';

    // ── 设备真实智能体 ──────────────────────────────────────────
    let agents = [];
    let loading = false;
    let showModal = false;
    let saving = false;
    let form = { event_tag: '', event_id: '', alarm_type: 'freeform', prompt: '', alarm_condition: '' };

    const ALARM_LABELS = { freeform: '描述型', yesno: '判断型' };

    // 从当前设备的快照（device.agents JSON 字符串）种入卡片，无需网络
    function seedFromSnapshot(device) {
        if (!device) { agents = []; return; }
        try {
            const parsed = JSON.parse(device.agents || '[]');
            agents = Array.isArray(parsed) ? parsed : [];
        } catch {
            agents = [];
        }
    }

    // selectedDevice 变化（切换顶栏设备）时即时刷新卡片
    $: seedFromSnapshot($selectedDevice);

    onMount(async () => {
        // 拉取全局设备存储，拿到 添加/获取详情 后持久化的最新 agents 快照
        await loadDevices();
    });

    // 刷新按钮：实时从设备拉取
    async function refreshAgents() {
        const dev = $selectedDevice;
        if (!dev) { showToast('请先在顶栏选择一个设备', 'error'); return; }
        loading = true;
        try {
            const res = await apiGet(`/devices/${dev.id}/agents`);
            agents = res.agents || [];
            showToast(`已从设备同步 ${res.count} 个智能体`, 'success');
        } catch (e) {
            // 设备离线/不可达：保留上次快照展示
            showToast(e.detail || '设备离线或不可达，展示上次同步结果', 'error');
        } finally {
            loading = false;
        }
    }

    function openModal() {
        if (!$selectedDevice) { showToast('请先在顶栏选择一个设备', 'error'); return; }
        form = { event_tag: '', event_id: '', alarm_type: 'freeform', prompt: '', alarm_condition: '' };
        showModal = true;
    }

    async function submitAgent() {
        const dev = $selectedDevice;
        if (!dev) { showToast('请先在顶栏选择一个设备', 'error'); return; }
        if (!form.event_tag.trim() || !form.event_id.trim() || !form.prompt.trim()) {
            showToast('名称、标识、提示词均为必填', 'error');
            return;
        }
        saving = true;
        try {
            const payload = {
                event_id: form.event_id.trim(),
                event_tag: form.event_tag.trim(),
                prompt: form.prompt.trim(),
                alarm_type: form.alarm_type,
                alarm_condition: form.alarm_condition.trim() || null
            };
            const res = await apiPost(`/devices/${dev.id}/agents`, payload);
            agents = res.agents || [];   // 下发后自动重新拉取并刷新
            showModal = false;
            showToast(res.message || '已下发到设备', 'success');
        } catch (e) {
            showToast(e.detail || '新增智能体失败（设备可能离线）', 'error');
        } finally {
            saving = false;
        }
    }

    // ── 内置级联模板（保留） ─────────────────────────────────────
    const templates = [
        { icon: 'fa-person-falling', iconWrap: 'bg-indigo-500/10 text-indigo-400 border-indigo-500/20', tag: '小+大级联模版', tagWrap: 'bg-indigo-950 text-indigo-400 border-indigo-500/30',
          title: '人员异常形体判定级联智能体', desc: '前置端侧小模型识别人体、过滤非人物体；仅裁切人体周边框图送交大模型 Agent 进行严密的滑倒、躺卧、检修等复杂动作精细区分。', thresh: '0.31', apply: '人员跌倒判定' },
        { icon: 'fa-truck', iconWrap: 'bg-amber-500/10 text-amber-400 border-amber-500/20', tag: '安全红线类', tagWrap: 'bg-slate-900 text-slate-400 border-slate-800',
          title: '机动车入侵与卸载物姿态检测', desc: '前置小模型监控通道内车辆或工程车入侵，发现后精确向外扩图 0.6 倍裁剪高空吊挂范围，大模型二次精审钢爪、吊钩绳索锁扣安全系数。', thresh: '0.32', apply: '吊装物状态' },
        { icon: 'fa-hard-hat', iconWrap: 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20', tag: 'PPE装备类', tagWrap: 'bg-slate-900 text-slate-400 border-slate-800',
          title: '劳保穿戴与行为规约分析级联', desc: '前置人体、人脸小模型捕获进入的高危作业者，自动向上和向下扩大框图截取肩部、躯干，多模态智能体大模型精细推理安全帽背心反光条完好度。', thresh: '0.35', apply: '劳保用品穿戴' }
    ];

    function useTemplate(name) {
        switchTab('aicontrol');
        requestChat('useTemplate', name);
    }
</script>

<div class="max-w-6xl mx-auto space-y-8">
    <!-- 分区一：设备智能体 -->
    <div>
        <div class="flex items-start justify-between gap-4 flex-wrap">
            <div>
                <h2 class="text-base font-bold text-white">设备智能体资产</h2>
                <p class="text-xs text-slate-400 mt-1">从当前设备实时获取的大模型智能体算法，可刷新同步或新增下发。</p>
                <span class="inline-flex items-center gap-1.5 mt-2 text-[11px] bg-emerald-500/10 text-emerald-300 border border-emerald-500/30 px-2.5 py-1 rounded-lg">
                    <i class="fa-solid fa-video text-[10px]"></i> 当前作用设备：<strong>{$selectedDevice?.name || '未选择'}</strong>
                </span>
            </div>
            <div class="flex items-center gap-2">
                <button on:click={refreshAgents} disabled={loading}
                    class="inline-flex items-center gap-1.5 text-xs bg-slate-800 hover:bg-slate-700 disabled:opacity-50 text-slate-200 border border-slate-700 px-3 py-1.5 rounded-lg transition-colors">
                    <i class="fa-solid fa-rotate {loading ? 'fa-spin' : ''} text-[11px]"></i> 刷新
                </button>
                <button on:click={openModal}
                    class="inline-flex items-center gap-1.5 text-xs bg-indigo-600 hover:bg-indigo-500 text-white px-3 py-1.5 rounded-lg transition-colors">
                    <i class="fa-solid fa-plus text-[11px]"></i> 新增智能体
                </button>
            </div>
        </div>

        {#if !$selectedDevice}
            <div class="mt-4 text-center text-xs text-slate-500 border border-dashed border-slate-800 rounded-2xl py-10">
                请先在顶栏选择一个设备以查看其智能体算法。
            </div>
        {:else if agents.length === 0}
            <div class="mt-4 text-center text-xs text-slate-500 border border-dashed border-slate-800 rounded-2xl py-10">
                当前设备暂无智能体算法，点击「刷新」从设备同步，或「新增智能体」下发一个。
            </div>
        {:else}
            <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6 mt-4">
                {#each agents as a}
                    <div class="bg-slate-950 p-5 rounded-2xl border border-slate-800 hover:border-indigo-500/50 transition-all shadow-sm space-y-4">
                        <div class="flex justify-between items-start">
                            <span class="bg-sky-500/10 text-sky-400 border-sky-500/20 p-2.5 rounded-xl border"><i class="fa-solid fa-robot text-lg"></i></span>
                            <span class="text-[9px] {a.alarm_type === 'yesno' ? 'bg-amber-950 text-amber-400 border-amber-500/30' : 'bg-slate-900 text-slate-400 border-slate-800'} border px-2 py-0.5 rounded font-bold">
                                {ALARM_LABELS[a.alarm_type] || a.alarm_type || '未知'}
                            </span>
                        </div>
                        <div>
                            <h3 class="font-bold text-white text-xs">{a.event_tag || a.event_id || '(未命名)'}</h3>
                            <p class="text-[11px] text-slate-400 mt-1.5 leading-relaxed line-clamp-3">{a.prompt || '（无提示词）'}</p>
                        </div>
                        <div class="pt-2 border-t border-slate-800 flex items-center justify-between text-[10px] text-slate-500">
                            <span>ID: {a.agent_id ?? '-'}</span>
                            <span>事件: {a.event_id ?? '-'}</span>
                        </div>
                    </div>
                {/each}
            </div>
        {/if}
    </div>

    <!-- 分区二：内置级联模板 -->
    <div>
        <h2 class="text-base font-bold text-white">级联智能体基础模板库</h2>
        <p class="text-xs text-slate-400 mt-1">内置结合小模型前置过滤器与大模型 Agent 的级联高敏模板，支持开箱即用及自由组装。</p>

        <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6 mt-4">
            {#each templates as t}
                <div class="bg-slate-950 p-5 rounded-2xl border border-slate-800 hover:border-indigo-500/50 transition-all shadow-sm space-y-4">
                    <div class="flex justify-between items-start">
                        <span class="{t.iconWrap} p-2.5 rounded-xl border"><i class="fa-solid {t.icon} text-lg"></i></span>
                        <span class="text-[9px] {t.tagWrap} border px-2 py-0.5 rounded font-bold">{t.tag}</span>
                    </div>
                    <div>
                        <h3 class="font-bold text-white text-xs">{t.title}</h3>
                        <p class="text-[11px] text-slate-400 mt-1.5 leading-relaxed">{t.desc}</p>
                    </div>
                    <div class="pt-2 border-t border-slate-800 flex items-center justify-between text-[10px]">
                        <span class="text-slate-500">建议小模型阈值: {t.thresh}</span>
                        <button on:click={() => useTemplate(t.apply)} class="text-indigo-400 font-bold hover:text-indigo-300 transition-colors">立即对话应用 <i class="fa-solid fa-arrow-right ml-1"></i></button>
                    </div>
                </div>
            {/each}
        </div>
    </div>
</div>

<!-- 新增智能体模态 -->
{#if showModal}
    <div class="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4" on:click|self={() => showModal = false}>
        <div class="bg-slate-900 border border-slate-700 rounded-2xl w-full max-w-lg p-6 space-y-4 shadow-2xl">
            <div class="flex items-center justify-between">
                <h3 class="text-sm font-bold text-white">新增智能体（下发到「{$selectedDevice?.name}」）</h3>
                <button on:click={() => showModal = false} class="text-slate-400 hover:text-white"><i class="fa-solid fa-xmark"></i></button>
            </div>

            <div class="space-y-3">
                <div>
                    <label class="text-[11px] text-slate-400">名称 (event_tag)<span class="text-red-400">*</span></label>
                    <input bind:value={form.event_tag} placeholder="如 高空抛物检测"
                        class="w-full mt-1 bg-slate-950 border border-slate-700 rounded-lg px-3 py-2 text-xs text-white focus:border-indigo-500 outline-none" />
                </div>
                <div>
                    <label class="text-[11px] text-slate-400">标识 (event_id)<span class="text-red-400">*</span></label>
                    <input bind:value={form.event_id} placeholder="英文/数字，如 high_altitude_throw"
                        class="w-full mt-1 bg-slate-950 border border-slate-700 rounded-lg px-3 py-2 text-xs text-white focus:border-indigo-500 outline-none" />
                </div>
                <div>
                    <label class="text-[11px] text-slate-400">类型</label>
                    <select bind:value={form.alarm_type}
                        class="w-full mt-1 bg-slate-950 border border-slate-700 rounded-lg px-3 py-2 text-xs text-white focus:border-indigo-500 outline-none">
                        <option value="freeform">描述型 (freeform)</option>
                        <option value="yesno">判断型 (yesno)</option>
                    </select>
                </div>
                <div>
                    <label class="text-[11px] text-slate-400">提示词 (prompt)<span class="text-red-400">*</span></label>
                    <textarea bind:value={form.prompt} rows="4" placeholder="描述该智能体的分析任务与报警条件"
                        class="w-full mt-1 bg-slate-950 border border-slate-700 rounded-lg px-3 py-2 text-xs text-white focus:border-indigo-500 outline-none resize-none"></textarea>
                </div>
                <div>
                    <label class="text-[11px] text-slate-400">报警条件 (可选，留空按类型默认)</label>
                    <input bind:value={form.alarm_condition} placeholder="留空即可，如 only_yes / none"
                        class="w-full mt-1 bg-slate-950 border border-slate-700 rounded-lg px-3 py-2 text-xs text-white focus:border-indigo-500 outline-none" />
                </div>
            </div>

            <div class="flex justify-end gap-2 pt-2">
                <button on:click={() => showModal = false}
                    class="text-xs bg-slate-800 hover:bg-slate-700 text-slate-200 px-4 py-2 rounded-lg transition-colors">取消</button>
                <button on:click={submitAgent} disabled={saving}
                    class="text-xs bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white px-4 py-2 rounded-lg transition-colors">
                    {saving ? '下发中...' : '下发到设备'}
                </button>
            </div>
        </div>
    </div>
{/if}
