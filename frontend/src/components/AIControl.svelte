<script>
    import { onMount, tick } from 'svelte';
    import { showToast, switchTab, chatRequest, selectedDevice, loadDevices } from '../lib/controlStore.js';
    import { apiPost, apiGet, apiPut, apiDelete, API_BASE } from '../lib/api.js';

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
        // yoloTarget=面板主目标（决定用哪个阈值字段）；yoloTargets=设备目标类型ID多选，下发为 target_types
        yoloTarget: 'human', yoloTargets: ['PERSON'],
        yoloHumanThresh: 0.31, yoloVehicleThresh: 0.32, yoloNonMotorThresh: 0.37,
        intrusionDuration: 3, alarmInterval: 10,
        cropUp: 0.5, cropDown: 0.3, cropLeft: 0.4, cropRight: 0.6,
        // 目标大小（面板 0~100 百分比，下发时折算成设备 targetMax/targetMin 的 0~1）：最小 0~100、最大 50~100
        maxTarget: 100, minTarget: 0, roiPoints: [],
        event_type: '', algo_cabin_name: '',    // 算法标识（propose/对话填充；查看态无来源，靠 deploy() guard 拦截）
        // 智能体任务（agent_real_task）专用：
        taskMode: 'smallmodel',   // 'agent' | 'smallmodel' | 'combined'
        task_id: null,            // 非空=正在编辑设备上的既有任务（保存走 PUT 真更新）；null=新建下发
        channel_device_id: null,
        device_id: null,
        agents: [],               // ≤4：{event_id,event_tag,alarm_type,prompt,alarm_condition,filter_enable,filter_keywords,roiId}
        // 算法仓（小模型/小+大）任务：多算法项，每项自带参数 + 绑池 ROI（roiId），与 agents[] 镜像。
        // Phase 1：由 propose/模板/查看归一化为【单项】；Phase 2 再加多槽编辑器。
        algorithms: [],           // {kind,event_type,algo_cabin_name,version,useFullFrame,roiId, 各参数…}
        rois: [{ id: 'full', name: '全屏检测', points: [], areaId: 1, areaType: 'POLYGON' }],   // 任务级 ROI 池（两种模式共享）
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
    let drawingRoiId = null; // 画布当前正在绘制/续画的检测区 id（与算法无关：先画区域，再在对应关系表里关联算法）
    let sceneImage = null;   // 视频区载入的真实报警大图（绝对 URL），null 时回退占位图
    let roiSvgRef;           // ROI 绘制图层，用于把点击换算成归一化坐标
    let chatScrollRef;
    let skills = [];         // 后端技能注册表元数据（/skills）
    let convSummary = '';    // 本会话滚动记忆/总结
    let showSummary = false; // 会话记忆面板开关
    let availableAgents = []; // 设备可选智能体算法（供智能体任务下拉，最多选 4）
    let availableAlgorithms = []; // 设备可选小模型算法目录（供小模型/小+大任务 Step1 多选）
    let wizardStep = 1;       // 右侧画板三步向导当前步：1 任务信息 / 2 ROI绘制 / 3 详情参数
    let panelView = 'list';   // 右侧面板视图：list=任务列表（默认）/ editor=布控编辑器（三步向导）
    let togglingTaskId = '';  // 正在切换「是否启用」的任务ID（防重复点击）
    let refreshingTasks = false;  // 正在从设备同步任务列表
    let listNonce = 0;        // 列表重绘计数：开关切换失败时用它把 DOM 复选框还原成真实值
    const WIZARD_STEPS = [
        { n: 1, ord: '第一步', label: '任务信息与算法选型' },
        { n: 2, ord: '第二步', label: 'ROI 绘制与算法关联' },
        { n: 3, ord: '第三步', label: '算法/智能体详情参数' }
    ];

    // convId 变化时持久化，刷新后可恢复到同一会话
    $: if (convId) localStorage.setItem(LS_CONV_KEY, convId);

    // ── ROI 池的设备侧标识（areaId / areaName / areaType）────────────────────
    // 设备 areas[i] 需要 areaId(区域号) / areaName(区域名) / areaType(几何类型)：
    // areaName 即池项 name（表格里可编辑），areaType 当前画布只产出多边形(POLYGON)，
    // areaId 由池统一分配且【同一任务内唯一】（同一块 ROI 被多个算法/智能体共用时共享同一号）。
    const AREA_TYPE_POLYGON = 'POLYGON';
    function fullRoiItem() {
        return { id: 'full', name: '全屏检测', points: [], areaId: 1, areaType: AREA_TYPE_POLYGON };
    }
    // 几何类型的中文显示名（当前画布只产出 POLYGON；未知类型原样展示，便于看出设备带回了什么）
    function areaTypeLabel(t) {
        return (t || AREA_TYPE_POLYGON) === AREA_TYPE_POLYGON ? '多边形' : t;
    }
    // 取池内最小空闲区域号（含默认「全屏检测」占用的号），用于新建检测区
    function nextAreaId(rois) {
        const used = new Set((rois || []).map((r) => Number(r.areaId)).filter((n) => Number.isInteger(n) && n > 0));
        let id = 1;
        while (used.has(id)) id += 1;
        return id;
    }
    // 池内是否存在缺号/非法号/撞号/缺几何类型的项（不变式的触发条件）
    function needsAreaMeta(rois) {
        const seen = new Set();
        for (const r of rois || []) {
            const aid = Number(r.areaId);
            if (!Number.isInteger(aid) || aid < 1 || seen.has(aid) || !r.areaType) return true;
            seen.add(aid);
        }
        return false;
    }
    // 按「已有号优先、缺号/撞号顺延到最小空闲号」补齐池项的 areaId/areaType
    function withAreaMeta(rois) {
        const used = new Set();
        return (rois || []).map((r) => {
            let aid = Number(r.areaId);
            if (!Number.isInteger(aid) || aid < 1 || used.has(aid)) {
                aid = 1;
                while (used.has(aid)) aid += 1;
            }
            used.add(aid);
            return { ...r, areaId: aid, areaType: r.areaType || AREA_TYPE_POLYGON };
        });
    }

    // ── 派生态：智能体任务 & 算法仓任务共享「池 + 逐项 ROI 绑定」模型 ────────
    $: isAgentTask = config.taskMode === 'agent';
    $: activeAgent = (config.agents || [])[config.activeAgentIndex] || null;
    // 算法仓任务的当前编辑算法项（与 activeAgent 镜像，仅第③步详情参数使用）
    $: activeAlgorithm = (config.algorithms || [])[config.activeAlgorithmIndex] || null;
    // 第②步的绘制对象是【检测区本身】，与当前算法/智能体无关：画完再在对应关系表里勾选关联项
    $: drawingRoi = (config.rois || []).find((r) => r.id === drawingRoiId) || null;
    // 绘制目标被删除 / 换任务重载配置后不在池中：复位为「待新建」，避免画布指向幽灵区域
    $: if (drawingRoiId && config.rois && !config.rois.some((r) => r.id === drawingRoiId)) drawingRoiId = null;
    // 不变式：ROI 池恒有默认「全屏检测」伪项（任何来源回填后补齐），它是对应关系表的默认关联行
    $: if (config.rois && !config.rois.some((r) => r.id === 'full')) {
        config.rois = [fullRoiItem(), ...config.rois];
    }
    // 不变式：每个池项都带设备侧下发所需的 areaId(任务内唯一，≥1 整数) 与 areaType(几何类型)。
    // 对话/模板/旧快照回填的池项可能缺号或撞号，这里统一补齐；仅在确有缺失/冲突时改写，避免反复触发响应式。
    $: if (config.rois && needsAreaMeta(config.rois)) config.rois = withAreaMeta(config.rois);

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

    // 任务列表数据源：设备快照 device_tasks（同步设备时由后端烘焙，含 task_status/task_enable/algorithms_label/detail）
    $: deviceTasks = (() => {
        let list = [];
        try { list = JSON.parse($selectedDevice?.device_tasks || '[]'); } catch (e) { list = []; }
        return Array.isArray(list) ? list : [];
    })();
    // 编辑态：task_id 非空 ⇒ 保存走真更新（PUT），按钮文案与提示同步切换
    $: isEditing = !!config.task_id;
    // 小+大协同任务专属参数（扩图倍数 / 二次大模型 / 裁切送检预览）仅该类型展示
    $: isCombinedTask = config.taskMode === 'combined';
    // 三阈值收敛为「检测目标 + 该目标阈值」一组控件：面板仍按目标写回对应字段（与后端 _thresh_key 对齐）
    $: threshKey = config.yoloTarget === 'vehicle' ? 'yoloVehicleThresh'
        : config.yoloTarget === 'human' ? 'yoloHumanThresh' : 'yoloNonMotorThresh';

    // ── 检测目标（设备 targetTypes）：支持多目标勾选 ───────────────────────
    // 选项优先取算法目录里该算法自带的 targetTypes（设备真实能力），取不到时用通用兜底集。
    const TARGET_TYPE_LABELS = { PERSON: '人员 (人体检测)', VEHICLE: '车辆', NON_MOTOR: '非机动车', NONMOTOR: '非机动车', FACE: '人脸' };
    const FALLBACK_TARGET_TYPES = ['PERSON', 'VEHICLE', 'NON_MOTOR'];
    const YOLO_TO_TARGET = { human: 'PERSON', vehicle: 'VEHICLE', any: 'NON_MOTOR' };
    const targetTypeLabel = (t) => TARGET_TYPE_LABELS[String(t || '').toUpperCase()] || t;
    // 设备目标类型ID → 面板主目标标识（与后端 _target_type_to_yolo 对齐）
    const targetToYolo = (t) => {
        const up = String(t || '').toUpperCase();
        return up === 'PERSON' ? 'human' : up === 'VEHICLE' ? 'vehicle' : 'any';
    };
    // 当前算法可选目标类型：目录行的 targetTypes 优先，缺失（离线快照）用兜底集
    $: targetTypeOptions = (() => {
        const hit = availableAlgorithms.find((a) => algoOptionKey(a) === algoItemKey(activeAlgorithm));
        const list = (hit?.targetTypes || []).filter(Boolean);
        const base = list.length ? list : FALLBACK_TARGET_TYPES;
        // 已选但目录里没有的目标（设备原值）也要出现在下拉里，否则会被静默丢弃
        return [...new Set([...base, ...selectedTargets])];
    })();
    // 已勾选目标：老配置只有单值 yoloTarget 时按它推导，保证回填不丢
    $: selectedTargets = (Array.isArray(config.yoloTargets) && config.yoloTargets.length)
        ? config.yoloTargets
        : [YOLO_TO_TARGET[config.yoloTarget] || 'PERSON'];
    let targetPickerOpen = false;
    // 下拉面板的展开方向/最大高度按按钮在视口中的实际可用空间计算：
    // 该控件位于第三步面板底部，固定「向下 + max-h-44」时会被外层滚动容器裁掉，导致选项看不全。
    let targetPickerUp = false;      // true = 向上展开
    let targetPickerMaxH = 200;      // 面板最大高度(px)，超出则面板内部滚动
    function toggleTargetPicker(e) {
        if (targetPickerOpen) { targetPickerOpen = false; return; }
        const r = e.currentTarget.getBoundingClientRect();
        const below = window.innerHeight - r.bottom - 12;   // 按钮下方剩余空间
        const above = r.top - 12;                            // 按钮上方剩余空间
        targetPickerUp = below < 160 && above > below;       // 下方不够且上方更宽裕时翻转向上
        targetPickerMaxH = Math.max(120, Math.min(300, targetPickerUp ? above : below));
        targetPickerOpen = true;
    }

    // 勾选/取消一个检测目标：至少保留一个；主目标(yoloTarget)恒跟随首个已选目标，阈值字段随之切换
    function toggleTargetType(tt, checked) {
        let next = checked ? [...selectedTargets, tt] : selectedTargets.filter((t) => t !== tt);
        next = [...new Set(next)];
        if (!next.length) { showToast('至少需要勾选一个检测目标。', 'warning'); return; }
        config = { ...config, yoloTargets: next, yoloTarget: targetToYolo(next[0]) };
    }

    // 设备任务类型 → 列表展示名（single_point_task 为纯小模型任务的设备原始类型名）
    const TASK_TYPE_LABELS = {
        'agent_real_task': '大模型任务',
        'small_task': '小模型任务',
        'single_point_task': '小模型任务',
        'small_and_agent_task': '大小协同任务'
    };
    const taskTypeLabel = (t) => TASK_TYPE_LABELS[t] || t || '—';
    const TASK_STATUS_CLASS = {
        '正常': 'bg-emerald-950/60 text-emerald-300 border-emerald-700/60',
        '异常': 'bg-rose-950/60 text-rose-300 border-rose-700/60',
        '未启用': 'bg-slate-900 text-slate-400 border-slate-700'
    };
    const taskStatusClass = (st) => TASK_STATUS_CLASS[st] || TASK_STATUS_CLASS['未启用'];

    // 阈值滑杆：只改「当前检测目标」对应的那一个阈值字段，其余字段保持设备原值（回填 round-trip 不丢）
    function setThresh(v) {
        const num = Math.min(0.9, Math.max(0.1, Number(v) || 0.1));
        config = { ...config, [threshKey]: +num.toFixed(2) };
    }

    // 目标大小：面板口径 0~100(目标框占画面百分比) → 设备 targetMax/targetMin 口径 0~1，保留两位小数
    function toTargetSize(v, dft) {
        const n = Number(v);
        const pct = Number.isFinite(n) ? n : dft;
        return +Math.min(1, Math.max(0, pct / 100)).toFixed(2);
    }

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
        drawingRoiId = null;
        sceneImage = null;
        showHistory = false;
        convSummary = '';
        showSummary = false;
        availableAgents = [];
        availableAlgorithms = [];
        wizardStep = 1;
        panelView = 'list';
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
    // 绘制与算法/智能体【解耦】：直接往画布上点即可，落点写入「当前绘制中的检测区」；
    // 没有绘制中的区域时自动新建一个「检测区N」池项。区域与算法的关联在下方对应关系表里勾选。
    function addRoiPoint(ev) {
        if (!roiDrawActive || !roiSvgRef) return;
        const rect = roiSvgRef.getBoundingClientRect();
        const x = Math.min(1, Math.max(0, (ev.clientX - rect.left) / rect.width));
        const y = Math.min(1, Math.max(0, (ev.clientY - rect.top) / rect.height));
        const pt = { x: +x.toFixed(4), y: +y.toFixed(4) };
        let roiId = drawingRoiId;
        if (!roiId || roiId === 'full' || !(config.rois || []).some((r) => r.id === roiId)) {
            const n = (config.rois || []).filter((r) => r.id !== 'full').length + 1;
            roiId = 'roi_' + Date.now();
            // 新检测区即时拿到任务内唯一的 areaId 与几何类型，随后随算法一起下发给设备
            config.rois = [...(config.rois || []),
                { id: roiId, name: `检测区${n}`, points: [], areaId: nextAreaId(config.rois), areaType: AREA_TYPE_POLYGON }];
            drawingRoiId = roiId;
        }
        config.rois = config.rois.map((r) => r.id === roiId ? { ...r, points: [...r.points, pt] } : r);
    }

    // 开始绘制一个全新的检测区（下一次落点时才真正建池项，避免留下空区域）
    function startNewRoi() {
        drawingRoiId = null;
        roiDrawActive = true;
    }

    // 续画/修改某个已有检测区（全屏项不可绘制）
    function editRoi(id) {
        if (id === 'full') return;
        drawingRoiId = id;
        roiDrawActive = true;
    }

    // 清除【当前绘制中】的检测区：整块删除，原本关联它的算法/智能体回落到全屏检测
    function clearRoi() {
        if (!drawingRoiId || drawingRoiId === 'full') {
            showToast('当前没有正在绘制的检测区。点击画布即可开始绘制。', 'info');
            return;
        }
        deleteRoi(drawingRoiId);
    }

    // roiPoints -> SVG points 字符串（viewBox 800x500）：取【当前绘制中】的检测区
    $: currentRoiPoints = drawingRoi?.points || [];
    $: roiSvgPoints = currentRoiPoints.map((p) => `${p.x * 800},${p.y * 500}`).join(' ');

    // 切换当前编辑的智能体
    function selectAgent(i) {
        config.activeAgentIndex = i;
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

    // 快照兜底：把 algorithms_ability([{name, cards[]}]) 拍平成算法目录行（无版本/目标类型/中文名）
    function abilityAlgorithmRows(dev) {
        let raw = [];
        try { raw = JSON.parse(dev?.algorithms_ability || '[]'); } catch (e) { raw = []; }
        return (Array.isArray(raw) ? raw : []).flatMap((p) => (p?.cards || []).map((t) => ({
            algoCabinName: p?.name || '', version: 'V2.0.0', eventType: t, eventName: '', targetTypes: []
        }))).filter((a) => a.eventType);
    }

    // ── 算法目录（小模型/小+大）：供 Step1 多选/新增算法。
    //    走后端 GET /devices/{id}/algorithms（实时取算法仓 + 卡片能力，设备离线时后端用快照兜底）。
    //    不要直接读 dev.available_algorithms —— 那里存的是任务里已用到的算法ID字符串，不是能力目录，
    //    早先按它解析会整形出一堆空对象并被过滤光，表现为「添加算法」目录为空。
    async function loadAvailableAlgorithms() {
        const dev = $selectedDevice;
        if (!dev?.id) { availableAlgorithms = []; return; }
        try {
            const res = await apiGet(`/devices/${dev.id}/algorithms?refresh=true`);
            availableAlgorithms = res?.algorithms || [];
        } catch (e) {
            availableAlgorithms = abilityAlgorithmRows(dev);  // 后端不可达时前端再兜底一次
        }
    }

    // 算法仓任务目录预热：算法目录（rows 优先用后端 proposal.available_algorithms，缺失则查设备算法目录接口）
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
            // 默认关联「全屏检测」（useFullFrame 与 roiId==='full' 恒等，部署门禁据此放行）
            roiId: 'full', useFullFrame: true,
            maxTarget: defaultConfig.maxTarget, minTarget: defaultConfig.minTarget, yoloTarget: defaultConfig.yoloTarget,
            yoloTargets: [...defaultConfig.yoloTargets],
            yoloHumanThresh: defaultConfig.yoloHumanThresh, yoloVehicleThresh: defaultConfig.yoloVehicleThresh,
            yoloNonMotorThresh: defaultConfig.yoloNonMotorThresh,
            intrusionDuration: defaultConfig.intrusionDuration, alarmInterval: defaultConfig.alarmInterval,
            cropUp: defaultConfig.cropUp, cropDown: defaultConfig.cropDown, cropLeft: defaultConfig.cropLeft, cropRight: defaultConfig.cropRight
        };
        if (kind === 'combined') {
            item.agent_id = ''; item.agentType = ''; item.event_tag = '';
            item.alarm_type = 'freeform'; item.prompt = ''; item.alarm_condition = null;
            item.filter_enable = false; item.filter_keywords = '';
        }
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

    // combined 算法项切换二次大模型：从设备智能体目录同步全量参数（event_tag/alarm_type/prompt/alarm_condition）；
    // 换智能体即改用新智能体自身的报警条件（设备未给则置 null 交后端按 alarm_type 推导），并复位关键词过滤
    function changeAlgoAgent(i, eventId) {
        const src = availableAgents.find((a) => String(a.event_id) === String(eventId)) || {};
        config.algorithms = config.algorithms.map((a, idx) => idx === i ? {
            ...a, agent_id: eventId, agentType: eventId, event_tag: src.event_tag || String(eventId),
            alarm_type: src.alarm_type || 'freeform', prompt: src.prompt || a.prompt || '',
            alarm_condition: src.alarm_condition || null,
            filter_enable: false, filter_keywords: ''
        } : a);
        if (i === (config.activeAlgorithmIndex || 0)) config.agentType = eventId;
    }

    // combined 算法项：就地修改二次大模型的某个参数（第③步「级联后置多模态 Agent」全量参数编辑）
    function setAlgoAgentField(i, key, value) {
        config.algorithms = config.algorithms.map((a, idx) => idx === i ? { ...a, [key]: value } : a);
    }

    // ── ROI 池：改名 / 改区域号 / 删除（删除后引用它的算法/智能体回落全屏；全屏项为默认不可删/改） ──
    function renameRoi(id, name) {
        if (id === 'full') return;
        config.rois = config.rois.map((r) => r.id === id ? { ...r, name } : r);
    }
    // 改设备侧区域号(areaId)：必须为 ≥1 的整数且【任务内唯一】（含默认全屏项占用的号），撞号则拒绝。
    // 返回 false 表示未写回，调用方据此把输入框还原为原值。
    function setAreaId(id, value) {
        const aid = Number(value);
        if (!Number.isInteger(aid) || aid < 1) {
            showToast('区域号(areaId)需为大于 0 的整数。', 'warning');
            return false;
        }
        if ((config.rois || []).some((r) => r.id !== id && Number(r.areaId) === aid)) {
            showToast(`区域号 ${aid} 已被其它检测区占用：同一任务内 areaId 必须唯一。`, 'warning');
            return false;
        }
        config.rois = config.rois.map((r) => r.id === id ? { ...r, areaId: aid } : r);
        return true;
    }
    function deleteRoi(id) {
        if (id === 'full') { showToast('全屏检测为默认项，不可删除。', 'info'); return; }
        config.rois = config.rois.filter((r) => r.id !== id);
        config.agents = (config.agents || []).map((a) => a.roiId === id ? { ...a, roiId: 'full' } : a);
        config.algorithms = (config.algorithms || []).map((a) => a.roiId === id ? { ...a, roiId: 'full', useFullFrame: true } : a);
        if (drawingRoiId === id) drawingRoiId = null;   // 删的是正在绘制的那块，画布回到「待新建」态
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
    // 对应关系表的完整行集：默认「全屏检测」置顶，其后是用户画出的自定义检测区
    $: tableRois = [
        (config.rois || []).find((r) => r.id === 'full') || fullRoiItem(),
        ...customRois
    ];
    // 画布叠加层：勾了「显示」、且不是当前正在绘制的那个区域（当前区由主多边形单独高亮）
    $: overlayRois = customRois.filter((r) => !hiddenRoiIds.has(r.id) && r.id !== drawingRoiId && (r.points || []).length >= 3);

    // 表内勾选：把第 i 个算法/智能体关联到该检测区；取消勾选则回落到默认「全屏检测」。
    // 数据模型仍是「每项单绑一个检测区」，故一行内勾选即互斥切换（第②步唯一的关联入口）。
    function toggleItemRoi(i, roiId, checked) {
        const target = (checked && roiId !== 'full') ? roiId : 'full';
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
        // 跨标签「对话级微调」灌参：视作新建，清掉上一次编辑残留的 task_id
        config = { ...config, ...data, task_id: data?.task_id ?? null };
        templateApplied = false;
        monitorActive = true;
        wizardStep = 1;
        panelView = 'editor';
        showToast('双级级联配置参数填充，裁切扩图区域渲染成功！', 'success');
        scrollToBottom();
    }

    // 面板三列参数（Phase 1 绑顶层 config）对应的键：多算法回填时把当前算法项的这些参数提到顶层，
    // 使单算法面板显示/编辑的是「当前算法」的真实值（下发时当前项也回读顶层，保持一致）。
    const PANEL_PARAM_KEYS = ['maxTarget', 'minTarget', 'yoloHumanThresh', 'yoloVehicleThresh',
        'yoloNonMotorThresh', 'yoloTarget', 'yoloTargets', 'intrusionDuration', 'alarmInterval',
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
        // 池里必须始终有默认「全屏检测」伪项（第②步对应关系表的默认关联行）
        const withFull = (list) => ((list || []).some((r) => r.id === 'full')
            ? list : [fullRoiItem(), ...(list || [])]);
        // useFullFrame 与 roiId==='full' 恒等：老快照可能两者不一致，统一以 roiId 为准
        const normItem = (it) => ({ ...it, roiId: it.roiId || 'full', useFullFrame: (it.roiId || 'full') === 'full' });
        if (Array.isArray(d.algorithms) && d.algorithms.length) {
            const rois = withFull((Array.isArray(d.rois) && d.rois.length) ? d.rois : []);
            const algorithms = d.algorithms.map(normItem);
            const idx = d.activeAlgorithmIndex || 0;
            const active = algorithms[idx] || algorithms[0];
            const out = {
                ...base, ...d, ...hoistItemParams(active),
                algorithms, rois,
                activeAlgorithmIndex: idx, roiPoints: []
            };
            // combined：顶层 agentType 用 event_id（对齐 Step3 下拉选项与下发 agent_id，避免误用 event_tag）
            if ((active?.kind || 'small') === 'combined') out.agentType = active.agentType || active.agent_id || out.agentType || '';
            return out;
        }
        // 旧单算法：由 event_type/algo_cabin_name/roiPoints(顶层) 组装一条 algorithms[] + 一个池 ROI
        const pts = d.roiPoints || base.roiPoints || [];
        const rois = [fullRoiItem()];
        let roiId = 'full';
        if (pts.length >= 3) { roiId = 'roi_1'; rois.push({ id: roiId, name: '检测区1', points: pts }); }
        const kind = (d.taskMode === 'combined') ? 'combined' : 'small';
        const item = normItem({
            kind,
            event_type: d.event_type || base.event_type || '',
            algo_cabin_name: d.algo_cabin_name || base.algo_cabin_name || '',
            version: d.version || 'V2.0.0',
            roiId
        });
        if (kind === 'combined') {
            item.agent_id = d.agent_id || d.agentType || '';
            item.event_tag = d.event_tag || d.agentType || '';
            item.alarm_type = d.alarm_type || 'freeform';
            item.prompt = d.prompt || '';
            item.alarm_condition = d.alarm_condition ?? null;
            item.filter_enable = !!d.filter_enable;
            item.filter_keywords = d.filter_keywords || '';
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
                rois: proposal.rois && proposal.rois.length ? proposal.rois : [fullRoiItem()],
                activeAgentIndex: proposal.activeAgentIndex || 0
            };
            availableAgents = proposal.available_agents || [];
            if (!availableAgents.length) await loadAvailableAgents();
        } else {
            config = normalizeWarehouseConfig(config, proposal);
            await loadWarehouseCatalogs(proposal.available_algorithms);
        }
        // 对话草案=新建：清掉上一次编辑残留的 task_id，避免把草案误存进既有任务
        config = { ...config, task_id: proposal.task_id ?? null };
        panelView = 'editor';
        // fromTemplate=对话选模板(路径 c)：免 ROI 门禁；普通 propose 草案：需画 ROI 才放行
        templateApplied = !!proposal.fromTemplate;
        monitorActive = true;
        wizardStep = 1;
        await loadSceneImage(proposal.alertType);
        roiDrawActive = true;
        showToast('已载入推荐参数与最新报警大图，请在视频区点击绘制检测区(ROI)。', 'success');
        await scrollToBottom();
    }

    // 点击任务列表 / 对话表格「编辑」：把该任务的真实参数(row.detail)回填到右侧控制面板，
    // 并在视频区载入设备最新报警大图（无则占位图）。detail 由后端在同步设备时烘焙进快照，离线仍可用。
    async function viewTask(row) {
        const d = row.detail || {};
        if (d.taskMode === 'agent') {
            config = {
                ...defaultConfig, ...d,
                agents: d.agents && d.agents.length ? d.agents : [],
                rois: d.rois && d.rois.length ? d.rois : [fullRoiItem()],
                activeAgentIndex: 0
            };
            await loadAvailableAgents();  // 拉可选智能体，便于下拉换绑
        } else {
            config = normalizeWarehouseConfig(defaultConfig, d);
            await loadWarehouseCatalogs();  // 预热算法/智能体目录，便于 Step1 增删换算法
        }
        // detail 由后端烘焙，已带 task_id/channel_device_id ⇒ 本次保存直接更新该任务；老快照缺失时回退列表行的值
        config = {
            ...config,
            task_id: config.task_id || d.task_id || row.task_id || null,
            channel_device_id: config.channel_device_id ?? d.channel_device_id ?? row.camera_device_id ?? null
        };
        panelView = 'editor';
        // 编辑态非模板；真实 ROI 已随算法项带回（全屏项 useFullFrame=true / 自定义项有点），门禁自然放行
        templateApplied = false;
        monitorActive = true;
        wizardStep = 1;
        await loadSceneImage(d.alertType);
        roiDrawActive = !(d.taskMode === 'agent');
        pushSystemTip(d.name || row.task_name || '布控任务');
        showToast(`已载入任务「${d.name || row.task_name || row.task_id}」的真实参数。`, 'success');
        await scrollToBottom();
    }

    // 列表「编辑」：复用 viewTask 的回填逻辑（同一套 detail → 面板映射），viewTask 内部已切到编辑器视图
    async function editTask(row) {
        await viewTask(row);
    }

    // 从设备重新拉取快照（任务列表数据源），再刷新全局设备 store
    async function refreshTaskList() {
        const device = $selectedDevice;
        if (!device?.id) { showToast('请先在顶栏选择一个设备。', 'error'); return; }
        refreshingTasks = true;
        try {
            await apiPost(`/devices/${device.id}/fetch`);
            await loadDevices();
            showToast('已从设备同步最新任务列表。', 'success');
        } catch (e) {
            showToast(e?.detail || '同步设备任务失败，请检查设备在线状态。', 'error');
        } finally {
            refreshingTasks = false;
        }
    }

    // 「是否启用」开关：PUT 任务 enable（设备无硬删除接口，停用即降级），成功后刷新快照
    async function toggleTaskEnable(row, enable) {
        const device = $selectedDevice;
        if (!device?.id) { showToast('请先在顶栏选择一个设备。', 'error'); return; }
        togglingTaskId = String(row.task_id);
        try {
            await apiPut(`/devices/${device.id}/tasks/${row.task_id}/enable`, { enable });
            showToast(`任务「${row.task_name || row.task_id}」已${enable ? '启用' : '停用'}。`, 'success');
            await loadDevices();
        } catch (e) {
            showToast(e?.detail || '切换启用状态失败，请检查设备在线状态。', 'error');
            listNonce += 1;   // 复选框已被点翻：重建列表行，还原为设备真实值
        } finally {
            togglingTaskId = '';
        }
    }

    // 新建布控任务：清空面板（task_id=null ⇒ 保存走新建下发），默认小模型任务 + 首个通道
    async function startNewTask() {
        config = { ...defaultConfig, agents: [], algorithms: [], rois: [fullRoiItem()] };
        const ch = channelOptions[0];
        if (ch) config.channel_device_id = ch.device_id;
        templateApplied = false;
        monitorActive = true;
        roiDrawActive = true;
        wizardStep = 1;
        panelView = 'editor';
        sceneImage = null;
        await loadWarehouseCatalogs(); // 加载算法目录与智能体目录，便于 Step1 增删换算法/智能体
        if (!(config.algorithms || []).length) addAlgorithmSlot();
        await loadSceneImage(null);
        showToast('已进入新建布控任务：请选择任务类型、通道与算法。', 'info');
    }

    // 新建时切换任务类型：不同类型的参数集不同，切换即补齐该类型所需的槽位与目录
    async function changeTaskMode(mode) {
        if (config.taskMode === mode) return;
        config = { ...config, taskMode: mode };
        if (mode === 'agent') {
            if (!availableAgents.length) await loadAvailableAgents();
            if (!(config.agents || []).length) addAgentSlot();
        } else {
            await loadWarehouseCatalogs();
            config.algorithms = (config.algorithms || []).map((a) => ({ ...a, kind: mode === 'combined' ? 'combined' : 'small' }));
            if (!config.algorithms.length) addAlgorithmSlot();
        }
        wizardStep = 1;
    }

    // 返回任务列表（保留面板参数，可再次进入继续编辑）
    function backToList() {
        panelView = 'list';
    }

    // 编辑保存成功后：刷新设备快照并回到列表
    async function afterTaskSaved() {
        await loadDevices();
        config = { ...defaultConfig };
        monitorActive = false;
        roiDrawActive = false;
        wizardStep = 1;
        panelView = 'list';
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
        // 强制 ROI 门禁（仅手动路径 templateApplied=false）：每条仓算法必须关联了「默认全屏检测」或「已画 ≥3 点的自定义检测区」，
        // 关联到一个点数不足的半成品区域不放行。模板/对话路径(templateApplied=true)跳过此门禁，用模板自带 ROI 或全屏。
        if (!templateApplied) {
            const algos = config.algorithms || [];
            const blocked = algos.some((item) => {
                if ((item.roiId || 'full') === 'full') return false;   // 默认全屏检测：直接放行
                const pts = (config.rois.find((r) => r.id === item.roiId)?.points) || [];
                return pts.length < 3;
            });
            if (!algos.length || blocked) {
                showToast('存在关联了未画完检测区(至少3个点)的算法，请在第二步补全或改回全屏检测。', 'warning');
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
            const activeThresh = yoloTarget === 'vehicle' ? p.yoloVehicleThresh
                : yoloTarget === 'human' ? p.yoloHumanThresh
                : p.yoloNonMotorThresh;
            // 检测目标支持多选：下发 item/面板的 yoloTargets；老配置只有单值 yoloTarget 时按它推导
            const picked = (Array.isArray(p.yoloTargets) && p.yoloTargets.length) ? p.yoloTargets : null;
            const target_types = picked || (yoloTarget === 'vehicle' ? ['VEHICLE'] : yoloTarget === 'human' ? ['PERSON'] : ['NON_MOTOR']);
            // 检测区：绑「全屏检测」→ 空点(设备侧回落全画面)，否则取池项点集；
            // areaId/areaName/areaType 随之一起下发（用户在第②步配置，areaId 任务内唯一）
            const roi = (config.rois || []).find((r) => r.id === (item.roiId || 'full')) || fullRoiItem();
            const roiPoints = ((item.roiId || 'full') === 'full') ? [] : (roi.points || []);
            const kind = item.kind || 'small';
            const algo = {
                kind,
                event_type: item.event_type || config.event_type,
                algo_cabin_name: item.algo_cabin_name || config.algo_cabin_name,
                version: item.version || config.version || 'V2.0.0',
                target_types,
                threshold: Number(activeThresh),
                // 目标大小：面板 0~100(画面占比百分比) → 设备 targetMax/targetMin 的 0~1，保留两位小数
                target_max: toTargetSize(p.maxTarget, 100),
                target_min: toTargetSize(p.minTarget, 0),
                duration: Math.round(Number(p.intrusionDuration)),
                cooldown: Math.round(Number(p.alarmInterval)),
                roiPoints,
                areaId: Number(roi.areaId) || 1,
                areaName: roi.name || '检测区',
                areaType: roi.areaType || AREA_TYPE_POLYGON
            };
            if (kind === 'combined') {
                // 小+大：追加扩图策略（target_expand 仅小+大生效）+ 二次大模型全量参数
                algo.target_expand = {
                    top: Number(p.cropUp), bottom: Number(p.cropDown),
                    left: Number(p.cropLeft), right: Number(p.cropRight)
                };
                algo.agent_id = p.agentType || item.agent_id;
                // event_tag/alarm_type/alarm_condition/filter_* 不在顶层面板键里，恒读各自 item（第③步就地编辑）
                algo.event_tag = item.event_tag || '';
                algo.alarm_type = item.alarm_type || 'freeform';
                algo.prompt = p.prompt || '';
                algo.alarm_condition = item.alarm_condition || null;
                // 关键词过滤仅描述型(freeform)有意义，判断型强制关闭（与 deployAgentTask/后端 _enrich_* 一致）
                const freeform = (item.alarm_type || 'freeform') === 'freeform';
                algo.filter_enable = freeform && !!item.filter_enable;
                algo.filter_keywords = freeform ? (item.filter_keywords || '') : '';
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
        // 编辑既有任务(task_id 非空)走 PUT 真更新：任务名/通道 PUT task，各仓 monitor 以原 monitor_id 覆盖规则
        const editing = !!config.task_id;
        try {
            const res = editing
                ? await apiPut(`/devices/${device.id}/tasks/${config.task_id}/warehouse-task`, body)
                : await apiPost(`/devices/${device.id}/deploy/warehouse-task`, body);
            const hasCombined = items.some((a) => a.kind === 'combined');
            if (editing) {
                showToast(`✅ 任务「${config.name}」已更新（${items.length} 个算法，task_id=${res.task_id}）。`, 'success');
                await afterTaskSaved();
            } else {
                showToast(`🚀 ${hasCombined ? '小+大级联' : '纯小模型'}布控任务「${config.name}」已下发（${items.length} 个算法，task_id=${res.task_id}）。`, 'success');
                setTimeout(() => switchTab('taskops'), 1000);
            }
        } catch (e) {
            showToast(e?.detail || (editing ? '任务更新失败，请检查设备在线状态与算法授权。' : '布控任务下发失败，请检查设备在线状态与算法授权。'), 'error');
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
            agents: config.agents.map((a) => {
                // 同 deployWarehouseTaskMulti：逐智能体解析所绑检测区，连同设备侧区域标识一起下发
                const roi = (config.rois || []).find((r) => r.id === (a.roiId || 'full')) || fullRoiItem();
                return {
                    event_id: a.event_id,
                    event_tag: a.event_tag || '',
                    alarm_type: a.alarm_type || 'freeform',
                    prompt: a.prompt || '',
                    alarm_condition: a.alarm_condition || null,
                    filter_enable: a.alarm_type === 'freeform' ? !!a.filter_enable : false,
                    filter_keywords: a.alarm_type === 'freeform' ? (a.filter_keywords || '') : '',
                    roiPoints: ((a.roiId || 'full') === 'full') ? [] : (roi.points || []),
                    areaId: Number(roi.areaId) || 1,
                    areaName: roi.name || '检测区',
                    areaType: roi.areaType || AREA_TYPE_POLYGON
                };
            })
        };
        const editing = !!config.task_id;
        try {
            const res = editing
                ? await apiPut(`/devices/${device.id}/tasks/${config.task_id}/agent-task`, body)
                : await apiPost(`/devices/${device.id}/deploy/agent-task`, body);
            if (editing) {
                showToast(`✅ 智能体任务「${config.name}」已更新（task_id=${res.task_id}）。`, 'success');
                await afterTaskSaved();
            } else {
                showToast(`🚀 智能体任务「${config.name}」已下发到设备（task_id=${res.task_id}）。`, 'success');
                setTimeout(() => switchTab('taskops'), 1000);
            }
        } catch (e) {
            showToast(e?.detail || (editing ? '智能体任务更新失败，请检查设备在线状态与智能体算法。' : '智能体任务下发失败，请检查设备在线状态与智能体算法。'), 'error');
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
                rois: d.rois && d.rois.length ? d.rois : [fullRoiItem()],
                activeAgentIndex: 0
            };
            await loadAvailableAgents();
        } else {
            config = normalizeWarehouseConfig(defaultConfig, d);
            await loadWarehouseCatalogs();  // 预热算法/智能体目录，便于 Step1 增删换算法
        }
        config = { ...config, task_id: null };   // 模板=新建：忽略模板快照里可能残留的 task_id
        panelView = 'editor';
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
                                                                            <i class="fa-solid fa-pen-to-square mr-1"></i>编辑
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

    <!-- 右侧：任务列表（默认） / 布控编辑器 -->
    <div class="flex-1 flex flex-col h-full bg-slate-900 overflow-y-auto p-5">
        {#if panelView === 'list'}
        <!-- 任务列表：数据源为设备快照 device_tasks（同步设备时烘焙，设备离线也可查看/编辑参数） -->
        <div class="mb-5 bg-slate-950/60 p-4 rounded-2xl border border-slate-800 flex items-center justify-between gap-3 flex-wrap">
            <div class="flex items-center space-x-3">
                <div class="bg-indigo-500/10 text-indigo-400 px-2.5 py-1.5 rounded-lg border border-indigo-500/20 text-xs font-bold">布控任务列表</div>
                <span class="text-[11px] text-slate-400">设备：{$selectedDevice?.name || '未选择'} · 共 {deviceTasks.length} 个任务</span>
            </div>
            <div class="flex items-center gap-2 shrink-0">
                <button on:click={refreshTaskList} disabled={refreshingTasks} title="从设备重新拉取任务/算法快照"
                        class="bg-slate-800 hover:bg-slate-700 text-slate-200 px-3 py-2 rounded-xl text-xs font-bold flex items-center transition-all border border-slate-700 disabled:opacity-50">
                    <i class="fa-solid fa-rotate mr-1.5 {refreshingTasks ? 'animate-spin' : ''}"></i>{refreshingTasks ? '同步中…' : '同步设备任务'}
                </button>
                <button on:click={startNewTask} class="bg-indigo-600 hover:bg-indigo-700 text-white px-4 py-2 rounded-xl text-xs font-bold flex items-center transition-all shadow-md shadow-indigo-500/25">
                    <i class="fa-solid fa-plus mr-1.5"></i>新建布控任务
                </button>
            </div>
        </div>

        <!-- shrink-0：本卡片带 overflow-hidden，在父级 flex 列中 min-height 会被算成 0，任务多时整张表会被压缩裁掉且没有滚动条。
             内层限高 + overflow-auto：任务多时表体自己出纵向滚动条，表头 sticky 常驻。 -->
        <div class="bg-slate-950 rounded-2xl border border-slate-800 overflow-hidden shrink-0">
            <div class="overflow-auto" style="max-height:calc(100vh - 300px)">
                <table class="w-full text-left border-collapse text-[11px]">
                    <thead class="bg-slate-900 text-[10px] text-slate-400 sticky top-0 z-10 shadow-sm">
                        <tr>
                            <th class="px-3 py-2.5 font-medium whitespace-nowrap">任务ID</th>
                            <th class="px-3 py-2.5 font-medium whitespace-nowrap">任务名称</th>
                            <th class="px-3 py-2.5 font-medium whitespace-nowrap">任务类型</th>
                            <th class="px-3 py-2.5 font-medium whitespace-nowrap">通道名称</th>
                            <th class="px-3 py-2.5 font-medium whitespace-nowrap">任务状态</th>
                            <th class="px-3 py-2.5 font-medium whitespace-nowrap">是否启用</th>
                            <th class="px-3 py-2.5 font-medium">关联智能体/算法</th>
                            <th class="px-3 py-2.5 font-medium whitespace-nowrap text-right">操作</th>
                        </tr>
                    </thead>
                    <tbody class="divide-y divide-slate-800">
                        {#key listNonce}
                            {#each deviceTasks as row, ri (row.task_id ?? ri)}
                                <tr class="hover:bg-slate-900/40 transition-colors">
                                    <td class="px-3 py-2.5 font-mono text-slate-400 whitespace-nowrap">{row.task_id ?? '—'}</td>
                                    <td class="px-3 py-2.5 text-slate-200 font-medium break-all max-w-[180px]">{row.task_name || '—'}</td>
                                    <td class="px-3 py-2.5 whitespace-nowrap">
                                        <span class="px-1.5 py-0.5 rounded border text-[10px] font-bold {row.task_type === 'agent_real_task' ? 'bg-purple-950/60 text-purple-300 border-purple-700/60' : row.task_type === 'small_and_agent_task' ? 'bg-indigo-950/60 text-indigo-300 border-indigo-700/60' : 'bg-amber-950/60 text-amber-300 border-amber-700/60'}">{taskTypeLabel(row.task_type)}</span>
                                    </td>
                                    <td class="px-3 py-2.5 text-slate-300 break-all max-w-[140px]">{row.camera_device_name || row.camera_device_id || '—'}</td>
                                    <td class="px-3 py-2.5 whitespace-nowrap">
                                        <span class="px-1.5 py-0.5 rounded border text-[10px] font-bold {taskStatusClass(row.task_status)}">{row.task_status || '—'}</span>
                                    </td>
                                    <td class="px-3 py-2.5 whitespace-nowrap">
                                        <label class="inline-flex items-center cursor-pointer" title={row.task_enable ? '点击停用该任务' : '点击启用该任务'}>
                                            <input type="checkbox" class="sr-only peer" checked={!!row.task_enable}
                                                   disabled={togglingTaskId === String(row.task_id)}
                                                   on:change={(e) => toggleTaskEnable(row, e.currentTarget.checked)} />
                                            <span class="w-9 h-5 rounded-full bg-slate-700 peer-checked:bg-emerald-600 relative transition-colors after:content-[''] after:absolute after:top-0.5 after:left-0.5 after:bg-white after:rounded-full after:h-4 after:w-4 after:transition-all peer-checked:after:translate-x-4"></span>
                                        </label>
                                    </td>
                                    <td class="px-3 py-2.5 text-slate-300 break-all max-w-[220px]">{row.algorithms_label || (Array.isArray(row.algorithms) ? row.algorithms.join('、') : row.algorithms) || '—'}</td>
                                    <td class="px-3 py-2.5 whitespace-nowrap text-right">
                                        <button on:click={() => editTask(row)} title="按任务类型载入其真实参数并编辑"
                                                class="text-[11px] px-2.5 py-1 rounded-md bg-indigo-600/20 text-indigo-300 border border-indigo-500/30 hover:bg-indigo-600/40 transition-all">
                                            <i class="fa-solid fa-pen-to-square mr-1"></i>编辑
                                        </button>
                                    </td>
                                </tr>
                            {:else}
                                <tr>
                                    <td colspan="8" class="px-3 py-10 text-center text-[11px] text-slate-500">
                                        <i class="fa-solid fa-inbox text-2xl text-slate-700 block mb-2"></i>
                                        该设备暂无布控任务：点右上「同步设备任务」从设备拉取，或「新建布控任务」直接布控。
                                    </td>
                                </tr>
                            {/each}
                        {/key}
                    </tbody>
                </table>
            </div>
        </div>
        <p class="text-[10px] text-slate-500 mt-3 leading-relaxed">
            <i class="fa-regular fa-lightbulb mr-1 text-amber-400"></i>
            点「编辑」按任务类型载入真实参数：大模型任务只展示分析间隔与智能体 Prompt；小模型任务只展示端侧检测参数（检测目标/阈值/目标个数/时长/冷却）；大小协同任务额外展示目标扩图倍数与二次大模型。
            关闭「是否启用」即停用该任务及其全部 monitor（设备无硬删除接口，停用为降级手段）。
        </p>
        {:else}
        <div class="mb-5 bg-slate-950/60 p-4 rounded-2xl border border-slate-800 flex items-center justify-between">
            <div class="flex items-center space-x-3">
                <div class="bg-indigo-500/10 text-indigo-400 px-2.5 py-1.5 rounded-lg border border-indigo-500/20 text-xs font-bold">{isAgentTask ? '大模型直推管道' : isCombinedTask ? '双级级联管道' : '小模型端侧管道'}</div>
                <!-- 管道示意与任务类型一致：大模型=按间隔抽帧直送 VLM；小模型=端侧算法直接出报警；小+大=检测命中后裁图复核 -->
                <div class="flex items-center text-[11px] text-slate-400 flex-wrap gap-y-1">
                    {#if isAgentTask}
                        <span class="flow-arrow font-medium">1. 边缘流</span>
                        <span class="flow-arrow text-slate-300 font-bold">2. 按间隔抽帧 ({config.interval}s)</span>
                        <span class="flow-arrow text-purple-400 font-bold">3. VLM Agent 整帧/ROI 识别</span>
                    {:else if isCombinedTask}
                        <span class="flow-arrow font-medium">1. 边缘流</span>
                        <span class="flow-arrow text-amber-400 font-bold">2. 小模型检测 (阈值过滤/ROI)</span>
                        <span class="flow-arrow text-blue-400 font-bold">3. 动态扩图裁切</span>
                        <span class="flow-arrow text-purple-400 font-bold">4. VLM Agent 深度识别</span>
                    {:else}
                        <span class="flow-arrow font-medium">1. 边缘流</span>
                        <span class="flow-arrow text-amber-400 font-bold">2. 小模型实时检测 (阈值过滤/ROI)</span>
                        <span class="flow-arrow text-emerald-400 font-bold">3. 端侧直接产出报警</span>
                    {/if}
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
                        <i class="fa-solid {isEditing ? 'fa-floppy-disk' : 'fa-rocket animate-bounce'} mr-2"></i>{isEditing ? '保存修改' : (isAgentTask ? '一键部署智能体任务' : isCombinedTask ? '一键部署小+大协同任务' : '一键部署小模型任务')}
                    </button>
                {/if}
                <button on:click={backToList} title="返回布控任务列表" class="bg-slate-800 hover:bg-slate-700 text-slate-200 px-3 py-2 rounded-xl text-xs font-bold flex items-center transition-all border border-slate-700 shrink-0">
                    <i class="fa-solid fa-list-ul mr-1.5"></i>任务列表
                </button>
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
                        {#if isEditing}
                            <span class="ml-2 text-[9px] font-bold px-1.5 py-0.5 rounded bg-amber-950/60 text-amber-300 border border-amber-800/60">编辑中 · task_id={config.task_id}</span>
                        {/if}
                    </h3>
                    {#if !isEditing}
                        <!-- 新建任务：任务类型决定后续可配置的参数集（编辑既有任务时类型由设备侧决定，不可切换） -->
                        <div>
                            <label class="block text-[10px] text-slate-400 mb-1">任务类型（决定第三步展示哪些参数）</label>
                            <div class="flex flex-wrap gap-1.5">
                                {#each [{ v: 'smallmodel', t: '小模型任务' }, { v: 'agent', t: '大模型任务' }, { v: 'combined', t: '大小协同任务' }] as m}
                                    <button type="button" on:click={() => changeTaskMode(m.v)}
                                            class="px-3 py-1.5 rounded-lg border text-[11px] font-bold transition-colors {config.taskMode === m.v ? 'bg-indigo-600/20 border-indigo-500/50 text-indigo-200' : 'bg-slate-900 border-slate-800 text-slate-400 hover:border-indigo-500/30'}">{m.t}</button>
                                {/each}
                            </div>
                        </div>
                    {/if}
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

            <!-- 当前编辑对象切换器（仅第③步）：第②步的绘制已与算法解耦，关联在对应关系表里完成 -->
            {#if monitorActive && wizardStep === 3}
                <div class="bg-slate-950/60 p-3 rounded-2xl border border-slate-800">
                    <div class="flex items-center justify-between mb-2">
                        <span class="text-[11px] font-bold text-slate-200 flex items-center"><i class="fa-solid fa-hand-pointer mr-1.5 text-indigo-400"></i>当前编辑对象（{isAgentTask ? '智能体' : '算法'}）</span>
                        <span class="text-[9px] text-slate-500">配置该项详情参数</span>
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

            {#if !monitorActive || wizardStep === 2}
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
                            <button on:click={startNewRoi} title="结束当前区域，下一次点击画布开始绘制新的检测区"
                                    class="px-2.5 py-1 rounded border bg-slate-900 hover:bg-indigo-950 hover:text-indigo-400 border-slate-800 hover:border-indigo-500/30 transition-colors">
                                <i class="fa-solid fa-plus mr-1"></i>绘制新区域
                            </button>
                            <button on:click={clearRoi} title="删除当前正在绘制的检测区" class="px-2.5 py-1 rounded border bg-slate-900 hover:bg-rose-950 hover:text-rose-400 border-slate-800 hover:border-rose-500/30 transition-colors">
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
                                <p class="text-[10px] text-slate-600">加载后自动渲染小模型检测框与已配置检测区</p>
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
                                    <i class="fa-solid fa-draw-polygon mr-1"></i>{drawingRoi ? `正在绘制：${drawingRoi.name}（已 ${currentRoiPoints.length} 点）` : '点击画面开始绘制新的检测区'}
                                </div>
                            {/if}
                            {#if isCombinedTask}
                                <div class="absolute bottom-2 right-2 bg-emerald-600 text-white text-[9px] font-bold px-1.5 py-0.5 rounded shadow flex items-center"><i class="fa-solid fa-crop mr-1"></i> Agent裁图区 (上扩{config.cropUp} / 下{config.cropDown})</div>
                            {:else if isAgentTask}
                                <div class="absolute bottom-2 right-2 bg-purple-600 text-white text-[9px] font-bold px-1.5 py-0.5 rounded shadow flex items-center"><i class="fa-solid fa-brain mr-1"></i> 大模型整帧/ROI 送检（间隔 {config.interval}s）</div>
                            {:else}
                                <div class="absolute bottom-2 right-2 bg-amber-600 text-white text-[9px] font-bold px-1.5 py-0.5 rounded shadow flex items-center"><i class="fa-solid fa-microchip mr-1"></i> 端侧小模型实时检测（无裁图送检）</div>
                            {/if}
                        {/if}
                    </div>
                </div>
                {/if}

                {#if monitorActive && wizardStep === 2}
                    <!-- ROI 区域管理与算法绑定对应关系表：行=检测区（首行为默认「全屏检测」），列=第①步勾选的算法/智能体。
                         这里是【唯一】的关联入口：画布只负责画区域，画完在本表勾选该区域要跑哪些算法。
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
                                        <th class="px-3 py-2 font-medium w-24">区域号 areaId</th>
                                        <th class="px-3 py-2 font-medium">ROI 区域名称 areaName (支持编辑)</th>
                                        <th class="px-3 py-2 font-medium w-24">几何类型 areaType</th>
                                        <th class="px-3 py-2 font-medium">关联绑定的算法 / 智能体 (源自第一步勾选)</th>
                                        <th class="px-3 py-2 font-medium w-28 text-right">操作</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {#each tableRois as roi (roi.id)}
                                        {@const isFull = roi.id === 'full'}
                                        <tr class="border-t border-slate-800 hover:bg-slate-900/40 transition-colors {roi.id === drawingRoiId ? 'bg-indigo-950/30' : ''}">
                                            <td class="px-3 py-3 align-middle">
                                                {#if isFull}
                                                    <i class="fa-solid fa-expand text-slate-600 text-[11px]" title="全屏检测覆盖整个画面，无需叠加预览"></i>
                                                {:else}
                                                    <input type="checkbox" checked={!hiddenRoiIds.has(roi.id)} on:change={() => toggleRoiVisible(roi.id)}
                                                           title="是否在画面上叠加显示该区域（仅预览，不影响部署）"
                                                           class="w-3.5 h-3.5 text-indigo-600 bg-slate-950 border-slate-700 rounded cursor-pointer" />
                                                {/if}
                                            </td>
                                            <td class="px-3 py-3 align-middle">
                                                {#if isFull}
                                                    <span class="text-[11px] font-mono text-slate-400" title="全屏检测的设备侧区域号（默认项，不可改）">{roi.areaId}</span>
                                                {:else}
                                                    <input type="number" min="1" step="1" value={roi.areaId}
                                                           on:change={(e) => { if (!setAreaId(roi.id, e.target.value)) e.target.value = roi.areaId; }}
                                                           title="下发给设备的区域号 areaId：同一任务内必须唯一"
                                                           class="w-16 bg-slate-950 border border-slate-700 text-slate-100 rounded px-2 py-1.5 text-[11px] font-mono focus:border-indigo-500 focus:outline-none" />
                                                {/if}
                                            </td>
                                            <td class="px-3 py-3 align-middle">
                                                {#if isFull}
                                                    <span class="inline-flex items-center gap-1.5 text-[11px] font-bold text-slate-200">
                                                        {roi.name}
                                                        <span class="px-1.5 py-0.5 rounded bg-slate-900 border border-slate-800 text-[9px] font-medium text-slate-500">默认</span>
                                                    </span>
                                                {:else}
                                                    <input type="text" value={roi.name} on:input={(e) => renameRoi(roi.id, e.target.value)} placeholder="检测区名称"
                                                           class="w-44 bg-slate-950 border border-indigo-500/40 text-slate-100 rounded px-2 py-1.5 text-[11px] font-bold focus:border-indigo-500 focus:outline-none" />
                                                {/if}
                                            </td>
                                            <td class="px-3 py-3 align-middle">
                                                {#if isFull}
                                                    <span class="text-[11px] text-slate-400" title="全画面四角多边形 POLYGON">全画面</span>
                                                {:else}
                                                    <span class="text-[11px] text-slate-400" title="下发的 areaType={roi.areaType}">{areaTypeLabel(roi.areaType)}</span>
                                                    <span class="text-[9px] font-mono ml-1 {(roi.points || []).length >= 3 ? 'text-slate-600' : 'text-amber-500'}">{(roi.points || []).length}点</span>
                                                {/if}
                                            </td>
                                            <td class="px-3 py-3 align-middle">
                                                <div class="flex items-center flex-wrap gap-2">
                                                    {#each boundItems as it (it.i)}
                                                        {@const bound = isFull ? ((it.roiId || 'full') === 'full') : (it.roiId === roi.id)}
                                                        <label class="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg border cursor-pointer transition-colors text-[10px] font-bold {bound ? 'bg-indigo-600/20 border-indigo-500/50 text-indigo-200' : 'bg-slate-900 border-slate-800 text-slate-500 hover:border-indigo-500/30'}">
                                                            <input type="checkbox" checked={bound}
                                                                   on:change={(e) => { toggleItemRoi(it.i, roi.id, e.target.checked); if (isFull) e.target.checked = true; }}
                                                                   class="w-3 h-3 text-indigo-600 bg-slate-950 border-slate-700 rounded cursor-pointer" />
                                                            <span class="whitespace-nowrap">{it.kind}: {it.label}{it.note ? `（${it.note}）` : ''}</span>
                                                        </label>
                                                    {:else}
                                                        <span class="text-[10px] text-slate-600">请先在第一步勾选{isAgentTask ? '智能体' : '算法'}</span>
                                                    {/each}
                                                </div>
                                            </td>
                                            <td class="px-3 py-3 align-middle text-right whitespace-nowrap">
                                                {#if isFull}
                                                    <span class="text-[10px] text-slate-600">不可删除</span>
                                                {:else}
                                                    <button type="button" on:click={() => editRoi(roi.id)} title="在画布上续画/修改该检测区"
                                                            class="text-[11px] mr-2 font-medium {roi.id === drawingRoiId ? 'text-indigo-300' : 'text-indigo-500 hover:text-indigo-400'}">
                                                        <i class="fa-solid fa-pen-to-square mr-1"></i>{roi.id === drawingRoiId ? '绘制中' : '继续绘制'}
                                                    </button>
                                                    <button type="button" on:click={() => deleteRoi(roi.id)} title="删除该检测区"
                                                            class="text-[11px] text-rose-500 hover:text-rose-400 font-medium">
                                                        <i class="fa-solid fa-trash-can mr-1"></i>删除
                                                    </button>
                                                {/if}
                                            </td>
                                        </tr>
                                    {/each}
                                </tbody>
                            </table>
                        </div>

                        <p class="text-[9px] text-slate-500 mt-2 leading-relaxed">
                            画布上直接点击即可绘制检测区（无需先选算法），画完自动新增一行；点「绘制新区域」开始下一块，行内「继续绘制」可续画已有区域。
                            区域名可直接改，删除后关联项自动回落到默认「全屏检测」。
                            每个{isAgentTask ? '智能体' : '算法'}同时只能关联一个区域，在别行勾选即改绑到该行；默认全部关联「全屏检测」。
                            {#if !isAgentTask}手动配置时，关联了未画完（少于 3 点）检测区的算法不可部署；套用模板则跳过此限制。{/if}
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

            </div>
            {/if}

            <!-- ③ 详情参数：逐算法 / 逐智能体配置（当前编辑对象见上方切换器）；未激活时保持原空面板样式 -->
            {#if !monitorActive || wizardStep === 3}
            <div class="space-y-4">
                <!-- 不能加 overflow-hidden：它既会裁掉「检测目标」下拉面板，又会让本卡片在父级 flex 列中 min-height 归零被压缩。
                     右上角装饰块改用 rounded-tr-2xl 自行对齐圆角，视觉与原先一致。 -->
                <div class="bg-slate-950 p-5 rounded-2xl border border-slate-800 shadow-lg relative shrink-0">
                    <div class="absolute top-0 right-0 h-16 w-16 bg-indigo-500/5 rounded-bl-full rounded-tr-2xl flex items-center justify-end pr-4 pt-4 pointer-events-none">
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
                    <div class="grid grid-cols-1 {isCombinedTask ? 'xl:grid-cols-3' : ''} gap-4 text-xs items-start">
                        <!-- 1. 前置轻量级算法（当前算法项的时长/目标大小/阈值/目标类型；面板绑顶层 config.*，切项时由 selectAlgorithm 写回/提取） -->
                        <div class="bg-slate-900/60 p-3.5 rounded-xl border border-slate-800/80 space-y-3 h-full">
                            <div class="flex items-center justify-between border-b border-slate-800 pb-2">
                                <span class="font-extrabold text-amber-400 flex items-center"><i class="fa-solid fa-microchip mr-1.5"></i> 1. 前置轻量级算法配置</span>
                                <span class="text-[9px] text-slate-500">端侧低算力常驻运行</span>
                            </div>
                            <!-- 延迟报警(duration) / 报警间隔(cooldownDuration)：单位秒 -->
                            <div class="grid grid-cols-2 gap-3">
                                <div>
                                    <label class="block text-[10px] text-slate-400 mb-1">延迟报警 (单位:秒)</label>
                                    <input type="number" min="0" step="1" bind:value={config.intrusionDuration} class="w-full bg-slate-950 border border-slate-800 text-slate-200 rounded p-1.5 focus:border-amber-500 text-[11px] font-mono text-center" />
                                </div>
                                <div>
                                    <label class="block text-[10px] text-slate-400 mb-1">报警间隔时长 (单位:秒)</label>
                                    <input type="number" min="0" step="1" bind:value={config.alarmInterval} class="w-full bg-slate-950 border border-slate-800 text-slate-200 rounded p-1.5 focus:border-amber-500 text-[11px] font-mono text-center" />
                                </div>
                            </div>
                            <!-- 目标大小：面板填 0~100 百分比，下发折算成设备 targetMin/targetMax 的 0~1；最小 0~100、最大 50~100 -->
                            <div class="grid grid-cols-2 gap-3">
                                <div>
                                    <label class="block text-[10px] text-slate-400 mb-1">最小目标大小 (0-100)</label>
                                    <input type="number" min="0" max="100" step="1" bind:value={config.minTarget} class="w-full bg-slate-950 border border-slate-800 text-amber-400 rounded p-1.5 focus:border-amber-500 text-[11px] font-mono text-center" />
                                </div>
                                <div>
                                    <label class="block text-[10px] text-slate-400 mb-1">最大目标 (50-100)</label>
                                    <input type="number" min="50" max="100" step="1" bind:value={config.maxTarget} class="w-full bg-slate-950 border border-slate-800 text-amber-400 rounded p-1.5 focus:border-amber-500 text-[11px] font-mono text-center" />
                                </div>
                            </div>
                            <!-- 设备侧一条规则只有一个 threshold：按「主目标」(已勾选的第一个)取对应阈值字段 -->
                            <div>
                                <div class="flex justify-between items-center mb-1 text-[10px]"><label class="text-slate-400">检测阈值</label><span class="font-mono text-amber-400">{config[threshKey]}</span></div>
                                <input type="range" min="0.1" max="0.9" step="0.01" value={config[threshKey]} on:input={(e) => setThresh(e.target.value)} class="w-full h-1 bg-slate-800 rounded-lg appearance-none cursor-pointer accent-amber-500" />
                            </div>
                            <!-- 检测目标：多目标勾选（设备 targetTypes）；首个勾选项即主目标，决定上面用哪条阈值 -->
                            <div>
                                <label class="block text-[10px] text-slate-400 mb-1">检测目标（可多选）</label>
                                <!-- relative 只包住「按钮 + 下拉面板」，使向上展开(bottom-full)时紧贴按钮，不被 label/说明文字顶开 -->
                                <div class="relative">
                                    <!-- 多选结果用可换行的标签块展示：目标名较长(如「人员 (人体检测)」)，单行 truncate 会看不全 -->
                                    <button type="button" on:click={toggleTargetPicker}
                                            title={selectedTargets.map(targetTypeLabel).join('、')}
                                            class="w-full flex items-start justify-between gap-2 bg-slate-950 border border-slate-800 hover:border-amber-500/50 text-slate-200 rounded p-1.5 text-[11px] text-left transition-colors">
                                        <span class="flex flex-wrap gap-1 min-w-0">
                                            {#each selectedTargets as tt}
                                                <span class="px-1.5 py-0.5 rounded bg-amber-500/10 text-amber-300 border border-amber-500/30 leading-tight">{targetTypeLabel(tt)}</span>
                                            {:else}
                                                <span class="text-slate-500 py-0.5 leading-tight">请选择检测目标</span>
                                            {/each}
                                        </span>
                                        <i class="fa-solid fa-chevron-down text-[9px] text-slate-500 shrink-0 mt-1 transition-transform {targetPickerOpen ? 'rotate-180' : ''}"></i>
                                    </button>
                                    {#if targetPickerOpen}
                                        <!-- 透明遮罩：点击面板外即收起下拉 -->
                                        <button type="button" aria-label="关闭检测目标选择" class="fixed inset-0 z-30 cursor-default" on:click={() => (targetPickerOpen = false)}></button>
                                        <!-- 方向与高度由 toggleTargetPicker 实时计算，选项多时面板内部滚动，不再被父容器裁切 -->
                                        <div class="absolute left-0 w-full z-40 {targetPickerUp ? 'bottom-full mb-1' : 'top-full mt-1'} bg-slate-950 border border-slate-700 rounded shadow-xl shadow-black/60 p-1 overflow-y-auto overscroll-contain"
                                             style="max-height:{targetPickerMaxH}px">
                                            {#each targetTypeOptions as tt}
                                                <label class="flex items-center gap-2 px-2 py-1.5 rounded cursor-pointer hover:bg-slate-900 text-[11px] {selectedTargets.includes(tt) ? 'text-amber-400 font-bold' : 'text-slate-300'}">
                                                    <input type="checkbox" checked={selectedTargets.includes(tt)}
                                                           on:change={(e) => toggleTargetType(tt, e.target.checked)}
                                                           class="w-3 h-3 shrink-0 text-amber-500 bg-slate-950 border-slate-700 rounded cursor-pointer" />
                                                    <span class="leading-tight">{targetTypeLabel(tt)}</span>
                                                    <span class="ml-auto shrink-0 text-[9px] font-mono text-slate-600">{tt}</span>
                                                </label>
                                            {/each}
                                        </div>
                                    {/if}
                                </div>
                                <p class="text-[9px] text-slate-500 mt-1">首个勾选目标为主目标（决定上方检测阈值取用的字段）。已选 {selectedTargets.length} / 共 {targetTypeOptions.length} 个目标。</p>
                            </div>
                        </div>

                        {#if isCombinedTask}
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

                        <!-- 3. 后置 Agent：小+大任务的「二次大模型」——下拉取设备智能体目录(availableAgents)，全量参数写入当前算法项 -->
                        <div class="bg-slate-900/60 p-3.5 rounded-xl border border-slate-800/80 space-y-3 h-full">
                            <div class="flex items-center justify-between border-b border-slate-800 pb-2">
                                <span class="font-extrabold text-indigo-400 flex items-center"><i class="fa-solid fa-brain mr-1.5"></i> 3. 级联后置多模态 Agent</span>
                                <span class="text-[9px] text-indigo-500/80 font-bold">本算法命中后的二次复核</span>
                            </div>
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
                            <!-- 智能体标识：event_id 为设备侧唯一 ID（只读）；event_tag 为报警名称（可改，随报警下发） -->
                            <div class="grid grid-cols-2 gap-3">
                                <div>
                                    <label class="block text-[10px] text-slate-400 mb-1">智能体 ID (event_id)</label>
                                    <input type="text" value={activeAlgorithm?.agent_id || config.agentType || ''} readonly
                                           class="w-full bg-slate-950/60 border border-slate-800 text-slate-500 rounded p-1.5 text-[11px] font-mono cursor-not-allowed" />
                                </div>
                                <div>
                                    <label class="block text-[10px] text-slate-400 mb-1">报警名称 (event_tag)</label>
                                    <input type="text" value={activeAlgorithm?.event_tag || ''} placeholder="如：跌倒检测"
                                           on:input={(e) => setAlgoAgentField(config.activeAlgorithmIndex || 0, 'event_tag', e.target.value)}
                                           class="w-full bg-slate-950 border border-slate-800 text-slate-200 rounded p-1.5 focus:border-indigo-500 text-[11px]" />
                                </div>
                            </div>
                            <!-- 报警类型：描述型(freeform)输出自然语言描述、走关键词过滤；判断型(yesno)输出是/否、走报警条件 -->
                            <div>
                                <label class="block text-[10px] text-slate-400 mb-1">报警类型 (alarm_type)</label>
                                <select value={activeAlgorithm?.alarm_type || 'freeform'}
                                        on:change={(e) => setAlgoAgentField(config.activeAlgorithmIndex || 0, 'alarm_type', e.target.value)}
                                        class="w-full bg-slate-950 border border-slate-800 text-slate-200 rounded p-1.5 focus:border-indigo-500 text-[11px]">
                                    <option value="freeform">描述型（freeform）· 输出自然语言描述</option>
                                    <option value="yesno">判断型（yesno）· 输出是 / 否</option>
                                </select>
                            </div>
                            <div>
                                <div class="flex justify-between items-center mb-1"><label class="text-[10px] text-slate-400">智能体大模型视觉推理 Prompt 策略</label><span class="text-[9px] text-slate-600">Markdown语义控制</span></div>
                                <textarea bind:value={config.prompt} rows="5" class="w-full text-[11px] font-mono text-slate-300 bg-slate-950 border border-slate-800 focus:border-indigo-500 rounded p-2 leading-relaxed" placeholder="等待指令注入..."></textarea>
                            </div>
                            {#if (activeAlgorithm?.alarm_type || 'freeform') === 'freeform'}
                                <!-- 描述型：关键词过滤（filter_enable/filter_keywords），命中关键词才上报 -->
                                <div class="pt-1 border-t border-slate-800/60">
                                    <div class="flex items-center justify-between">
                                        <label class="text-[10px] text-slate-400 flex items-center"><i class="fa-solid fa-filter mr-1.5 text-indigo-400"></i>条件判断（属性分析）</label>
                                        <input type="checkbox" checked={!!activeAlgorithm?.filter_enable}
                                               on:change={(e) => setAlgoAgentField(config.activeAlgorithmIndex || 0, 'filter_enable', e.target.checked)}
                                               class="w-3.5 h-3.5 text-indigo-600 bg-slate-950 border-slate-800 rounded cursor-pointer" />
                                    </div>
                                    {#if activeAlgorithm?.filter_enable}
                                        <input type="text" value={activeAlgorithm?.filter_keywords || ''}
                                               on:input={(e) => setAlgoAgentField(config.activeAlgorithmIndex || 0, 'filter_keywords', e.target.value)}
                                               placeholder="过滤条件关键词，例如：红色上衣 / 未戴安全帽"
                                               class="mt-2 w-full bg-slate-950 border border-slate-800 text-slate-200 rounded p-2 focus:border-indigo-500 text-[11px]" />
                                    {/if}
                                    <p class="text-[9px] text-slate-500 mt-1">仅描述型生效：大模型描述命中关键词才上报告警。</p>
                                </div>
                            {:else}
                                <!-- 判断型(yesno)：报警条件 alarm_condition —— 勾选=仅「是」报警(only_yes)，不勾=是/否都报警(none) -->
                                <div class="pt-1 border-t border-slate-800/60">
                                    <label class="flex items-center justify-between cursor-pointer">
                                        <span class="text-[10px] text-slate-400 flex items-center"><i class="fa-solid fa-circle-check mr-1.5 text-indigo-400"></i>仅在判定为「是」时报警</span>
                                        <input type="checkbox" checked={(activeAlgorithm?.alarm_condition || '') === 'only_yes'}
                                               on:change={(e) => setAlgoAgentField(config.activeAlgorithmIndex || 0, 'alarm_condition', e.target.checked ? 'only_yes' : 'none')}
                                               class="w-3.5 h-3.5 text-indigo-600 bg-slate-950 border-slate-800 rounded cursor-pointer" />
                                    </label>
                                    <p class="text-[9px] text-slate-500 mt-1">不勾选则是 / 否两种判定都会上报（alarm_condition=none）。</p>
                                </div>
                            {/if}
                        </div>
                        {/if}
                    </div>
                    {/if}
                </div>
            </div>
            {/if}
        </div>
        {/if}
    </div>
</div>

<style>
    .flow-arrow::after { content: "➔"; margin: 0 8px; color: #475569; }
    .flow-arrow:last-child::after { content: ""; }
</style>
