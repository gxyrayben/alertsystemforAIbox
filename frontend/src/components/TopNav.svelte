<script>
    import { createEventDispatcher } from 'svelte';
    import { devices, selectedDevice, selectDevice } from '../lib/controlStore.js';

    export let activeMenu = 'devices';
    const dispatch = createEventDispatcher();

    // 顶部“当前设备”下拉开关
    let deviceMenuOpen = false;
    function pickDevice(id) {
        selectDevice(id);
        deviceMenuOpen = false;
    }
    function statusDot(status) {
        if (status === '在线') return 'bg-emerald-400';
        if (status === '异常') return 'bg-rose-400';
        return 'bg-slate-500';
    }

    // 归属于“基础配置”的子功能项
    const basicIds = ['devices', 'tasks', 'logs', 'services', 'network', 'llm'];

    // fa = FontAwesome 图标类；badge = 右上角红色计数（可选）
    const menuItems = [
        { id: 'aicontrol', fa: 'fa-comments', label: 'AI 双模态布控' },
        { id: 'taskops', fa: 'fa-table-list', label: '任务运维列表' },
        { id: 'feedback', fa: 'fa-circle-exclamation', label: '告警反馈闭环', badge: 1 },
        { id: 'alerts', fa: 'fa-bell', label: '预警管理' },
        { id: 'library', fa: 'fa-diagram-project', label: '智能体资产库' },
        { id: 'basic', fa: 'fa-gear', label: '基础配置' }
    ];

    // 当前激活的顶部项：基础配置下的任意子项都算作 basic 激活
    $: isItemActive = (id) =>
        id === 'basic' ? basicIds.includes(activeMenu) || activeMenu === 'basic' : activeMenu === id;

    function selectMenu(id) {
        activeMenu = id;
        dispatch('menuSelect', id);
    }
</script>

<header class="h-16 bg-surface2 border-b border-edge flex items-center px-5 gap-5 shrink-0 z-20">
    <!-- Logo + 标题 -->
    <div class="flex items-center gap-3 shrink-0">
        <div class="w-10 h-10 rounded-xl bg-gradient-to-br from-accent to-accent2 flex items-center justify-center shadow-lg shadow-accent/30">
            <i class="fa-solid fa-shield-halved text-white text-lg"></i>
        </div>
        <div class="leading-tight hidden xl:block">
            <h1 class="text-base font-bold text-white tracking-wide">AI视觉布控优化系统</h1>
            <p class="text-[11px] text-muted">Integrated Security Management</p>
        </div>
    </div>

    <!-- 横向导航：药丸标签组，包在一个带边框的圆角容器里 -->
    <nav class="flex-1 flex items-center gap-1 overflow-x-auto min-w-0 bg-bg/40 border border-edge/70 rounded-2xl p-1.5">
        {#each menuItems as item}
            <button
                on:click={() => selectMenu(item.id)}
                class="relative flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-semibold whitespace-nowrap transition-all
                {isItemActive(item.id)
                    ? 'bg-indigo-600 text-white shadow-lg shadow-indigo-500/30'
                    : 'text-muted hover:bg-surface hover:text-ink'}"
            >
                <i class="fa-solid {item.fa} text-[15px] {isItemActive(item.id) ? 'text-white' : 'text-slate-400'}"></i>
                <span>{item.label}</span>
                {#if item.badge}
                    <span class="inline-flex items-center justify-center min-w-[18px] h-[18px] px-1 ml-0.5 text-[10px] font-bold text-white bg-rose-500 rounded-full leading-none shadow shadow-rose-500/40">
                        {item.badge}
                    </span>
                {/if}
            </button>
        {/each}
    </nav>

    <!-- 右侧状态：当前设备下拉选择 -->
    <div class="flex items-center gap-3 shrink-0">
        <div class="relative">
            <button
                on:click={() => (deviceMenuOpen = !deviceMenuOpen)}
                class="flex items-center gap-2 px-3.5 py-2 rounded-xl bg-emerald-500/10 border border-emerald-500/30 hover:bg-emerald-500/15 transition-colors"
            >
                <span class="w-2 h-2 rounded-full {statusDot($selectedDevice?.status)} {$selectedDevice?.status === '在线' ? 'animate-pulse' : ''}"></span>
                <span class="text-sm font-semibold text-emerald-300 whitespace-nowrap max-w-[180px] truncate">
                    {$selectedDevice ? $selectedDevice.name : '未选择设备'}
                </span>
                <i class="fa-solid fa-chevron-down text-[10px] text-emerald-400/80 transition-transform {deviceMenuOpen ? 'rotate-180' : ''}"></i>
            </button>

            {#if deviceMenuOpen}
                <!-- 点击外部关闭 -->
                <div class="fixed inset-0 z-30" on:click={() => (deviceMenuOpen = false)}></div>
                <div class="absolute right-0 mt-2 w-72 bg-surface2 border border-edge rounded-xl shadow-2xl z-40 overflow-hidden">
                    <div class="px-3.5 py-2.5 border-b border-edge">
                        <p class="text-[11px] font-semibold text-muted uppercase tracking-wider">选择当前设备</p>
                    </div>
                    <div class="max-h-80 overflow-y-auto py-1">
                        {#each $devices as d}
                            <button
                                on:click={() => pickDevice(d.id)}
                                class="w-full flex items-center gap-2.5 px-3.5 py-2.5 text-left transition-colors
                                {$selectedDevice && String($selectedDevice.id) === String(d.id) ? 'bg-indigo-600/20' : 'hover:bg-surface'}"
                            >
                                <span class="w-2 h-2 rounded-full shrink-0 {statusDot(d.status)}"></span>
                                <span class="flex-1 min-w-0">
                                    <span class="block text-sm font-semibold text-ink truncate">{d.name}</span>
                                    <span class="block text-[11px] text-muted font-mono truncate">{d.ip}:{d.port}</span>
                                </span>
                                {#if $selectedDevice && String($selectedDevice.id) === String(d.id)}
                                    <i class="fa-solid fa-check text-indigo-400 text-xs shrink-0"></i>
                                {/if}
                            </button>
                        {:else}
                            <div class="px-3.5 py-4 text-center text-xs text-muted">暂无设备，请到「设备接入」添加</div>
                        {/each}
                    </div>
                </div>
            {/if}
        </div>
        <div class="w-9 h-9 rounded-full bg-gradient-to-br from-accent to-accent2 flex items-center justify-center text-white text-sm font-bold ring-2 ring-edge shrink-0">
            A
        </div>
    </div>
</header>
