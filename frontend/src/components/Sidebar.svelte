<script>
    import Icon from '../lib/Icon.svelte';
    import { createEventDispatcher } from 'svelte';

    export let activeMenu = 'devices';
    const dispatch = createEventDispatcher();

    const menuItems = [
        { id: 'devices', icon: 'Server', label: '设备接入' },
        { id: 'tasks', icon: 'ClipboardList', label: '任务管理' },
        { id: 'alerts', icon: 'AlertTriangle', label: '预警管理' },
        { id: 'services', icon: 'Settings', label: '服务管理' },
        { id: 'network', icon: 'Network', label: '网络配置' },
        { id: 'llm', icon: 'Cpu', label: '大模型配置' },
        { id: 'sessions', icon: 'MessageSquare', label: '会话管理' }
    ];

    function selectMenu(id) {
        activeMenu = id;
        dispatch('menuSelect', id);
    }
</script>

<aside class="w-64 bg-slate-900 text-slate-300 flex flex-col shadow-xl z-20 shrink-0">
    <div class="h-16 flex items-center px-6 border-b border-slate-800">
        <Icon name="Activity" className="w-6 h-6 text-blue-500 mr-3" />
        <h1 class="text-lg font-bold text-white tracking-wider">智能管理平台</h1>
    </div>
    <nav class="flex-1 py-6 px-3 space-y-2">
        {#each menuItems as item}
            <button on:click={() => selectMenu(item.id)} class="w-full flex items-center px-4 py-3 rounded-lg cursor-pointer transition-colors {activeMenu === item.id ? 'bg-blue-600 text-white shadow-md' : 'hover:bg-slate-800 hover:text-white'}">
                <Icon name={item.icon} className="w-5 h-5 mr-3" />
                <span class="font-medium">{item.label}</span>
            </button>
        {/each}
    </nav>
</aside>
