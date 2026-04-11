<script>
    import { createEventDispatcher } from 'svelte';
    
    export let task = null; // null means create new
    export let devices = [];
    export let tasks = []; // pass down all tasks
    
    const dispatch = createEventDispatcher();
    
    // Initial state
    let formData = task ? { ...task } : {
        name: '',
        task_type: 'Prompt调优',
        device_id: '',
        channel: '',
        algorithms: '[]',
        status: '未布控', // hardcoded internally
        assignee: '',
        priority: '中',
        due_date: ''
    };
    
    const taskTypes = ['Prompt调优', '警戒分析'];
    const priorities = ['高', '中', '低'];
    const mockChannels = ['CH01 (主入口)', 'CH02 (次入口)', 'CH03 (周边)', 'CH04 (室内)'];
    const availableAlgorithms = ['区域入侵', '越界检测', '车辆违停', '人员聚集', '烟火检测', '异常离岗'];

    // parse JSON array string for algorithms
    let selectedAlgorithms = [];
    try {
        if (formData.algorithms) {
            selectedAlgorithms = JSON.parse(formData.algorithms);
        }
    } catch(e) {
        selectedAlgorithms = [];
    }

    $: formData.algorithms = JSON.stringify(selectedAlgorithms);

    // Dynamic list of channels based on selected device (mock)
    $: availableChannels = formData.device_id ? mockChannels : [];
    
    // Calculate related tasks based on selected device and channel
    $: relatedTasks = (formData.device_id && formData.channel) 
        ? tasks.filter(t => t.device_id === formData.device_id && t.channel === formData.channel && t.id !== formData.id) 
        : [];

    function toggleAlgorithm(alg) {
        if (selectedAlgorithms.includes(alg)) {
            selectedAlgorithms = selectedAlgorithms.filter(a => a !== alg);
        } else {
            selectedAlgorithms = [...selectedAlgorithms, alg];
        }
    }

    function handleSave() {
        if (!formData.name || !formData.device_id || !formData.channel) {
            alert('请填写任务名称、关联设备和关联通道');
            return;
        }
        if (selectedAlgorithms.length === 0) {
            alert('请至少选择一个智能体算法');
            return;
        }
        dispatch('save', formData);
    }
    
    function handleCancel() {
        dispatch('close');
    }
</script>

