<script>
    import { createEventDispatcher } from 'svelte';
    import { onMount } from 'svelte';
    
    export let task = null; // null means create new
    export let devices = [];
    export let tasks = []; // pass down all tasks
    
    const dispatch = createEventDispatcher();
    
    // Initial state
    let formData = task ? { ...task } : {
        name: '',
        task_type: 'Prompt调优',
        device_id: '',
        device_task: '',
        channel: '',
        algorithms: '[]',
        status: '未布控', // hardcoded internally
        assignee: '',
        priority: '中',
        due_date: ''
    };
    
    const taskTypes = ['Prompt调优', '警戒分析'];
    const priorities = ['高', '中', '低'];
    
    // State for algorithms
    let selectedAlgorithms = [];
    try {
        if (formData.algorithms) {
            selectedAlgorithms = JSON.parse(formData.algorithms);
        }
    } catch(e) {
        selectedAlgorithms = [];
    }

    // Reactively find the selected device object
    $: selectedDevice = devices.find(d => d.device_id === formData.device_id);

    // Get dynamic options from the selected device data
    $: availableDeviceTasks = selectedDevice ? parseJson(selectedDevice.device_tasks) : [];
    
    // Find the selected device task object to get its associated channels
    $: selectedDeviceTaskObj = availableDeviceTasks.find(t => t.task_name === formData.device_task);
    
    // Filter channels: if a task is selected, show only channels associated with that task. 
    // Otherwise show all channels of the device.
    $: availableChannels = selectedDevice 
        ? (selectedDeviceTaskObj 
            ? selectedDeviceTaskObj.device_name.split(',').map(s => s.trim())
            : parseJson(selectedDevice.channels).map(c => c.device_name))
        : [];
    
    $: availableAlgorithms = selectedDevice ? parseJson(selectedDevice.available_algorithms) : [];
    
    // Calculate related system tasks (existing in our DB) based on selected device and channel
    $: systemRelatedTasks = (formData.device_id && formData.channel) 
        ? tasks.filter(t => t.device_id === formData.device_id && t.channel === formData.channel && t.id !== formData.id) 
        : [];

    // Reset channel/task/algorithms if device changes and previously selected items are no longer valid
    $: if (formData.device_id) {
        // Validation check could go here, but usually users want to keep selections if they match
    }

    let showAlgDropdown = false;

    function parseJson(str) {
        try { return JSON.parse(str || '[]'); } catch(e) { return []; }
    }

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
        
        // Update formData algorithms string before dispatching
        formData.algorithms = JSON.stringify(selectedAlgorithms);
        
        dispatch('save', formData);
    }
    
    function handleCancel() {
        dispatch('close');
    }

    // Close dropdown when clicking outside
    function handleClickOutside(e) {
        if (showAlgDropdown && !e.target.closest('.alg-dropdown-container')) {
            showAlgDropdown = false;
        }
    }
</script>

<svelte:window on:click={handleClickOutside} />

