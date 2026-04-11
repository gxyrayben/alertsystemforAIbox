<script>
    import { onMount, tick } from 'svelte';
    import Icon from '../lib/Icon.svelte';
    import { API_BASE } from '../lib/config.js';

    let chatMessages = [
        { role: 'model', text: '您好！我是安防综合管理平台的专属 AI 助手。您可以向我询问关于设备接入配置、预警处理规范或日常安防管理建议。有什么我可以帮您的吗？' }
    ];
    let chatInput = '';
    let isChatLoading = false;
    let chatScrollRef;

    async function handleSendMessage() {
        if (!chatInput.trim() || isChatLoading) return;
        
        const userText = chatInput.trim();
        const newUserMsg = { role: 'user', text: userText };
        
        chatMessages = [...chatMessages, newUserMsg];
        chatInput = '';
        isChatLoading = true;
        
        await scrollToBottom();

        try {
            const res = await fetch(`${API_BASE}/chat`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ messages: chatMessages })
            });
            const data = await res.json();
            chatMessages = [...chatMessages, { role: 'model', text: data.text }];
        } catch (error) {
            chatMessages = [...chatMessages, { role: 'model', text: "请求失败，请检查后端服务是否启动。" }];
        } finally {
            isChatLoading = false;
            await scrollToBottom();
        }
    }

    async function scrollToBottom() {
        await tick();
        if (chatScrollRef) {
            chatScrollRef.scrollTop = chatScrollRef.scrollHeight;
        }
    }
</script>

<div class="bg-white rounded-xl shadow-sm border border-gray-200 flex flex-col h-full overflow-hidden">
    <div bind:this={chatScrollRef} class="flex-1 overflow-y-auto p-6 space-y-6 bg-gray-50/50">
        {#each chatMessages as msg}
            <div class="flex {msg.role === 'user' ? 'justify-end' : 'justify-start'}">
                <div class="flex max-w-[80%] {msg.role === 'user' ? 'flex-row-reverse' : 'flex-row'}">
                    <div class="flex-shrink-0 flex items-center justify-center w-10 h-10 rounded-full shadow-sm {msg.role === 'user' ? 'bg-blue-600 ml-4' : 'bg-slate-800 mr-4'}">
                        <Icon name={msg.role === 'user' ? "User" : "Bot"} className="w-5 h-5 {msg.role === 'user' ? 'text-white' : 'text-blue-400'}" />
                    </div>
                    <div class="px-5 py-3.5 rounded-2xl shadow-sm {msg.role === 'user' ? 'bg-blue-600 text-white rounded-tr-none' : 'bg-white border text-gray-800 rounded-tl-none'}">
                        <div class="whitespace-pre-wrap leading-relaxed text-sm">{msg.text}</div>
                    </div>
                </div>
            </div>
        {/each}
        {#if isChatLoading}
            <div class="flex justify-start">
                <div class="flex flex-row max-w-[80%]">
                    <div class="flex-shrink-0 flex items-center justify-center w-10 h-10 rounded-full shadow-sm bg-slate-800 mr-4"><Icon name="Bot" className="w-5 h-5 text-blue-400" /></div>
                    <div class="px-5 py-3.5 rounded-2xl shadow-sm bg-white border rounded-tl-none flex items-center space-x-2">
                        <div class="w-2 h-2 bg-gray-400 rounded-full animate-bounce"></div>
                        <div class="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style="animation-delay: 0.2s"></div>
                        <div class="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style="animation-delay: 0.4s"></div>
                    </div>
                </div>
            </div>
        {/if}
    </div>
    <div class="p-4 bg-white border-t border-gray-200">
        <div class="max-w-4xl mx-auto relative flex items-end">
            <textarea
                bind:value={chatInput}
                on:keydown={(e) => { if(e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSendMessage(); } }}
                placeholder="输入您的问题... (按 Enter 发送)"
                class="w-full bg-gray-50 border border-gray-300 rounded-2xl pl-5 pr-14 py-3.5 outline-none focus:ring-2 focus:ring-blue-500 resize-none min-h-[52px] max-h-32 text-sm"
                rows="1"
            ></textarea>
            <button on:click={handleSendMessage} disabled={!chatInput.trim() || isChatLoading} class="absolute right-2 bottom-1.5 p-2 rounded-xl flex items-center justify-center {!chatInput.trim() || isChatLoading ? 'bg-gray-200 text-gray-400' : 'bg-blue-600 text-white shadow-sm'}">
                <Icon name={isChatLoading ? "Loader2" : "Send"} className="w-5 h-5 ml-0.5 {isChatLoading ? 'animate-spin' : ''}" />
            </button>
        </div>
    </div>
</div>