<div class="fixed inset-0 bg-slate-900/50 backdrop-blur-sm z-50 flex items-center justify-center p-4">
    <div class="bg-white rounded-xl shadow-2xl w-full max-w-2xl overflow-hidden flex flex-col max-h-[90vh]">
        <div class="px-6 py-4 border-b border-slate-100 flex justify-between items-center bg-slate-50">
            <h3 class="text-xl font-semibold text-slate-800">{task ? '编辑任务' : '新建任务'}</h3>
            <button on:click={handleCancel} class="text-slate-400 hover:text-slate-600 transition-colors">
                <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path></svg>
            </button>
        </div>
        
        <div class="p-6 overflow-y-auto flex-1 space-y-5">
            <!-- 基础信息 -->
            <div class="grid grid-cols-2 gap-4">
                <div class="col-span-2 sm:col-span-1">
                    <label class="block text-sm font-medium text-slate-700 mb-1" for="taskName">任务名称 <span class="text-red-500">*</span></label>
                    <input id="taskName" type="text" bind:value={formData.name} class="w-full px-3 py-2 border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500" placeholder="例如：测试安防任务" />
                </div>
                <div class="col-span-2 sm:col-span-1">
                    <label class="block text-sm font-medium text-slate-700 mb-1" for="taskType">任务类型 <span class="text-red-500">*</span></label>
                    <select id="taskType" bind:value={formData.task_type} class="w-full px-3 py-2 border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500">
                        {#each taskTypes as type}
                            <option value={type}>{type}</option>
                        {/each}
                    </select>
                </div>
            </div>

            <!-- 设备和通道 -->
            <div class="grid grid-cols-2 gap-4">
                <div class="col-span-2 sm:col-span-1">
                    <label class="block text-sm font-medium text-slate-700 mb-1" for="deviceId">关联设备 <span class="text-red-500">*</span></label>
                    <select id="deviceId" bind:value={formData.device_id} class="w-full px-3 py-2 border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500">
                        <option value="">请选择设备</option>
                        {#each devices as device}
                            <option value={device.device_id}>{device.name} ({device.device_id})</option>
                        {/each}
                    </select>
                </div>
                <div class="col-span-2 sm:col-span-1">
                    <label class="block text-sm font-medium text-slate-700 mb-1" for="channelId">关联通道 <span class="text-red-500">*</span></label>
                    <select id="channelId" bind:value={formData.channel} disabled={!formData.device_id} class="w-full px-3 py-2 border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:bg-slate-100">
                        <option value="">{formData.device_id ? '请选择通道' : '请先选择设备'}</option>
                        {#each availableChannels as channel}
                            <option value={channel}>{channel}</option>
                        {/each}
                    </select>
                </div>
            </div>

            <!-- 智能体算法选择 -->
            <div>
                <label class="block text-sm font-medium text-slate-700 mb-2">智能体算法 <span class="text-red-500">*</span></label>
                <div class="flex flex-wrap gap-2">
                    {#each availableAlgorithms as alg}
                        <button 
                            type="button" 
                            class="px-3 py-1.5 text-sm rounded-full border transition-colors {selectedAlgorithms.includes(alg) ? 'bg-blue-50 border-blue-200 text-blue-700 font-medium' : 'bg-white border-slate-200 text-slate-600 hover:bg-slate-50'}"
                            on:click={() => toggleAlgorithm(alg)}
                        >
                            {#if selectedAlgorithms.includes(alg)}
                                <svg class="w-3.5 h-3.5 inline mr-1" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"></path></svg>
                            {/if}
                            {alg}
                        </button>
                    {/each}
                </div>
            </div>

            <!-- 关联任务信息展示 -->
            {#if formData.device_id && formData.channel}
                <div class="bg-blue-50/50 rounded-lg p-4 border border-blue-100">
                    <h4 class="text-sm font-medium text-blue-900 mb-2 flex items-center">
                        <svg class="w-4 h-4 mr-1 text-blue-500" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 16h-1v-4h-1m1-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"></path></svg>
                        该通道下已关联的任务：
                    </h4>
                    {#if relatedTasks.length > 0}
                        <ul class="list-disc list-inside text-sm text-blue-700 pl-4 space-y-1">
                            {#each relatedTasks as rt}
                                <li>{rt.name} <span class="text-blue-500/70">({rt.task_type})</span></li>
                            {/each}
                        </ul>
                    {:else}
                        <p class="text-sm text-blue-600/70 pl-1">暂无其他任务关联此通道。</p>
                    {/if}
                </div>
            {/if}

            <!-- 其他 -->
            <div class="grid grid-cols-2 gap-4">
                <div class="col-span-2 sm:col-span-1">
                    <label class="block text-sm font-medium text-slate-700 mb-1" for="priority">优先级</label>
                    <select id="priority" bind:value={formData.priority} class="w-full px-3 py-2 border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500">
                        {#each priorities as priority}
                            <option value={priority}>{priority}</option>
                        {/each}
                    </select>
                </div>
                <div class="col-span-2 sm:col-span-1">
                    <label class="block text-sm font-medium text-slate-700 mb-1" for="assignee">负责人</label>
                    <input id="assignee" type="text" bind:value={formData.assignee} class="w-full px-3 py-2 border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500" placeholder="例如：张三" />
                </div>
            </div>
        </div>
        
        <div class="px-6 py-4 border-t border-slate-100 flex justify-end gap-3 bg-slate-50">
            <button on:click={handleCancel} class="px-4 py-2 border border-slate-300 rounded-lg text-slate-700 font-medium hover:bg-slate-100 transition-colors">取消</button>
            <button on:click={handleSave} class="px-4 py-2 bg-blue-600 text-white rounded-lg font-medium hover:bg-blue-700 transition-colors shadow-sm">保存</button>
        </div>
    </div>
</div>