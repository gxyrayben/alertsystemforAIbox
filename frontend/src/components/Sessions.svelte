<script>
    import { onMount, tick } from 'svelte';
    import Icon from '../lib/Icon.svelte';
    import { apiGet, apiPost, apiDelete } from '../lib/api.js';

    const WELCOME = { role: 'model', text: '您好！我是 BOX 设备任务管理智能体 🤖。我可以帮您：\n• 查询已接入的设备列表\n• 查看某个设备下各视频流通道的算法任务\n• 通过对话创建 / 修改算法分析任务\n\n试试对我说：「查一下所有设备」或「给设备 M0141... 新建一个人体检测任务」。' };

    let devices = [];                // 已接入设备（用于生成默认会话项）
    let conversations = [];          // 历史会话列表
    let activeConvId = null;         // 当前会话 id（null = 新会话未落库）
    let activeDeviceId = null;       // 当前会话绑定的设备 device_id（null = 通用会话）
    let chatMessages = [WELCOME];
    let chatInput = '';
    let isChatLoading = false;
    let chatScrollRef;

    onMount(async () => {
        await Promise.all([loadDevices(), loadConversations()]);
    });

    async function loadDevices() {
        try {
            devices = await apiGet('/devices');
        } catch (e) { console.error(e); }
    }

    async function loadConversations() {
        try {
            conversations = await apiGet('/conversations');
        } catch (e) { console.error(e); }
    }

    function newConversation() {
        activeConvId = null;
        activeDeviceId = null;
        chatMessages = [WELCOME];
        chatInput = '';
    }

    // 点击某台设备的默认会话：进入该设备专属上下文
    function openDeviceConversation(device) {
        if (isChatLoading) return;
        activeConvId = null;
        activeDeviceId = device.device_id;
        chatMessages = [{
            role: 'model',
            text: `已进入设备「${device.name}」(${device.device_id}) 的专属会话 🎯\n\n您可以直接对我说：\n• 「查看当前设备的任务」\n• 「新建一个人体检测任务，通道 CH01」\n• 「把某个任务的优先级改为高」\n\n我会默认针对该设备进行操作。`
        }];
        chatInput = '';
        scrollToBottom();
    }

    async function openConversation(id) {
        if (isChatLoading) return;
        try {
            const conv = await apiGet(`/conversations/${id}`);
            activeConvId = conv.id;
            activeDeviceId = null; // 历史会话暂不回填设备上下文
            chatMessages = conv.messages && conv.messages.length
                ? conv.messages.map(m => ({ role: m.role, text: m.text }))
                : [WELCOME];
            await scrollToBottom();
        } catch (e) { console.error(e); }
    }

    async function deleteConversation(id, e) {
        e.stopPropagation();
        if (!confirm('确定删除该会话吗？')) return;
        try {
            await apiDelete(`/conversations/${id}`);
            if (activeConvId === id) newConversation();
            await loadConversations();
        } catch (err) { console.error(err); }
    }

    async function handleSendMessage() {
        if (!chatInput.trim() || isChatLoading) return;

        const userText = chatInput.trim();
        chatMessages = [...chatMessages, { role: 'user', text: userText }];
        chatInput = '';
        isChatLoading = true;
        await scrollToBottom();

        try {
            const data = await apiPost('/chat', {
                messages: chatMessages.filter(m => m !== WELCOME),
                conversation_id: activeConvId,
                device_id: activeDeviceId,
            });
            chatMessages = [...chatMessages, { role: 'model', text: data.text }];
            if (data.conversation_id && data.conversation_id !== activeConvId) {
                activeConvId = data.conversation_id;
            }
            await loadConversations();
        } catch (error) {
            const text = error.status
                ? `请求失败: ${error.detail || '未知错误'}`
                : "网络错误，请检查后端服务是否启动。";
            chatMessages = [...chatMessages, { role: 'model', text }];
        } finally {
            isChatLoading = false;
            await scrollToBottom();
        }
    }

    async function scrollToBottom() {
        await tick();
        if (chatScrollRef) chatScrollRef.scrollTop = chatScrollRef.scrollHeight;
    }

    function fmtTime(ts) {
        const d = new Date(ts);
        return `${d.getMonth() + 1}/${d.getDate()} ${d.getHours().toString().padStart(2, '0')}:${d.getMinutes().toString().padStart(2, '0')}`;
    }

    // 当前活动设备对象（用于对话区顶部标识）
    $: activeDevice = devices.find(d => d.device_id === activeDeviceId) || null;
