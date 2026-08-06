<script>
    import { tasksList, showToast, switchTab, requestChat, selectedDevice } from '../lib/controlStore.js';

    let search = '';

    $: deviceName = $selectedDevice?.name;
    $: tasks = $tasksList.filter((t) => {
        const matchesDevice = !deviceName || t.device === deviceName;
        const q = search.trim();
        const matchesSearch = !q || t.name.includes(q) || (t.agentType || '').includes(q);
        return matchesDevice && matchesSearch;
    });

    function fineTune(task) {
        switchTab('aicontrol');
        requestChat('loadConfig', { ...task });
    }

    function toggleStatus(task) {
        tasksList.update((list) =>
            list.map((t) => (t.id === task.id ? { ...t, status: t.status === 'active' ? 'paused' : 'active' } : t))
        );
        showToast(task.status === 'active' ? '任务已挂起，小模型端侧过滤器已释放。' : '重新启动边缘流与后置Agent管道。', task.status === 'active' ? 'info' : 'success');
    }

    function removeTask(task) {
        tasksList.update((list) => list.filter((t) => t.id !== task.id));
        showToast('布控级联任务已被删除清除。', 'warning');
    }
</script>

<div class="max-w-6xl mx-auto space-y-6">
    <!-- 头部/搜索 -->
    <div class="flex flex-col sm:flex-row justify-between items-start sm:items-center bg-slate-950 p-5 rounded-2xl border border-slate-800 gap-4">
        <div>
            <h2 class="text-base font-bold text-white">级联布控实时任务列表</h2>
            <p class="text-xs text-slate-400 mt-0.5">展示端侧小模型与云边 VLM Agent 高敏智能体的级联链路</p>
            <span class="inline-flex items-center gap-1.5 mt-2 text-[11px] bg-emerald-500/10 text-emerald-300 border border-emerald-500/30 px-2.5 py-1 rounded-lg">
                <i class="fa-solid fa-video text-[10px]"></i> 当前设备：<strong>{deviceName || '未选择'}</strong>
            </span>
        </div>
        <div class="flex items-center space-x-2 w-full sm:w-auto">
            <div class="relative flex-1 sm:flex-initial">
                <i class="fa-solid fa-magnifying-glass absolute left-3 top-1/2 -translate-y-1/2 text-slate-500 text-xs"></i>
                <input bind:value={search} type="text" placeholder="搜索设备/关联智能体..." class="w-full sm:w-60 bg-slate-900 border border-slate-800 text-slate-100 rounded-xl pl-9 pr-4 py-1.5 text-xs focus:border-indigo-500" />
            </div>
            <button on:click={() => switchTab('aicontrol')} class="bg-indigo-600 hover:bg-indigo-700 text-white px-3.5 py-1.5 rounded-xl text-xs font-bold flex items-center transition-all shadow-sm shrink-0">
                <i class="fa-solid fa-plus mr-1.5"></i> 新增对话布控
            </button>
        </div>
    </div>

    <!-- 统计 -->
    <div class="grid grid-cols-1 sm:grid-cols-4 gap-4">
        <div class="bg-slate-950 p-4 rounded-xl border border-slate-800 flex items-center justify-between">
            <div><p class="text-[11px] text-slate-400 font-medium">双模级联任务</p><p class="text-xl font-bold text-slate-100 mt-1">{tasks.length} <span class="text-xs text-slate-500 font-normal">项活动</span></p></div>
            <div class="bg-indigo-500/10 text-indigo-400 p-3 rounded-lg"><i class="fa-solid fa-network-wired text-lg"></i></div>
        </div>
        <div class="bg-slate-950 p-4 rounded-xl border border-slate-800 flex items-center justify-between">
            <div><p class="text-[11px] text-slate-400 font-medium">小模型初筛吞吐</p><p class="text-xl font-bold text-amber-500 mt-1">4,281 <span class="text-xs text-slate-500 font-normal">帧/日</span></p></div>
            <div class="bg-amber-500/10 text-amber-400 p-3 rounded-lg"><i class="fa-solid fa-shield-halved text-lg"></i></div>
        </div>
        <div class="bg-slate-950 p-4 rounded-xl border border-slate-800 flex items-center justify-between">
            <div><p class="text-[11px] text-slate-400 font-medium">智能体精筛选小图</p><p class="text-xl font-bold text-emerald-400 mt-1">118 <span class="text-xs text-slate-500 font-normal">次/日</span></p></div>
            <div class="bg-emerald-500/10 text-emerald-400 p-3 rounded-lg"><i class="fa-solid fa-crop text-lg"></i></div>
        </div>
        <div class="bg-slate-950 p-4 rounded-xl border border-slate-800 flex items-center justify-between">
            <div><p class="text-[11px] text-slate-400 font-medium">节省边缘带宽比例</p><p class="text-xl font-bold text-sky-400 mt-1">87.5% <span class="text-xs text-slate-500 font-normal">减少率</span></p></div>
            <div class="bg-sky-500/10 text-sky-400 p-3 rounded-lg"><i class="fa-solid fa-chart-line text-lg"></i></div>
        </div>
    </div>

    <!-- 任务卡片 -->
    <div class="grid grid-cols-1 gap-4">
        {#each tasks as task (task.id)}
            <div class="bg-slate-950 p-5 rounded-2xl border border-slate-800 flex flex-col md:flex-row md:items-center justify-between gap-4 hover:border-slate-700 transition-all">
                <div class="space-y-2 max-w-2xl">
                    <div class="flex items-center space-x-2">
                        <span class="text-[10px] bg-slate-900 text-slate-400 border border-slate-800 font-bold px-2 py-0.5 rounded">任务ID: {task.id}</span>
                        {#if task.status === 'active'}
                            <span class="text-[10px] bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 font-semibold px-2 py-0.5 rounded flex items-center"><span class="w-1.5 h-1.5 bg-emerald-500 rounded-full mr-1 animate-pulse"></span> 级联级运行中</span>
                        {:else}
                            <span class="text-[10px] bg-slate-700/30 text-slate-400 border border-slate-700 font-semibold px-2 py-0.5 rounded flex items-center"><span class="w-1.5 h-1.5 bg-slate-500 rounded-full mr-1"></span> 已挂起</span>
                        {/if}
                    </div>
                    <h3 class="font-bold text-slate-100 text-sm">{task.name}</h3>
                    <div class="grid grid-cols-2 gap-4 bg-slate-900/60 p-2.5 rounded-lg border border-slate-800/80 text-[11px]">
                        <div class="text-slate-400"><strong class="text-amber-400">前置初筛：</strong> 目标[{task.yoloTarget}], 人体阈值[{task.yoloHumanThresh}], 扩图[上{task.cropUp}, 下{task.cropDown}, 左{task.cropLeft}, 右{task.cropRight}]</div>
                        <div class="text-slate-400"><strong class="text-indigo-400">Agent深度：</strong> 使用[{task.agentType}]智能体分析小图，高精度规避漏报</div>
                    </div>
                    <p class="text-[10px] text-slate-400 font-mono line-clamp-1 leading-relaxed bg-slate-900 p-2 rounded border border-slate-800"><strong>Agent Prompt:</strong> {task.prompt}</p>
                    <div class="flex flex-wrap gap-4 text-[11px] text-slate-500 pt-1">
                        <span><i class="fa-solid fa-video mr-1"></i> 设备: <strong>{task.device || deviceName || '—'}</strong></span>
                        <span><i class="fa-solid fa-clock mr-1"></i> 报警间隔: <strong>{task.alarmInterval}秒</strong></span>
                        <span><i class="fa-solid fa-bell mr-1"></i> 今日小图送检: <strong class="text-slate-300">{task.todayAlerts} 次</strong></span>
                    </div>
                </div>
                <div class="flex flex-col sm:flex-row items-stretch md:items-center gap-2 shrink-0">
                    <button on:click={() => fineTune(task)} class="bg-indigo-500/10 hover:bg-indigo-500/25 text-indigo-400 border border-indigo-500/30 px-4 py-2 rounded-xl text-xs font-bold transition-all flex items-center justify-center"><i class="fa-solid fa-wand-magic-sparkles mr-1.5"></i> 对话级微调</button>
                    {#if task.status === 'active'}
                        <button on:click={() => toggleStatus(task)} class="bg-amber-500/10 hover:bg-amber-500/20 text-amber-400 border border-amber-500/30 px-4 py-2 rounded-xl text-xs font-bold transition-all flex items-center justify-center"><i class="fa-solid fa-pause mr-1.5"></i> 暂停</button>
                    {:else}
                        <button on:click={() => toggleStatus(task)} class="bg-emerald-500/10 hover:bg-emerald-500/20 text-emerald-400 border border-emerald-500/30 px-4 py-2 rounded-xl text-xs font-bold transition-all flex items-center justify-center"><i class="fa-solid fa-play mr-1.5"></i> 开启</button>
                    {/if}
                    <button on:click={() => removeTask(task)} class="bg-rose-500/10 hover:bg-rose-500/20 text-rose-400 border border-rose-500/30 p-2 rounded-xl text-xs transition-all flex items-center justify-center"><i class="fa-solid fa-trash"></i></button>
                </div>
            </div>
        {:else}
            <div class="bg-slate-950 p-12 text-center rounded-2xl border border-slate-800 text-slate-500">
                <i class="fa-solid fa-rectangle-list text-4xl mb-3 text-slate-700"></i>
                <p class="text-xs">设备 [{deviceName || '未选择'}] 暂无级联任务，请在「AI 双模态布控」对话框下发。</p>
            </div>
        {/each}
    </div>
</div>
