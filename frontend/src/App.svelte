<script>
    import Sidebar from './components/Sidebar.svelte';
    import Devices from './components/Devices.svelte';
    import Tasks from './components/Tasks.svelte';
    import Alerts from './components/Alerts.svelte';
    import Network from './components/Network.svelte';
    import Services from './components/Services.svelte';
    import LLMConfig from './components/LLMConfig.svelte';
    import Logs from './components/Logs.svelte';
    import Sessions from './components/Sessions.svelte';

    let activeMenu = localStorage.getItem('activeMenu') || 'network';
    
    $: if (activeMenu) {
        localStorage.setItem('activeMenu', activeMenu);
    }

    const menuTitles = {
        'devices': '设备接入',
        'tasks': '任务管理',
        'alerts': '预警管理',
        'services': '服务管理',
        'network': '网络配置',
        'llm': '模型配置',
        'sessions': '会话管理',
        'logs': '日志管理'
    };

    function handleMenuSelect(event) {
        activeMenu = event.detail;
    }
</script>

<div class="flex h-screen bg-gray-100 text-gray-800 font-sans">
    <Sidebar {activeMenu} on:menuSelect={handleMenuSelect} />

    <main class="flex-1 flex flex-col overflow-hidden min-w-0">
        <header class="h-16 bg-white border-b border-gray-200 flex items-center px-8 shadow-sm shrink-0">
            <h2 class="text-xl font-semibold text-gray-800">
                {menuTitles[activeMenu]}
            </h2>
        </header>

        <div class="flex-1 overflow-auto p-6">
            {#if activeMenu === 'devices'}
                <Devices />
            {:else if activeMenu === 'tasks'}
                <Tasks />
            {:else if activeMenu === 'alerts'}
                <Alerts />
            {:else if activeMenu === 'network'}
                <Network />
            {:else if activeMenu === 'llm'}
                <LLMConfig />
            {:else if activeMenu === 'logs'}
                <Logs />
            {:else if activeMenu === 'services'}
                <Services />
            {:else if activeMenu === 'sessions'}
                <Sessions />
            {/if}
        </div>
    </main>
</div>

<style>
    :global(body) {
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
    }
    
    :global(.animate-spin) {
        animation: spin 2s linear infinite;
    }
    @keyframes spin {
        from { transform: rotate(0deg); }
        to { transform: rotate(360deg); }
    }
</style>