</script>

<div class="flex h-full gap-4">
    <!-- 左侧：设备默认会话 + 历史会话 -->
    <div class="w-64 shrink-0 bg-surface rounded-xl border border-edge flex flex-col overflow-hidden">
        <div class="p-3 border-b border-edge">
            <button on:click={newConversation} class="w-full btn-primary py-2 text-sm">
                <Icon name="Plus" className="w-4 h-4 mr-1.5" /> 新建会话
            </button>
        </div>

        <div class="flex-1 overflow-y-auto p-2 space-y-4">
            <!-- 设备默认会话区 -->
            <div>
                <div class="px-2 mb-1.5 text-[11px] font-semibold text-muted uppercase tracking-wider flex items-center gap-1.5">
                    <Icon name="Server" className="w-3.5 h-3.5" /> 设备默认会话
                </div>
                <div class="space-y-1">
                    {#each devices as device}
                        <div
                            on:click={() => openDeviceConversation(device)}
                            class="flex items-center px-3 py-2.5 rounded-lg cursor-pointer transition-colors {activeDeviceId === device.device_id ? 'bg-accent/15 text-ink ring-1 ring-accent/40' : 'text-muted hover:bg-surface2 hover:text-ink'}"
                        >
                            <div class="w-8 h-8 rounded-lg bg-gradient-to-br from-accent to-accent2 flex items-center justify-center shrink-0 mr-2.5">
                                <Icon name="Cpu" className="w-4 h-4 text-white" />
                            </div>
                            <div class="min-w-0 flex-1">
                                <div class="text-sm font-medium truncate">{device.name}</div>
                                <div class="text-[11px] text-muted truncate">{device.device_id}</div>
                            </div>
                            <span class="ml-1 shrink-0 w-2 h-2 rounded-full {device.status === '在线' ? 'bg-emerald-400' : 'bg-slate-500'}" title={device.status}></span>
                        </div>
                    {:else}
                        <div class="text-center text-muted text-xs py-4">暂无已接入设备</div>
                    {/each}
                </div>
            </div>

            <!-- 历史会话区 -->
            <div>
                <div class="px-2 mb-1.5 text-[11px] font-semibold text-muted uppercase tracking-wider flex items-center gap-1.5">
                    <Icon name="MessageSquare" className="w-3.5 h-3.5" /> 历史会话
                </div>
                <div class="space-y-1">
                    {#each conversations as conv}
                        <div
                            on:click={() => openConversation(conv.id)}
                            class="group flex items-center justify-between px-3 py-2.5 rounded-lg cursor-pointer transition-colors {activeConvId === conv.id ? 'bg-accent/15 text-ink' : 'text-muted hover:bg-surface2 hover:text-ink'}"
                        >
                            <div class="min-w-0 flex-1">
                                <div class="text-sm font-medium truncate">{conv.title}</div>
                                <div class="text-[11px] text-muted">{fmtTime(conv.updated_at)}</div>
                            </div>
                            <button on:click={(e) => deleteConversation(conv.id, e)} class="opacity-0 group-hover:opacity-100 text-muted hover:text-red-400 transition-opacity ml-2 shrink-0" title="删除">
                                <Icon name="Trash2" className="w-4 h-4" />
                            </button>
                        </div>
                    {:else}
                        <div class="text-center text-muted text-xs py-4">暂无历史会话</div>
                    {/each}
                </div>
            </div>
        </div>
    </div>

    <!-- 右侧：对话区 -->
    <div class="flex-1 bg-surface rounded-xl shadow-sm border border-edge flex flex-col overflow-hidden min-w-0">
        {#if activeDevice}
            <div class="px-5 py-3 border-b border-edge bg-surface2 flex items-center gap-2 text-sm">
                <Icon name="Cpu" className="w-4 h-4 text-accent" />
                <span class="text-ink font-medium">当前设备：{activeDevice.name}</span>
                <span class="text-muted text-xs font-mono">{activeDevice.device_id}</span>
            </div>
        {/if}
        <div bind:this={chatScrollRef} class="flex-1 overflow-y-auto p-6 space-y-6 bg-surface2">
            {#each chatMessages as msg}
                <div class="flex {msg.role === 'user' ? 'justify-end' : 'justify-start'}">
                    <div class="flex max-w-[80%] {msg.role === 'user' ? 'flex-row-reverse' : 'flex-row'}">
                        <div class="flex-shrink-0 flex items-center justify-center w-10 h-10 rounded-full shadow-sm {msg.role === 'user' ? 'bg-accent ml-4' : 'bg-slate-800 mr-4'}">
                            <Icon name={msg.role === 'user' ? "User" : "Bot"} className="w-5 h-5 {msg.role === 'user' ? 'text-white' : 'text-blue-400'}" />
                        </div>
                        <div class="px-5 py-3.5 rounded-2xl shadow-sm {msg.role === 'user' ? 'bg-accent text-white rounded-tr-none' : 'bg-surface border text-ink rounded-tl-none'}">
                            <div class="whitespace-pre-wrap leading-relaxed text-sm">{msg.text}</div>
                        </div>
                    </div>
                </div>
            {/each}
            {#if isChatLoading}
                <div class="flex justify-start">
                    <div class="flex flex-row max-w-[80%]">
                        <div class="flex-shrink-0 flex items-center justify-center w-10 h-10 rounded-full shadow-sm bg-slate-800 mr-4"><Icon name="Bot" className="w-5 h-5 text-blue-400" /></div>
                        <div class="px-5 py-3.5 rounded-2xl shadow-sm bg-surface border rounded-tl-none flex items-center space-x-2">
                            <div class="w-2 h-2 bg-muted rounded-full animate-bounce"></div>
                            <div class="w-2 h-2 bg-muted rounded-full animate-bounce" style="animation-delay: 0.2s"></div>
                            <div class="w-2 h-2 bg-muted rounded-full animate-bounce" style="animation-delay: 0.4s"></div>
                        </div>
                    </div>
                </div>
            {/if}
        </div>
        <div class="p-4 bg-surface border-t border-edge">
            <div class="max-w-4xl mx-auto relative flex items-end">
                <textarea
                    bind:value={chatInput}
                    on:keydown={(e) => { if(e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSendMessage(); } }}
                    placeholder={activeDevice ? `针对「${activeDevice.name}」提问... (按 Enter 发送)` : "输入您的问题... (按 Enter 发送)"}
                    class="w-full bg-surface2 border border-edge rounded-2xl pl-5 pr-14 py-3.5 outline-none focus:ring-2 focus:ring-blue-500 resize-none min-h-[52px] max-h-32 text-sm"
                    rows="1"
                ></textarea>
                <button on:click={handleSendMessage} disabled={!chatInput.trim() || isChatLoading} class="absolute right-2 bottom-1.5 p-2 rounded-xl flex items-center justify-center {!chatInput.trim() || isChatLoading ? 'bg-edge text-muted' : 'bg-accent text-white shadow-sm'}">
                    <Icon name={isChatLoading ? "Loader2" : "Send"} className="w-5 h-5 ml-0.5 {isChatLoading ? 'animate-spin' : ''}" />
                </button>
            </div>
        </div>
    </div>
</div>
