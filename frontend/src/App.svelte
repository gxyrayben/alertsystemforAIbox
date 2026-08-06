<script>
    import TopNav from './components/TopNav.svelte';
    import Devices from './components/Devices.svelte';
    import Tasks from './components/Tasks.svelte';
    import Alerts from './components/Alerts.svelte';
    import Network from './components/Network.svelte';
    import Services from './components/Services.svelte';
    import LLMConfig from './components/LLMConfig.svelte';
    import Logs from './components/Logs.svelte';
    import AIControl from './components/AIControl.svelte';
    import TaskOps from './components/TaskOps.svelte';
    import Feedback from './components/Feedback.svelte';
    import AgentLibrary from './components/AgentLibrary.svelte';
    import Toast from './components/Toast.svelte';
    import { onMount } from 'svelte';
    import { activeMenu, switchTab, loadDevices } from './lib/controlStore.js';

    onMount(() => {
        loadDevices();
    });

    // 基础配置下的子功能项
    const basicItems = [
        { id: 'devices', fa: 'fa-server', label: '设备接入' },
        { id: 'tasks', fa: 'fa-list-check', label: '任务管理' },
        { id: 'alerts', fa: 'fa-bell', label: '预警管理' },
        { id: 'logs', fa: 'fa-file-lines', label: '日志管理' },
        { id: 'services', fa: 'fa-gears', label: '服务管理' },
        { id: 'network', fa: 'fa-network-wired', label: '网络配置' },
        { id: 'llm', fa: 'fa-microchip', label: '模型配置' }
    ];
    const basicIds = basicItems.map((i) => i.id);

    $: isBasic = basicIds.includes($activeMenu);

    function handleMenuSelect(event) {
        const id = event.detail;
        // 点击“基础配置”默认进入第一个子项
        switchTab(id === 'basic' ? basicItems[0].id : id);
    }
</script>

<div class="flex flex-col h-screen bg-bg text-ink font-sans">
    <TopNav activeMenu={$activeMenu} on:menuSelect={handleMenuSelect} />

    {#if isBasic}
        <!-- 基础配置：左侧功能项 + 右侧内容 -->
        <div class="flex-1 flex overflow-hidden min-w-0">
            <aside class="w-56 shrink-0 bg-surface2 border-r border-edge p-3 overflow-y-auto">
                <p class="px-3 py-2 text-xs font-semibold text-muted uppercase tracking-wider">基础配置</p>
                <nav class="flex flex-col gap-1">
                    {#each basicItems as item}
                        <button
                            on:click={() => switchTab(item.id)}
                            class="flex items-center px-3 py-2.5 rounded-xl text-sm font-semibold transition-all text-left
                            {$activeMenu === item.id
                                ? 'bg-indigo-600 text-white shadow-lg shadow-indigo-500/30'
                                : 'text-muted hover:bg-surface hover:text-ink'}"
                        >
                            <i class="fa-solid {item.fa} w-5 mr-2.5 text-center {$activeMenu === item.id ? 'text-white' : 'text-slate-400'}"></i>
                            {item.label}
                        </button>
                    {/each}
                </nav>
            </aside>

            <main class="flex-1 overflow-auto p-6 min-w-0">
                {#if $activeMenu === 'devices'}
                    <Devices />
                {:else if $activeMenu === 'tasks'}
                    <Tasks />
                {:else if $activeMenu === 'alerts'}
                    <Alerts />
                {:else if $activeMenu === 'logs'}
                    <Logs />
                {:else if $activeMenu === 'network'}
                    <Network />
                {:else if $activeMenu === 'llm'}
                    <LLMConfig />
                {:else if $activeMenu === 'services'}
                    <Services />
                {/if}
            </main>
        </div>
    {:else}
        <main class="flex-1 overflow-auto p-6 min-w-0">
            {#if $activeMenu === 'aicontrol'}
                <AIControl />
            {:else if $activeMenu === 'taskops'}
                <TaskOps />
            {:else if $activeMenu === 'feedback'}
                <Feedback />
            {:else if $activeMenu === 'library'}
                <AgentLibrary />
            {/if}
        </main>
    {/if}
</div>

<Toast />

<style>
    :global(.animate-spin) {
        animation: spin 2s linear infinite;
    }
    @keyframes spin {
        from { transform: rotate(0deg); }
        to { transform: rotate(360deg); }
    }
</style>
