<script>
    import { onMount, tick } from 'svelte';
    import { tasksList, showToast, switchTab, chatRequest, selectedDevice } from '../lib/controlStore.js';
    import { apiPost, apiGet, apiDelete, API_BASE } from '../lib/api.js';

    const LS_CONV_KEY = 'aiChatConvId';

    // image_1f70c6.png 在原型中为本地相机截图，这里用占位图代替
    const CAM = 'https://placehold.co/800x500/1e293b/94a3b8?text=EdgeNode-01+Camera+Feed';
    const CROP = 'https://images.unsplash.com/photo-1581092160607-ee22621dd758?auto=format&fit=crop&w=250&q=80';

    const WELCOME = {
        role: 'ai',
        html: `<p class="font-medium text-white mb-1.5">您好！我是本设备的 AI 布控运维助理 🚀</p>
        选定顶部设备后，您可以直接向我提问，我会实时查询并以<strong>表格</strong>展示结果：
        <p class="mt-2.5 text-[11px] text-indigo-300 font-medium bg-indigo-950/40 p-2.5 rounded-lg border border-indigo-500/20">
        💡 <strong>示例提问：</strong><br>1. 当前设备接入了多少个视频流？<br>2. 当前设备已经布控了哪些任务？</p>
        我也可以协助为通道创建 / 修改算法分析任务。`
    };

    const defaultConfig = {
        name: '', device: 'diaozhuang-2', interval: 3, agentType: '跌倒test', prompt: '',
        yoloTarget: 'human', yoloHumanThresh: 0.31, yoloVehicleThresh: 0.32, yoloNonMotorThresh: 0.37,
        intrusionDuration: 3, alarmInterval: 10,
        cropUp: 0.5, cropDown: 0.3, cropLeft: 0.4, cropRight: 0.6,
        maxTarget: 1.0, minTarget: 0.0, roiPoints: []
    };

    let messages = [WELCOME];
    let apiMessages = []; // 送往后端 /chat 的中立历史 [{role:'user'|'model', text}]
    let convId = null;
    let conversations = [];   // 会话历史列表
    let showHistory = false;  // 历史面板开关
    let sending = false;
    let abortController = null;  // 进行中 /chat 请求的取消句柄（「停止任务」用）
    let chatInput = '';
    let chatImage = null;
    let config = { ...defaultConfig };
    let monitorActive = false;
    let roiDrawActive = false;
    let sceneImage = null;   // 视频区载入的真实报警大图（绝对 URL），null 时回退占位图
    let roiSvgRef;           // ROI 绘制图层，用于把点击换算成归一化坐标
    let chatScrollRef;
    let skills = [];         // 后端技能注册表元数据（/skills）
    let convSummary = '';    // 本会话滚动记忆/总结
    let showSummary = false; // 会话记忆面板开关

    // convId 变化时持久化，刷新后可恢复到同一会话
    $: if (convId) localStorage.setItem(LS_CONV_KEY, convId);

    const presets = [
        { icon: '📹', text: '当前设备接入了多少个视频流？请用表格列出所有通道。' },
        { icon: '📋', text: '当前设备已经布控了哪些任务？请用表格展示任务信息。' },
        { icon: '🔑', text: '查看当前设备的小模型算法授权。' },
        { icon: '🧩', text: '查看当前设备可布控的小模型算法。' },
        { icon: '🤖', text: '查看当前设备已有的智能体算法列表。' },
        { icon: '🚀', text: '帮我在当前设备上创建一个纯大模型布控任务。' }
    ];

    // 拉取后端技能注册表，用于渲染技能面板与快捷提问
    async function loadSkills() {
        try {
            const res = await apiGet('/skills');
            skills = res?.skills || [];
        } catch (e) {
            console.error(e);
            skills = [];
        }
    }

    async function scrollToBottom() {
        await tick();
        if (chatScrollRef) chatScrollRef.scrollTop = chatScrollRef.scrollHeight;
    }

    function injectPreset(text) {
        chatInput = text;
    }

    function mockUpload() {
        chatImage = CROP;
        showToast('参考小图配置成功！Agent将联合参考小图做多模态姿态/材质深度核算。', 'info');
    }
    function clearUpload() {
        chatImage = null;
    }

    function resetChat({ silent = false } = {}) {
        stopTask();
        messages = [WELCOME];
        apiMessages = [];
        convId = null;
        localStorage.removeItem(LS_CONV_KEY);
        config = { ...defaultConfig };
        monitorActive = false;
        roiDrawActive = false;
        sceneImage = null;
        showHistory = false;
        convSummary = '';
        showSummary = false;
        if (!silent) showToast('已开启新对话。', 'info');
    }

    // 停止任务：中止进行中的 /chat 请求（后端本轮仍会自行完成并入库，不影响历史留存）
    function stopTask() {
        if (abortController) {
            abortController.abort();
            abortController = null;
        }
    }

    // 清除当前会话：先中止进行中的请求，再把当前会话刷入历史列表，最后重置为新会话。
    // 后端每轮对话都会自动持久化，故当前会话无需额外保存动作即已存于历史。
    async function clearSession() {
        stopTask();
        const hadConversation = !!convId;
        if (hadConversation) await loadConversations(); // 让刚结束的会话立即出现在历史中
        resetChat({ silent: true });
        showToast(hadConversation ? '当前会话已清除并保存到历史。' : '已开启新对话。', 'info');
    }

    // 载入「当前设备最新报警大图」到视频流展示区，供用户在真实场景上画 ROI。
    // 数据模型按 deviceName 存储报警，故取当前设备最新一条带图报警；
    // 优先按方案事件类型(alertType)匹配，无匹配则回退最新任意一条。
    async function loadSceneImage(alertType) {
        const device = $selectedDevice;
        if (!device?.name) { sceneImage = null; return; }
        const base = `/alerts?deviceName=${encodeURIComponent(device.name)}`;
        const pickImage = (list) => (list || []).find((a) => a.imageUrl);
        try {
            let hit = null;
            if (alertType) {
                const typed = await apiGet(`${base}&alertType=${encodeURIComponent(alertType)}`);
                hit = pickImage(typed);
            }
            if (!hit) {
                const all = await apiGet(base);
                hit = pickImage(all);
            }
            if (hit) {
                sceneImage = `${API_BASE}${hit.imageUrl}`;
            } else {
                sceneImage = null;
                showToast(`设备「${device.name}」暂无报警大图，已使用占位场景，仍可绘制 ROI。`, 'warning');
            }
        } catch (e) {
            sceneImage = null;
            showToast('加载报警大图失败，已使用占位场景。', 'warning');
        }
    }

    // 在报警大图上点击落点，构成检测区(ROI)多边形；坐标归一化到 0~1 存入 config.roiPoints。
    function addRoiPoint(ev) {
        if (!roiDrawActive || !roiSvgRef) return;
        const rect = roiSvgRef.getBoundingClientRect();
        const x = Math.min(1, Math.max(0, (ev.clientX - rect.left) / rect.width));
        const y = Math.min(1, Math.max(0, (ev.clientY - rect.top) / rect.height));
        config.roiPoints = [...config.roiPoints, { x: +x.toFixed(4), y: +y.toFixed(4) }];
    }

    function clearRoi() {
        config.roiPoints = [];
        showToast('已清除检测区，可重新绘制。', 'info');
    }

    // roiPoints -> SVG points 字符串（viewBox 800x500）
    $: roiSvgPoints = (config.roiPoints || []).map((p) => `${p.x * 800},${p.y * 500}`).join(' ');

    // ── 会话历史：加载列表 / 打开某会话 / 删除 ──────────────────────────
    async function loadConversations() {
        try {
            conversations = await apiGet('/conversations');
        } catch (e) {
            console.error(e);
        }
    }

    // 后端消息 → 前端渲染/接口两套结构
    function hydrate(detail) {
        const msgs = [];
        const api = [];
        for (const m of detail.messages || []) {
            if (m.role === 'user') {
                msgs.push({ role: 'user', text: m.text });
                api.push({ role: 'user', text: m.text });
            } else {
                msgs.push({ role: 'ai', text: m.text, tables: m.tables || [] });
                api.push({ role: 'model', text: m.text });
            }
        }
        messages = msgs.length ? msgs : [WELCOME];
        apiMessages = api;
    }

    async function openConversation(id) {
        try {
            const detail = await apiGet(`/conversations/${id}`);
            convId = id;
            convSummary = detail.summary || '';
            hydrate(detail);
            showHistory = false;
            await scrollToBottom();
        } catch (e) {
            showToast('加载会话失败。', 'error');
        }
    }

    async function deleteConversation(id, ev) {
        ev.stopPropagation();
        try {
            await apiDelete(`/conversations/${id}`);
            conversations = conversations.filter((c) => c.id !== id);
            if (id === convId) resetChat();
            showToast('会话已删除。', 'info');
        } catch (e) {
            showToast('删除会话失败。', 'error');
        }
    }

    function fmtTime(ts) {
        const d = new Date(ts);
        const p = (n) => String(n).padStart(2, '0');
        return `${d.getMonth() + 1}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
    }

    function toggleRoi() {
        roiDrawActive = !roiDrawActive;
        showToast(roiDrawActive
            ? '手动ROI绘制模式开启。支持通过划区限制小模型初筛目标，阻止非监控区噪声。'
            : '退出区域绘制模式。', 'info');
    }

    function applyConfig(data) {
        config = { ...config, ...data };
        monitorActive = true;
        showToast('双级级联配置参数填充，裁切扩图区域渲染成功！', 'success');
        scrollToBottom();
    }

    // 智能体返回布控方案：填充推荐参数 -> 载入真实报警大图 -> 激活监视 + 开启 ROI 绘制
    async function applyProposal(proposal) {
        config = { ...config, ...proposal, roiPoints: [] };
        monitorActive = true;
        await loadSceneImage(proposal.alertType);
        roiDrawActive = true;
        showToast('已载入推荐参数与最新报警大图，请在视频区点击绘制检测区(ROI)。', 'success');
        await scrollToBottom();
    }

    // 点击任务表「查看」：把该任务的真实参数(row.detail)回填到右侧控制面板，
    // 并在视频区载入设备最新报警大图（无则占位图）。detail 由后端在同步设备时烘焙进快照，离线仍可用。
    async function viewTask(row) {
        const d = row.detail || {};
        config = { ...defaultConfig, ...d, roiPoints: d.roiPoints || [] };
        monitorActive = true;
        await loadSceneImage(d.alertType);
        roiDrawActive = !(d.roiPoints && d.roiPoints.length);
        pushSystemTip(d.name || row.task_name || '布控任务');
        showToast(`已载入任务「${d.name || row.task_name || row.task_id}」的真实参数。`, 'success');
        await scrollToBottom();
    }

    function pushSystemTip(taskName) {
        messages = [...messages, {
            role: 'tip',
            html: `已为您重新载入任务：<strong>[${taskName}]</strong><br>您可以直接对我说：“把检测目标前置人体阈值提高到 0.45” 或 “把上面扩图设为 0.8”，系统会自动在对应的算法框中做出修正。`
        }];
        scrollToBottom();
    }

    async function sendMessage() {
        const text = chatInput.trim();
        if ((!text && !chatImage) || sending) return;

        const device = $selectedDevice;
        messages = [...messages, { role: 'user', text, image: chatImage }];
        apiMessages = [...apiMessages, { role: 'user', text }];
        chatInput = '';
        chatImage = null;
        sending = true;
        abortController = new AbortController();
        messages = [...messages, { role: 'ai', pending: true, html: '<span class="text-slate-500"><i class="fa-solid fa-spinner animate-spin mr-1.5"></i>正在查询设备数据…</span>' }];
        await scrollToBottom();

        try {
            const res = await apiPost('/chat', {
                messages: apiMessages,
                conversation_id: convId,
                device_id: device?.device_id || null
            }, { signal: abortController.signal });
            const isNew = !convId;
            convId = res.conversation_id || convId;
            apiMessages = [...apiMessages, { role: 'model', text: res.text }];
            messages = messages.filter((m) => !m.pending);
            messages = [...messages, { role: 'ai', text: res.text, tables: res.tables || [] }];
            if (res.summary !== undefined) convSummary = res.summary || convSummary;
            if (isNew || conversations[0]?.id !== convId) loadConversations(); // 刷新历史列表
            if (res.proposal) await applyProposal(res.proposal);
        } catch (e) {
            messages = messages.filter((m) => !m.pending);
            if (e?.name === 'AbortError') {
                // 用户主动「停止任务」：给出提示而非错误
                messages = [...messages, { role: 'tip', html: '<i class="fa-solid fa-circle-stop mr-1.5"></i>已停止本次任务，您可以重新提问或清除会话。' }];
                showToast('已停止当前任务。', 'info');
            } else {
                const detail = e?.detail || '与智能体通信失败，请检查「模型配置」与后端服务。';
                messages = [...messages, { role: 'ai', html: `<span class="text-rose-400"><i class="fa-solid fa-triangle-exclamation mr-1.5"></i>${detail}</span>` }];
                showToast(detail, 'error');
            }
        } finally {
            sending = false;
            abortController = null;
            await scrollToBottom();
        }
    }

    function deploy() {
        if (!config.name) {
            showToast('参数尚未配置，请在左侧发送对话进行级联提取。', 'warning');
            return;
        }
        const newId = 'TSK-' + Math.floor(Math.random() * 900 + 100);
        const newTask = { id: newId, status: 'active', todayAlerts: 0, ...config, device: $selectedDevice?.name || config.device };
        tasksList.update((list) => [newTask, ...list]);
        showToast(`🚀 级联布控任务 [${newTask.name}] 成功分发并编译至边端芯片中！`, 'success');
        setTimeout(() => switchTab('taskops'), 1000);
    }

    function handleEnter(e) {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            sendMessage();
        }
    }

    // 响应来自其他标签的请求（对话级微调 / 套用模板）
    onMount(() => {
        // 刷新后恢复：加载技能面板 + 历史列表 + 上次活动会话
        (async () => {
            await loadSkills();
            await loadConversations();
            const saved = localStorage.getItem(LS_CONV_KEY);
            if (saved && conversations.some((c) => c.id === saved)) {
                await openConversation(saved);
            }
        })();

        const unsub = chatRequest.subscribe((req) => {
            if (!req) return;
            if (req.type === 'loadConfig') {
                applyConfig(req.payload);
                pushSystemTip(req.payload.name);
                showToast(`已进入 [${req.payload.name}] 的级联协同调整环境。`, 'info');
            } else if (req.type === 'useTemplate') {
                resetChat();
                chatInput = `请为我配置【${req.payload}】。检测到目标后裁剪图片送智能体进行高精度判定。`;
                sendMessage();
                showToast(`已套用高敏级联模板: [${req.payload}]。请在右侧控制仓调阅细节。`, 'success');
            }
        });
        return unsub;
    });
</script>

<div class="flex h-full -m-6">
    <!-- 左侧：对话协作面板 -->
    <div class="w-[38%] min-w-[440px] max-w-[640px] bg-slate-950 border-r border-slate-800 flex flex-col h-full shrink-0">
        <div class="p-4 border-b border-slate-800 flex items-center justify-between bg-slate-900/40 relative">
            <div class="flex items-center space-x-2">
                <span class="flex h-2 w-2 relative">
                    <span class="animate-ping absolute inline-flex h-full w-full rounded-full bg-indigo-400 opacity-75"></span>
                    <span class="relative inline-flex rounded-full h-2 w-2 bg-indigo-500"></span>
                </span>
                <span class="font-semibold text-slate-200 text-xs">🤖 智能体模式 · 已就绪</span>
            </div>
            <div class="flex items-center space-x-3">
                <button on:click={() => (showSummary = !showSummary)} class="text-[11px] font-medium transition-colors {showSummary ? 'text-indigo-400' : 'text-slate-400 hover:text-indigo-400'}" title="本会话记忆/总结">
                    <i class="fa-solid fa-brain mr-1"></i>记忆{convSummary ? ' •' : ''}
                </button>
                <button on:click={() => { showHistory = !showHistory; if (showHistory) loadConversations(); }} class="text-[11px] font-medium transition-colors {showHistory ? 'text-indigo-400' : 'text-slate-400 hover:text-indigo-400'}">
                    <i class="fa-solid fa-clock-rotate-left mr-1"></i>历史{conversations.length ? ` (${conversations.length})` : ''}
                </button>
                <button on:click={clearSession} class="text-[11px] text-slate-400 hover:text-rose-400 font-medium transition-colors" title="清除当前会话（自动保存到历史）">
                    <i class="fa-solid fa-broom mr-1"></i>清除会话
                </button>
            </div>

            {#if showHistory}
                <button class="fixed inset-0 z-10 cursor-default" on:click={() => (showHistory = false)} aria-label="关闭历史"></button>
                <div class="absolute right-4 top-14 z-20 w-80 max-h-96 overflow-y-auto bg-slate-900 border border-slate-700 rounded-xl shadow-2xl shadow-black/50 p-1.5">
                    <p class="text-[10px] font-bold text-slate-500 uppercase tracking-wider px-2 py-1.5">对话历史</p>
                    {#each conversations as c (c.id)}
                        <div on:click={() => openConversation(c.id)} on:keydown={(e) => e.key === 'Enter' && openConversation(c.id)} role="button" tabindex="0"
                             class="group flex items-center justify-between px-2.5 py-2 rounded-lg cursor-pointer transition-colors {c.id === convId ? 'bg-indigo-600/20 border border-indigo-500/30' : 'hover:bg-slate-800 border border-transparent'}">
                            <div class="min-w-0 flex-1">
                                <p class="text-[11px] text-slate-200 truncate">{c.title || '新会话'}</p>
                                <p class="text-[9px] text-slate-500 mt-0.5">{fmtTime(c.updated_at)}</p>
                            </div>
                            <button on:click={(e) => deleteConversation(c.id, e)} class="ml-2 shrink-0 text-slate-600 hover:text-rose-400 opacity-0 group-hover:opacity-100 transition-opacity" title="删除会话">
                                <i class="fa-solid fa-trash-can text-[11px]"></i>
                            </button>
                        </div>
                    {:else}
                        <p class="text-[11px] text-slate-600 text-center py-4">暂无历史对话</p>
                    {/each}
                </div>
            {/if}
        </div>

        {#if showSummary}
            <div class="px-4 py-3 border-b border-slate-800 bg-indigo-950/20">
                <p class="text-[10px] font-bold text-indigo-300 uppercase tracking-wider mb-1.5 flex items-center">
                    <i class="fa-solid fa-brain mr-1.5"></i>本会话记忆 / 滚动总结
                </p>
                {#if convSummary}
                    <p class="text-[11px] text-slate-300 leading-relaxed whitespace-pre-wrap">{convSummary}</p>
                {:else}
                    <p class="text-[11px] text-slate-600">对话累积到一定长度后，智能体会自动生成并在此展示会话记忆，用于压缩早期上下文。</p>
                {/if}
            </div>
        {/if}

        <div bind:this={chatScrollRef} class="flex-1 overflow-y-auto p-4 space-y-4">
            {#each messages as msg}
                {#if msg.role === 'user'}
                    <div class="flex space-x-3 items-start justify-end">
                        <div class="bg-indigo-600 text-white rounded-2xl rounded-tr-none p-3.5 text-xs leading-relaxed max-w-[85%] shadow-md">
                            {#if msg.text}<p>{msg.text}</p>{/if}
                            {#if msg.image}<img src={msg.image} alt="" class="mt-2 rounded-lg max-h-32 object-cover border border-indigo-400" />{/if}
                        </div>
                    </div>
                {:else if msg.role === 'tip'}
                    <div class="flex space-x-3 items-start bg-amber-950/40 p-3.5 rounded-2xl border border-amber-500/20">
                        <div class="text-amber-400 p-1 rounded shrink-0 text-xs"><i class="fa-solid fa-sliders"></i></div>
                        <div class="text-[11px] text-slate-300 leading-relaxed">{@html msg.html}</div>
                    </div>
                {:else}
                    <div class="flex space-x-3 items-start">
                        <div class="bg-indigo-600/20 text-indigo-400 border border-indigo-500/20 p-2 rounded-xl shrink-0"><i class="fa-solid fa-robot"></i></div>
                        <div class="bg-slate-900 border border-slate-800 rounded-2xl rounded-tl-none p-3.5 text-xs leading-relaxed max-w-[92%] text-slate-300 shadow-lg space-y-3">
                            {#if msg.html}
                                <div>{@html msg.html}</div>
                            {:else if msg.text}
                                <p class="whitespace-pre-wrap">{msg.text}</p>
                            {/if}
                            {#if msg.tables && msg.tables.length}
                                {#each msg.tables as tbl}
                                    <div>
                                        <p class="text-[11px] font-bold text-indigo-300 mb-1.5"><i class="fa-solid fa-table-cells mr-1"></i>{tbl.title}</p>
                                        <div class="overflow-x-auto border border-slate-800 rounded-lg">
                                            <table class="w-full text-[11px] border-collapse">
                                                <thead class="bg-slate-950/80">
                                                    <tr>
                                                        {#each tbl.columns as col}
                                                            <th class="px-2.5 py-1.5 text-left font-semibold text-slate-400 whitespace-nowrap border-b border-slate-800">{col.label}</th>
                                                        {/each}
                                                    </tr>
                                                </thead>
                                                <tbody class="divide-y divide-slate-800">
                                                    {#each tbl.rows as row}
                                                        <tr class="hover:bg-slate-950/60">
                                                            {#each tbl.columns as col}
                                                                {#if col.type === 'action'}
                                                                    <td class="px-2.5 py-1.5 align-top whitespace-nowrap">
                                                                        <button on:click={() => viewTask(row)}
                                                                                class="text-[11px] px-2 py-0.5 rounded-md bg-indigo-600/20 text-indigo-300 border border-indigo-500/30 hover:bg-indigo-600/40 transition-all">
                                                                            <i class="fa-solid fa-eye mr-1"></i>查看
                                                                        </button>
                                                                    </td>
                                                                {:else if col.key === 'category'}
                                                                    <td class="px-2.5 py-1.5 text-slate-300 align-top break-all max-w-[160px]">{row.category === '大模型任务' ? '智能体任务' : (row.category ?? '—')}</td>
                                                                {:else}
                                                                    <td class="px-2.5 py-1.5 text-slate-300 align-top break-all max-w-[160px]">{row[col.key] ?? '—'}</td>
                                                                {/if}
                                                            {/each}
                                                        </tr>
                                                    {:else}
                                                        <tr><td colspan={tbl.columns.length} class="px-2.5 py-3 text-center text-slate-600">暂无数据，请先在「设备接入」执行「获取详情」同步</td></tr>
                                                    {/each}
                                                </tbody>
                                            </table>
                                        </div>
                                    </div>
                                {/each}
                            {/if}
                        </div>
                    </div>
                {/if}
            {/each}
        </div>

        <div class="px-4 py-2.5 border-t border-slate-800/80 bg-slate-900/20">
            <p class="text-[10px] font-bold text-slate-500 uppercase tracking-wider mb-2">🧠 智能体技能（点击唤起，当前设备：{$selectedDevice?.name || '未选择'}）</p>
            {#if skills.length}
                <div class="grid grid-cols-3 gap-1.5">
                    {#each skills as s (s.id)}
                        <button on:click={() => injectPreset(s.preset)} title={s.description}
                                class="text-left bg-slate-900 hover:bg-indigo-950/40 border border-slate-800 hover:border-indigo-500/50 p-2 rounded-lg transition-all">
                            <div class="text-[11px] font-bold text-slate-200 truncate">{s.icon} {s.name}</div>
                            <div class="text-[9px] text-slate-500 mt-0.5 line-clamp-2 leading-snug">{s.description}</div>
                        </button>
                    {/each}
                </div>
            {:else}
                <div class="grid grid-cols-2 gap-1.5">
                    {#each presets as p}
                        <button on:click={() => injectPreset(p.text)} class="text-[11px] bg-slate-900 text-slate-300 hover:text-indigo-400 border border-slate-800 hover:border-indigo-500/50 p-2 rounded-lg transition-all text-left truncate">
                            {p.icon} <b>{p.text}</b>
                        </button>
                    {/each}
                </div>
            {/if}
        </div>

        <div class="p-4 border-t border-slate-800 bg-slate-950">
            <div class="relative bg-slate-900 border border-slate-800 rounded-2xl focus-within:border-indigo-500 focus-within:ring-2 focus-within:ring-indigo-950 transition-all p-2">
                <textarea bind:value={chatInput} on:keydown={handleEnter} placeholder="向本设备智能体提问，如：当前设备接入了多少个视频流？" class="w-full bg-transparent border-0 focus:outline-none focus:ring-0 text-xs text-slate-200 p-2 resize-none h-16"></textarea>

                {#if chatImage}
                    <div class="relative inline-block m-2 p-1 border border-slate-700 bg-slate-950 rounded-lg">
                        <img src={chatImage} alt="上传预览" class="h-14 w-14 object-cover rounded" />
                        <button on:click={clearUpload} class="absolute -top-1.5 -right-1.5 bg-rose-500 text-white rounded-full p-0.5 hover:bg-rose-600 text-[10px] w-4 h-4 flex items-center justify-center"><i class="fa-solid fa-xmark"></i></button>
                    </div>
                {/if}

                <div class="flex items-center justify-between pt-2 border-t border-slate-800/60 mt-1">
                    <div class="flex items-center space-x-1.5">
                        <button on:click={mockUpload} class="p-2 text-slate-400 hover:text-indigo-400 hover:bg-slate-800/50 rounded-lg transition-colors flex items-center" title="上传示例图片">
                            <i class="fa-solid fa-image text-sm"></i><span class="text-[9px] ml-1.5 text-slate-400">参考小图</span>
                        </button>
                        <button class="p-2 text-slate-400 hover:text-indigo-400 hover:bg-slate-800/50 rounded-lg transition-colors" title="语音指令输入"><i class="fa-solid fa-microphone text-sm"></i></button>
                    </div>
                    {#if sending}
                        <button on:click={stopTask} class="bg-rose-600 hover:bg-rose-700 text-white px-4 py-1.5 rounded-xl text-xs font-semibold flex items-center transition-all shadow-md shadow-rose-500/20">
                            停止任务 <i class="fa-solid fa-stop ml-1.5 text-[10px]"></i>
                        </button>
                    {:else}
                        <button on:click={sendMessage} class="bg-indigo-600 hover:bg-indigo-700 text-white px-4 py-1.5 rounded-xl text-xs font-semibold flex items-center transition-all shadow-md shadow-indigo-500/20">
                            发送 <i class="fa-solid fa-paper-plane ml-1.5 text-[10px]"></i>
                        </button>
                    {/if}
                </div>
            </div>
        </div>
    </div>

    <!-- 右侧：画布 / 参数面板 -->
    <div class="flex-1 flex flex-col h-full bg-slate-900 overflow-y-auto p-5">
        <div class="mb-5 bg-slate-950/60 p-4 rounded-2xl border border-slate-800 flex items-center justify-between">
            <div class="flex items-center space-x-3">
                <div class="bg-indigo-500/10 text-indigo-400 px-2.5 py-1.5 rounded-lg border border-indigo-500/20 text-xs font-bold">双级级联管道</div>
                <div class="flex items-center text-[11px] text-slate-400 flex-wrap gap-y-1">
                    <span class="flow-arrow font-medium">1. 边缘流</span>
                    <span class="flow-arrow text-amber-400 font-bold">2. 小模型检测 (阈值过滤/ROI)</span>
                    <span class="flow-arrow text-blue-400 font-bold">3. 动态扩图裁切</span>
                    <span class="flow-arrow text-purple-400 font-bold">4. VLM Agent 深度识别</span>
                </div>
            </div>
            {#if monitorActive}
                <button on:click={deploy} class="bg-indigo-600 hover:bg-indigo-700 text-white px-4 py-2 rounded-xl text-xs font-bold flex items-center transition-all shadow-md shadow-indigo-500/25 shrink-0">
                    <i class="fa-solid fa-rocket mr-2 animate-bounce"></i>一键部署双级任务
                </button>
            {/if}
        </div>

        <div class="flex flex-col gap-5 items-stretch">
            <!-- 视频流 + 叠加层 -->
            <div class="space-y-4">
                <div class="bg-slate-950 p-4 rounded-2xl border border-slate-800 shadow-sm">
                    <div class="flex items-center justify-between mb-3 pb-3 border-b border-slate-800">
                        <div class="flex items-center space-x-2">
                            <span class="w-2.5 h-2.5 bg-rose-500 rounded-full animate-pulse"></span>
                            <span class="font-bold text-xs text-slate-200">{monitorActive ? `设备实况监视：${$selectedDevice?.name || '当前设备'} (已激活小模型+Agent双层过滤器)` : '未载入通道流 (发送指令激活)'}</span>
                        </div>
                        <div class="flex space-x-1.5 text-[11px] text-slate-400">
                            <button on:click={toggleRoi} class="px-2.5 py-1 rounded border transition-colors {roiDrawActive ? 'bg-indigo-600 text-white border-indigo-600' : 'bg-slate-900 hover:bg-indigo-950 hover:text-indigo-400 border-slate-800 hover:border-indigo-500/30'}">
                                <i class="fa-solid fa-draw-polygon mr-1"></i>画制检测区 (ROI)
                            </button>
                            <button on:click={clearRoi} class="px-2.5 py-1 rounded border bg-slate-900 hover:bg-rose-950 hover:text-rose-400 border-slate-800 hover:border-rose-500/30 transition-colors">
                                <i class="fa-solid fa-eraser mr-1"></i>清除
                            </button>
                            <span class="px-2 py-1 bg-slate-900 rounded border border-slate-800 font-mono">1080P</span>
                        </div>
                    </div>

                    <div class="relative rounded-xl overflow-hidden bg-slate-950 aspect-[16/10]">
                        {#if !monitorActive}
                            <div class="absolute inset-0 flex items-center justify-center text-slate-500 text-xs flex-col space-y-2 px-4 text-center">
                                <i class="fa-solid fa-video-slash text-4xl text-slate-700"></i>
                                <span class="text-slate-400 font-medium">请在左侧对话框下发包含小模型与Agent的级联布控指令</span>
                                <p class="text-[10px] text-slate-600">加载后自动渲染小模型检测框与裁剪扩图边界</p>
                            </div>
                        {:else}
                            <img src={sceneImage || CAM} alt="" class="w-full h-full object-cover" />
                            <svg bind:this={roiSvgRef} on:click={addRoiPoint} role="presentation"
                                 class="absolute inset-0 w-full h-full {roiDrawActive ? 'cursor-crosshair' : 'pointer-events-none'}"
                                 viewBox="0 0 800 500" preserveAspectRatio="none">
                                {#if config.roiPoints && config.roiPoints.length}
                                    <polygon points={roiSvgPoints} fill="rgba(99,102,241,0.14)" stroke="#6366f1" stroke-width="2.5" />
                                    {#each config.roiPoints as p}
                                        <circle cx={p.x * 800} cy={p.y * 500} r="5" fill="#6366f1" stroke="#fff" stroke-width="1.5" />
                                    {/each}
                                {:else}
                                    <polygon points="20,20 780,20 780,480 20,480" fill="rgba(99,102,241,0.06)" stroke="#6366f1" stroke-width="2" stroke-dasharray="6" />
                                {/if}
                            </svg>
                            {#if roiDrawActive}
                                <div class="absolute top-2 left-2 bg-indigo-600/90 text-white text-[10px] font-bold px-2 py-1 rounded shadow">
                                    <i class="fa-solid fa-draw-polygon mr-1"></i>点击画点绘制检测区（已 {config.roiPoints?.length || 0} 点）
                                </div>
                            {/if}
                            <div class="absolute bottom-2 right-2 bg-emerald-600 text-white text-[9px] font-bold px-1.5 py-0.5 rounded shadow flex items-center"><i class="fa-solid fa-crop mr-1"></i> Agent裁图区 (上扩{config.cropUp} / 下{config.cropDown})</div>
                        {/if}
                    </div>
                </div>

                {#if monitorActive}
                    <div class="bg-slate-950 p-4 rounded-2xl border border-slate-800">
                        <div class="flex items-center justify-between mb-3">
                            <div class="flex items-center space-x-2">
                                <span class="p-1 bg-emerald-500/10 text-emerald-400 rounded"><i class="fa-solid fa-crop text-xs"></i></span>
                                <span class="font-bold text-xs text-slate-200">前置轻量算法裁切扩图流 (送检小图预览)</span>
                            </div>
                            <span class="text-[10px] text-slate-500 font-mono">Size: 320x450 (JPG)</span>
                        </div>
                        <div class="grid grid-cols-12 gap-4 items-center">
                            <div class="col-span-4 bg-slate-900 p-2 rounded-xl border border-slate-800 flex justify-center relative overflow-hidden">
                                <img src={CROP} alt="" class="h-28 object-cover rounded border border-slate-700" />
                                <div class="absolute bottom-2 left-2 bg-slate-950/80 text-[9px] text-emerald-400 px-2 py-0.5 rounded-full border border-emerald-500/20 font-mono">裁剪特写</div>
                            </div>
                            <div class="col-span-8 space-y-2">
                                <p class="text-xs text-slate-400 leading-relaxed">
                                    <i class="fa-solid fa-circle-info text-indigo-400 mr-1"></i>
                                    <b>边缘协同机制</b>：端侧 YOLO 小模型敏捷捕获运动目标，触发过滤规则后按倍数裁切高分辨率小图，仅将此<b>“局部特写图”</b>送往大模型 Agent 精细推理，使边缘布控的<b>带宽与算力成本降低 85%</b>。
                                </p>
                                <div class="flex space-x-2 text-[10px]">
                                    <span class="bg-indigo-950 text-indigo-300 border border-indigo-500/20 px-2 py-1 rounded font-mono">输入大小: ~25KB</span>
                                    <span class="bg-emerald-950 text-emerald-300 border border-emerald-500/20 px-2 py-1 rounded font-mono">大模型推理耗时: ~120ms</span>
                                </div>
                            </div>
                        </div>
                    </div>
                {/if}
            </div>

            <!-- 参数控制面板（移至视频流下方，横向铺满） -->
            <div class="space-y-4">
                <div class="bg-slate-950 p-5 rounded-2xl border border-slate-800 shadow-lg relative overflow-hidden">
                    <div class="absolute top-0 right-0 h-16 w-16 bg-indigo-500/5 rounded-bl-full flex items-center justify-end pr-4 pt-4 pointer-events-none">
                        <i class="fa-solid fa-code-merge text-indigo-500/40 text-base animate-pulse"></i>
                    </div>
                    <h3 class="font-bold text-white text-xs mb-4 flex items-center">
                        <span class="bg-indigo-600 text-white p-1 rounded mr-2"><i class="fa-solid fa-sliders text-xs"></i></span>
                        AI 级联提取与细化控制面板
                    </h3>

                    <div class="grid grid-cols-1 xl:grid-cols-3 gap-4 text-xs items-start">
                        <!-- 1. 前置轻量级算法 -->
                        <div class="bg-slate-900/60 p-3.5 rounded-xl border border-slate-800/80 space-y-3 h-full">
                            <div class="flex items-center justify-between border-b border-slate-800 pb-2">
                                <span class="font-extrabold text-amber-400 flex items-center"><i class="fa-solid fa-microchip mr-1.5"></i> 1. 前置轻量级算法配置</span>
                                <span class="text-[9px] text-slate-500">端侧低算力常驻运行</span>
                            </div>
                            <div class="grid grid-cols-2 gap-3">
                                <div>
                                    <div class="flex justify-between items-center mb-1 text-[10px]"><label class="text-slate-400">最大目标限制</label><span class="font-mono text-amber-400">{(+config.maxTarget).toFixed(2)}</span></div>
                                    <input type="range" min="0" max="1" step="0.05" bind:value={config.maxTarget} class="w-full h-1 bg-slate-800 rounded-lg appearance-none cursor-pointer accent-amber-500" />
                                </div>
                                <div>
                                    <div class="flex justify-between items-center mb-1 text-[10px]"><label class="text-slate-400">最小目标限制</label><span class="font-mono text-amber-400">{(+config.minTarget).toFixed(2)}</span></div>
                                    <input type="range" min="0" max="1" step="0.05" bind:value={config.minTarget} class="w-full h-1 bg-slate-800 rounded-lg appearance-none cursor-pointer accent-amber-500" />
                                </div>
                            </div>
                            <div class="grid grid-cols-2 gap-3">
                                <div>
                                    <div class="flex justify-between items-center mb-1 text-[10px]"><label class="text-slate-400">人体检测阈值</label><span class="font-mono text-amber-400">{config.yoloHumanThresh}</span></div>
                                    <input type="range" min="0.1" max="0.9" step="0.01" bind:value={config.yoloHumanThresh} class="w-full h-1 bg-slate-800 rounded-lg appearance-none cursor-pointer accent-amber-500" />
                                </div>
                                <div>
                                    <div class="flex justify-between items-center mb-1 text-[10px]"><label class="text-slate-400">机动车检测阈值</label><span class="font-mono text-amber-400">{config.yoloVehicleThresh}</span></div>
                                    <input type="range" min="0.1" max="0.9" step="0.01" bind:value={config.yoloVehicleThresh} class="w-full h-1 bg-slate-800 rounded-lg appearance-none cursor-pointer accent-amber-500" />
                                </div>
                            </div>
                            <div class="grid grid-cols-2 gap-3">
                                <div>
                                    <label class="block text-[10px] text-slate-400 mb-1">前置检测目标</label>
                                    <select bind:value={config.yoloTarget} class="w-full bg-slate-950 border border-slate-800 text-slate-200 rounded p-1.5 focus:border-amber-500 text-[11px]">
                                        <option value="human">人员 (人体检测)</option>
                                        <option value="vehicle">车辆</option>
                                        <option value="any">全部目标</option>
                                    </select>
                                </div>
                                <div>
                                    <div class="flex justify-between items-center mb-1 text-[10px]"><label class="text-slate-400">非机动车检测阈值</label><span class="font-mono text-amber-400">{config.yoloNonMotorThresh}</span></div>
                                    <input type="range" min="0.1" max="0.9" step="0.01" bind:value={config.yoloNonMotorThresh} class="w-full h-1 bg-slate-800 rounded-lg appearance-none cursor-pointer accent-amber-500" />
                                </div>
                            </div>
                            <div class="grid grid-cols-2 gap-3">
                                <div>
                                    <label class="block text-[10px] text-slate-400 mb-1">入侵时长检测 (单位:秒)</label>
                                    <input type="number" bind:value={config.intrusionDuration} class="w-full bg-slate-950 border border-slate-800 text-slate-200 rounded p-1.5 focus:border-amber-500 text-[11px] font-mono text-center" />
                                </div>
                                <div>
                                    <label class="block text-[10px] text-slate-400 mb-1">报警间隔时长 (单位:秒)</label>
                                    <input type="number" bind:value={config.alarmInterval} class="w-full bg-slate-950 border border-slate-800 text-slate-200 rounded p-1.5 focus:border-amber-500 text-[11px] font-mono text-center" />
                                </div>
                            </div>
                        </div>

                        <!-- 2. 扩图倍数 -->
                        <div class="bg-slate-900/60 p-3.5 rounded-xl border border-slate-800/80 space-y-3 h-full">
                            <div class="flex items-center justify-between border-b border-slate-800 pb-2">
                                <span class="font-extrabold text-emerald-400 flex items-center"><i class="fa-solid fa-crop-simple mr-1.5"></i> 2. 目标扩图倍数配置</span>
                                <span class="text-[9px] text-emerald-500/80 font-bold">小图截取缩放比例</span>
                            </div>
                            <div class="grid grid-cols-4 gap-2">
                                <div><label class="block text-[9px] text-slate-500 text-center mb-0.5">上 (UP)</label><input type="number" step="0.1" bind:value={config.cropUp} class="w-full bg-slate-950 border border-slate-800 text-emerald-400 rounded p-1 text-center font-mono font-bold text-[11px]" /></div>
                                <div><label class="block text-[9px] text-slate-500 text-center mb-0.5">下 (DOWN)</label><input type="number" step="0.1" bind:value={config.cropDown} class="w-full bg-slate-950 border border-slate-800 text-emerald-400 rounded p-1 text-center font-mono font-bold text-[11px]" /></div>
                                <div><label class="block text-[9px] text-slate-500 text-center mb-0.5">左 (LEFT)</label><input type="number" step="0.1" bind:value={config.cropLeft} class="w-full bg-slate-950 border border-slate-800 text-emerald-400 rounded p-1 text-center font-mono font-bold text-[11px]" /></div>
                                <div><label class="block text-[9px] text-slate-500 text-center mb-0.5">右 (RIGHT)</label><input type="number" step="0.1" bind:value={config.cropRight} class="w-full bg-slate-950 border border-slate-800 text-emerald-400 rounded p-1 text-center font-mono font-bold text-[11px]" /></div>
                            </div>
                            <p class="text-[9px] text-slate-500 leading-relaxed text-center">扩图能够为 VLM 深度智能体提供足够的环境上下文关系，防止小图特征过窄。</p>
                        </div>

                        <!-- 3. 后置 Agent -->
                        <div class="bg-slate-900/60 p-3.5 rounded-xl border border-slate-800/80 space-y-3 h-full">
                            <div class="flex items-center justify-between border-b border-slate-800 pb-2">
                                <span class="font-extrabold text-indigo-400 flex items-center"><i class="fa-solid fa-brain mr-1.5"></i> 3. 级联后置多模态 Agent</span>
                                <div class="flex items-center space-x-1.5"><span class="text-[9px] text-slate-500">关联智能体</span><input type="checkbox" checked class="w-3.5 h-3.5 text-indigo-600 bg-slate-950 border-slate-800 rounded cursor-pointer" /></div>
                            </div>
                            <div class="grid grid-cols-2 gap-3">
                                <div><label class="block text-[10px] text-slate-400 mb-1">目标任务名称</label><input type="text" bind:value={config.name} placeholder="自动计算生成" class="w-full bg-slate-950 border border-slate-800 text-slate-200 rounded p-2 focus:border-indigo-500 text-[11px]" /></div>
                                <div>
                                    <label class="block text-[10px] text-slate-400 mb-1">选择目标智能体</label>
                                    <select bind:value={config.agentType} class="w-full bg-slate-950 border border-slate-800 text-slate-200 rounded p-2 focus:border-indigo-500 text-[11px]">
                                        <option value="跌倒test">跌倒test (异常形体判别)</option>
                                        <option value="吊装中">吊装中 (防掉落吊钩异常识别)</option>
                                        <option value="表面缺陷">表面缺陷 (划痕缺陷)</option>
                                        <option value="防护装备">防护装备 (PPE安全服)</option>
                                    </select>
                                </div>
                            </div>
                            <div>
                                <div class="flex justify-between items-center mb-1"><label class="text-[10px] text-slate-400">智能体大模型视觉推理 Prompt 策略</label><span class="text-[9px] text-slate-600">Markdown语义控制</span></div>
                                <textarea bind:value={config.prompt} rows="5" class="w-full text-[11px] font-mono text-slate-300 bg-slate-950 border border-slate-800 focus:border-indigo-500 rounded p-2 leading-relaxed" placeholder="等待指令注入..."></textarea>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    </div>
</div>

<style>
    .flow-arrow::after { content: "➔"; margin: 0 8px; color: #475569; }
    .flow-arrow:last-child::after { content: ""; }
</style>