<div class="fixed inset-0 bg-slate-900/50 backdrop-blur-sm z-50 flex items-center justify-center p-4">
    <div class="bg-white rounded-xl shadow-2xl w-full max-w-2xl overflow-hidden flex flex-col max-h-[90vh]">
        <div class="px-6 py-4 border-b border-slate-100 flex justify-between items-center bg-slate-50">
            <h3 class="text-xl font-semibold text-slate-800">{task ? '编辑任务' : '新建任务'}</h3>
            <button on:click={handleCancel} class="text-slate-400 hover:text-slate-600 transition-colors">
                <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path></svg>
            </button>
        </div>
        
        <div class="p-6 overflow-y-auto flex-1">
            <div class="grid grid-cols-1 md:grid-cols-2 gap-x-6 gap-y-5">
                <!-- 任务名称 -->
                <div>
                    <label class="block text-sm font-medium text-slate-700 mb-1.5" for="taskName">任务名称 <span class="text-red-500">*</span></label>
                    <input id="taskName" type="text" bind:value={formData.name} class="w-full h-10 px-3 py-2 text-sm border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 transition-shadow" placeholder="例如：测试安防任务" />
                </div>
                
                <!-- 任务类型 -->
                <div>
                    <label class="block text-sm font-medium text-slate-700 mb-1.5" for="taskType">任务类型 <span class="text-red-500">*</span></label>
                    <select id="taskType" bind:value={formData.task_type} class="w-full h-10 px-3 py-2 text-sm border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 transition-shadow bg-white">
                        {#each taskTypes as type}
                            <option value={type}>{type}</option>
                        {/each}
                    </select>
                </div>

                <!-- 关联设备 -->
                <div>
                    <label class="block text-sm font-medium text-slate-700 mb-1.5" for="deviceId">关联设备 <span class="text-red-500">*</span></label>
                    <select id="deviceId" bind:value={formData.device_id} class="w-full h-10 px-3 py-2 text-sm border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 transition-shadow bg-white">
                        <option value="">请选择设备</option>
                        {#each devices as device}
                            <option value={device.device_id}>{device.name} ({device.device_id})</option>
                        {/each}
                    </select>
                </div>

                <!-- 关联任务 (Device Task) -->
                <div>
                    <label class="block text-sm font-medium text-slate-700 mb-1.5" for="deviceTask">关联任务</label>
                    <select id="deviceTask" bind:value={formData.device_task} disabled={!formData.device_id} class="w-full h-10 px-3 py-2 text-sm border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 transition-shadow disabled:bg-slate-100 disabled:text-slate-500 bg-white">
                        <option value="">{formData.device_id ? '请选择关联任务' : '请先选择设备'}</option>
                        {#each availableDeviceTasks as dtask}
                            <option value={dtask.task_name}>{dtask.task_name}</option>
                        {/each}
                    </select>
                </div>
                
                <!-- 关联通道 -->
                <div>
                    <label class="block text-sm font-medium text-slate-700 mb-1.5" for="channelId">关联通道 <span class="text-red-500">*</span></label>
                    <select id="channelId" bind:value={formData.channel} disabled={!formData.device_id} class="w-full h-10 px-3 py-2 text-sm border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 transition-shadow disabled:bg-slate-100 disabled:text-slate-500 bg-white">
                        <option value="">{formData.device_id ? '请选择通道' : '请先选择设备'}</option>
                        {#each availableChannels as channel}
                            <option value={channel}>{channel}</option>
                        {/each}
                    </select>
                </div>

                <!-- 优先级 -->
                <div>
                    <label class="block text-sm font-medium text-slate-700 mb-1.5" for="priority">优先级</label>
                    <select id="priority" bind:value={formData.priority} class="w-full h-10 px-3 py-2 text-sm border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 transition-shadow bg-white">
                        {#each priorities as priority}
                            <option value={priority}>{priority}</option>
                        {/each}
                    </select>
                </div>

                <!-- 智能体算法 (Custom Multi-Select Dropdown) -->
                <div class="col-span-1 md:col-span-2 alg-dropdown-container relative">
                    <label class="block text-sm font-medium text-slate-700 mb-1.5">智能体算法 <span class="text-red-500">*</span></label>
                    <button 
                        type="button"
                        disabled={!formData.device_id}
                        class="w-full h-10 px-3 py-2 text-sm border border-slate-300 rounded-lg flex items-center justify-between focus:outline-none focus:ring-2 focus:ring-blue-500 transition-shadow disabled:bg-slate-100 disabled:cursor-not-allowed bg-white"
                        on:click={() => showAlgDropdown = !showAlgDropdown}
                    >
                        <span class="truncate text-slate-700">
                            {!formData.device_id ? '请先选择设备获取算法列表' : (selectedAlgorithms.length ? selectedAlgorithms.join(', ') : '请选择智能体算法')}
                        </span>
                        <svg class="w-4 h-4 text-slate-400 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"></path></svg>
                    </button>
                    
                    {#if showAlgDropdown && formData.device_id}
                        <div class="absolute z-10 mt-1 w-full bg-white border border-slate-200 rounded-lg shadow-lg max-h-48 overflow-y-auto">
                            {#each availableAlgorithms as alg}
                                <label class="flex items-center px-4 py-2.5 hover:bg-slate-50 cursor-pointer border-b border-slate-50 last:border-0 transition-colors">
                                    <input 
                                        type="checkbox" 
                                        class="w-4 h-4 text-blue-600 rounded border-slate-300 focus:ring-blue-500 mr-3" 
                                        checked={selectedAlgorithms.includes(alg)} 
                                        on:change={() => toggleAlgorithm(alg)} 
                                    />
                                    <span class="text-sm text-slate-700">{alg}</span>
                                </label>
                            {/each}
                            {#if availableAlgorithms.length === 0}
                                <div class="px-4 py-3 text-sm text-slate-500 text-center">该设备暂无可用算法</div>
                            {/if}
                        </div>
                    {/if}
                </div>
                
                <!-- 负责人 -->
                <div class="col-span-1 md:col-span-2">
                    <label class="block text-sm font-medium text-slate-700 mb-1.5" for="assignee">负责人</label>
                    <input id="assignee" type="text" bind:value={formData.assignee} class="w-full h-10 px-3 py-2 text-sm border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 transition-shadow" placeholder="例如：张三" />
                </div>
            </div>

            <!-- 关联任务信息展示 -->
            {#if formData.device_id && formData.channel}
                <div class="mt-6 bg-blue-50/50 rounded-lg p-4 border border-blue-100">
                    <h4 class="text-sm font-medium text-blue-900 mb-2 flex items-center">
                        <svg class="w-4 h-4 mr-1.5 text-blue-500" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 16h-1v-4h-1m1-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"></path></svg>
                        该通道下已绑定的系统任务：
                    </h4>
                    {#if systemRelatedTasks.length > 0}
                        <ul class="list-disc list-inside text-sm text-blue-700 pl-4 space-y-1.5">
                            {#each systemRelatedTasks as rt}
                                <li>{rt.name} <span class="text-blue-500/70 ml-1">({rt.task_type})</span></li>
                            {/each}
                        </ul>
                    {:else}
                        <p class="text-sm text-blue-600/70 pl-5">暂无其他系统任务关联此通道。</p>
                    {/if}
                </div>
            {/if}
        </div>
        
        <div class="px-6 py-4 border-t border-slate-100 flex justify-end gap-3 bg-slate-50">
            <button on:click={handleCancel} class="px-5 py-2 text-sm border border-slate-300 rounded-lg text-slate-700 font-medium hover:bg-slate-100 transition-colors shadow-sm bg-white">取消</button>
            <button on:click={handleSave} class="px-5 py-2 text-sm bg-blue-600 text-white rounded-lg font-medium hover:bg-blue-700 transition-colors shadow-sm">保存</button>
        </div>
    </div>
</div>