<script>
    import { onMount } from 'svelte';
    import Icon from '../lib/Icon.svelte';
    import TaskModal from './TaskModal.svelte';
    import { API_BASE } from '../lib/config.js';

    let tasks = [];
    let devices = [];
    let total = 0;
    let page = 1;
    const size = 10;

    let showModal = false;
    let editingTask = null;

    let tuningTaskId = null;
    let tuningResult = null;

    async function handleAutoTune(task) {
        if (!confirm('确定要对该任务进行自动AI调优吗？\n系统将拉取最新告警图片并调用大模型进行多模态分析。')) return;
        
        tuningTaskId = task.id;
        tuningResult = null;
        try {
            const res = await fetch(`${API_BASE}/api/tasks/${task.id}/auto_tune`, { method: 'POST' });
            if (res.ok) {
                tuningResult = await res.json();
            } else {
                const err = await res.json();
                alert(`调优失败: ${err.detail || '未知错误'}`);
            }
        } catch (error) {
            console.error(error);
            alert('网络错误，调优失败');
        } finally {
            tuningTaskId = null;
        }
    }

    function closeTuningModal() {
        tuningResult = null;
    }

    onMount(async () => {
        await fetchDevices();
        await fetchTasks();
    });

    async function fetchDevices() {
        try {
            const res = await fetch(`${API_BASE}/devices`);
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
                        <th class="py-3 px-6 font-medium">关联通道</th>
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
                            <td class="py-3 px-6">{task.channel || '-'}</td>
                            <td class="py-3 px-6">
                                <span class="px-2.5 py-1 text-xs rounded-full font-medium {task.status === '布控中' ? 'bg-green-100 text-green-700' : task.status === '已完成' ? 'bg-blue-100 text-blue-700' : 'bg-slate-100 text-slate-600'}">
                                    {task.status}
                                </span>
                            </td>
                            <td class="py-3 px-6 text-right space-x-3">
                                {#if task.task_type === 'Prompt调优'}
                                    <button on:click={() => handleAutoTune(task)} disabled={tuningTaskId === task.id} class="text-purple-600 hover:text-purple-800 transition-colors disabled:opacity-50" title="AI 自动调优">
                                        {#if tuningTaskId === task.id}
                                            <Icon name="Loader2" className="w-5 h-5 inline animate-spin" />
                                        {:else}
                                            <Icon name="Sparkles" className="w-5 h-5 inline" />
                                        {/if}
                                    </button>
                                {/if}
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
                            <td colspan="7" class="py-12 text-center text-slate-400">暂无任务</td>
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
    <TaskModal task={editingTask} {devices} {tasks} on:save={saveTask} on:close={closeModal} />
{/if}

{#if tuningResult}
    <div class="fixed inset-0 z-50 flex items-center justify-center bg-black bg-opacity-40 backdrop-blur-sm p-4">
        <div class="bg-white rounded-xl shadow-2xl w-full max-w-2xl max-h-[90vh] flex flex-col overflow-hidden">
            <div class="px-6 py-4 border-b flex justify-between items-center bg-purple-50">
                <h3 class="text-lg font-semibold text-purple-900 flex items-center">
                    <Icon name="Sparkles" className="w-5 h-5 mr-2 text-purple-600" />
                    AI 自动调优结果
                </h3>
                <button on:click={closeTuningModal} class="text-purple-400 hover:text-purple-600"><Icon name="X" className="w-5 h-5" /></button>
            </div>
            <div class="p-6 overflow-y-auto flex-1 space-y-6">
                <!-- 图片展示 -->
                <div>
                    <h4 class="text-sm font-medium text-slate-700 mb-2">本次分析的告警图片：</h4>
                    <div class="rounded-lg overflow-hidden border bg-slate-50 flex justify-center max-h-64">
                        <img src="{API_BASE}/{tuningResult.alert_image}" alt="告警图" class="max-h-full object-contain" />
                    </div>
                </div>
                
                <!-- 判定结果 -->
                <div class="flex items-start">
                    <div class="mr-4 mt-1">
                        {#if tuningResult.is_false_positive}
                            <span class="inline-flex items-center px-2.5 py-1 rounded-full text-xs font-medium bg-red-100 text-red-800">
                                判定：误报 (False Positive)
                            </span>
                        {:else}
                            <span class="inline-flex items-center px-2.5 py-1 rounded-full text-xs font-medium bg-green-100 text-green-800">
                                判定：正常告警 (True Positive)
                            </span>
                        {/if}
                    </div>
                    <div class="flex-1 bg-slate-50 p-3 rounded-lg border text-sm text-slate-700">
                        <strong>分析原因：</strong> {tuningResult.reason}
                    </div>
                </div>

                <!-- Prompt 对比 -->
                {#if tuningResult.is_false_positive && tuningResult.updated_device}
                    <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
                        <div class="border rounded-lg overflow-hidden flex flex-col">
                            <div class="bg-slate-100 px-3 py-2 text-xs font-semibold text-slate-600 border-b">优化前 Prompt</div>
                            <div class="p-3 text-xs font-mono text-slate-500 whitespace-pre-wrap overflow-y-auto flex-1 bg-white">{tuningResult.old_prompt}</div>
                        </div>
                        <div class="border border-purple-200 rounded-lg overflow-hidden flex flex-col shadow-sm">
                            <div class="bg-purple-100 px-3 py-2 text-xs font-semibold text-purple-700 border-b border-purple-200">优化后 Prompt (已下发设备)</div>
                            <div class="p-3 text-xs font-mono text-purple-900 whitespace-pre-wrap overflow-y-auto flex-1 bg-purple-50/30">{tuningResult.new_prompt}</div>
                        </div>
                    </div>
                {:else if !tuningResult.updated_device && tuningResult.is_false_positive}
                    <div class="text-sm text-red-600 bg-red-50 p-3 rounded border border-red-100">
                        虽然判定为误报，但由于设备网络或协议原因，未成功将新 Prompt 下发至设备。
                    </div>
                {:else}
                    <div class="text-sm text-slate-600 bg-slate-50 p-3 rounded border border-slate-200 text-center">
                        大模型判定此告警为正常抓拍，非误报，无需优化 Prompt。
                    </div>
                {/if}
            </div>
            <div class="px-6 py-4 border-t bg-slate-50 flex justify-end">
                <button on:click={closeTuningModal} class="px-6 py-2 bg-purple-600 hover:bg-purple-700 text-white rounded-lg font-medium shadow-sm transition-colors">
                    完成
                </button>
            </div>
        </div>
    </div>
{/if}