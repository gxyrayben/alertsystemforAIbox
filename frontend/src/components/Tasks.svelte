<script>
    import { onMount } from 'svelte';
    import Icon from '../lib/Icon.svelte';
    import TaskModal from './TaskModal.svelte';

    export let API_BASE = 'http://localhost:8000';

    let tasks = [];
    let devices = [];
    let total = 0;
    let page = 1;
    const size = 10;

    let showModal = false;
    let editingTask = null;

    onMount(async () => {
        await fetchDevices();
        await fetchTasks();
    });

    async function fetchDevices() {
        try {
            const res = await fetch(`${API_BASE}/api/devices`);
            if (res.ok) {
                devices = await res.json();
            }
        } catch (error) {
            console.error("Failed to fetch devices", error);
        }
    }

    async function fetchTasks() {
        try {
            const res = await fetch(`${API_BASE}/api/tasks?page=${page}&size=${size}`);
            if (res.ok) {
                const data = await res.json();
                tasks = data.tasks;
                total = data.total;
            }
        } catch (error) {
            console.error("Failed to fetch tasks", error);
        }
    }

    function openModal(task = null) {
        editingTask = task;
        showModal = true;
    }

    function closeModal() {
        showModal = false;
        editingTask = null;
    }

    async function saveTask(event) {
        const taskData = event.detail;
        const method = editingTask ? 'PUT' : 'POST';
        const url = editingTask ? `${API_BASE}/api/tasks/${editingTask.id}` : `${API_BASE}/api/tasks`;
        
        try {
            const res = await fetch(url, {
                method,
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(taskData)
            });
            if (res.ok) {
                closeModal();
                fetchTasks();
            } else {
                alert('保存失败');
            }
        } catch (error) {
            alert('网络错误');
        }
    }

    async function deleteTask(taskId) {
        if (!confirm('确定要删除此任务吗？')) return;
        try {
            const res = await fetch(`${API_BASE}/api/tasks/${taskId}`, { method: 'DELETE' });
            if (res.ok) {
                if (tasks.length === 1 && page > 1) page--;
                fetchTasks();
            }
        } catch (error) {
            alert('删除失败');
        }
    }

    function getDeviceName(deviceId) {
        const device = devices.find(d => d.device_id === deviceId);
        return device ? device.name : deviceId;
    }
</script>

<div class="h-full flex flex-col bg-slate-100 p-6 overflow-hidden relative">
    <h2 class="text-2xl font-bold text-slate-800 mb-6">任务管理</h2>
    <div class="bg-white rounded-xl shadow-sm border border-slate-200 flex-1 flex flex-col overflow-hidden">
        <div class="p-4 border-b border-slate-200 flex justify-between items-center bg-slate-50">
            <span class="text-slate-600">共找到 <strong class="text-slate-900">{total}</strong> 个任务</span>
            <button on:click={() => openModal()} class="bg-blue-600 hover:bg-blue-700 text-white px-4 py-2 rounded-lg font-medium flex items-center transition-colors shadow-sm">
                <span class="mr-2 text-lg leading-none">+</span> 新建任务
            </button>
        </div>
        
        <div class="flex-1 overflow-auto">
            <table class="w-full text-left border-collapse">
                <thead>
                    <tr class="bg-slate-50 border-b border-slate-200 text-slate-500 text-sm">
                        <th class="py-3 px-6 font-medium">任务ID</th>
                        <th class="py-3 px-6 font-medium">任务名称</th>
                        <th class="py-3 px-6 font-medium">任务类型</th>
                        <th class="py-3 px-6 font-medium">关联设备</th>
                        <th class="py-3 px-6 font-medium">任务状态</th>
                        <th class="py-3 px-6 font-medium text-right">操作</th>
                    </tr>
                </thead>
                <tbody class="divide-y divide-slate-100 text-slate-700">
                    {#each tasks as task}
                        <tr class="hover:bg-slate-50 transition-colors">
                            <td class="py-3 px-6 font-mono text-xs">{task.id}</td>
                            <td class="py-3 px-6 font-medium">{task.name}</td>
                            <td class="py-3 px-6">{task.task_type}</td>
                            <td class="py-3 px-6">{getDeviceName(task.device_id)}</td>
                            <td class="py-3 px-6">
                                <span class="px-2.5 py-1 text-xs rounded-full font-medium {task.status === '布控中' ? 'bg-green-100 text-green-700' : task.status === '已完成' ? 'bg-blue-100 text-blue-700' : 'bg-slate-100 text-slate-600'}">
                                    {task.status}
                                </span>
                            </td>
                            <td class="py-3 px-6 text-right space-x-3">
                                <button on:click={() => openModal(task)} class="text-blue-500 hover:text-blue-700 transition-colors" title="编辑">
                                    <Icon name="Edit" className="w-5 h-5 inline" />
                                </button>
                                <button on:click={() => deleteTask(task.id)} class="text-red-500 hover:text-red-700 transition-colors" title="删除">
                                    <Icon name="Trash2" className="w-5 h-5 inline" />
                                </button>
                            </td>
                        </tr>
                    {:else}
                        <tr>
                            <td colspan="6" class="py-12 text-center text-slate-400">暂无任务</td>
                        </tr>
                    {/each}
                </tbody>
            </table>
        </div>
        
        <div class="p-4 border-t border-slate-200 flex justify-between items-center bg-slate-50">
            <span class="text-sm text-slate-500">第 <strong>{page}</strong> 页 / 共 <strong>{Math.ceil(total / size) || 1}</strong> 页</span>
            <div class="flex gap-2">
                <button 
                    disabled={page === 1}
                    on:click={() => { page--; fetchTasks(); }}
                    class="p-2 rounded border border-slate-300 text-slate-600 hover:bg-slate-100 disabled:opacity-50 disabled:cursor-not-allowed">
                    <Icon name="ChevronLeft" className="w-4 h-4" />
                </button>
                <button 
                    disabled={page >= Math.ceil(total / size) || total === 0}
                    on:click={() => { page++; fetchTasks(); }}
                    class="p-2 rounded border border-slate-300 text-slate-600 hover:bg-slate-100 disabled:opacity-50 disabled:cursor-not-allowed">
                    <Icon name="ChevronRight" className="w-4 h-4" />
                </button>
            </div>
        </div>
    </div>
</div>

{#if showModal}
    <TaskModal task={editingTask} {devices} on:save={saveTask} on:close={closeModal} />
{/if}