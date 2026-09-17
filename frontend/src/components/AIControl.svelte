<script>
    import { onMount, tick } from 'svelte';
    import { showToast, switchTab, chatRequest, selectedDevice } from '../lib/controlStore.js';
    import { apiPost, apiGet, apiDelete, API_BASE } from '../lib/api.js';

    const LS_CONV_KEY = 'aiChatConvId';

    // 无报警大图时的默认场景：内联 SVG（自包含，不依赖外网/CDN，边缘内网可用），仍可在其上绘制 ROI
    const CAM = 'data:image/svg+xml,' + encodeURIComponent(
        `<svg xmlns="http://www.w3.org/2000/svg" width="800" height="500" viewBox="0 0 800 500">
          <rect width="800" height="500" fill="#0f172a"/>
          <g stroke="#1e293b" stroke-width="1">
            <path d="M0 125H800M0 250H800M0 375H800M200 0V500M400 0V500M600 0V500"/>
          </g>
          <g fill="none" stroke="#334155" stroke-width="3">
            <path d="M40 40H100M40 40V100M760 40H700M760 40V100M40 460H100M40 460V400M760 460H700M760 460V400"/>
          </g>
          <g transform="translate(400 210)" fill="none" stroke="#475569" stroke-width="4" stroke-linecap="round" stroke-linejoin="round">
            <rect x="-46" y="-30" width="70" height="52" rx="8"/>
            <path d="M24 -12 54 -28V22L24 6"/>
          </g>
          <text x="400" y="300" fill="#64748b" font-family="sans-serif" font-size="24" font-weight="bold" text-anchor="middle">暂无报警大图</text>
          <text x="400" y="332" fill="#475569" font-family="sans-serif" font-size="14" text-anchor="middle">默认场景 · 可直接在此绘制检测区(ROI)</text>
        </svg>`);
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
        name: '', device: 'diaozhuang-2', interval: 5, agentType: '跌倒test', prompt: '',
        yoloTarget: 'human', yoloHumanThresh: 0.31, yoloVehicleThresh: 0.32, yoloNonMotorThresh: 0.37,
        intrusionDuration: 3, alarmInterval: 10,
        cropUp: 0.5, cropDown: 0.3, cropLeft: 0.4, cropRight: 0.6,
        maxTarget: 1.0, minTarget: 0.0, roiPoints: [],
        event_type: '', algo_cabin_name: '',    // 算法标识（propose/对话填充；查看态无来源，靠 deploy() guard 拦截）
        // 智能体任务（agent_real_task）专用：
        taskMode: 'smallmodel',   // 'agent' | 'smallmodel' | 'combined'
        channel_device_id: null,
        device_id: null,
        agents: [],               // ≤4：{event_id,event_tag,alarm_type,prompt,alarm_condition,filter_enable,filter_keywords,roiId}
        // 算法仓（小模型/小+大）任务：多算法项，每项自带参数 + 绑池 ROI（roiId），与 agents[] 镜像。
        // Phase 1：由 propose/模板/查看归一化为【单项】；Phase 2 再加多槽编辑器。
        algorithms: [],           // {kind,event_type,algo_cabin_name,version,useFullFrame,roiId, 各参数…}
        rois: [{ id: 'full', name: '全屏检测', points: [] }],   // 任务级 ROI 池（两种模式共享）
        activeAgentIndex: 0,
        activeAlgorithmIndex: 0
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
    let templateApplied = false;   // true=当前面板参数来自「套用模板」(路径 b/c)，部署时跳过强制 ROI 门禁；手动配置为 false
    let monitorActive = false;
    let roiDrawActive = false;
    let sceneImage = null;   // 视频区载入的真实报警大图（绝对 URL），null 时回退占位图
    let roiSvgRef;           // ROI 绘制图层，用于把点击换算成归一化坐标
    let chatScrollRef;
    let skills = [];         // 后端技能注册表元数据（/skills）
    let convSummary = '';    // 本会话滚动记忆/总结
    let showSummary = false; // 会话记忆面板开关
    let availableAgents = []; // 设备可选智能体算法（供智能体任务下拉，最多选 4）
    let availableAlgorithms = []; // 设备可选小模型算法目录（供小模型/小+大任务 Step1 多选）
    let wizardStep = 1;       // 右侧画板三步向导当前步：1 任务信息 / 2 ROI绘制 / 3 详情参数
    const WIZARD_STEPS = [
        { n: 1, ord: '第一步', label: '任务信息与算法选型' },
        { n: 2, ord: '第二步', label: 'ROI 绘制与算法关联' },
        { n: 3, ord: '第三步', label: '算法/智能体详情参数' }
    ];

    // convId 变化时持久化，刷新后可恢复到同一会话
    $: if (convId) localStorage.setItem(LS_CONV_KEY, convId);

    // ── 派生态：智能体任务 & 算法仓任务共享「池 + 逐项 ROI 绑定」模型 ────────
    $: isAgentTask = config.taskMode === 'agent';
    $: activeAgent = (config.agents || [])[config.activeAgentIndex] || null;
    // 算法仓任务的当前编辑算法项（与 activeAgent 镜像；Phase 1 恒为第 0 项）
    $: activeAlgorithm = (config.algorithms || [])[config.activeAlgorithmIndex] || null;
    // ROI 绘制/绑定的作用对象：大模型任务=当前智能体，算法仓任务=当前算法项
    $: activeItem = isAgentTask ? activeAgent : activeAlgorithm;
    $: activeRoi = (config.rois || []).find((r) => r.id === activeItem?.roiId) || (config.rois || [])[0] || { points: [] };

    // Step1「关联通道」下拉项：解析 $selectedDevice.channels（镜像 Alerts.svelte parseChannelsNames：按 device_id 去重 + display_name）
    $: channelOptions = (() => {
        let list = [];
        try { list = JSON.parse($selectedDevice?.channels || '[]'); } catch (e) { list = []; }
        const seen = new Set();
        const out = [];
        for (const c of (Array.isArray(list) ? list : [])) {
            const id = c.device_id;
            if (id === undefined || id === null) continue;
            const key = String(id);
            if (seen.has(key)) continue;
            seen.add(key);
            out.push({ device_id: id, display_name: `${c.device_name || '通道'}-${id}` });
        }
        return out;
    })();

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
        templateApplied = false;
        monitorActive = false;
        roiDrawActive = false;
        sceneImage = null;
        showHistory = false;
        convSummary = '';
        showSummary = false;
        availableAgents = [];
        availableAlgorithms = [];
        wizardStep = 1;
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

    // 在报警大图上点击落点，构成检测区(ROI)多边形；坐标归一化到 0~1。
    // 两种任务共用一条代码路径：写入【当前活动项 activeItem】(大模型=当前智能体 / 算法仓=当前算法)
    // 绑定的池 ROI；若当前绑的是全屏，则先新建一个「检测区N」池项并把 activeItem 改绑到它。
    function addRoiPoint(ev) {
        if (!roiDrawActive || !roiSvgRef || !activeItem) return;
        const rect = roiSvgRef.getBoundingClientRect();
        const x = Math.min(1, Math.max(0, (ev.clientX - rect.left) / rect.width));
        const y = Math.min(1, Math.max(0, (ev.clientY - rect.top) / rect.height));
        const pt = { x: +x.toFixed(4), y: +y.toFixed(4) };
        let roiId = activeItem.roiId;
        if (roiId === 'full') {
            // 从全屏切到自定义检测区：新建区域并把当前项改绑到它
            const n = config.rois.filter((r) => r.id !== 'full').length + 1;
            roiId = 'roi_' + Date.now();
            config.rois = [...config.rois, { id: roiId, name: `检测区${n}`, points: [] }];
            activeItem.roiId = roiId;
            if (!isAgentTask) activeItem.useFullFrame = false;  // 画了自定义区即取消「全屏」标记（仅算法仓项有此字段）
            syncActiveItem();
        }
        config.rois = config.rois.map((r) => r.id === roiId ? { ...r, points: [...r.points, pt] } : r);
    }

    // 把当前活动项(activeItem)写回其所属数组，触发 Svelte 响应式刷新（两模式各自的数组）
    function syncActiveItem() {
        if (isAgentTask) config.agents = [...config.agents];
        else config.algorithms = [...config.algorithms];
    }

    function clearRoi() {
        if (!activeItem) return;
        const roiId = activeItem.roiId;
        if (roiId === 'full') {
            showToast('全屏检测无需清除。请先选择/绘制自定义检测区。', 'info');
            return;
        }
        // 移除该自定义检测区并把当前项回落到全屏
        config.rois = config.rois.filter((r) => r.id !== roiId);
        activeItem.roiId = 'full';
        if (!isAgentTask) activeItem.useFullFrame = false;
        syncActiveItem();
        showToast(isAgentTask ? '已清除该智能体的检测区，已回落为全屏检测。' : '已清除该算法的检测区，已回落为全屏检测。', 'info');
    }

    // roiPoints -> SVG points 字符串（viewBox 800x500）：取当前活动项绑定的池 ROI
    $: currentRoiPoints = (activeRoi?.points) || [];
    $: roiSvgPoints = currentRoiPoints.map((p) => `${p.x * 800},${p.y * 500}`).join(' ');

    // 切换当前编辑的智能体
    function selectAgent(i) {
        config.activeAgentIndex = i;
    }

    // 当前活动项绑定某个 ROI（列表单选：改绑即切换）
    function bindRoi(roiId) {
        if (!activeItem) return;
        activeItem.roiId = roiId;
        if (!isAgentTask) activeItem.useFullFrame = (roiId === 'full');  // 绑到 full 即显式选择全屏
        syncActiveItem();
    }

    // 算法仓任务：切「本算法使用全屏检测」——勾选即回落到 'full' 池项并置标记（供门禁放行）
    function toggleActiveFullFrame(checked) {
        if (!activeAlgorithm) return;
        activeAlgorithm.useFullFrame = checked;
        if (checked) activeAlgorithm.roiId = 'full';
        config.algorithms = [...config.algorithms];
    }

    // 新增一个智能体槽位（≤4），默认取第一个未被占用的可选智能体
    function addAgentSlot() {
        if (config.agents.length >= 4) return;
        const a = availableAgents[0] || {};
        config.agents = [...config.agents, {
            event_id: a.event_id || '', event_tag: a.event_tag || '',
            alarm_type: a.alarm_type || 'freeform', prompt: a.prompt || '',
            alarm_condition: a.alarm_condition || null, filter_enable: false, filter_keywords: '', roiId: 'full'
        }];
        config.activeAgentIndex = config.agents.length - 1;
    }

    function removeAgentSlot(i) {
        if (config.agents.length <= 1) return;
        config.agents = config.agents.filter((_, idx) => idx !== i);
        if (config.activeAgentIndex >= config.agents.length) config.activeAgentIndex = config.agents.length - 1;
    }

    // 某槽位切换所选智能体：从 availableAgents 同步 event_tag/alarm_type/prompt/alarm_condition
    function changeAgent(i, eventId) {
        const src = availableAgents.find((a) => String(a.event_id) === String(eventId)) || {};
        config.agents = config.agents.map((a, idx) => idx === i ? {
            ...a, event_id: eventId, event_tag: src.event_tag || eventId,
            alarm_type: src.alarm_type || 'freeform', prompt: src.prompt || a.prompt || '',
            // 换智能体即改用新智能体自身的报警条件；设备未给则置 null 交后端按 alarm_type 推导，
            // 避免把上一个智能体的条件残留到新选中的智能体上
            alarm_condition: src.alarm_condition || null
        } : a);
    }

    // 判断型(yesno)智能体的报警条件：勾选=only_yes（仅「是」报警），不勾=none（是/否都报警）
    function setAgentAlarmCondition(onlyYes) {
        if (!activeAgent) return;
        const idx = config.activeAgentIndex;
        config.agents = config.agents.map((a, i) => i === idx ? { ...a, alarm_condition: onlyYes ? 'only_yes' : 'none' } : a);
    }

    // 拉取设备可选智能体列表（refresh=false 用快照，离线安全）供下拉展示
    async function loadAvailableAgents() {
        const device = $selectedDevice;
        if (!device?.id) { availableAgents = []; return; }
        try {
            const res = await apiGet(`/devices/${device.id}/agents?refresh=false`);
            availableAgents = res?.agents || [];
        } catch (e) {
            availableAgents = [];
        }
    }

    // ── 算法目录（小模型/小+大）：供 Step1 多选/新增算法。优先用 proposal.available_algorithms，
    //    缺失时 best-effort 解析设备快照 $selectedDevice.available_algorithms / algorithms_ability。
    async function loadAvailableAlgorithms() {
        const dev = $selectedDevice;
        let raw = [];
        try { raw = JSON.parse(dev?.available_algorithms || dev?.algorithms_ability || '[]'); } catch (e) { raw = []; }
        availableAlgorithms = (Array.isArray(raw) ? raw : []).map((a) => ({
            algoCabinName: a.algoCabinName || a.alg_name || a.algo_cabin_name || '',
            version: a.version || a.alg_version || 'V2.0.0',
            eventType: a.eventType || a.event_type || a.alertor_type || '',
            eventName: a.eventName || a.event_name || '',
            targetTypes: a.targetTypes || a.target_type || []
        })).filter((a) => a.eventType || a.algoCabinName);
    }

    // 算法仓任务目录预热：算法目录（rows 优先用后端 proposal.available_algorithms，缺失则解析设备快照）
    // + 小+大任务额外取智能体目录（Step1 逐算法/Step3 的「二次大模型」下拉需要）
    async function loadWarehouseCatalogs(rows) {
        availableAlgorithms = Array.isArray(rows) && rows.length ? rows : [];
        if (!availableAlgorithms.length) await loadAvailableAlgorithms();
        if (config.taskMode === 'combined' && !availableAgents.length) await loadAvailableAgents();
    }

    // Step1 切换关联通道：仅改写 config.channel_device_id（下发直接读它）。
    // 已知边界：智能体槽位上的「已布控」徽标是按方案原通道注入的，切通道后不自动重拉，故提示用户核对。
    function onChannelChange() {
        if (isAgentTask && (config.agents || []).some((a) => a.deployed)) {
            showToast('已切换目标通道；槽位上的「已布控」标记仍来自原通道，请自行核对。', 'warning');
        }
    }

    // 算法目录行/算法项的复合标识（事件类型 + 算法仓名），用于下拉选中与切换定位
    const algoOptionKey = (a) => `${a?.eventType || ''}|${a?.algoCabinName || ''}`;
    const algoItemKey = (it) => `${it?.event_type || ''}|${it?.algo_cabin_name || ''}`;
    // 算法项展示名：优先取目录中文事件名，回退事件类型/算法仓名
    function algoLabel(it) {
        if (!it) return '算法';
        const hit = availableAlgorithms.find((a) => algoOptionKey(a) === algoItemKey(it));
        return hit?.eventName || hit?.eventType || it.event_type || it.algo_cabin_name || '算法';
    }

    // 把顶层面板参数写回【当前算法项】（切项/新增前保参）；combined 额外同步 agent_id/agentType
    function writeBackActiveAlgorithm() {
        const idx = config.activeAlgorithmIndex || 0;
        const cur = (config.algorithms || [])[idx];
        if (!cur) return;
        for (const k of PANEL_PARAM_KEYS) if (config[k] !== undefined) cur[k] = config[k];
        if ((cur.kind || 'small') === 'combined') {
            cur.agent_id = config.agentType || cur.agent_id || '';
            cur.agentType = cur.agent_id;
        }
        config.algorithms = [...config.algorithms];
    }

    // 切换当前编辑算法：先写回旧项，再 activeAlgorithmIndex=i，再把新项参数提到顶层（面板绑顶层 = 当前算法）
    function selectAlgorithm(i) {
        if (!config.algorithms || i < 0 || i >= config.algorithms.length) return;
        if (i === (config.activeAlgorithmIndex || 0)) return;
        writeBackActiveAlgorithm();
        config.activeAlgorithmIndex = i;
        const item = config.algorithms[i];
        config = { ...config, ...hoistItemParams(item) };
        if ((item.kind || 'small') === 'combined') config.agentType = item.agent_id || item.agentType || '';
    }

    // 新增算法槽：默认取目录首项，逐项参数对齐 defaultConfig（供 Step3 细调）；combined 附二次大模型占位
    function addAlgorithmSlot() {
        if (!availableAlgorithms.length) { showToast('暂无可选算法目录（设备离线或未授权时不可新增算法）。', 'warning'); return; }
        writeBackActiveAlgorithm();
        const a = availableAlgorithms[0] || {};
        const kind = config.taskMode === 'combined' ? 'combined' : 'small';
        const item = {
            kind,
            event_type: a.eventType || '', algo_cabin_name: a.algoCabinName || '', version: a.version || 'V2.0.0',
            roiId: 'full', useFullFrame: false,
            maxTarget: defaultConfig.maxTarget, minTarget: defaultConfig.minTarget, yoloTarget: defaultConfig.yoloTarget,
            yoloHumanThresh: defaultConfig.yoloHumanThresh, yoloVehicleThresh: defaultConfig.yoloVehicleThresh,
            yoloNonMotorThresh: defaultConfig.yoloNonMotorThresh,
            intrusionDuration: defaultConfig.intrusionDuration, alarmInterval: defaultConfig.alarmInterval,
            cropUp: defaultConfig.cropUp, cropDown: defaultConfig.cropDown, cropLeft: defaultConfig.cropLeft, cropRight: defaultConfig.cropRight
        };
        if (kind === 'combined') { item.agent_id = ''; item.agentType = ''; item.event_tag = ''; item.prompt = ''; }
        config.algorithms = [...config.algorithms, item];
        config.activeAlgorithmIndex = config.algorithms.length - 1;
        config = { ...config, ...hoistItemParams(item) };
    }

    function removeAlgorithmSlot(i) {
        if ((config.algorithms || []).length <= 1) return;
        let idx = config.activeAlgorithmIndex || 0;
        config.algorithms = config.algorithms.filter((_, k) => k !== i);
        if (i < idx) idx -= 1;
        else if (i === idx) idx = Math.min(idx, config.algorithms.length - 1);
        config.activeAlgorithmIndex = Math.max(0, idx);
        config = { ...config, ...hoistItemParams(config.algorithms[config.activeAlgorithmIndex]) };
    }

    // 某算法槽切换所选算法：从目录同步 event_type/algo_cabin_name/version
    function changeAlgorithm(i, key) {
        const src = availableAlgorithms.find((a) => algoOptionKey(a) === key) || {};
        config.algorithms = config.algorithms.map((a, idx) => idx === i ? {
            ...a, event_type: src.eventType || a.event_type || '',
            algo_cabin_name: src.algoCabinName || a.algo_cabin_name || '', version: src.version || a.version || 'V2.0.0'
        } : a);
    }

    // combined 算法项切换二次大模型：写 item.agent_id/agentType/event_tag；若为当前项同步顶层 agentType
    function changeAlgoAgent(i, eventId) {
        const src = availableAgents.find((a) => String(a.event_id) === String(eventId)) || {};
        config.algorithms = config.algorithms.map((a, idx) => idx === i ? {
            ...a, agent_id: eventId, agentType: eventId, event_tag: src.event_tag || a.event_tag || String(eventId)
        } : a);
        if (i === (config.activeAlgorithmIndex || 0)) config.agentType = eventId;
    }

    // ── ROI 池：改名 / 删除（删除后引用它的算法/智能体回落全屏；全屏项为默认不可删/改） ──
    function renameRoi(id, name) {
        if (id === 'full') return;
        config.rois = config.rois.map((r) => r.id === id ? { ...r, name } : r);
    }
    function deleteRoi(id) {
        if (id === 'full') { showToast('全屏检测为默认项，不可删除。', 'info'); return; }
        config.rois = config.rois.filter((r) => r.id !== id);
        config.agents = (config.agents || []).map((a) => a.roiId === id ? { ...a, roiId: 'full' } : a);
        config.algorithms = (config.algorithms || []).map((a) => a.roiId === id ? { ...a, roiId: 'full', useFullFrame: true } : a);
        showToast('已删除该检测区，关联项已回落为全屏检测。', 'info');
    }

    // ── 第②步「ROI 区域管理与算法绑定对应关系表」视图辅助 ────────────────
    // 「显示」列：仅控制该检测区是否在画布上叠加预览，纯视图态，不进入 config/部署 payload
    let hiddenRoiIds = new Set();
    function toggleRoiVisible(id) {
        if (hiddenRoiIds.has(id)) hiddenRoiIds.delete(id);
        else hiddenRoiIds.add(id);
        hiddenRoiIds = hiddenRoiIds;   // 重新赋值以触发 Svelte 响应式
    }

    // 删除/重置/切会话后清掉已不存在的检测区 id，避免 'roi_1' 这类固定 id 被复用时误继承隐藏态
    $: if (config.rois) {
        const live = new Set(config.rois.map((r) => r.id));
        let pruned = false;
        for (const id of hiddenRoiIds) if (!live.has(id)) { hiddenRoiIds.delete(id); pruned = true; }
        if (pruned) hiddenRoiIds = hiddenRoiIds;
    }
    // 第①步勾选的算法/智能体 -> 表格里的可勾选列
    $: boundItems = isAgentTask
        ? (config.agents || []).map((a, i) => ({ i, kind: 'Agent', label: a.event_tag || '智能体', note: a.alarm_type === 'freeform' ? '描述型' : '判断型', roiId: a.roiId }))
        : (config.algorithms || []).map((a, i) => ({ i, kind: '小模型', label: algoLabel(a), note: '', roiId: a.roiId }));
    // 自定义检测区（不含默认「全屏检测」伪项，它没有几何形状、不可改名删除）
    $: customRois = (config.rois || []).filter((r) => r.id !== 'full');
    // 仍是全屏检测（未绑定任何自定义区域）的项，表尾汇总提示用
    $: fullFrameItems = boundItems.filter((it) => it.roiId === 'full' || !it.roiId);
    // 画布叠加层：勾了「显示」、且不是当前正在编辑的那个区域
    $: overlayRois = customRois.filter((r) => !hiddenRoiIds.has(r.id) && r.id !== activeItem?.roiId && (r.points || []).length >= 3);

    // 表内勾选：把第 i 个算法/智能体绑到该检测区；取消勾选则回落全屏。
    // 与 bindRoi 同语义（数据模型仍是「每项单绑一个检测区」），只是把隐式的「当前活动项」改为显式下标。
    function toggleItemRoi(i, roiId, checked) {
        const target = checked ? roiId : 'full';
        if (isAgentTask) {
            config.agents = config.agents.map((a, idx) => idx === i ? { ...a, roiId: target } : a);
        } else {
            config.algorithms = config.algorithms.map((a, idx) => idx === i ? { ...a, roiId: target, useFullFrame: target === 'full' } : a);
        }
    }

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
        templateApplied = false;
        monitorActive = true;
        wizardStep = 1;
        showToast('双级级联配置参数填充，裁切扩图区域渲染成功！', 'success');
        scrollToBottom();
    }

    // 面板三列参数（Phase 1 绑顶层 config）对应的键：多算法回填时把当前算法项的这些参数提到顶层，
    // 使单算法面板显示/编辑的是「当前算法」的真实值（下发时当前项也回读顶层，保持一致）。
    const PANEL_PARAM_KEYS = ['maxTarget', 'minTarget', 'yoloHumanThresh', 'yoloVehicleThresh',
        'yoloNonMotorThresh', 'yoloTarget', 'intrusionDuration', 'alarmInterval',
        'cropUp', 'cropDown', 'cropLeft', 'cropRight', 'prompt', 'agentType'];
    function hoistItemParams(item) {
        const out = {};
        for (const k of PANEL_PARAM_KEYS) if (item && item[k] !== undefined) out[k] = item[k];
        return out;
    }

    // 把「算法仓任务」来源(d) 归一化为面板可用的 {algorithms[], rois[] 池, activeAlgorithmIndex}：
    // - d.algorithms 存在（后端 detail 烘焙的多算法逆映射 / 新模板）→ 采用其池与算法项，并把当前算法参数提到顶层供面板；
    // - 旧单算法快照/模板（仅 event_type/algo_cabin_name/roiPoints/顶层阈值）→ 归一化为【单项】algorithms[] + 池。
    // 顶层参数键保留（Phase 1 三列面板仍绑顶层）；下发时当前项读顶层、其余项读各自 item（多算法原样 round-trip）。
    function normalizeWarehouseConfig(base, d) {
        if (Array.isArray(d.algorithms) && d.algorithms.length) {
            const rois = (Array.isArray(d.rois) && d.rois.length) ? d.rois : [{ id: 'full', name: '全屏检测', points: [] }];
            const idx = d.activeAlgorithmIndex || 0;
            const active = d.algorithms[idx] || d.algorithms[0];
            const out = {
                ...base, ...d, ...hoistItemParams(active),
                algorithms: d.algorithms, rois,
                activeAlgorithmIndex: idx, roiPoints: []
            };
            // combined：顶层 agentType 用 event_id（对齐 Step3 下拉选项与下发 agent_id，避免误用 event_tag）
            if ((active?.kind || 'small') === 'combined') out.agentType = active.agentType || active.agent_id || out.agentType || '';
            return out;
        }
        // 旧单算法：由 event_type/algo_cabin_name/roiPoints(顶层) 组装一条 algorithms[] + 一个池 ROI
        const pts = d.roiPoints || base.roiPoints || [];
        const rois = [{ id: 'full', name: '全屏检测', points: [] }];
        let roiId = 'full';
        let useFullFrame = false;
        if (pts.length >= 3) { roiId = 'roi_1'; rois.push({ id: roiId, name: '检测区1', points: pts }); }
        const kind = (d.taskMode === 'combined') ? 'combined' : 'small';
        const item = {
            kind,
            event_type: d.event_type || base.event_type || '',
            algo_cabin_name: d.algo_cabin_name || base.algo_cabin_name || '',
            version: d.version || 'V2.0.0',
            roiId, useFullFrame
        };
        if (kind === 'combined') {
            item.agent_id = d.agent_id || d.agentType || '';
            item.event_tag = d.event_tag || d.agentType || '';
        }
        return {
            ...base, ...d,
            algorithms: [item], rois,
            activeAlgorithmIndex: 0, roiPoints: pts,
            // combined：顶层 agentType 用 event_id（对齐 Step3 下拉选项与下发 agent_id，避免误用 event_tag）
            ...(kind === 'combined' ? { agentType: item.agent_id || '' } : {})
        };
    }

    // 智能体返回布控方案：填充推荐参数 -> 载入真实报警大图 -> 激活监视 + 开启 ROI 绘制
    async function applyProposal(proposal) {
        if (proposal.taskMode === 'agent') {
            // 纯大模型任务：铺 agents/rois 结构 + 可选智能体下拉
            config = {
                ...config, ...proposal,
                agents: proposal.agents && proposal.agents.length ? proposal.agents : config.agents,
                rois: proposal.rois && proposal.rois.length ? proposal.rois : [{ id: 'full', name: '全屏检测', points: [] }],
                activeAgentIndex: proposal.activeAgentIndex || 0
            };
            availableAgents = proposal.available_agents || [];
            if (!availableAgents.length) await loadAvailableAgents();
        } else {
            config = normalizeWarehouseConfig(config, proposal);
            await loadWarehouseCatalogs(proposal.available_algorithms);
        }
        // fromTemplate=对话选模板(路径 c)：免 ROI 门禁；普通 propose 草案：需画 ROI 才放行
        templateApplied = !!proposal.fromTemplate;
        monitorActive = true;
        wizardStep = 1;
        await loadSceneImage(proposal.alertType);
        roiDrawActive = true;
        showToast('已载入推荐参数与最新报警大图，请在视频区点击绘制检测区(ROI)。', 'success');
        await scrollToBottom();
    }

    // 点击任务表「查看」：把该任务的真实参数(row.detail)回填到右侧控制面板，
    // 并在视频区载入设备最新报警大图（无则占位图）。detail 由后端在同步设备时烘焙进快照，离线仍可用。
    async function viewTask(row) {
        const d = row.detail || {};
        if (d.taskMode === 'agent') {
            config = {
                ...defaultConfig, ...d,
                agents: d.agents && d.agents.length ? d.agents : [],
                rois: d.rois && d.rois.length ? d.rois : [{ id: 'full', name: '全屏检测', points: [] }],
                activeAgentIndex: 0
            };
            await loadAvailableAgents();  // 拉可选智能体，便于下拉换绑
        } else {
            config = normalizeWarehouseConfig(defaultConfig, d);
            await loadWarehouseCatalogs();  // 预热算法/智能体目录，便于 Step1 增删换算法
        }
        // 查看态非模板；真实 ROI 已随算法项带回（全屏项 useFullFrame=true / 自定义项有点），门禁自然放行
        templateApplied = false;
        monitorActive = true;
        wizardStep = 1;
        await loadSceneImage(d.alertType);
        roiDrawActive = !(d.taskMode === 'agent');
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

    async function deploy() {
        if (!config.name) {
            showToast('参数尚未配置，请在左侧发送对话进行级联提取。', 'warning');
            return;
        }
        if (isAgentTask) {
            await deployAgentTask();
            return;
        }
        // 强制 ROI 门禁（仅手动路径 templateApplied=false）：每条仓算法必须「画了 ≥3 点的检测区」或「显式勾选使用全屏」，
        // 纯默认(roiId='full' 且未勾全屏)不放行。模板/对话路径(templateApplied=true)跳过此门禁，用模板自带 ROI 或全屏。
        if (!templateApplied) {
            const algos = config.algorithms || [];
            const blocked = algos.some((item) => {
                if (item.useFullFrame) return false;
                const pts = (config.rois.find((r) => r.id === item.roiId)?.points) || [];
                return pts.length < 3;
            });
            if (!algos.length || blocked) {
                showToast('请先为每个算法绘制检测区(ROI)或勾选使用全屏，再部署。', 'warning');
                return;
            }
        }
        await deployWarehouseTaskMulti();
    }

    // 算法仓多算法真实下发：把 config.algorithms[] 映射成 WarehouseTaskDeploy.algorithms[]，一次提交 N 条算法。
    // Phase 1 三列面板仍绑顶层 config.*，故【激活项】参数读 config.*（面板编辑落点），其余项读各自 item.*（回填带回的值）。
    // 逐项 ROI：勾选全屏→空点(设备侧全画面)；否则按 item.roiId 从共享池 config.rois 解析（同 deployAgentTask）。
    async function deployWarehouseTaskMulti() {
        const device = $selectedDevice;
        if (!device?.id) { showToast('请先在顶栏选择一个设备。', 'error'); return; }
        const channelId = config.channel_device_id;
        if (channelId === null || channelId === undefined || channelId === '') {
            showToast('缺少目标视频流通道(channel_device_id)，请先通过对话生成布控方案。', 'warning');
            return;
        }
        const activeIdx = config.activeAlgorithmIndex || 0;
        const items = (config.algorithms || []).map((item, i) => {
            const p = (i === activeIdx) ? config : item;   // 激活项读顶层面板值，其余项读各自 item
            // 三阈值 → 设备单阈值：按「前置检测目标」取对应阈值；目标类型对齐后端 _target_type_to_yolo。
            const yoloTarget = p.yoloTarget ?? config.yoloTarget;
            const threshold = yoloTarget === 'vehicle' ? p.yoloVehicleThresh
                : yoloTarget === 'human' ? p.yoloHumanThresh
                : p.yoloNonMotorThresh;
            const target_types = yoloTarget === 'vehicle' ? ['VEHICLE'] : ['PERSON'];
            const roiPoints = item.useFullFrame ? [] : ((config.rois.find((r) => r.id === item.roiId)?.points) || []);
            const kind = item.kind || 'small';
            const algo = {
                kind,
                event_type: item.event_type || config.event_type,
                algo_cabin_name: item.algo_cabin_name || config.algo_cabin_name,
                version: item.version || config.version || 'V2.0.0',
                target_types,
                threshold: Number(threshold),
                // 面板「最大/最小目标限制」是 0~1 滑杆，设备 targetMax/targetMin 为整数目标数，取整下发。
                target_max: Math.round(Number(p.maxTarget)),
                target_min: Math.round(Number(p.minTarget)),
                duration: Math.round(Number(p.intrusionDuration)),
                cooldown: Math.round(Number(p.alarmInterval)),
                roiPoints
            };
            if (kind === 'combined') {
                // 小+大：追加扩图策略（target_expand 仅小+大生效）+ 二次大模型智能体标识
                algo.target_expand = {
                    top: Number(p.cropUp), bottom: Number(p.cropDown),
                    left: Number(p.cropLeft), right: Number(p.cropRight)
                };
                algo.agent_id = p.agentType || item.agent_id;
                algo.event_tag = (i === activeIdx) ? (config.agentType || '') : (item.event_tag || item.agentType || '');
                algo.prompt = p.prompt || '';
                algo.alarm_condition = null;
            }
            return algo;
        });
        if (!items.length) {
            showToast('尚未配置任何算法，请先通过对话生成布控方案或添加算法。', 'warning');
            return;
        }
        if (items.some((a) => !a.event_type || !a.algo_cabin_name)) {
            showToast('缺少算法标识(event_type / algo_cabin_name)，请先通过对话生成布控方案后再部署。', 'warning');
            return;
        }
        const body = {
            channel_device_id: Number(channelId),
            task_name: config.name,
            algorithms: items
        };
        try {
            const res = await apiPost(`/devices/${device.id}/deploy/warehouse-task`, body);
            const hasCombined = items.some((a) => a.kind === 'combined');
            showToast(`🚀 ${hasCombined ? '小+大级联' : '纯小模型'}布控任务「${config.name}」已下发（${items.length} 个算法，task_id=${res.task_id}）。`, 'success');
            setTimeout(() => switchTab('taskops'), 1000);
        } catch (e) {
            showToast(e?.detail || '布控任务下发失败，请检查设备在线状态与算法授权。', 'error');
        }
    }

    // 智能体任务真实下发：组装 AgentTaskDeploy 调 /devices/{id}/deploy/agent-task
    async function deployAgentTask() {
        const device = $selectedDevice;
        if (!device?.id) { showToast('请先在顶栏选择一个设备。', 'error'); return; }
        const channelId = config.channel_device_id;
        if (channelId === null || channelId === undefined || channelId === '') {
            showToast('缺少目标视频流通道(channel_device_id)，请先通过对话生成布控方案。', 'warning');
            return;
        }
        if (!config.agents.length || config.agents.some((a) => !a.event_id)) {
            showToast('请为每个智能体槽位选择一个智能体算法。', 'warning');
            return;
        }
        const body = {
            channel_device_id: Number(channelId),
            task_name: config.name,
            analysis_interval: Number(config.interval) || 5,
            agents: config.agents.map((a) => ({
                event_id: a.event_id,
                event_tag: a.event_tag || '',
                alarm_type: a.alarm_type || 'freeform',
                prompt: a.prompt || '',
                alarm_condition: a.alarm_condition || null,
                filter_enable: a.alarm_type === 'freeform' ? !!a.filter_enable : false,
                filter_keywords: a.alarm_type === 'freeform' ? (a.filter_keywords || '') : '',
                roiPoints: (config.rois.find((r) => r.id === a.roiId)?.points) || []
            }))
        };
        try {
            const res = await apiPost(`/devices/${device.id}/deploy/agent-task`, body);
            showToast(`🚀 智能体任务「${config.name}」已下发到设备（task_id=${res.task_id}）。`, 'success');
            setTimeout(() => switchTab('taskops'), 1000);
        } catch (e) {
            showToast(e?.detail || '智能体任务下发失败，请检查设备在线状态与智能体算法。', 'error');
        }
    }

    // ---- 参数模板库：保存当前面板参数为模板 / 套用已存模板（灌面板，确认后再部署）----
    let templates = [];            // 后端 /task-templates 列表
    let selectedTemplateId = '';   // 下拉当前选中
    let savingTemplate = false;

    async function loadTemplates() {
        try {
            templates = await apiGet('/task-templates');
        } catch (e) {
            console.error('加载参数模板失败', e);
        }
    }

    // 保存整份面板 config 快照为模板；task_mode/event_type 便于列表分类与场景匹配
    async function saveAsTemplate() {
        if (!monitorActive) {
            showToast('请先生成或套用一份布控参数后再保存为模板。', 'warning');
            return;
        }
        const input = window.prompt('为该参数模板命名：', config.name || '');
        if (input === null) return;                 // 用户取消
        const name = input.trim();
        if (!name) { showToast('模板名称不能为空。', 'warning'); return; }
        savingTemplate = true;
        try {
            await apiPost('/task-templates', {
                name,
                task_mode: config.taskMode || 'smallmodel',
                event_type: config.alertType || config.event_type || '',
                config,                              // 整份面板快照（含 taskMode/阈值/扩图/ROI 等）
                description: ''
            });
            showToast(`已保存参数模板「${name}」。`, 'success');
            await loadTemplates();
        } catch (e) {
            showToast(e?.detail || '保存模板失败，请重试。', 'error');
        } finally {
            savingTemplate = false;
        }
    }

    // 套用模板：把 tpl.config 灌进面板（agent 铺 agents/rois 结构；仓任务经归一化器兼容旧单算法快照），
    // 不自动下发——用户确认参数后再点部署。模板路径 templateApplied=true ⇒ 部署跳过强制 ROI 门禁（用模板自带 ROI 或全屏）。
    async function applyTemplate(tpl) {
        if (!tpl) return;
        const d = tpl.config || {};
        if (d.taskMode === 'agent') {
            config = {
                ...defaultConfig, ...d,
                agents: d.agents && d.agents.length ? d.agents : [],
                rois: d.rois && d.rois.length ? d.rois : [{ id: 'full', name: '全屏检测', points: [] }],
                activeAgentIndex: 0
            };
            await loadAvailableAgents();
        } else {
            config = normalizeWarehouseConfig(defaultConfig, d);
            await loadWarehouseCatalogs();  // 预热算法/智能体目录，便于 Step1 增删换算法
        }
        templateApplied = true;   // 路径(b) 面板选模板：跳过强制 ROI 门禁
        monitorActive = true;
        wizardStep = 1;
        await loadSceneImage(d.alertType);
        roiDrawActive = !(d.taskMode === 'agent');   // 仓任务仍开绘制，允许用户按需重画 ROI（非强制）
        showToast(`已套用参数模板「${tpl.name}」，可直接部署（如需可重新绘制检测区(ROI)）。`, 'success');
    }

    function onSelectTemplate(e) {
        const id = e.target.value;
        if (!id) return;
        applyTemplate(templates.find((t) => t.id === id));
        selectedTemplateId = '';   // 复位为占位项：下拉作「套用」动作菜单，可重复套用同一模板
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
            await loadTemplates();
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
                if (req.payload && typeof req.payload === 'object') {
                    // 对象负载：直接把模板参数灌进面板（参数模板库跨标签套用；tpl={name,config,...}）
                    applyTemplate(req.payload);
                } else {
                    // 字符串负载：保留 AgentLibrary 现有行为（转成对话指令发送）
                    resetChat();
                    chatInput = `请为我配置【${req.payload}】。检测到目标后裁剪图片送智能体进行高精度判定。`;
                    sendMessage();
                    showToast(`已套用高敏级联模板: [${req.payload}]。请在右侧控制仓调阅细节。`, 'success');
                }
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
                                                                {:else if col.key === 'algorithms'}
                                                                    <td class="px-2.5 py-1.5 text-slate-300 align-top break-all max-w-[160px]">{row[col.key] ?? '—'}</td>
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
            <div class="flex items-center gap-2 shrink-0">
                <!-- 参数模板库：套用（下拉）/ 保存当前面板参数 -->
                <select on:change={onSelectTemplate} bind:value={selectedTemplateId} title="套用参数模板"
                        class="bg-slate-900 border border-slate-700 text-slate-300 text-[11px] rounded-lg px-2 py-2 max-w-[150px] focus:border-indigo-500 focus:outline-none">
                    <option value="">🗂️ 套用模板…</option>
                    {#each templates as t (t.id)}
                        <option value={t.id}>{t.name}</option>
                    {/each}
                </select>
                {#if monitorActive}
                    <button on:click={saveAsTemplate} disabled={savingTemplate} title="把当前面板参数保存为模板"
                            class="bg-slate-800 hover:bg-slate-700 text-slate-200 px-3 py-2 rounded-xl text-xs font-bold flex items-center transition-all border border-slate-700 shrink-0 disabled:opacity-50">
                        <i class="fa-solid fa-bookmark mr-1.5"></i>保存为模板
                    </button>
                    <button on:click={deploy} class="bg-indigo-600 hover:bg-indigo-700 text-white px-4 py-2 rounded-xl text-xs font-bold flex items-center transition-all shadow-md shadow-indigo-500/25 shrink-0">
                        <i class="fa-solid fa-rocket mr-2 animate-bounce"></i>{isAgentTask ? '一键部署智能体任务' : '一键部署双级任务'}
                    </button>
                {/if}
            </div>
        </div>

        <!-- 三步向导步骤条：① 任务信息 / ② ROI 绘制 / ③ 详情参数。点击任意步即切换，每步信息均可展示并修改。
             配色区分三态：已配置(绿) / 正在配置(靛蓝) / 未配置(灰) -->
        {#if monitorActive}
            <div class="mb-5 bg-slate-950/60 p-2 rounded-2xl border border-slate-800 flex items-center gap-2">
                <div class="flex-1 flex items-center gap-1 flex-wrap">
                    {#each WIZARD_STEPS as s, i}
                        {#if i > 0}
                            <i class="fa-solid fa-chevron-right text-[9px] shrink-0 {wizardStep >= s.n ? 'text-emerald-600/60' : 'text-slate-700'}"></i>
                        {/if}
                        <button type="button" on:click={() => (wizardStep = s.n)}
                                class="flex items-center gap-2 px-3 py-2 rounded-xl text-[11px] font-bold border transition-all
                                    {wizardStep === s.n
                                        ? 'bg-indigo-600 text-white border-indigo-500 shadow-md shadow-indigo-500/25'
                                        : wizardStep > s.n
                                            ? 'bg-emerald-950/40 text-emerald-300 border-emerald-700/60 hover:border-emerald-500'
                                            : 'bg-transparent text-slate-500 border-transparent hover:text-indigo-300 hover:border-indigo-500/40'}">
                            <span class="w-4 h-4 rounded-full flex items-center justify-center text-[9px] font-mono shrink-0
                                {wizardStep === s.n
                                    ? 'bg-white/20 text-white'
                                    : wizardStep > s.n
                                        ? 'bg-emerald-500 text-slate-950 font-bold'
                                        : 'border border-slate-700 text-slate-500'}">{s.n}</span>
                            <span class="whitespace-nowrap">{s.ord}: {s.label}</span>
                        </button>
                    {/each}
                </div>
                <div class="flex items-center gap-1 shrink-0 pl-2 border-l border-slate-800">
                    <button type="button" title="上一步" disabled={wizardStep === 1} on:click={() => (wizardStep = Math.max(1, wizardStep - 1))}
                            class="px-2 py-2 rounded-lg border border-slate-800 bg-slate-900 text-slate-400 hover:text-indigo-300 hover:border-indigo-500/40 disabled:opacity-30 disabled:cursor-not-allowed"><i class="fa-solid fa-chevron-left text-[10px]"></i></button>
                    <button type="button" title="下一步" disabled={wizardStep === 3} on:click={() => (wizardStep = Math.min(3, wizardStep + 1))}
                            class="px-2 py-2 rounded-lg border border-slate-800 bg-slate-900 text-slate-400 hover:text-indigo-300 hover:border-indigo-500/40 disabled:opacity-30 disabled:cursor-not-allowed"><i class="fa-solid fa-chevron-right text-[10px]"></i></button>
                </div>
            </div>
        {/if}

        <div class="flex flex-col gap-5 items-stretch">
            <!-- ① 任务信息：任务名称 / 关联通道 / 分析间隔 / 勾选算法或智能体 -->
            {#if monitorActive && wizardStep === 1}
                <div class="bg-slate-950 p-5 rounded-2xl border border-slate-800 shadow-lg space-y-4">
                    <h3 class="font-bold text-white text-xs flex items-center pb-3 border-b border-slate-800">
                        <span class="bg-indigo-600 text-white p-1 rounded mr-2"><i class="fa-solid fa-circle-info text-xs"></i></span>
                        第一步 · 任务信息
                        <span class="ml-2 text-[10px] font-normal text-slate-500">{isAgentTask ? '大模型智能体任务' : (config.taskMode === 'combined' ? '小+大协同任务' : '小模型任务')}</span>
                    </h3>
                    <div class="grid grid-cols-1 md:grid-cols-3 gap-3">
                        <div>
                            <label class="block text-[10px] text-slate-400 mb-1">任务名称（模型自动生成，可修改）</label>
                            <input type="text" bind:value={config.name} placeholder="自动计算生成" class="w-full bg-slate-950 border border-slate-800 text-slate-200 rounded p-2 focus:border-indigo-500 text-[11px]" />
                        </div>
                        <div>
                            <label class="block text-[10px] text-slate-400 mb-1">关联通道（目标视频流）</label>
                            <select bind:value={config.channel_device_id} on:change={onChannelChange}
                                    class="w-full bg-slate-950 border border-slate-800 text-slate-200 rounded p-2 focus:border-indigo-500 text-[11px]">
                                {#if !channelOptions.some((c) => String(c.device_id) === String(config.channel_device_id))}
                                    <option value={config.channel_device_id}>{config.channel_device_id ?? '（无可选通道）'}</option>
                                {/if}
                                {#each channelOptions as c}
                                    <option value={c.device_id}>{c.display_name}</option>
                                {/each}
                            </select>
                        </div>
                        <div>
                            <label class="block text-[10px] text-slate-400 mb-1">分析间隔（单位:秒）</label>
                            {#if isAgentTask}
                                <input type="number" min="1" bind:value={config.interval} class="w-full bg-slate-950 border border-slate-800 text-slate-200 rounded p-2 focus:border-indigo-500 text-[11px] font-mono text-center" />
                            {:else}
                                <div class="w-full bg-slate-900/60 border border-slate-800 text-slate-500 rounded p-2 text-[11px] text-center" title="小模型 / 小+大为端侧实时分析，无分析间隔概念">实时分析（无分析间隔）</div>
                            {/if}
                        </div>
                    </div>

                    <!-- 勾选算法 / 智能体：智能体任务用 agents[] 槽位；小模型、小+大用 algorithms[] 槽位（同一任务可布控多个算法） -->
                    <div>
                        <div class="flex items-center justify-between mb-2">
                            <span class="font-extrabold text-indigo-300 flex items-center text-[11px]"><i class="fa-solid fa-layer-group mr-1.5"></i>{isAgentTask ? '勾选智能体' : '勾选算法'}</span>
                            <span class="text-[9px] text-slate-500">{isAgentTask ? `最多关联 4 个智能体 (${config.agents.length}/4)` : `已选 ${(config.algorithms || []).length} 个算法 · 点选设为当前编辑对象`}</span>
                        </div>
                        {#if isAgentTask}
                            <div class="space-y-2">
                                {#each config.agents as agent, i}
                                    <div class="flex items-center gap-1.5 p-1.5 rounded-lg border transition-colors cursor-pointer {i === config.activeAgentIndex ? 'border-indigo-500 bg-indigo-950/30' : 'border-slate-800 bg-slate-950/40 hover:border-slate-700'}" on:click={() => selectAgent(i)}>
                                        <span class="text-[9px] font-mono text-slate-500 w-4 text-center">{i + 1}</span>
                                        {#if agent.deployed}
                                            <span class="text-[8px] font-bold px-1 py-0.5 rounded bg-emerald-950/60 text-emerald-400 border border-emerald-800/60 whitespace-nowrap" title="该通道已布控的智能体">已布控</span>
                                        {:else}
                                            <span class="text-[8px] font-bold px-1 py-0.5 rounded bg-indigo-950/60 text-indigo-300 border border-indigo-700/60 whitespace-nowrap" title="本次即将布控的智能体">即将</span>
                                        {/if}
                                        <select value={agent.event_id} on:change={(e) => changeAgent(i, e.target.value)} on:click|stopPropagation class="flex-1 bg-slate-950 border border-slate-800 text-slate-200 rounded p-1.5 focus:border-indigo-500 text-[11px]">
                                            <option value="" disabled>选择智能体算法…</option>
                                            {#each availableAgents as a}
                                                <option value={a.event_id}>{a.event_tag}{a.alarm_type === 'freeform' ? '（描述型）' : '（判断型）'}</option>
                                            {/each}
                                        </select>
                                        {#if config.agents.length > 1}
                                            <button type="button" on:click|stopPropagation={() => removeAgentSlot(i)} class="text-slate-600 hover:text-rose-400 px-1" title="移除该智能体"><i class="fa-solid fa-xmark text-xs"></i></button>
                                        {/if}
                                    </div>
                                {/each}
                                <button type="button" on:click={addAgentSlot} disabled={config.agents.length >= 4} class="w-full py-1.5 rounded-lg border border-dashed border-slate-700 text-[10px] text-slate-400 hover:border-indigo-500 hover:text-indigo-400 disabled:opacity-40 disabled:cursor-not-allowed disabled:hover:border-slate-700 disabled:hover:text-slate-400">
                                    <i class="fa-solid fa-plus mr-1"></i>添加智能体
                                </button>
                            </div>
                        {:else}
                            <div class="space-y-2">
                                {#each config.algorithms as item, i}
                                    <div class="flex items-center gap-1.5 p-1.5 rounded-lg border transition-colors cursor-pointer {i === (config.activeAlgorithmIndex || 0) ? 'border-indigo-500 bg-indigo-950/30' : 'border-slate-800 bg-slate-950/40 hover:border-slate-700'}" on:click={() => selectAlgorithm(i)}>
                                        <span class="text-[9px] font-mono text-slate-500 w-4 text-center">{i + 1}</span>
                                        <select value={algoItemKey(item)} on:change={(e) => changeAlgorithm(i, e.target.value)} on:click|stopPropagation class="flex-1 bg-slate-950 border border-slate-800 text-slate-200 rounded p-1.5 focus:border-indigo-500 text-[11px]">
                                            {#if !availableAlgorithms.some((a) => algoOptionKey(a) === algoItemKey(item))}
                                                <option value={algoItemKey(item)}>{algoLabel(item)}（当前）</option>
                                            {/if}
                                            {#each availableAlgorithms as a}
                                                <option value={algoOptionKey(a)}>{a.eventName || a.eventType}{a.algoCabinName ? `（${a.algoCabinName}）` : ''}</option>
                                            {/each}
                                        </select>
                                        {#if config.taskMode === 'combined'}
                                            <select value={item.agent_id || ''} on:change={(e) => changeAlgoAgent(i, e.target.value)} on:click|stopPropagation title="该算法命中后送检的二次大模型" class="flex-1 bg-slate-950 border border-slate-800 text-slate-200 rounded p-1.5 focus:border-indigo-500 text-[11px]">
                                                <option value="" disabled>二次大模型…</option>
                                                {#each availableAgents as a}
                                                    <option value={a.event_id}>{a.event_tag}</option>
                                                {/each}
                                            </select>
                                        {/if}
                                        {#if config.algorithms.length > 1}
                                            <button type="button" on:click|stopPropagation={() => removeAlgorithmSlot(i)} class="text-slate-600 hover:text-rose-400 px-1" title="移除该算法"><i class="fa-solid fa-xmark text-xs"></i></button>
                                        {/if}
                                    </div>
                                {/each}
                                <button type="button" on:click={addAlgorithmSlot} class="w-full py-1.5 rounded-lg border border-dashed border-slate-700 text-[10px] text-slate-400 hover:border-indigo-500 hover:text-indigo-400">
                                    <i class="fa-solid fa-plus mr-1"></i>添加算法
                                </button>
                                <p class="text-[9px] text-slate-500 leading-relaxed">同一任务可布控多个算法：每个算法在第②步各自关联检测区，在第③步各自配置参数。</p>
                            </div>
                        {/if}
                    </div>
                </div>
            {/if}

            <!-- 当前编辑对象切换器（第②③步共用）：第②步为该项绘制/关联 ROI，第③步配置该项详情参数 -->
            {#if monitorActive && wizardStep !== 1}
                <div class="bg-slate-950/60 p-3 rounded-2xl border border-slate-800">
                    <div class="flex items-center justify-between mb-2">
                        <span class="text-[11px] font-bold text-slate-200 flex items-center"><i class="fa-solid fa-hand-pointer mr-1.5 text-indigo-400"></i>当前编辑对象（{isAgentTask ? '智能体' : '算法'}）</span>
                        <span class="text-[9px] text-slate-500">{wizardStep === 2 ? '为该项绘制 / 关联检测区' : '配置该项详情参数'}</span>
                    </div>
                    <div class="flex flex-wrap gap-1.5">
                        {#if isAgentTask}
                            {#each config.agents as agent, i}
                                <button type="button" on:click={() => selectAgent(i)}
                                        class="px-2.5 py-1.5 rounded-lg border text-[10px] font-medium transition-colors {i === config.activeAgentIndex ? 'bg-indigo-600/20 border-indigo-500/50 text-indigo-200' : 'bg-slate-900 border-slate-800 text-slate-400 hover:border-indigo-500/30'}">
                                    <span class="font-mono text-[9px] mr-1">{i + 1}</span>{agent.event_tag || '智能体'}
                                </button>
                            {/each}
                        {:else}
                            {#each config.algorithms as item, i}
                                <button type="button" on:click={() => selectAlgorithm(i)}
                                        class="px-2.5 py-1.5 rounded-lg border text-[10px] font-medium transition-colors {i === (config.activeAlgorithmIndex || 0) ? 'bg-indigo-600/20 border-indigo-500/50 text-indigo-200' : 'bg-slate-900 border-slate-800 text-slate-400 hover:border-indigo-500/30'}">
                                    <span class="font-mono text-[9px] mr-1">{i + 1}</span>{algoLabel(item)}
                                </button>
                            {/each}
                        {/if}
                    </div>
                </div>
            {/if}

            {#if !monitorActive || wizardStep === 2 || (wizardStep === 3 && !isAgentTask)}
            <!-- ② ROI 绘制：视频/图片画布（未激活时为占位提示） -->
            <div class="space-y-4">
                {#if !monitorActive || wizardStep === 2}
                <div class="bg-slate-950 p-4 rounded-2xl border border-slate-800 shadow-sm">
                    {#if monitorActive}
                        <h3 class="font-bold text-white text-xs flex items-center mb-3">
                            <span class="bg-indigo-600 text-white p-1 rounded mr-2"><i class="fa-solid fa-draw-polygon text-xs"></i></span>
                            第二步 · ROI 绘制与算法关联
                            <span class="ml-2 text-[10px] font-normal text-slate-500">基于监控画面绘制 ROI 区域，并与勾选{isAgentTask ? '智能体' : '算法'}建立关联</span>
                        </h3>
                    {/if}
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
                                <!-- 其它检测区的叠加预览（受表格「显示」列控制，仅视图层，不参与部署） -->
                                {#each overlayRois as r (r.id)}
                                    <polygon points={r.points.map((p) => `${p.x * 800},${p.y * 500}`).join(' ')}
                                             fill="rgba(148,163,184,0.07)" stroke="#64748b" stroke-width="1.5" stroke-dasharray="5" />
                                {/each}
                                {#if currentRoiPoints.length}
                                    <polygon points={roiSvgPoints} fill="rgba(99,102,241,0.14)" stroke="#6366f1" stroke-width="2.5" />
                                    {#each currentRoiPoints as p}
                                        <circle cx={p.x * 800} cy={p.y * 500} r="5" fill="#6366f1" stroke="#fff" stroke-width="1.5" />
                                    {/each}
                                {:else}
                                    <polygon points="20,20 780,20 780,480 20,480" fill="rgba(99,102,241,0.06)" stroke="#6366f1" stroke-width="2" stroke-dasharray="6" />
                                {/if}
                            </svg>
                            {#if roiDrawActive}
                                <div class="absolute top-2 left-2 bg-indigo-600/90 text-white text-[10px] font-bold px-2 py-1 rounded shadow">
                                    <i class="fa-solid fa-draw-polygon mr-1"></i>点击画点绘制检测区（已 {currentRoiPoints.length} 点）{#if isAgentTask && activeAgent}· 当前：{activeAgent.event_tag || '智能体'}{:else if !isAgentTask && activeAlgorithm}· 当前：{activeAlgorithm.event_type || '算法'}{/if}
                                </div>
                            {/if}
                            {#if !isAgentTask}
                                <div class="absolute bottom-2 right-2 bg-emerald-600 text-white text-[9px] font-bold px-1.5 py-0.5 rounded shadow flex items-center"><i class="fa-solid fa-crop mr-1"></i> Agent裁图区 (上扩{config.cropUp} / 下{config.cropDown})</div>
                            {/if}
                        {/if}
                    </div>
                </div>
                {/if}

                {#if monitorActive && wizardStep === 2}
                    <!-- ROI 区域管理与算法绑定对应关系表：行=检测区，列=第①步勾选的算法/智能体。
                         数据模型仍是「每个算法/智能体单绑一个检测区」，故同一列只会在一行呈勾选态（在别行勾选即改绑）。 -->
                    <div class="bg-slate-950 p-4 rounded-2xl border border-slate-800">
                        <div class="flex items-center justify-between mb-3 gap-3 flex-wrap">
                            <span class="font-bold text-xs text-slate-200 flex items-center">
                                <i class="fa-solid fa-table-list mr-1.5 text-indigo-400"></i>ROI 区域管理与算法绑定对应关系表
                            </span>
                            <span class="text-[10px] text-slate-500 flex items-center">
                                <i class="fa-regular fa-lightbulb mr-1 text-amber-400"></i>提示：在此处勾选每个区域具体需要跑第一步选中的哪些算法
                            </span>
                        </div>

                        <div class="overflow-x-auto rounded-xl border border-slate-800">
                            <table class="w-full text-left border-collapse">
                                <thead>
                                    <tr class="bg-slate-900/60 text-[10px] text-slate-400">
                                        <th class="px-3 py-2 font-medium w-12">显示</th>
                                        <th class="px-3 py-2 font-medium">ROI 区域名称 (支持编辑)</th>
                                        <th class="px-3 py-2 font-medium w-24">几何类型</th>
                                        <th class="px-3 py-2 font-medium">关联绑定的算法 / 智能体 (源自第一步勾选)</th>
                                        <th class="px-3 py-2 font-medium w-20 text-right">操作</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {#each customRois as roi (roi.id)}
                                        <tr class="border-t border-slate-800 hover:bg-slate-900/40 transition-colors">
                                            <td class="px-3 py-3 align-middle">
                                                <input type="checkbox" checked={!hiddenRoiIds.has(roi.id)} on:change={() => toggleRoiVisible(roi.id)}
                                                       title="是否在画面上叠加显示该区域（仅预览，不影响部署）"
                                                       class="w-3.5 h-3.5 text-indigo-600 bg-slate-950 border-slate-700 rounded cursor-pointer" />
                                            </td>
                                            <td class="px-3 py-3 align-middle">
                                                <input type="text" value={roi.name} on:input={(e) => renameRoi(roi.id, e.target.value)} placeholder="检测区名称"
                                                       class="w-44 bg-slate-950 border border-indigo-500/40 text-slate-100 rounded px-2 py-1.5 text-[11px] font-bold focus:border-indigo-500 focus:outline-none" />
                                            </td>
                                            <td class="px-3 py-3 align-middle">
                                                <span class="text-[11px] text-slate-400">多边形</span>
                                                <span class="text-[9px] text-slate-600 font-mono ml-1">{(roi.points || []).length}点</span>
                                            </td>
                                            <td class="px-3 py-3 align-middle">
                                                <div class="flex items-center flex-wrap gap-2">
                                                    {#each boundItems as it (it.i)}
                                                        <label class="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg border cursor-pointer transition-colors text-[10px] font-bold {it.roiId === roi.id ? 'bg-indigo-600/20 border-indigo-500/50 text-indigo-200' : 'bg-slate-900 border-slate-800 text-slate-500 hover:border-indigo-500/30'}">
                                                            <input type="checkbox" checked={it.roiId === roi.id}
                                                                   on:change={(e) => toggleItemRoi(it.i, roi.id, e.target.checked)}
                                                                   class="w-3 h-3 text-indigo-600 bg-slate-950 border-slate-700 rounded cursor-pointer" />
                                                            <span class="whitespace-nowrap">{it.kind}: {it.label}{it.note ? `（${it.note}）` : ''}</span>
                                                        </label>
                                                    {:else}
                                                        <span class="text-[10px] text-slate-600">请先在第一步勾选{isAgentTask ? '智能体' : '算法'}</span>
                                                    {/each}
                                                </div>
                                            </td>
                                            <td class="px-3 py-3 align-middle text-right">
                                                <button type="button" on:click={() => deleteRoi(roi.id)} title="删除该检测区"
                                                        class="text-[11px] text-rose-500 hover:text-rose-400 font-medium whitespace-nowrap">
                                                    <i class="fa-solid fa-trash-can mr-1"></i>删除
                                                </button>
                                            </td>
                                        </tr>
                                    {:else}
                                        <tr class="border-t border-slate-800">
                                            <td colspan="5" class="px-3 py-6 text-center text-[11px] text-slate-500">
                                                <i class="fa-solid fa-draw-polygon mr-1.5 text-slate-700"></i>
                                                暂无自定义检测区：先在上方选中一个{isAgentTask ? '智能体' : '算法'}，再点「画制检测区 (ROI)」在画面上绘制
                                            </td>
                                        </tr>
                                    {/each}
                                </tbody>
                            </table>
                        </div>

                        <!-- 表尾：仍走全屏检测的项 + 算法仓任务的「全屏检测」开关（保留原控件） -->
                        <div class="flex items-center justify-between gap-3 mt-3 flex-wrap">
                            <div class="flex items-center gap-1.5 flex-wrap text-[10px] text-slate-500">
                                <span>全屏检测（未绑定区域）：</span>
                                {#each fullFrameItems as it (it.i)}
                                    <span class="px-2 py-0.5 rounded bg-slate-900 border border-slate-800 text-slate-400 font-medium">{it.kind}: {it.label}</span>
                                {:else}
                                    <span class="text-slate-600">无</span>
                                {/each}
                            </div>
                            {#if !isAgentTask}
                                <label class="flex items-center space-x-1.5 cursor-pointer text-[10px] text-slate-300 shrink-0">
                                    <input type="checkbox" checked={!!activeAlgorithm?.useFullFrame} on:change={(e) => toggleActiveFullFrame(e.target.checked)} disabled={!activeAlgorithm}
                                           class="w-3.5 h-3.5 text-indigo-600 bg-slate-950 border-slate-700 rounded cursor-pointer" />
                                    <span>当前算法（{activeAlgorithm ? algoLabel(activeAlgorithm) : '未选择'}）使用全屏检测</span>
                                </label>
                            {/if}
                        </div>

                        <p class="text-[9px] text-slate-500 mt-2 leading-relaxed">
                            先在上方选中一个{isAgentTask ? '智能体' : '算法'}，再点「画制检测区」在画面上绘制；绘制后自动新增一行并绑定到当前对象。区域名可直接改，删除后关联项回落为全屏检测。
                            每个{isAgentTask ? '智能体' : '算法'}同时只能绑定一个区域，在别行勾选即改绑到该行。
                            {#if !isAgentTask}手动配置需为每个算法绘制检测区或勾选「使用全屏检测」后方可部署；套用模板则跳过此限制。{/if}
                        </p>
                    </div>

                    <!-- 表格底部翻步按钮（与顶部步骤条共用 wizardStep，不新增状态） -->
                    <div class="flex items-center justify-between gap-3">
                        <button type="button" on:click={() => (wizardStep = 1)}
                                class="px-4 py-2.5 rounded-xl border border-slate-800 bg-slate-950 text-slate-300 text-[11px] font-bold hover:border-indigo-500/40 hover:text-indigo-300 transition-colors">
                            <i class="fa-solid fa-arrow-left mr-1.5"></i>上一步：修改任务与算法
                        </button>
                        <button type="button" on:click={() => (wizardStep = 3)}
                                class="px-4 py-2.5 rounded-xl bg-indigo-600 hover:bg-indigo-700 text-white text-[11px] font-bold shadow-md shadow-indigo-500/25 transition-colors">
                            下一步：配置算法/智能体详情参数<i class="fa-solid fa-arrow-right ml-1.5"></i>
                        </button>
                    </div>
                {/if}

                <!-- 扩图预览（随第③步详情参数一起展示：与「目标扩图倍数」配置同屏） -->
                {#if monitorActive && wizardStep === 3 && !isAgentTask}
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
            {/if}

            <!-- ③ 详情参数：逐算法 / 逐智能体配置（当前编辑对象见上方切换器）；未激活时保持原空面板样式 -->
            {#if !monitorActive || wizardStep === 3}
            <div class="space-y-4">
                <div class="bg-slate-950 p-5 rounded-2xl border border-slate-800 shadow-lg relative overflow-hidden">
                    <div class="absolute top-0 right-0 h-16 w-16 bg-indigo-500/5 rounded-bl-full flex items-center justify-end pr-4 pt-4 pointer-events-none">
                        <i class="fa-solid fa-code-merge text-indigo-500/40 text-base animate-pulse"></i>
                    </div>
                    <h3 class="font-bold text-white text-xs mb-4 flex items-center">
                        <span class="bg-indigo-600 text-white p-1 rounded mr-2"><i class="fa-solid fa-sliders text-xs"></i></span>
                        {monitorActive ? '第三步 · 详情参数' : 'AI 级联提取与细化控制面板'}
                        {#if monitorActive}
                            <span class="ml-2 text-[10px] font-normal text-slate-500">当前：{isAgentTask ? (activeAgent?.event_tag || '（请先在第一步勾选智能体）') : (activeAlgorithm ? algoLabel(activeAlgorithm) : '（请先在第一步勾选算法）')}</span>
                        {/if}
                    </h3>

                    {#if isAgentTask}
                        <!-- 智能体任务：当前智能体的 Prompt + 属性型条件判断（逐项直绑 activeAgent.*，槽位增删改见第一步） -->
                        {#if activeAgent}
                            <div class="bg-slate-900/60 p-3.5 rounded-xl border border-slate-800/80 space-y-3 text-xs">
                                <div class="flex items-center justify-between border-b border-slate-800 pb-2">
                                    <span class="font-extrabold text-indigo-400 flex items-center"><i class="fa-solid fa-brain mr-1.5"></i>级联后置多模态 Agent 详情</span>
                                    <span class="text-[9px] text-indigo-500/80 font-bold">第 {config.activeAgentIndex + 1} / {config.agents.length} 个智能体</span>
                                </div>
                                <div>
                                    <div class="flex justify-between items-center mb-1"><label class="text-[10px] text-slate-400">智能体 Prompt 策略（{activeAgent.event_tag || '当前智能体'}）</label><span class="text-[9px] text-slate-600">Markdown语义控制</span></div>
                                    <textarea bind:value={activeAgent.prompt} on:input={() => (config.agents = [...config.agents])} rows="5" class="w-full text-[11px] font-mono text-slate-300 bg-slate-950 border border-slate-800 focus:border-indigo-500 rounded p-2 leading-relaxed" placeholder="等待指令注入..."></textarea>
                                </div>
                                {#if activeAgent.alarm_type === 'freeform'}
                                    <div class="pt-1 border-t border-slate-800/60">
                                        <div class="flex items-center justify-between">
                                            <label class="text-[10px] text-slate-400 flex items-center"><i class="fa-solid fa-filter mr-1.5 text-indigo-400"></i>条件判断（属性分析）</label>
                                            <input type="checkbox" bind:checked={activeAgent.filter_enable} on:change={() => (config.agents = [...config.agents])} class="w-3.5 h-3.5 text-indigo-600 bg-slate-950 border-slate-800 rounded cursor-pointer" />
                                        </div>
                                        {#if activeAgent.filter_enable}
                                            <input type="text" bind:value={activeAgent.filter_keywords} on:input={() => (config.agents = [...config.agents])} placeholder="过滤条件关键词，例如：红色上衣 / 未戴安全帽" class="mt-2 w-full bg-slate-950 border border-slate-800 text-slate-200 rounded p-2 focus:border-indigo-500 text-[11px]" />
                                        {/if}
                                    </div>
                                {:else}
                                    <!-- 判断型(yesno)智能体：报警条件 alarm_condition —— 勾选=仅「是」报警(only_yes)，不勾=是/否都报警(none)。
                                         缺省(null)时按后端 _default_alarm_condition 推导为 only_yes，故勾选态默认为真。 -->
                                    <div class="pt-1 border-t border-slate-800/60">
                                        <div class="flex items-center justify-between">
                                            <span class="text-[10px] text-slate-400 flex items-center"><i class="fa-solid fa-circle-question mr-1.5 text-indigo-400"></i>条件判断（是 / 否）</span>
                                            <label class="flex items-center gap-1.5 cursor-pointer">
                                                <span class="text-[9px] text-slate-500">仅判定为「是」时报警</span>
                                                <input type="checkbox" checked={(activeAgent.alarm_condition || 'only_yes') === 'only_yes'}
                                                       on:change={(e) => setAgentAlarmCondition(e.target.checked)}
                                                       class="w-3.5 h-3.5 text-indigo-600 bg-slate-950 border-slate-800 rounded cursor-pointer" />
                                            </label>
                                        </div>
                                        <p class="mt-1.5 text-[9px] text-slate-500 leading-relaxed">
                                            {(activeAgent.alarm_condition || 'only_yes') === 'only_yes'
                                                ? '当前：only_yes —— 大模型判定为「是」才产生报警（推荐，判断型默认值）。'
                                                : '当前：none —— 判定为「是」或「否」都产生报警。'}
                                        </p>
                                    </div>
                                {/if}
                            </div>
                        {:else}
                            <p class="text-[11px] text-slate-500">请先在第一步「勾选智能体」，再回到本步配置其详情参数。</p>
                        {/if}
                    {:else}
                    <div class="grid grid-cols-1 xl:grid-cols-3 gap-4 text-xs items-start">
                        <!-- 1. 前置轻量级算法（当前算法项的阈值/目标/时长/冷却；面板绑顶层 config.*，切项时由 selectAlgorithm 写回/提取） -->
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

                        <!-- 2. 扩图倍数（target_expand 仅小+大生效，供二次大模型补足环境上下文） -->
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

                        <!-- 3. 后置 Agent：小+大任务的「二次大模型」——下拉取设备智能体目录(availableAgents)，写入当前算法项 -->
                        <div class="bg-slate-900/60 p-3.5 rounded-xl border border-slate-800/80 space-y-3 h-full">
                            <div class="flex items-center justify-between border-b border-slate-800 pb-2">
                                <span class="font-extrabold text-indigo-400 flex items-center"><i class="fa-solid fa-brain mr-1.5"></i> 3. 级联后置多模态 Agent</span>
                                <span class="text-[9px] {config.taskMode === 'combined' ? 'text-indigo-500/80' : 'text-slate-500'} font-bold">{config.taskMode === 'combined' ? '本算法命中后的二次复核' : '仅小+大协同任务可配置'}</span>
                            </div>
                            {#if config.taskMode === 'combined'}
                                <div>
                                    <label class="block text-[10px] text-slate-400 mb-1">选择二次大模型智能体（取自设备智能体目录）</label>
                                    <select value={config.agentType || ''} on:change={(e) => changeAlgoAgent(config.activeAlgorithmIndex || 0, e.target.value)}
                                            class="w-full bg-slate-950 border border-slate-800 text-slate-200 rounded p-2 focus:border-indigo-500 text-[11px]">
                                        <option value="" disabled>选择智能体算法…</option>
                                        {#each availableAgents as a}
                                            <option value={a.event_id}>{a.event_tag}{a.alarm_type === 'freeform' ? '（描述型）' : '（判断型）'}</option>
                                        {/each}
                                    </select>
                                    {#if !availableAgents.length}
                                        <p class="text-[9px] text-amber-500/80 mt-1">未取到设备智能体目录（设备离线时不可选）。</p>
                                    {/if}
                                </div>
                                <div>
                                    <div class="flex justify-between items-center mb-1"><label class="text-[10px] text-slate-400">智能体大模型视觉推理 Prompt 策略</label><span class="text-[9px] text-slate-600">Markdown语义控制</span></div>
                                    <textarea bind:value={config.prompt} rows="5" class="w-full text-[11px] font-mono text-slate-300 bg-slate-950 border border-slate-800 focus:border-indigo-500 rounded p-2 leading-relaxed" placeholder="等待指令注入..."></textarea>
                                </div>
                            {:else}
                                <p class="text-[10px] text-slate-500 leading-relaxed">纯小模型任务由端侧算法直接产出报警，无需二次大模型推理。若需大模型复核，请创建「小+大协同」任务。</p>
                            {/if}
                        </div>
                    </div>
                    {/if}
                </div>
            </div>
            {/if}
        </div>
    </div>
</div>

<style>
    .flow-arrow::after { content: "➔"; margin: 0 8px; color: #475569; }
    .flow-arrow:last-child::after { content: ""; }
</style>
