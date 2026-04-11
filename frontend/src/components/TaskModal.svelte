<script>
    import { createEventDispatcher } from 'svelte';
    
    export let task = null; // null means create new
    export let devices = [];
    
    const dispatch = createEventDispatcher();
    
    // Initial state
    let formData = task ? { ...task } : {
        name: '',
        task_type: '区域告警',
        device_id: '',
        status: '未布控',
        assignee: '',
        priority: '中',
        due_date: ''
    };
    
    const taskTypes = ['区域告警', '人员布控', '设备巡检'];
    const statuses = ['未布控', '布控中', '已完成'];
    const priorities = ['高', '中', '低'];
    
    function handleSave() {
        if (!formData.name || !formData.device_id) {
            alert('请填写任务名称和关联设备');
            return;
        }
        dispatch('save', formData);
    }
    
    function handleCancel() {
        dispatch('close');
    }
</script>

<div class="fixed inset-0 bg-slate-900/50 backdrop-blur-sm z-50 flex items-center justify-center p-4">
    <div class="bg-white rounded-xl shadow-2xl w-full max-w-xl overflow-hidden flex flex-col max-h-[90vh]">
        <div class="px-6 py-4 border-b border-slate-100 flex justify-between items-center bg-slate-50">
            <h3 class="text-xl font-semibold text-slate-800">{task ? '编辑任务' : '新建任务'}</h3>
            <button on:click={handleCancel} class="text-slate-400 hover:text-slate-600 transition-colors">
                <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path></svg>
            </button>
        </div>
        
        <div class="p-6 overflow-y-auto flex-1 space-y-4">
            <div>
                <label class="block text-sm font-medium text-slate-700 mb-1">任务名称 <span class="text-red-500">*</span></label>
                <input type="text" bind:value={formData.name} class="w-full px-3 py-2 border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500" placeholder="例如：测试安防任务" />
            </div>
            <div class="grid grid-cols-2 gap-4">
                <div>
                    <label class="block text-sm font-medium text-slate-700 mb-1">任务类型 <span class="text-red-500">*</span></label>
                    <select bind:value={formData.task_type} class="w-full px-3 py-2 border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500">
                        {#each taskTypes as type}
                            <option value={type}>{type}</option>
                        {/each}
                    </select>
                </div>
                <div>
                    <label class="block text-sm font-medium text-slate-700 mb-1">关联设备 <span class="text-red-500">*</span></label>
                    <select bind:value={formData.device_id} class="w-full px-3 py-2 border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500">
                        <option value="">请选择设备</option>
                        {#each devices as device}
                            <option value={device.device_id}>{device.name} ({device.device_id})</option>
                        {/each}
                    </select>
                </div>
            </div>
            <div class="grid grid-cols-2 gap-4">
                <div>
                    <label class="block text-sm font-medium text-slate-700 mb-1">任务状态 <span class="text-red-500">*</span></label>
                    <select bind:value={formData.status} class="w-full px-3 py-2 border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500">
                        {#each statuses as status}
                            <option value={status}>{status}</option>
                        {/each}
                    </select>
                </div>
                <div>
                    <label class="block text-sm font-medium text-slate-700 mb-1">优先级</label>
                    <select bind:value={formData.priority} class="w-full px-3 py-2 border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500">
                        {#each priorities as priority}
                            <option value={priority}>{priority}</option>
                        {/each}
                    </select>
                </div>
            </div>
            <div>
                <label class="block text-sm font-medium text-slate-700 mb-1">负责人</label>
                <input type="text" bind:value={formData.assignee} class="w-full px-3 py-2 border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500" placeholder="例如：张三" />
            </div>
        </div>
        
        <div class="px-6 py-4 border-t border-slate-100 flex justify-end gap-3 bg-slate-50">
            <button on:click={handleCancel} class="px-4 py-2 border border-slate-300 rounded-lg text-slate-700 font-medium hover:bg-slate-100 transition-colors">取消</button>
            <button on:click={handleSave} class="px-4 py-2 bg-blue-600 text-white rounded-lg font-medium hover:bg-blue-700 transition-colors shadow-sm">保存</button>
        </div>
    </div>
</div>
