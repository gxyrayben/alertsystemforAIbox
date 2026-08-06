<script>
    import { onMount } from 'svelte';
    import TaskModal from './TaskModal.svelte';
    import { API_BASE, apiGet, apiPost, apiPut, apiDelete } from '../lib/api.js';

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
            tuningResult = await apiPost(`/api/tasks/${task.id}/auto_tune`);
        } catch (error) {
            console.error(error);
            alert(error.status ? `调优失败: ${error.detail || '未知错误'}` : '网络错误，调优失败');
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
            devices = await apiGet('/devices');
        } catch (error) {
            console.error("Failed to fetch devices", error);
        }
    }

    async function fetchTasks() {
        try {
            const data = await apiGet(`/api/tasks?page=${page}&size=${size}`);
            tasks = data.tasks;
            total = data.total;
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
        try {
            if (editingTask) {
                await apiPut(`/api/tasks/${editingTask.id}`, taskData);
            } else {
                await apiPost('/api/tasks', taskData);
            }
            closeModal();
            fetchTasks();
        } catch (error) {
            alert(error.status ? '保存失败' : '网络错误');
        }
    }

    async function deleteTask(taskId) {
        if (!confirm('确定要删除此任务吗？')) return;
        try {
            await apiDelete(`/api/tasks/${taskId}`);
            if (tasks.length === 1 && page > 1) page--;
            fetchTasks();
        } catch (error) {
            alert('删除失败');
        }
    }

    function getDeviceName(deviceId) {
        const device = devices.find(d => d.device_id === deviceId);
        return device ? device.name : deviceId;
    }
</script>

<div class="h-full flex flex-col p-6 overflow-hidden relative">
    <h2 class="text-2xl font-bold text-white mb-6">任务管理</h2>
    <div class="bg-slate-950 rounded-2xl border border-slate-800 flex-1 flex flex-col overflow-hidden">
        <div class="p-4 border-b border-slate-800 flex justify-between items-center bg-slate-900/40">
            <span class="text-slate-400">共找到 <strong class="text-slate-100">{total}</strong> 个任务</span>
            <button on:click={() => openModal()} class="bg-indigo-600 hover:bg-indigo-700 text-white rounded-xl font-bold px-4 py-2 flex items-center shadow-sm">
                <i class="fa-solid fa-plus mr-2"></i> 新建任务
            </button>
        </div>

        <div class="flex-1 overflow-auto">
            <table class="w-full text-left border-collapse">
                <thead>
                    <tr class="bg-slate-900/60 border-b border-slate-800">
                        <th class="py-3 px-6 text-[11px] font-semibold text-slate-500 uppercase tracking-wider">任务ID</th>
                        <th class="py-3 px-6 text-[11px] font-semibold text-slate-500 uppercase tracking-wider">任务名称</th>
                        <th class="py-3 px-6 text-[11px] font-semibold text-slate-500 uppercase tracking-wider">任务类型</th>
                        <th class="py-3 px-6 text-[11px] font-semibold text-slate-500 uppercase tracking-wider">关联设备</th>
                        <th class="py-3 px-6 text-[11px] font-semibold text-slate-500 uppercase tracking-wider">关联通道</th>
                        <th class="py-3 px-6 text-[11px] font-semibold text-slate-500 uppercase tracking-wider">任务状态</th>
                        <th class="py-3 px-6 text-[11px] font-semibold text-slate-500 uppercase tracking-wider text-right">操作</th>
                    </tr>
                </thead>
                <tbody class="divide-y divide-slate-800 text-slate-300">
                    {#each tasks as task}
                        <tr class="hover:bg-slate-900/60 transition-colors">
                            <td class="py-3 px-6 font-mono text-xs text-slate-500">{task.id}</td>
                            <td class="py-3 px-6 font-medium text-slate-100">{task.name}</td>
                            <td class="py-3 px-6">{task.task_type}</td>
                            <td class="py-3 px-6">{getDeviceName(task.device_id)}</td>
                            <td class="py-3 px-6">{task.channel || '-'}</td>
                            <td class="py-3 px-6">
                                <span class="rounded-full px-2.5 py-1 text-xs font-medium {task.status === '布控中' ? 'bg-emerald-500/10 text-emerald-400' : task.status === '已完成' ? 'bg-indigo-500/10 text-indigo-400' : 'bg-slate-800 text-slate-400'}">
                                    {task.status}
                                </span>
                            </td>
                            <td class="py-3 px-6 text-right space-x-3">
                                {#if task.task_type === 'Prompt调优'}
                                    <button on:click={() => handleAutoTune(task)} disabled={tuningTaskId === task.id} class="text-indigo-400 hover:text-indigo-300 transition-colors disabled:opacity-50" title="AI 自动调优">
                                        {#if tuningTaskId === task.id}
                                            <i class="fa-solid fa-spinner text-base inline animate-spin"></i>
                                        {:else}
                                            <i class="fa-solid fa-wand-magic-sparkles text-base inline"></i>
                                        {/if}
                                    </button>
                                {/if}
                                <button on:click={() => openModal(task)} class="text-indigo-400 hover:text-indigo-300 transition-colors" title="编辑">
                                    <i class="fa-solid fa-pen-to-square text-base inline"></i>
                                </button>
                                <button on:click={() => deleteTask(task.id)} class="text-rose-400 hover:text-rose-300 transition-colors" title="删除">
                                    <i class="fa-solid fa-trash text-base inline"></i>
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

        <div class="p-4 border-t border-slate-800 flex justify-between items-center bg-slate-900/40">
            <span class="text-sm text-slate-400">第 <strong>{page}</strong> 页 / 共 <strong>{Math.ceil(total / size) || 1}</strong> 页</span>
            <div class="flex gap-2">
                <button
                    disabled={page === 1}
                    on:click={() => { page--; fetchTasks(); }}
                    class="p-2 rounded-lg border border-slate-800 text-slate-400 hover:bg-slate-800 disabled:opacity-50 disabled:cursor-not-allowed">
                    <i class="fa-solid fa-chevron-left text-sm"></i>
                </button>
                <button
                    disabled={page >= Math.ceil(total / size) || total === 0}
                    on:click={() => { page++; fetchTasks(); }}
                    class="p-2 rounded-lg border border-slate-800 text-slate-400 hover:bg-slate-800 disabled:opacity-50 disabled:cursor-not-allowed">
                    <i class="fa-solid fa-chevron-right text-sm"></i>
                </button>
            </div>
        </div>
    </div>
</div>

{#if showModal}
    <TaskModal task={editingTask} {devices} {tasks} on:save={saveTask} on:close={closeModal} />
{/if}

{#if tuningResult}
    <div class="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4">
        <div class="bg-slate-950 border border-slate-800 rounded-2xl shadow-2xl w-full max-w-2xl max-h-[90vh] flex flex-col overflow-hidden">
            <div class="px-6 py-4 border-b border-slate-800 flex justify-between items-center bg-indigo-500/10">
                <h3 class="text-lg font-semibold text-indigo-300 flex items-center">
                    <i class="fa-solid fa-wand-magic-sparkles text-base mr-2 text-indigo-400"></i>
                    AI 自动调优结果
                </h3>
                <button on:click={closeTuningModal} class="text-slate-400 hover:text-slate-200"><i class="fa-solid fa-xmark text-base"></i></button>
            </div>
            <div class="p-6 overflow-y-auto flex-1 space-y-6">
                <!-- 图片展示 -->
                <div>
                    <h4 class="text-sm font-medium text-slate-200 mb-2">本次分析的告警图片：</h4>
                    <div class="rounded-xl overflow-hidden border border-slate-800 bg-slate-900 flex justify-center max-h-64">
                        <img src="{API_BASE}/{tuningResult.alert_image}" alt="告警图" class="max-h-full object-contain" />
                    </div>
                </div>

                <!-- 判定结果 -->
                <div class="flex items-start">
                    <div class="mr-4 mt-1">
                        {#if tuningResult.is_false_positive}
                            <span class="inline-flex items-center px-2.5 py-1 rounded-full text-xs font-medium bg-rose-500/10 text-rose-400">
                                判定：误报 (False Positive)
                            </span>
                        {:else}
                            <span class="inline-flex items-center px-2.5 py-1 rounded-full text-xs font-medium bg-emerald-500/10 text-emerald-400">
                                判定：正常告警 (True Positive)
                            </span>
                        {/if}
                    </div>
                    <div class="flex-1 bg-slate-900 border border-slate-800 p-3 rounded-xl text-sm text-slate-200">
                        <strong>分析原因：</strong> {tuningResult.reason}
                    </div>
                </div>

                <!-- Prompt 对比 -->
                {#if tuningResult.is_false_positive && tuningResult.updated_device}
                    <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
                        <div class="border border-slate-800 rounded-xl overflow-hidden flex flex-col">
                            <div class="bg-slate-900 px-3 py-2 text-xs font-semibold text-slate-400 border-b border-slate-800">优化前 Prompt</div>
                            <div class="p-3 text-xs font-mono text-slate-400 whitespace-pre-wrap overflow-y-auto flex-1 bg-slate-900">{tuningResult.old_prompt}</div>
                        </div>
                        <div class="border border-indigo-500/30 rounded-xl overflow-hidden flex flex-col shadow-sm">
                            <div class="bg-indigo-500/10 px-3 py-2 text-xs font-semibold text-indigo-300 border-b border-indigo-500/30">优化后 Prompt (已下发设备)</div>
                            <div class="p-3 text-xs font-mono text-indigo-200 whitespace-pre-wrap overflow-y-auto flex-1 bg-indigo-500/10">{tuningResult.new_prompt}</div>
                        </div>
                    </div>
                {:else if !tuningResult.updated_device && tuningResult.is_false_positive}
                    <div class="text-sm text-rose-400 bg-rose-500/10 p-3 rounded-xl border border-rose-500/20">
                        虽然判定为误报，但由于设备网络或协议原因，未成功将新 Prompt 下发至设备。
                    </div>
                {:else}
                    <div class="text-sm text-slate-400 bg-slate-900 p-3 rounded-xl border border-slate-800 text-center">
                        大模型判定此告警为正常抓拍，非误报，无需优化 Prompt。
                    </div>
                {/if}
            </div>
            <div class="px-6 py-4 border-t border-slate-800 bg-slate-900/40 flex justify-end">
                <button on:click={closeTuningModal} class="bg-indigo-600 hover:bg-indigo-700 text-white rounded-xl font-bold px-6 py-2">
                    完成
                </button>
            </div>
        </div>
    </div>
{/if}