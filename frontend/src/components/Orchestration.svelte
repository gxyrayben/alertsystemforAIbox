<script>
    // 任务编排：把设备已有的算法/智能体告警，用画布串联成新的业务预警。
    // 交互参考「串并校验编排中心」：左侧分类元件库（可搜索）拖入画布 →
    // 按住节点右侧【输出端】拖到目标节点左侧【输入端】连线（带跟随临时线）→
    // 点击连线可断开；右侧「节点参数配置 / 规则 JSON」双页签；支持模板、自动排布、试运行。
    import { onMount, onDestroy } from 'svelte';
    import { API_BASE, apiGet, apiPost, apiPut, apiDelete } from '../lib/api.js';
    import { devices, selectedDevice, showToast } from '../lib/controlStore.js';

    let orchList = [];
    let bizAlarms = [];
    let loading = false;
    let mainTab = 'cards';             // cards / alarms

    // ── 元件库数据（来自当前设备）──
    let taskOptions = [];
    let algoOptions = [];
    let agentOptions = [];
    let channelOptions = [];
    let alertStats = {};              // alertType -> 近24h 条数（标注元件是否真在产生告警）
    let paletteSearch = '';
    // 校验（诊断）
    let diagnoseResult = null;
    let diagnosing = false;
    let showDiagnose = false;

    // ── 节点元数据（badge/配色/分类/默认参数）──
    const CATALOG = {
        task:   { badge: '任务', color: 'sky',     category: 'source', params: () => ({ task_id: '', task_name: '', channelid: '' }) },
        algo:   { badge: '算法', color: 'amber',   category: 'source', params: () => ({ kind: 'warehouse', event_type: '', event_name: '', event_id: '', event_tag: '', channelid: '' }) },
        logic:  { badge: '逻辑', color: 'violet',  category: 'logic',  params: () => ({ logic_type: 'logic_and', ...LOGIC_OPS[0].params }) },
        llm:    { badge: 'VLM',  color: 'emerald', category: 'ai',     params: () => ({ ...VLM_OP.params }) },
        output: { badge: '输出', color: 'rose',    category: 'output', params: () => ({ ...OUTPUT_OP.params }) },
    };
    const logicOpByKey = (key) => LOGIC_OPS.find((o) => o.key === key) || LOGIC_OPS[0];

    // ── 10 类产品化逻辑算子（参数/文案 1:1 对齐设计表）──
    // unwired=true：需要额外数据源（告警生命周期 / BBox 坐标 / 防区拓扑），运行时暂未接入，评估时按放行处理
    const LOGIC_OPS = [
        { key: 'logic_and', badge: 'AND', title: '多路并联与校验', subtitle: '同一时间窗内所有分支全部触发（同一窗口只报警一次）',
          desc: '多条件同时具备才报警（并联与门）',
          params: { windowType: '滚动时间窗 (Tumbling Window)', windowSec: 15, watermarkToleranceSec: 3 } },
        { key: 'logic_vote', badge: 'K/N', title: 'K-of-N 权重投票门', subtitle: '3路风险源中任意命中 ≥2路（或积分≥60）',
          desc: '多路互补覆盖 / 轻微违章叠加升级',
          params: { voteMode: '至少命中 K 路 (K-of-N Majority)', minRequiredBranches: 2, windowSec: 30,
                    weightConfig: '抽烟=40分, 离岗少员=35分, 未戴安全帽=30分 (满60分触发)' } },
        { key: 'logic_not', badge: 'A!B', title: '互斥抑制校验 (A AND NOT B)', subtitle: '主事件A触发，且前后10s内无抑制事件B',
          desc: '用合规状态算法给违规告警做白名单豁免降噪',
          params: { primaryStreamDesc: '主流A：违规/闯入告警', inhibitorStreamDesc: '抑制流B：合法豁免信号',
                    preLookbackSec: 10, postWaitSec: 5, onSuppressedAction: '记录为「已豁免抑制日志」不产生工单' } },
        { key: 'logic_seq', badge: 'A→B', title: '时序先后跟随算子', subtitle: 'A发生后等待 [180s~300s] 检测到 B',
          desc: '避免刚入位就被误判（时序状态机）',
          params: { stepADesc: '前置状态A（先发事件）', stepBDesc: '后置状态B（后发事件）',
                    minWaitSec: 180, maxWindowSec: 300, continuityPolicy: '宽松跟随 (忽略中间无关事件)' } },
        { key: 'logic_duration', badge: '驻留', title: '状态持续驻留算子 (HOLD)', subtitle: '异常状态连续保持 ≥60s（容忍3s遮挡闪断）',
          desc: '解决瞬时假离岗/误报抖动',
          params: { holdDurationSec: 60, maxHeartbeatGapSec: 3,
                    note: '解决人员短暂弯腰被遮挡导致的「假离岗」或车辆借道掉头误报' } },
        { key: 'logic_autoclose', badge: '消警', title: '状态恢复自动消警 (AUTO-CLR)', subtitle: '检测到恢复事件(复岗/插枪/摆好围挡)自动销单',
          desc: '告警全生命周期闭环', unwired: true,
          params: { recoveryCondition: '收到正向恢复事件 (在岗人数≥1 / 围挡已摆好 / 充电枪已插上)',
                    recoveryConfirmSec: 10, autoCloseTimeoutMin: 60, notifyOnResolve: true } },
        { key: 'logic_iou', badge: 'IoU', title: '同画面目标框 IoU/包含绑定', subtitle: '校验两算法BBox重叠度 IoU≥0.45 或父子框包含',
          desc: '确认多算法命中的是同一个目标', unwired: true,
          params: { spatialMatchMode: '框包含或相交 (父框:人体闯入 ⊃ 子框:未戴安全帽/抽烟)', iouThreshold: 0.45,
                    maxTimeDiffMs: 1500, sameCameraRequired: true, coordinateNormalize: '归一化相对坐标 [0~1] (兼容不同分辨率)' } },
        { key: 'logic_cross_cam', badge: '跨镜', title: '跨摄像头同防区/车位拓扑绑定', subtitle: '按物理防区Tag关联多路摄像头',
          desc: '不同角度相机按防区精准配对', unwired: true,
          params: { topologyJoinKey: '物理防区/车位绑定键 (zoneTag / berthId)', boundDevicesGroup: '吊装防区#1: [设备36, 围挡2, 牵引绳3]',
                    enableReIdFeature: false, reIdSimilarityThreshold: 0.75 } },
        { key: 'logic_debounce', badge: '防抖', title: '滑动窗口频次防抖聚合', subtitle: '20s内连续触发 ≥3次 聚合成1条',
          desc: '消除按帧推理的告警风暴刷屏',
          params: { windowSec: 20, minHitCount: 3, mergeSnapshotPolicy: '抽样3张代表图 (首帧 + 最高置信度帧 + 尾帧)',
                    suppressDuplicateSec: 120 } },
        { key: 'logic_schedule', badge: '排班', title: '排班日历与电子作业票门控', subtitle: '校验当前时段与是否有合法作业票',
          desc: '让算法懂业务排班与施工许可',
          params: { scheduleMode: '全天布控，但关联电子作业票白名单校验', activeTimeRange: '00:00-23:59',
                    workPermitCheck: '查询安全生产系统：若存在生效中《作业票》则降级为提示', holidayOverride: true } },
    ];
    const VLM_OP = {
        badge: 'VLM', title: '多模态大模型 (VLM) 二次复核', subtitle: '拼接上游抓拍图，按 Prompt 语义终审过滤误报',
        params: { model: 'Vision-Agent-Pro (支持多图时序对比)', imageStitchMode: '自动拼接上游各分支抓拍图 + 绘制红框高亮',
                  prompt: '请综合核验拼接图：确认是否为真实违规作业，排除阴影或假人误报。仅回答「是」或「否」。',
                  passThreshold: 0.85, fallbackOnTimeout: '超时3秒默认放行告警 (安全兜底)' },
    };
    const OUTPUT_OP = {
        badge: '输出', title: '生成二次复合预警单 & 联动', subtitle: '合成证据链 + 冷却锁 + 多通道触达',
        params: { ruleName: '业务预警', output_id: '', cooldownSec: 300,
                  cooldownScope: '按 [规则ID + 通道设备ID] 冷却静默', actions: '① 生成多图证据链卡片 ② 现场音柱语音驱逐 ③ 推送安全员企微' },
    };

    // 参数元数据（Label / 控件类型 / 下拉选项 / 废弃键）统一在 lib/orchestrationSchema.js 维护，
    // 避免之前 5 张并行 Map 同一 key 多处维护导致的漂移（severity 曾在表单里残留）。
    import { PARAM_HIDDEN, fieldMeta, normalizeConfig, visibleParams } from '../lib/orchestrationSchema.js';
    import ParamField from './orchestration/ParamField.svelte';

    const COLOR_CLASSES = {
        sky:     { border: 'border-sky-500/40',     head: 'bg-sky-500/10',     text: 'text-sky-300',     dot: 'bg-sky-400' },
        amber:   { border: 'border-amber-500/40',   head: 'bg-amber-500/10',   text: 'text-amber-300',   dot: 'bg-amber-400' },
        violet:  { border: 'border-violet-500/40',  head: 'bg-violet-500/10',  text: 'text-violet-300',  dot: 'bg-violet-400' },
        emerald: { border: 'border-emerald-500/40', head: 'bg-emerald-500/10', text: 'text-emerald-300', dot: 'bg-emerald-400' },
        rose:    { border: 'border-rose-500/40',    head: 'bg-rose-500/10',    text: 'text-rose-300',    dot: 'bg-rose-400' },
    };
    const cc = (color) => COLOR_CLASSES[color] || COLOR_CLASSES.sky;

    const NODE_W = 236;
    const PORT_Y = 46;                 // 端口相对节点的纵向锚点
    const CANVAS_W = 2600, CANVAS_H = 1600;

    onMount(async () => { await loadList(); await loadAlarms(); });
    onDestroy(() => {
        window.removeEventListener('pointermove', onWindowPointerMove);
        window.removeEventListener('pointerup', onWindowPointerUp);
    });

    async function loadList() {
        loading = true;
        try { orchList = (await apiGet('/orchestration'))?.items || []; }
        catch (e) { console.error(e); } finally { loading = false; }
    }
    async function loadAlarms() {
        try { bizAlarms = (await apiGet('/orchestration/alarms?limit=100'))?.items || []; }
        catch (e) { console.error(e); }
    }

    // 元件库：设备任务 / 算法仓算法 / 智能体 / 通道
    async function loadPalette() {
        taskOptions = []; algoOptions = []; agentOptions = []; channelOptions = []; alertStats = {};
        const dev = $selectedDevice;
        if (!dev?.id) return;
        // 近 24h 各算法告警条数：用于标注「这个算法到底有没有在产生告警」
        try {
            const s = await apiGet('/orchestration/alert-types?hours=24');
            (s?.items || []).forEach((x) => { alertStats[x.alertType] = x.count; });
        } catch (e) { console.error(e); }
        try {
            const tasks = JSON.parse(dev.device_tasks || '[]');
            taskOptions = (Array.isArray(tasks) ? tasks : []).map((t) => ({
                task_id: String(t.task_id ?? ''), task_name: t.task_name || t.task_id || '未命名任务',
                task_type: t.task_type || '',
                // 关联通道（只读展示）取值：detail.channel_device_id 或摘要里的 camera_device_id
                detail: t.detail || {},
                channel_device_id: String(t.detail?.channel_device_id ?? t.camera_device_id ?? ''),
                camera_device_name: t.camera_device_name || '',
            })).filter((t) => t.task_id);
        } catch (e) { console.error(e); }
        try { algoOptions = (await apiGet(`/devices/${dev.id}/algorithms?refresh=false`))?.algorithms || []; }
        catch (e) { console.error(e); }
        try { agentOptions = (await apiGet(`/devices/${dev.id}/agents?refresh=false`))?.agents || []; }
        catch (e) { console.error(e); }
        try {
            const raw = JSON.parse(dev.channels || '[]');
            const seen = new Set();
            channelOptions = (Array.isArray(raw) ? raw : []).map((c) => ({
                id: String(c?.device_id ?? ''), name: String(c?.device_name ?? ''),
            })).filter((c) => c.id && c.name && !seen.has(c.id) && seen.add(c.id));
        } catch (e) { console.error(e); }
    }

    // ── 编辑器状态 ──
    let editorOpen = false;
    let editingId = null;
    let editorName = '';
    let editorDeviceId = '';
    let editorEnabled = true;      // 新建/编辑一律默认启用（可在工具栏关掉）
    let nodes = [];
    let edges = [];
    let selectedNodeId = null;
    let wiringFromId = null;
    let tempEdgePath = '';
    let rightTab = 'props';
    let saving = false;
    let canvasRef = null;
    let dragging = null;               // {id, dx, dy}
    let runBanner = null;              // 试运行结果横幅

    // 历史配置归一化（剔除已废弃键 + 改写防区粒度旧值）统一由 schema 模块提供
    const normalizeLegacyConfig = (n) => ({ ...n, config: normalizeConfig(n.config) });

    function openEditor(orch) {
        if (orch) {
            editingId = orch.id;
            editorName = orch.name;
            editorDeviceId = orch.device_id || '';
            nodes = (orch.nodes || []).map((n) => normalizeLegacyConfig({ ...n, config: { ...(n.config || {}) } }));
            edges = (orch.edges || []).map((e, i) => ({ id: e.id || `e_${i}`, source: e.source, target: e.target }));
            editorEnabled = true;      // 编辑保存后默认开启
        } else {
            editingId = null; editorName = ''; editorDeviceId = $selectedDevice?.device_id || '';
            nodes = []; edges = [];
            editorEnabled = true;      // 新建默认开启
        }
        selectedNodeId = nodes[0]?.id || null;
        wiringFromId = null; tempEdgePath = ''; rightTab = 'props'; runBanner = null;
        editorOpen = true;
    }
    function closeEditor() { editorOpen = false; }

    let seq = 0;
    const newId = (t) => `${t}_${Date.now().toString(36)}${(seq++).toString(36)}`;
    const nodeById = (id) => nodes.find((n) => n.id === id);

    function addNode(type, x, y, preset = {}) {
        const meta = CATALOG[type] || CATALOG.algo;
        const node = { id: newId(type), type, x: Math.max(8, x), y: Math.max(8, y), config: { ...meta.params(), ...preset } };
        nodes = [...nodes, node];
        selectedNodeId = node.id;
        return node;
    }

    // ── 元件库 → 画布 ──
    function onPaletteDragStart(ev, payload) {
        ev.dataTransfer.setData('text/plain', JSON.stringify(payload));
        ev.dataTransfer.effectAllowed = 'copy';
    }
    function onCanvasDrop(ev) {
        ev.preventDefault();
        let payload = null;
        try { payload = JSON.parse(ev.dataTransfer.getData('text/plain') || 'null'); } catch (e) { payload = null; }
        if (!payload?.type) return;
        const rect = canvasRef.getBoundingClientRect();
        const x = ev.clientX - rect.left - NODE_W / 2;
        const y = ev.clientY - rect.top - 30;
        addNode(payload.type, x, y, payload.config || {});
        showToast(`已添加元件：${nodeTitle(payload.type, payload.config || {})}`, 'info');
    }
    function onCanvasDragOver(ev) { ev.preventDefault(); }

    // ── 节点拖动 + 端口拖拽连线（pointer 事件，窗口级监听） ──
    function onNodePointerDown(ev, id) {
        if (ev.button !== 0) return;
        if (ev.target?.dataset?.port) return;          // 点在端口上 → 走连线逻辑
        if (ev.target?.closest?.('[data-del]')) return;
        const node = nodeById(id);
        const rect = canvasRef.getBoundingClientRect();
        dragging = { id, dx: ev.clientX - rect.left - node.x, dy: ev.clientY - rect.top - node.y };
        selectedNodeId = id;
        window.addEventListener('pointermove', onWindowPointerMove);
        window.addEventListener('pointerup', onWindowPointerUp);
        ev.preventDefault();
    }
    function onWindowPointerMove(ev) {
        const rect = canvasRef?.getBoundingClientRect();
        if (!rect) return;
        if (dragging) {
            const nodes2 = nodes.map((n) => n.id === dragging.id
                ? { ...n, x: Math.max(0, ev.clientX - rect.left - dragging.dx), y: Math.max(0, ev.clientY - rect.top - dragging.dy) }
                : n);
            nodes = nodes2;
        } else if (wiringFromId) {
            const from = nodeById(wiringFromId);
            if (from) {
                const x1 = from.x + NODE_W, y1 = from.y + PORT_Y;
                const x2 = ev.clientX - rect.left, y2 = ev.clientY - rect.top;
                const dx = Math.max(Math.abs(x2 - x1) * 0.5, 40);
                tempEdgePath = `M ${x1} ${y1} C ${x1 + dx} ${y1}, ${x2 - dx} ${y2}, ${x2} ${y2}`;
            }
        }
    }
    function onWindowPointerUp() {
        if (dragging) { dragging = null; updateDsl(); }
        if (wiringFromId) { wiringFromId = null; tempEdgePath = ''; }
        window.removeEventListener('pointermove', onWindowPointerMove);
        window.removeEventListener('pointerup', onWindowPointerUp);
    }
    function onPortDown(ev, id) {
        ev.stopPropagation();
        wiringFromId = id;
        window.addEventListener('pointermove', onWindowPointerMove);
        window.addEventListener('pointerup', onWindowPointerUp);
    }
    function onPortUp(ev, id) {
        ev.stopPropagation();
        if (wiringFromId && wiringFromId !== id) {
            if (!edges.some((e) => e.source === wiringFromId && e.target === id)) {
                edges = [...edges, { id: `e_${Date.now().toString(36)}`, source: wiringFromId, target: id }];
                updateDsl();
                showToast('已建立连线。', 'info');
            }
        }
        wiringFromId = null; tempEdgePath = '';
    }
    function deleteEdge(id) {
        edges = edges.filter((e) => e.id !== id);
        updateDsl();
        showToast('已断开该连线。', 'info');
    }
    function deleteNode(id) {
        nodes = nodes.filter((n) => n.id !== id);
        edges = edges.filter((e) => e.source !== id && e.target !== id);
        if (selectedNodeId === id) selectedNodeId = nodes[0]?.id || null;
        updateDsl();
    }
    function clearCanvas() {
        if (!nodes.length) return;
        if (!confirm('确定清空画布上的全部节点与连线？')) return;
        nodes = []; edges = []; selectedNodeId = null; updateDsl();
        showToast('画布已清空。', 'info');
    }
    function autoLayout() {
        // 列顺序：任务 → 算法 → 逻辑 → VLM复核 → 输出
        const COL_X = [40, 360, 680, 1000, 1320];
        const ROW_H = 140;
        const columns = [
            nodes.filter((n) => n.type === 'task'),
            nodes.filter((n) => n.type === 'algo'),
            nodes.filter((n) => n.type === 'logic'),
            nodes.filter((n) => n.type === 'llm'),
            nodes.filter((n) => n.type === 'output'),
        ];
        columns.forEach((col, ci) => {
            // 同列内保持用户原有上下顺序，纵向均匀铺开
            const ordered = [...col].sort((a, b) => a.y - b.y);
            const totalH = (ordered.length - 1) * ROW_H;
            const startY = Math.max(50, 260 - totalH / 2);
            ordered.forEach((n, i) => {
                const t = nodeById(n.id);
                if (!t) return;
                t.x = COL_X[ci];
                t.y = startY + i * ROW_H;
            });
        });
        nodes = [...nodes];
        showToast('已按「任务 → 算法 → 逻辑 → 复核 → 输出」自动排布。', 'info');
    }

    // ── 节点展示信息 ──
    function nodeTitle(type, cfg) {
        cfg = cfg || {};
        if (type === 'task') return '任务元件';
        if (type === 'algo') return (cfg.kind === 'agent' ? (cfg.event_tag || cfg.event_id) : (cfg.event_name || cfg.event_type)) || '算法元件';
        if (type === 'logic') return logicOpByKey(cfg.logic_type).title;
        if (type === 'llm') return VLM_OP.title;
        if (type === 'output') return cfg.ruleName || cfg.name || '输出元件';
        return type;
    }
    function nodeSubtitle(node) {
        const c = node.config || {};
        if (node.type === 'task') {
            if (!c.task_id) return '未选择任务（请在右侧配置）';
            const ch = taskChannelText(c.task_id);
            return `任务：${c.task_name || c.task_id}${ch ? ` · 分析通道：${ch}` : ''}`;
        }
        if (node.type === 'algo') {
            const kind = c.kind === 'agent' ? '智能体算法' : '算法仓算法';
            const key = c.kind === 'agent' ? c.event_id : c.event_type;
            return key ? `${kind} · ${key}` : '未选择算法（请在右侧配置）';
        }
        if (node.type === 'logic') {
            const op = logicOpByKey(c.logic_type);
            const wt = (c.windowType || '').includes('会话') ? '会话窗' : ((c.windowType || '').includes('滚动') ? '滚动窗' : '');
            if (c.logic_type === 'logic_and') return `全部命中 · ${wt} ${c.windowSec ?? 15}s（同窗只发一次）`;
            if (c.logic_type === 'logic_vote') return `至少命中 ${c.minRequiredBranches ?? 2} 路（${wt || '滚动窗'} ${c.windowSec ?? 30}s）`;
            if (c.logic_type === 'logic_seq') return `A 后 ${c.minWaitSec ?? 0}s ~ ${c.maxWindowSec ?? 300}s 内出现 B`;
            if (c.logic_type === 'logic_not') return `A 命中且 [−${c.preLookbackSec ?? 10}s, +${c.postWaitSec ?? 5}s] 内无 B`;
            if (c.logic_type === 'logic_duration') return `持续 ≥${c.holdDurationSec ?? 60}s（闪断容忍 ${c.maxHeartbeatGapSec ?? 3}s）`;
            if (c.logic_type === 'logic_debounce') return `${c.windowSec ?? 20}s 内累计 ≥${c.minHitCount ?? 3} 次才放行`;
            if (c.logic_type === 'logic_schedule') return `生效时段 ${c.activeTimeRange || '全天'}`;
            return op.subtitle;
        }
        if (node.type === 'llm') return c.model || VLM_OP.subtitle;
        if (node.type === 'output') return c.output_id ? `输出ID ${c.output_id}` : '未设置输出ID（请在右侧配置）';
        return '';
    }
    function nodeBadge(node) {
        if (node.type === 'logic') return logicOpByKey(node.config?.logic_type).badge;
        return CATALOG[node.type]?.badge || node.type;
    }
    function nodeColor(node) {
        if (node.type === 'logic') {
            const k = node.config?.logic_type || '';
            if (k === 'logic_not') return 'amber';
            if (k === 'logic_seq' || k === 'logic_duration') return 'sky';
        }
        return CATALOG[node.type]?.color || 'sky';
    }
    function isUnwired(node) { return node.type === 'logic' && !!logicOpByKey(node.config?.logic_type).unwired; }
    // 端口：任务元件是纯数据源（无输入）；算法元件支持【输入 + 输出】（输入=前置门控）；输出元件无输出
    function showInputPort(node) { return node.type !== 'task'; }
    function showOutputPort(node) { return node.type !== 'output'; }
    function inputPortHint(node) {
        if (node.type === 'algo') return '输入端：前置门控（上游命中后本算法才计入）';
        if (node.type === 'logic') return '输入端：接入上游事件流';
        if (node.type === 'llm') return '输入端：待复核的候选事件';
        return '输入端：生成业务预警的上游事件';
    }
    function taskById(taskId) { return taskOptions.find((t) => t.task_id === String(taskId)); }
    /** 任务元件「关联通道」只读展示：取任务 detail.channel_device_id 并映射成通道名 */
    function taskChannelText(taskId) {
        const t = taskById(taskId);
        const d = t?.detail || {};
        const cid = String(d.channel_device_id ?? t?.channel_device_id ?? '');
        if (!cid) return '';
        const ch = channelOptions.find((c) => c.id === cid);
        return ch ? `${ch.name}（通道 ${cid}）` : `通道 ${cid}`;
    }
    function nodeChannelBadge(node) {
        const cid = String(node.config?.channelid || '');
        if (!cid) return '';
        const ch = channelOptions.find((c) => c.id === cid);
        return ch ? `${ch.name}` : cid;
    }

    // ── 连线几何（响应式派生）──
    // 关键坑：Svelte 的依赖分析只认「语句里直接出现的变量名」，不跟进函数体。
    //   · d={edgeD(e)}            → 依赖 [edgeD, e]，拖动节点时不会重算
    //   · nodeById(e.source)      → 依赖 [nodeById, edges]，同样漏掉 nodes
    // 所以这里必须在派生语句内 **直接引用 nodes**，拖动时连线才会实时跟随。
    $: edgeGeom = edges.map((e) => {
        const s = nodes.find((n) => n.id === e.source);
        const t = nodes.find((n) => n.id === e.target);
        if (!s || !t) return null;
        const x1 = s.x + NODE_W, y1 = s.y + PORT_Y;
        const x2 = t.x, y2 = t.y + PORT_Y;
        const dx = Math.max(Math.abs(x2 - x1) * 0.5, 40);
        return {
            id: e.id,
            d: `M ${x1} ${y1} C ${x1 + dx} ${y1}, ${x2 - dx} ${y2}, ${x2} ${y2}`,
            mx: (x1 + x2) / 2,
            my: (y1 + y2) / 2,
        };
    }).filter(Boolean);

    // ── 元件库分组 ──
    $: paletteGroups = (() => {
        const kw = (paletteSearch || '').trim().toLowerCase();
        const hit = (s) => !kw || String(s || '').toLowerCase().includes(kw);
        const groups = [];
        // ① 任务元件：只有 1 个通用元件（属性：关联任务 + 只读的关联通道）
        if (hit('任务') || hit('task')) {
            groups.push({ title: '① 任务元件', dot: 'bg-sky-400', hint: '1 个通用元件', items: [
                { type: 'task', icon: '务', name: '任务元件', tag: '任务', tagKind: 'sky',
                  desc: '关联设备布控任务；关联通道自动带出',
                  config: { task_id: '', task_name: '', channelid: '' } },
            ]});
        }

        // ② 算法元件：每个算法一个元件（算法仓 + 智能体）
        const algoItems = [
            ...algoOptions.filter((a) => hit(a.eventName) || hit(a.eventType)).map((a) => ({
                type: 'algo', icon: '算', name: a.eventName || a.eventType, tag: '算法仓', tagKind: 'amber',
                desc: `${a.algoCabinName || '算法仓'} · ${a.eventType}${(a.targetTypes || []).length ? ` · ${a.targetTypes.join('/')}` : ''}`,
                hits: alertStats[a.eventType] || 0, hitsKey: a.eventType,
                config: { kind: 'warehouse', event_type: a.eventType, event_name: a.eventName || '', channelid: '' },
            })),
            ...agentOptions.filter((g) => hit(g.event_tag) || hit(g.event_id)).map((g) => ({
                type: 'algo', icon: '智', name: g.event_tag || g.event_id, tag: '智能体', tagKind: 'violet',
                desc: `智能体算法 · event_id ${g.event_id}`,
                hits: alertStats[String(g.event_id)] || 0, hitsKey: String(g.event_id),
                config: { kind: 'agent', event_id: g.event_id, event_tag: g.event_tag || '', channelid: '' },
            })),
        ];
        if (algoItems.length) groups.push({ title: '② 算法元件', dot: 'bg-amber-400', hint: '每个算法一个元件', items: algoItems });

        // ③ 逻辑元件：10 类产品化算子（参数 1:1）
        const logicItems = LOGIC_OPS.filter((o) => hit(o.title) || hit(o.badge) || hit(o.desc) || hit(o.subtitle)).map((o) => ({
            type: 'logic', icon: o.badge, name: o.title, tag: o.badge, tagKind: 'violet',
            desc: o.subtitle + (o.unwired ? ' · 运行时待接入' : ''), unwired: o.unwired,
            config: { logic_type: o.key, ...o.params },
        }));
        if (logicItems.length) groups.push({ title: '③ 逻辑元件（10 类算子）', dot: 'bg-violet-400', hint: '组合上游命中事件', items: logicItems });

        if (hit('智能复核') || hit('多模态') || hit('VLM') || hit(VLM_OP.title)) {
            groups.push({ title: '④ 智能复核元件', dot: 'bg-emerald-400', hint: '命中后调大模型复核', items: [
                { type: 'llm', icon: 'VLM', name: VLM_OP.title, tag: 'VLM', tagKind: 'emerald', desc: VLM_OP.subtitle, config: { ...VLM_OP.params } },
            ]});
        }
        if (hit('输出') || hit('预警') || hit(OUTPUT_OP.title)) {
            groups.push({ title: '⑤ 输出元件', dot: 'bg-rose-400', hint: '生成业务预警', items: [
                { type: 'output', icon: '出', name: OUTPUT_OP.title, tag: '输出', tagKind: 'rose', desc: '自定义预警名称与输出 ID', config: { ...OUTPUT_OP.params } },
            ]});
        }
        return groups;
    })();

    // ── 模板（本地预设，快速起步）──
    const PRESETS = [
        { id: 'and2', name: '模板1 [AND 并联与校验]：双算法同窗校验', build: () => {
            const a = algoOptions[0], b = algoOptions[1] || algoOptions[0];
            const n1 = addNode('algo', 40, 60, a ? { kind: 'warehouse', event_type: a.eventType, event_name: a.eventName || '', channelid: '' } : {});
            const n2 = addNode('algo', 40, 220, b ? { kind: 'warehouse', event_type: b.eventType, event_name: b.eventName || '', channelid: '' } : {});
            const n3 = addNode('logic', 400, 150, { logic_type: 'logic_and', ...logicOpByKey('logic_and').params });
            const n4 = addNode('output', 780, 150, { ...OUTPUT_OP.params, ruleName: '并联校验预警', output_id: 'biz-and' });
            edges = [...edges, { id: `e_${Date.now()}a`, source: n1.id, target: n3.id }, { id: `e_${Date.now()}b`, source: n2.id, target: n3.id }, { id: `e_${Date.now()}c`, source: n3.id, target: n4.id }];
        } },
        { id: 'seq', name: '模板2 [A→B 时序跟随 + VLM 复核]：先后状态串联', build: () => {
            const a = algoOptions[0], b = algoOptions[1] || algoOptions[0];
            const n1 = addNode('algo', 40, 60, a ? { kind: 'warehouse', event_type: a.eventType, event_name: a.eventName || '', channelid: '' } : {});
            const n2 = addNode('algo', 40, 220, b ? { kind: 'warehouse', event_type: b.eventType, event_name: b.eventName || '', channelid: '' } : {});
            const n3 = addNode('logic', 400, 150, { logic_type: 'logic_seq', ...logicOpByKey('logic_seq').params });
            const n4 = addNode('llm', 740, 150, { ...VLM_OP.params });
            const n5 = addNode('output', 1060, 150, { ...OUTPUT_OP.params, ruleName: '时序串联预警', output_id: 'biz-seq' });
            edges = [...edges, { id: `e_${Date.now()}a`, source: n1.id, target: n3.id }, { id: `e_${Date.now()}b`, source: n2.id, target: n3.id },
                     { id: `e_${Date.now()}c`, source: n3.id, target: n4.id }, { id: `e_${Date.now()}d`, source: n4.id, target: n5.id }];
        } },
        { id: 'vote', name: '模板3 [K/N 投票门]：多源风险叠加升级', build: () => {
            const picks = algoOptions.slice(0, 3);
            const srcs = (picks.length ? picks : [null]).map((a, i) => addNode('algo', 40, 60 + i * 150,
                a ? { kind: 'warehouse', event_type: a.eventType, event_name: a.eventName || '', channelid: '' } : {}));
            const n4 = addNode('logic', 400, 150, { logic_type: 'logic_vote', ...logicOpByKey('logic_vote').params });
            const n5 = addNode('output', 780, 150, { ...OUTPUT_OP.params, ruleName: '投票聚合预警', output_id: 'biz-vote' });
            srcs.forEach((s, i) => edges = [...edges, { id: `e_${Date.now()}${i}`, source: s.id, target: n4.id }]);
            edges = [...edges, { id: `e_${Date.now()}z`, source: n4.id, target: n5.id }];
        } },
        { id: 'denoise', name: '模板4 [防抖聚合 + 驻留]：告警风暴降噪', build: () => {
            const a = algoOptions[0];
            const n1 = addNode('algo', 40, 150, a ? { kind: 'warehouse', event_type: a.eventType, event_name: a.eventName || '', channelid: '' } : {});
            const n2 = addNode('logic', 360, 150, { logic_type: 'logic_debounce', ...logicOpByKey('logic_debounce').params });
            const n3 = addNode('logic', 680, 150, { logic_type: 'logic_duration', ...logicOpByKey('logic_duration').params });
            const n4 = addNode('output', 1020, 150, { ...OUTPUT_OP.params, ruleName: '聚合降噪预警', output_id: 'biz-denoise' });
            edges = [...edges, { id: `e_${Date.now()}a`, source: n1.id, target: n2.id }, { id: `e_${Date.now()}b`, source: n2.id, target: n3.id },
                     { id: `e_${Date.now()}c`, source: n3.id, target: n4.id }];
        } },
    ];
    function loadPreset(pid) {
        const p = PRESETS.find((x) => x.id === pid);
        if (!p) return;
        if (nodes.length && !confirm('加载模板会覆盖当前画布内容，确定继续？')) return;
        nodes = []; edges = []; selectedNodeId = null;
        p.build();
        nodes = [...nodes];
        showToast(`已加载${p.name}`, 'success');
    }

    // ── 右侧参数面板 ──
    // 注意：必须直接引用 nodes（不能用 nodeById(selectedNodeId)）——Svelte 的依赖分析不跟进函数体，
    // 否则 patchConfig 改了 nodes 后面板不会重算（与连线几何那个坑同源）。
    $: selectedNode = nodes.find((n) => n.id === selectedNodeId) || null;
    function patchConfig(patch) {
        if (!selectedNodeId) return;
        nodes = nodes.map((n) => n.id === selectedNodeId ? { ...n, config: { ...n.config, ...patch } } : n);
        updateDsl();
    }
    $: dslJson = (() => {
        try {
            return JSON.stringify({
                name: editorName || '(未命名)',
                device_id: editorDeviceId || '',
                nodes: nodes.map((n) => ({ id: n.id, type: n.type, x: Math.round(n.x), y: Math.round(n.y), config: n.config })),
                edges: edges.map((e) => ({ source: e.source, target: e.target })),
            }, null, 2);
        } catch (e) { return '{}'; }
    })();
    function updateDsl() { nodes = [...nodes]; }
    async function copyDsl() {
        try { await navigator.clipboard.writeText(dslJson); showToast('已复制规则 JSON。', 'success'); }
        catch (e) { showToast('复制失败，请手动选择。', 'warning'); }
    }

    // ── 保存 / 启停 / 删除 / 试运行 ──
    async function save() {
        if (!editorName.trim()) { showToast('请填写编排任务名称。', 'warning'); return; }
        if (!nodes.length) { showToast('画布为空，请先拖入元件。', 'warning'); return; }
        saving = true;
        const body = {
            name: editorName.trim(), device_id: editorDeviceId,
            status: editorEnabled ? 'enabled' : 'stopped',
            nodes: nodes.map((n) => ({ id: n.id, type: n.type, x: n.x, y: n.y, config: n.config })),
            edges: edges.map((e) => ({ source: e.source, target: e.target })),
        };
        try {
            const tip = editorEnabled ? '已启用' : '已停用';
            if (editingId) { await apiPut(`/orchestration/${editingId}`, body); showToast(`编排任务已更新（${tip}）。`, 'success'); }
            else { await apiPost('/orchestration', body); showToast(`编排任务已创建（${tip}）。`, 'success'); }
            editorOpen = false;
            await loadList();
        } catch (e) { showToast(e?.detail || '保存失败', 'error'); }
        finally { saving = false; }
    }
    async function toggleStatus(o) {
        const next = o.status === 'enabled' ? 'stopped' : 'enabled';
        try {
            await apiPut(`/orchestration/${o.id}/status`, { status: next });
            o.status = next; orchList = [...orchList];
            showToast(`已${next === 'enabled' ? '启用' : '停止'}「${o.name}」。`, 'success');
        } catch (e) { showToast(e?.detail || '操作失败', 'error'); }
    }
    async function removeOrch(o) {
        if (!confirm(`确定删除编排任务「${o.name}」？`)) return;
        try { await apiDelete(`/orchestration/${o.id}`); await loadList(); showToast('已删除。', 'info'); }
        catch (e) { showToast(e?.detail || '删除失败', 'error'); }
    }
    // ── 校验（逐节点诊断）──
    async function diagnose() {
        if (!nodes.length) { showToast('画布为空，请先拖入元件。', 'warning'); return; }
        diagnosing = true;
        showDiagnose = true;
        try {
            const body = {
                name: editorName || '(未命名)', device_id: editorDeviceId, status: editorEnabled ? 'enabled' : 'stopped',
                nodes: nodes.map((n) => ({ id: n.id, type: n.type, x: n.x, y: n.y, config: n.config })),
                edges: edges.map((e) => ({ source: e.source, target: e.target })),
            };
            diagnoseResult = await apiPost('/orchestration/diagnose?hours=24', body);
        } catch (e) {
            diagnoseResult = { error: e?.detail || '校验失败' };
        } finally { diagnosing = false; }
    }

    async function runNow() {        runBanner = { state: 'running', text: '正在按编排图回看最近时间窗的原始告警并评估…' };
        try {
            const r = await apiPost('/orchestration/run', {});
            const total = r?.total ?? 0;
            runBanner = { state: 'ok', text: `试运行完成：本轮新增 ${total} 条业务预警${total ? '' : '（无满足条件的告警，或该编排处于停止状态）'}` };
            await loadAlarms();
            setTimeout(() => (runBanner = null), 8000);
        } catch (e) {
            runBanner = { state: 'err', text: e?.detail || '试运行失败' };
        }
    }

    function fmt(ts) {
        if (!ts) return '';
        const d = new Date(Number(ts)); const p = (n) => String(n).padStart(2, '0');
        return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
    }
</script>

<style>
    .canvas-grid {
        background-color: #020617;
        background-image: radial-gradient(#1e293b 1.25px, transparent 1.25px);
        background-size: 20px 20px;
    }
    @keyframes dashFlow { to { stroke-dashoffset: -24; } }
    .edge-flowing { stroke-dasharray: 6 6; animation: dashFlow 0.6s linear infinite; }
    @keyframes pulseRing {
        0% { box-shadow: 0 0 0 0 rgba(99, 102, 241, 0.5); }
        70% { box-shadow: 0 0 0 8px rgba(99, 102, 241, 0); }
        100% { box-shadow: 0 0 0 0 rgba(99, 102, 241, 0); }
    }
    .node-selected { animation: pulseRing 2s infinite; }
</style>

<!-- 编辑态与列表态互斥：编辑器做成「页面内视图」，保留顶部导航栏，不再全屏浮层 -->
{#if !editorOpen}
<div class="space-y-5">
    <!-- 顶部：页签 + 操作 -->
    <div class="flex items-center justify-between flex-wrap gap-3">
        <div class="flex items-center gap-3">
            <h2 class="text-lg font-bold text-white flex items-center"><i class="fa-solid fa-diagram-project mr-2 text-indigo-400"></i>任务编排</h2>
            <div class="flex rounded-xl border border-slate-800 overflow-hidden">
                <button on:click={() => (mainTab = 'cards')} class="px-3 py-1.5 text-xs font-bold {mainTab === 'cards' ? 'bg-indigo-600 text-white' : 'bg-slate-900 text-slate-400'}">编排任务（{orchList.length}）</button>
                <button on:click={() => { mainTab = 'alarms'; loadAlarms(); }} class="px-3 py-1.5 text-xs font-bold {mainTab === 'alarms' ? 'bg-indigo-600 text-white' : 'bg-slate-900 text-slate-400'}">业务预警（{bizAlarms.length}）</button>
            </div>
        </div>
        <div class="flex items-center gap-2">
            <button on:click={runNow} class="text-xs text-amber-300 border border-amber-600/40 hover:bg-amber-500/10 rounded-lg px-3 py-2"><i class="fa-solid fa-play mr-1"></i>沙盘推演（试运行）</button>
            {#if mainTab === 'cards'}
                <button on:click={async () => { await loadPalette(); openEditor(null); }} class="bg-indigo-600 hover:bg-indigo-700 text-white rounded-xl px-4 py-2 text-sm font-bold"><i class="fa-solid fa-plus mr-1.5"></i>新建编排</button>
            {/if}
        </div>
    </div>

    {#if runBanner}
        <div class="rounded-xl border px-4 py-3 text-xs flex items-center gap-2
            {runBanner.state === 'ok' ? 'border-emerald-600/40 bg-emerald-950/40 text-emerald-300' : runBanner.state === 'err' ? 'border-rose-600/40 bg-rose-950/40 text-rose-300' : 'border-slate-700 bg-slate-900/60 text-slate-300'}">
            <i class="fa-solid {runBanner.state === 'running' ? 'fa-arrows-rotate animate-spin' : runBanner.state === 'ok' ? 'fa-circle-check' : 'fa-triangle-exclamation'}"></i>
            {runBanner.text}
        </div>
    {/if}

    {#if mainTab === 'cards'}
        {#if !$selectedDevice?.id}
            <div class="bg-slate-950 border border-amber-500/30 rounded-2xl p-6 text-center text-amber-300/90 text-sm">
                请先在右上角选择设备 —— 元件库（任务 / 原子算法 / 通道）来自当前设备。
            </div>
        {:else if loading}
            <div class="p-10 text-center text-slate-400"><i class="fa-solid fa-arrows-rotate animate-spin mr-2"></i>加载中…</div>
        {:else if !orchList.length}
            <div class="bg-slate-950 border border-slate-800 rounded-2xl p-12 text-center">
                <i class="fa-solid fa-diagram-project text-3xl text-slate-700 mb-3"></i>
                <p class="text-sm text-slate-400">还没有编排任务</p>
                <p class="text-[11px] text-slate-600 mt-1.5">从元件库拖入「任务/原子算法 → 逻辑 → 输出」，连线后保存即可启用。</p>
                <button on:click={async () => { await loadPalette(); openEditor(null); }} class="mt-4 bg-indigo-600 hover:bg-indigo-700 text-white rounded-xl px-4 py-2 text-sm font-bold">创建第一个编排</button>
            </div>
        {:else}
            <div class="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
                {#each orchList as o}
                    <div class="bg-slate-950 border border-slate-800 rounded-2xl p-4 flex flex-col gap-3">
                        <div class="flex items-start justify-between gap-2">
                            <h3 class="text-sm font-bold text-white truncate" title={o.name}>{o.name}</h3>
                            <div class="shrink-0 flex items-center gap-1.5">
                                <!-- 异常：配置/连线层面能判定为"不会正常工作"的问题，悬停看明细 -->
                                {#if o.has_issue}
                                    <span class="text-[10px] px-2 py-0.5 rounded-full border text-rose-300 border-rose-700/60 bg-rose-950/50 cursor-help"
                                          title={`检测到 ${o.issues?.length || 0} 个问题：\n· ${(o.issues || []).join('\n· ')}`}>
                                        <i class="fa-solid fa-triangle-exclamation mr-1"></i>异常
                                    </span>
                                {/if}
                                <span class="text-[10px] px-2 py-0.5 rounded-full border {o.status === 'enabled' ? 'text-emerald-300 border-emerald-700/60 bg-emerald-950/50' : 'text-slate-400 border-slate-700 bg-slate-900'}">
                                    {o.status === 'enabled' ? '运行中' : '已停止'}
                                </span>
                            </div>
                        </div>
                        <div class="flex items-center gap-3 text-[11px] text-slate-500">
                            <span><i class="fa-solid fa-server mr-1"></i>{o.device_id || '不限设备'}</span>
                            <span><i class="fa-solid fa-circle-nodes mr-1"></i>{o.node_count} 节点 · {o.edge_count} 连线</span>
                        </div>
                        <p class="text-[10px] text-slate-600">更新于 {fmt(o.updated_at)}</p>
                        <div class="mt-auto pt-3 border-t border-slate-800 flex items-center justify-between">
                            <label class="relative inline-flex items-center cursor-pointer" title={o.status === 'enabled' ? '点击停止' : '点击启用'}>
                                <input type="checkbox" checked={o.status === 'enabled'} on:change={() => toggleStatus(o)} class="sr-only peer">
                                <div class="w-9 h-5 bg-slate-700 rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-slate-300 after:border-slate-400 after:border after:rounded-full after:h-4 after:w-4 after:transition-all peer-checked:bg-emerald-600"></div>
                            </label>
                            <div class="flex items-center gap-1.5">
                                <button on:click={async () => { await loadPalette(); const d = await apiGet(`/orchestration/${o.id}`); openEditor(d); }}
                                        class="text-[11px] text-indigo-400 hover:bg-indigo-500/10 px-2 py-1 rounded-lg"><i class="fa-solid fa-pen"></i> 编辑</button>
                                <button on:click={() => removeOrch(o)} class="text-[11px] text-rose-400 hover:bg-rose-500/10 px-2 py-1 rounded-lg"><i class="fa-solid fa-trash"></i></button>
                            </div>
                        </div>
                    </div>
                {/each}
            </div>
        {/if}
    {:else}
        <div class="bg-slate-950 border border-slate-800 rounded-2xl overflow-hidden">
            <div class="px-5 py-3 border-b border-slate-800 bg-slate-900/40 text-sm font-bold text-white">编排产生的业务预警（最近 100 条）</div>
            {#if !bizAlarms.length}
                <div class="p-10 text-center text-slate-500 text-sm">暂无业务预警（编排触发后这里会实时出现）。</div>
            {:else}
                <table class="w-full text-xs">
                    <thead class="bg-slate-900/60 text-slate-500">
                        <tr class="text-left">
                            <th class="px-4 py-2.5 font-semibold">输出名称</th>
                            <th class="px-4 py-2.5 font-semibold">输出ID</th>
                            <th class="px-4 py-2.5 font-semibold">所属编排</th>
                            <th class="px-4 py-2.5 font-semibold">设备/通道</th>
                            <th class="px-4 py-2.5 font-semibold">触发说明</th>
                            <th class="px-4 py-2.5 font-semibold">时间</th>
                        </tr>
                    </thead>
                    <tbody class="divide-y divide-slate-800">
                        {#each bizAlarms as a}
                            <tr class="hover:bg-slate-900/50">
                                <td class="px-4 py-2.5 text-slate-200 font-bold">{a.output_name}</td>
                                <td class="px-4 py-2.5 text-slate-400 font-mono">{a.output_id || '—'}</td>
                                <td class="px-4 py-2.5 text-slate-300">{a.orchestration_name}</td>
                                <td class="px-4 py-2.5 text-slate-400">{a.device_name}{a.channelname ? ` · ${a.channelname}` : ''}</td>
                                <td class="px-4 py-2.5 text-slate-400 max-w-xs truncate" title={a.summary}>{a.summary}</td>
                                <td class="px-4 py-2.5 text-slate-500">{fmt(a.created_at)}</td>
                            </tr>
                        {/each}
                    </tbody>
                </table>
            {/if}
        </div>
    {/if}
</div>

{:else}
<!-- ══════════ 编排编辑器（页面内视图：保留顶部导航，高度占满剩余空间） ══════════ -->
    <!-- 高度取 main 的内容区（main 是 flex-1，高度确定）：顶部导航因此始终可见 -->
    <div class="relative bg-slate-950 border border-slate-800 rounded-2xl flex flex-col overflow-hidden
                h-full min-h-[520px]">
        <!-- 顶栏 -->
        <div class="h-14 px-4 border-b border-slate-800 bg-slate-900/60 flex items-center gap-3 shrink-0">
            <i class="fa-solid fa-diagram-project text-indigo-400"></i>
            <input bind:value={editorName} placeholder="编排任务名称"
                   class="w-72 bg-slate-950 border border-slate-800 text-slate-100 rounded-xl px-3 py-2 text-sm placeholder-slate-500 outline-none focus:border-indigo-500" />
            <div class="flex items-center gap-1.5 text-xs text-slate-400">
                <span>绑定设备</span>
                <select bind:value={editorDeviceId} class="bg-slate-950 border border-slate-800 text-slate-200 rounded-lg px-2 py-1.5 text-xs outline-none">
                    <option value="">不限设备</option>
                    {#each $devices as d}<option value={d.device_id}>{d.name}</option>{/each}
                </select>
            </div>
            <span class="text-[11px] text-slate-600">{nodes.length} 节点 · {edges.length} 连线</span>
            <!-- 默认开启：新建/编辑保存后立即生效，可在此关掉 -->
            <label class="flex items-center gap-1.5 text-xs cursor-pointer select-none rounded-lg border px-2.5 py-1.5 transition-colors
                          {editorEnabled ? 'border-emerald-600/50 bg-emerald-950/30 text-emerald-300' : 'border-slate-700 text-slate-400'}"
                   title="保存后是否立即启用本编排任务">
                <input type="checkbox" bind:checked={editorEnabled} class="w-3.5 h-3.5 accent-emerald-500" />
                <span>{editorEnabled ? '保存后启用' : '保存后停用'}</span>
            </label>
            <div class="ml-auto flex items-center gap-2">
                <button on:click={autoLayout} class="text-xs text-slate-300 border border-slate-700 hover:bg-slate-800 rounded-lg px-3 py-2"><i class="fa-solid fa-wand-magic-sparkles mr-1"></i>自动排布</button>
                <button on:click={diagnose} disabled={diagnosing} class="text-xs text-emerald-300 border border-emerald-600/50 hover:bg-emerald-500/10 disabled:opacity-50 rounded-lg px-3 py-2">
                    <i class="fa-solid {diagnosing ? 'fa-arrows-rotate animate-spin' : 'fa-stethoscope'} mr-1"></i>校验
                </button>
                <button on:click={clearCanvas} class="text-xs text-slate-300 border border-slate-700 hover:bg-rose-500/10 hover:text-rose-300 rounded-lg px-3 py-2"><i class="fa-solid fa-eraser mr-1"></i>清空画布</button>
                <button on:click={save} disabled={saving} class="bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50 text-white rounded-xl px-4 py-2 text-sm font-bold">{saving ? '保存中…' : '保存'}</button>
                <button on:click={closeEditor} class="text-slate-400 hover:text-slate-200 border border-slate-700 rounded-xl px-3 py-2 text-sm">关闭</button>
            </div>
        </div>

        <div class="flex-1 flex overflow-hidden">
            <!-- 元件库 -->
            <aside class="w-72 shrink-0 border-r border-slate-800 bg-slate-900/30 flex flex-col">
                <div class="p-3 border-b border-slate-800 bg-slate-900/50">
                    <label class="block text-[10px] font-bold text-slate-500 uppercase tracking-wider mb-1.5">一键加载模板</label>
                    <select on:change={(e) => loadPreset(e.target.value)} class="w-full text-xs bg-slate-950 border border-slate-800 rounded-lg px-2.5 py-2 text-slate-200 outline-none focus:border-indigo-500">
                        <option value="">选择模板…</option>
                        {#each PRESETS as p}<option value={p.id}>{p.name}</option>{/each}
                    </select>
                </div>
                <div class="p-3 border-b border-slate-800">
                    <div class="relative">
                        <input bind:value={paletteSearch} placeholder="搜索元件 / 算法…"
                               class="w-full pl-8 pr-3 py-1.5 text-xs bg-slate-950 border border-slate-800 focus:border-indigo-500 rounded-lg outline-none text-slate-200 placeholder-slate-600" />
                        <i class="fa-solid fa-magnifying-glass text-[11px] text-slate-500 absolute left-2.5 top-2.5"></i>
                    </div>
                </div>
                <div class="flex-1 overflow-y-auto p-3 space-y-4">
                    {#if !$selectedDevice?.id}
                        <p class="text-[11px] text-amber-400/90 leading-relaxed">未选择设备：请先关闭编辑器、在右上角选择设备，元件库才能列出该设备的任务/算法/通道。</p>
                    {/if}
                    {#each paletteGroups as g}
                        <div>
                            <div class="flex items-center justify-between mb-2">
                                <span class="text-[11px] font-bold text-slate-300 flex items-center gap-1.5"><span class="w-2 h-2 rounded-full {g.dot}"></span>{g.title}</span>
                                <span class="text-[9px] text-slate-500">{g.hint}</span>
                            </div>
                            <div class="space-y-1.5">
                                {#each g.items as it}
                                    <div draggable="true" on:dragstart={(ev) => onPaletteDragStart(ev, it)}
                                         class="group p-2 rounded-lg border border-slate-800 hover:border-indigo-500 bg-slate-950 hover:bg-indigo-500/5 cursor-grab active:cursor-grabbing transition flex items-start gap-2">
                                        <div class="w-6 h-6 rounded bg-slate-800 text-slate-300 group-hover:text-indigo-300 flex items-center justify-center shrink-0 mt-0.5 font-bold text-[10px]">{it.icon}</div>
                                        <div class="min-w-0 flex-1">
                                            <div class="flex items-center justify-between gap-1">
                                                <span class="text-[11px] font-semibold text-slate-200 group-hover:text-white truncate">{it.name}</span>
                                                <span class="text-[9px] px-1.5 py-0.5 rounded bg-slate-900 text-slate-400 shrink-0">{it.tag}</span>
                                            </div>
                                            <div class="text-[10px] text-slate-500 truncate" title={it.desc}>{it.desc}</div>
                                            {#if it.hits !== undefined}
                                                {#if it.hits > 0}
                                                    <div class="text-[9px] text-emerald-400/90 mt-0.5"><i class="fa-solid fa-circle-check mr-1"></i>近24h {it.hits} 条告警</div>
                                                {:else}
                                                    <div class="text-[9px] text-amber-400/90 mt-0.5" title="近 24 小时没有该类型的告警上报，选中它很可能永远匹配不到"><i class="fa-solid fa-triangle-exclamation mr-1"></i>近24h 无告警</div>
                                                {/if}
                                            {/if}
                                        </div>
                                    </div>
                                {/each}
                            </div>
                        </div>
                    {/each}
                    {#if !paletteGroups.length}
                        <p class="text-[11px] text-slate-500">没有匹配的元件。</p>
                    {/if}
                </div>
                <div class="p-3 border-t border-slate-800 text-[10px] text-slate-500 leading-relaxed">
                    💡 从左侧拖入元件；按住节点右侧 <span class="text-indigo-400 font-bold">● 输出端</span> 拖到目标左侧 <span class="text-violet-400 font-bold">● 输入端</span> 完成连线；点击连线可断开。
                </div>
            </aside>

            <!-- 画布 -->
            <section class="flex-1 relative overflow-auto canvas-grid">
                <div bind:this={canvasRef} class="relative" style="width:{CANVAS_W}px;height:{CANVAS_H}px"
                     on:dragover={onCanvasDragOver} on:drop={onCanvasDrop}>
                    <!-- 连线层 -->
                    <svg class="absolute inset-0 pointer-events-none" width={CANVAS_W} height={CANVAS_H}>
                        <defs>
                            <marker id="arrow-def" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
                                <path d="M 0 1 L 10 5 L 0 9 z" fill="#64748b" />
                            </marker>
                        </defs>
                        {#each edgeGeom as g (g.id)}
                            <path d={g.d} fill="none" stroke="#64748b" stroke-width="2.2" marker-end="url(#arrow-def)"
                                  class="pointer-events-auto cursor-pointer hover:stroke-rose-500 transition-colors" on:click={() => deleteEdge(g.id)} />
                        {/each}
                        {#if tempEdgePath}
                            <path d={tempEdgePath} fill="none" stroke="#6366f1" stroke-width="2.5" stroke-dasharray="5,5" />
                        {/if}
                    </svg>
                    <!-- 连线中点标签（可点删） -->
                    {#each edgeGeom as g (g.id)}
                        <button class="absolute -translate-x-1/2 -translate-y-1/2 text-[9px] px-1.5 py-0.5 rounded-full bg-slate-900 border border-slate-700 text-slate-400 hover:text-rose-300 hover:border-rose-500"
                                style="left:{g.mx}px;top:{g.my}px" on:click={() => deleteEdge(g.id)} title="点击断开连线">事件流</button>
                    {/each}
                    <!-- 节点层 -->
                    {#each nodes as n (n.id)}
                        <div class="absolute select-none" style="width:{NODE_W}px;left:{n.x}px;top:{n.y}px"
                             on:pointerdown={(ev) => onNodePointerDown(ev, n.id)}>
                            <div class="rounded-xl border-2 bg-slate-950 shadow-lg overflow-hidden {cc(nodeColor(n)).border} {selectedNodeId === n.id ? 'border-indigo-500 node-selected' : ''}">
                                <div class="px-2.5 py-1.5 {cc(nodeColor(n)).head} border-b border-slate-800 flex items-center justify-between">
                                    <span class="text-[10px] font-bold {cc(nodeColor(n)).text} flex items-center gap-1.5">
                                        <span class="w-2 h-2 rounded-full {cc(nodeColor(n)).dot}"></span>{nodeBadge(n)}
                                        {#if isUnwired(n)}<span class="text-[8px] px-1 rounded bg-amber-500/20 text-amber-300 border border-amber-500/40" title="运行时暂未接入，评估时按放行处理">待接入</span>{/if}
                                    </span>
                                    <button data-del="1" on:click={(ev) => { ev.stopPropagation(); deleteNode(n.id); }}
                                            class="text-slate-500 hover:text-rose-400 text-xs px-1" title="删除节点">×</button>
                                </div>
                                <div class="p-2.5">
                                    <div class="text-[11px] font-bold text-slate-100 truncate" title={nodeTitle(n.type, n.config)}>{nodeTitle(n.type, n.config)}</div>
                                    <div class="text-[10px] text-slate-500 mt-1 leading-snug">{nodeSubtitle(n)}</div>
                                    {#if nodeChannelBadge(n)}
                                        <div class="mt-1.5 px-1.5 py-0.5 rounded bg-indigo-500/10 border border-indigo-500/30 text-[9px] text-indigo-300 truncate">
                                            <i class="fa-solid fa-video mr-1"></i>通道：{nodeChannelBadge(n)}
                                        </div>
                                    {/if}
                                    <div class="mt-2 pt-1.5 border-t border-slate-800 flex items-center justify-between text-[9px] text-slate-600">
                                        <span class="truncate">ID <code class="text-slate-500">{n.id.slice(0, 10)}</code></span>
                                        <span class="text-indigo-400">点击配置 →</span>
                                    </div>
                                </div>
                            </div>
                            {#if showInputPort(n)}
                                <div data-port="in" on:pointerup={(ev) => onPortUp(ev, n.id)} title={inputPortHint(n)}
                                     class="absolute -left-2 top-[46px] -translate-y-1/2 w-4 h-4 rounded-full bg-slate-900 border-2 border-violet-500 hover:scale-125 transition-transform cursor-crosshair"></div>
                            {/if}
                            {#if showOutputPort(n)}
                                <div data-port="out" on:pointerdown={(ev) => onPortDown(ev, n.id)} title="输出端：按住拖出连线"
                                     class="absolute -right-2 top-[46px] -translate-y-1/2 w-4 h-4 rounded-full bg-indigo-600 border-2 border-white hover:scale-125 transition-transform cursor-crosshair"></div>
                            {/if}
                        </div>
                    {/each}
                </div>
            </section>

            <!-- 右侧参数 / JSON -->
            <aside class="w-[350px] shrink-0 border-l border-slate-800 bg-slate-900/30 flex flex-col">
                <div class="flex border-b border-slate-800 bg-slate-900/50">
                    <button on:click={() => (rightTab = 'props')} class="flex-1 py-2.5 text-xs font-bold {rightTab === 'props' ? 'text-indigo-300 border-b-2 border-indigo-500 bg-slate-950/40' : 'text-slate-500 hover:text-slate-300'}">节点参数配置</button>
                    <button on:click={() => (rightTab = 'json')} class="flex-1 py-2.5 text-xs font-bold {rightTab === 'json' ? 'text-indigo-300 border-b-2 border-indigo-500 bg-slate-950/40' : 'text-slate-500 hover:text-slate-300'}">规则 JSON</button>
                </div>

                {#if rightTab === 'props'}
                    <div class="flex-1 overflow-y-auto p-4 space-y-3">
                        {#if !selectedNode}
                            <p class="text-[11px] text-slate-500 text-center py-12 leading-relaxed">点击画布中的任意元件节点<br>配置其参数</p>
                        {:else}
                            <div class="flex items-center gap-2 pb-2 border-b border-slate-800">
                                <span class="w-2 h-2 rounded-full {cc(nodeColor(selectedNode)).dot}"></span>
                                <span class="text-xs font-bold text-slate-200">{nodeBadge(selectedNode)} · {nodeTitle(selectedNode.type, selectedNode.config)}</span>
                            </div>

                            {#if selectedNode.type === 'task'}
                                <!-- 任务元件：属性1 关联任务（可选）；属性2 关联通道（只展示） -->
                                <div>
                                    <label class="text-[11px] text-slate-400">1. 关联任务</label>
                                    <select value={selectedNode.config.task_id}
                                            on:change={(e) => { const t = taskOptions.find((x) => x.task_id === e.target.value); patchConfig({ task_id: e.target.value, task_name: t?.task_name || '' }); }}
                                            class="w-full bg-slate-950 border border-slate-800 text-slate-200 rounded-lg p-2 mt-1 text-xs">
                                        <option value="">选择任务…</option>
                                        {#each taskOptions as t}<option value={t.task_id}>{t.task_name}</option>{/each}
                                    </select>
                                </div>
                                <div>
                                    <label class="text-[11px] text-slate-400">2. 关联通道（自动带出，不可修改）</label>
                                    <div class="w-full mt-1 rounded-lg border border-slate-800 bg-slate-900/60 px-2.5 py-2 text-xs text-slate-300 flex items-center gap-2">
                                        <i class="fa-solid fa-video text-indigo-400"></i>
                                        <span class="truncate">{selectedNode.config.task_id ? (taskChannelText(selectedNode.config.task_id) || '该任务未关联通道') : '请先选择任务'}</span>
                                    </div>
                                    <p class="text-[10px] text-slate-500 mt-1 leading-relaxed">当前任务的分析通道由设备侧布控决定，此处仅展示，用于确认告警来自哪一路画面。</p>
                                </div>
                            {:else if selectedNode.type === 'algo'}
                                <!-- 算法元件：属性「算法类型」只展示，不可选择；算法身份由拖入的元件决定 -->
                                <div>
                                    <label class="text-[11px] text-slate-400">1. 算法类型（由元件决定，不可修改）</label>
                                    <div class="w-full mt-1 rounded-lg border border-slate-800 bg-slate-900/60 px-2.5 py-2 text-xs text-slate-200 flex items-center gap-2">
                                        <i class="fa-solid {(selectedNode.config.kind === 'agent') ? 'fa-robot' : 'fa-microchip'} text-amber-400"></i>
                                        <span>{selectedNode.config.kind === 'agent' ? '智能体算法' : '算法仓'}</span>
                                    </div>
                                </div>
                                <div class="pt-2 border-t border-slate-800">
                                    <label class="text-[11px] text-slate-400">2. 已绑定算法</label>
                                    <div class="w-full mt-1 rounded-lg border border-slate-800 bg-slate-900/60 px-2.5 py-2 text-xs text-slate-300">
                                        <div class="font-semibold truncate">{nodeTitle('algo', selectedNode.config)}</div>
                                        <div class="text-[10px] text-slate-500 mt-0.5 font-mono truncate">
                                            {selectedNode.config.kind === 'agent' ? selectedNode.config.event_id : selectedNode.config.event_type}
                                        </div>
                                    </div>
                                    <p class="text-[10px] text-slate-500 mt-1.5 leading-relaxed">算法身份来自元件库中拖入的那个元件；如需换算法，请从左侧②组重新拖入。</p>
                                </div>
                                <div class="pt-2 border-t border-slate-800">
                                    <label class="text-[11px] text-slate-400">输入端语义</label>
                                    <p class="text-[10px] text-slate-500 mt-1 leading-relaxed">接入上游后作为<b class="text-slate-400">前置门控</b>：上游命中时，本算法命中的事件才向下游传递。</p>
                                </div>
                            {:else if selectedNode.type === 'logic'}
                                <!-- 算子身份由拖入的元件决定，不提供下拉切换 -->
                                <div class="rounded-lg border border-slate-800 bg-slate-900/60 px-2.5 py-2">
                                    <div class="text-xs font-bold {cc(nodeColor(selectedNode)).text}">{nodeBadge(selectedNode)} · {nodeTitle('logic', selectedNode.config)}</div>
                                    <p class="text-[10px] text-slate-500 mt-1 leading-relaxed">{logicOpByKey(selectedNode.config.logic_type).subtitle}</p>
                                    {#if logicOpByKey(selectedNode.config.logic_type).unwired}
                                        <p class="text-[10px] text-amber-400/90 mt-1.5 leading-relaxed"><i class="fa-solid fa-triangle-exclamation mr-1"></i>运行时暂未接入（需设备提供告警生命周期 / BBox 坐标 / 防区拓扑），当前按「放行」处理。</p>
                                    {/if}
                                    <p class="text-[10px] text-slate-600 mt-1.5">如需换算子，请从左侧③组重新拖入对应元件。</p>
                                </div>
                                <div class="pt-2 border-t border-slate-800 space-y-2.5">
                                    <p class="text-[10px] font-bold text-slate-500 uppercase tracking-wider">算子参数</p>
                                    {#each visibleParams(selectedNode) as [k, v]}
                                        <ParamField name={k} value={v} onPatch={patchConfig} />
                                    {/each}
                                    <p class="text-[10px] text-slate-500 leading-relaxed border-t border-slate-800 pt-2">
                                        连线顺序即端口语义：<b class="text-slate-400">先连的在上（如 A）、后连的在下（如 B）</b>。
                                    </p>
                                </div>
                            {:else if selectedNode.type === 'llm'}
                                <div class="pt-1 space-y-2.5">
                                    {#each visibleParams(selectedNode) as [k, v]}
                                        <ParamField name={k} value={v} onPatch={patchConfig} />
                                    {/each}
                                    <p class="text-[10px] text-slate-500 leading-relaxed border-t border-slate-800 pt-2">命中后会取告警图调用多模态大模型；调用失败按「放行」处理，避免漏报。</p>
                                </div>
                            {:else if selectedNode.type === 'output'}
                                <div class="pt-1 space-y-2.5">
                                    {#each visibleParams(selectedNode) as [k, v]}
                                        <ParamField name={k} value={v} onPatch={patchConfig} />
                                    {/each}
                                </div>
                            {/if}

                            {#if selectedNode.type === 'algo'}
                                <div class="pt-2 border-t border-slate-800">
                                    <label class="text-[11px] text-slate-400">限定通道（可选，留空=不限）</label>
                                    <select value={selectedNode.config.channelid || ''} on:change={(e) => patchConfig({ channelid: e.target.value })}
                                            class="w-full bg-slate-950 border border-slate-800 text-slate-200 rounded-lg p-2 mt-1 text-xs">
                                        <option value="">不限通道（该算法所有通道）</option>
                                        {#each channelOptions as c}<option value={c.id}>{c.name}（{c.id}）</option>{/each}
                                    </select>
                                </div>
                            {/if}
                        {/if}
                    </div>
                {:else}
                    <div class="flex-1 flex flex-col overflow-hidden bg-slate-950">
                        <div class="p-3 border-b border-slate-800 flex items-center justify-between">
                            <span class="text-[11px] text-slate-400">后端规则引擎直接解析此 DAG</span>
                            <button on:click={copyDsl} class="px-2.5 py-1 rounded bg-slate-900 hover:bg-slate-800 text-indigo-400 text-[11px] font-medium transition">复制 JSON</button>
                        </div>
                        <pre class="flex-1 p-3 text-[11px] font-mono overflow-auto leading-relaxed text-emerald-300 whitespace-pre-wrap break-all">{dslJson}</pre>
                    </div>
                {/if}
            </aside>
        </div>

        <!-- 校验结果面板 -->
        {#if showDiagnose}
            <div class="absolute right-4 bottom-4 w-[620px] max-h-[70vh] bg-slate-950 border border-slate-700 rounded-2xl shadow-2xl flex flex-col overflow-hidden">
                <div class="px-4 py-3 border-b border-slate-800 bg-slate-900/60 flex items-center justify-between">
                    <span class="text-sm font-bold text-white"><i class="fa-solid fa-stethoscope mr-2 text-emerald-400"></i>编排校验结果</span>
                    <button on:click={() => (showDiagnose = false)} class="text-slate-400 hover:text-slate-200"><i class="fa-solid fa-xmark"></i></button>
                </div>
                {#if diagnosing}
                    <div class="p-8 text-center text-slate-400 text-xs"><i class="fa-solid fa-arrows-rotate animate-spin mr-2"></i>正在按图求值…</div>
                {:else if diagnoseResult?.error}
                    <div class="p-6 text-center text-rose-300 text-xs">{diagnoseResult.error}</div>
                {:else if diagnoseResult}
                    <div class="flex-1 overflow-y-auto p-4 space-y-3 text-xs">
                        <div class="rounded-xl border px-3 py-2.5 {diagnoseResult.fired ? 'border-emerald-600/40 bg-emerald-950/30' : 'border-amber-600/40 bg-amber-950/30'}">
                            {#if diagnoseResult.fired}
                                <p class="text-emerald-300 font-bold"><i class="fa-solid fa-circle-check mr-1.5"></i>编排可以触发（输出节点有命中）</p>
                            {:else if diagnoseResult.outputs?.some((o) => o.cooldown_silenced)}
                                <p class="text-sky-300 font-bold"><i class="fa-solid fa-snowflake mr-1.5"></i>命中条件成立，但正处于冷却静默期（未重复报警）</p>
                            {:else}
                                <p class="text-amber-300 font-bold"><i class="fa-solid fa-triangle-exclamation mr-1.5"></i>编排当前不会触发 —— 按下面「未命中原因」逐条排查</p>
                            {/if}
                            <p class="text-[10px] text-slate-400 mt-1">
                                设备：{diagnoseResult.device_name || diagnoseResult.device_id || '不限'}
                                ｜回看 {diagnoseResult.window_seconds}s 共扫描 {diagnoseResult.alerts_scanned} 条告警
                            </p>

                            {#each diagnoseResult.outputs || [] as o}
                                {#if o.cooldown}
                                    <p class="text-[10px] mt-1 {o.cooldown.remaining > 0 ? 'text-sky-300' : 'text-slate-400'}">
                                        <i class="fa-solid fa-snowflake mr-1"></i>冷却锁[{o.cooldown.scope} {o.cooldown.sec}s]
                                        {#if o.cooldown.remaining > 0}· 静默中，剩余 {o.cooldown.remaining}s{/if}
                                    </p>
                                {/if}
                            {/each}
                        </div>

                        <div>
                            <p class="text-[10px] font-bold text-slate-500 uppercase tracking-wider mb-1.5">连线/配置问题</p>
                            {#if diagnoseResult.warnings?.length}
                                <div class="space-y-1">
                                    {#each diagnoseResult.warnings as w}
                                        <div class="rounded-lg border border-rose-600/40 bg-rose-950/20 px-2.5 py-1.5 text-[10px] text-rose-200 leading-relaxed">
                                            <i class="fa-solid fa-link-slash mr-1"></i>{w}
                                        </div>
                                    {/each}
                                </div>
                            {:else}
                                <p class="text-[10px] text-emerald-400/80"><i class="fa-solid fa-circle-check mr-1"></i>连线结构没问题</p>
                            {/if}
                        </div>

                        <div>
                            <p class="text-[10px] font-bold text-slate-500 uppercase tracking-wider mb-1.5">该设备近 {diagnoseResult.hours}h 实际上报的告警类型</p>
                            <div class="flex flex-wrap gap-1.5">
                                {#each diagnoseResult.alert_types_in_window as t}
                                    <span class="px-1.5 py-0.5 rounded bg-slate-900 border border-slate-700 text-[10px] text-slate-300">
                                        <code class="text-indigo-300">{t.alertType}</code> · {t.count}
                                    </span>
                                {:else}
                                    <span class="text-[10px] text-amber-400">该设备近 {diagnoseResult.hours}h 没有任何告警上报</span>
                                {/each}
                            </div>
                            <p class="text-[10px] text-slate-500 mt-1 leading-relaxed">算法元件绑定的算法必须出现在上面这份列表里（否则它永远匹配不到）。</p>
                        </div>

                        <div class="space-y-1.5">
                            <p class="text-[10px] font-bold text-slate-500 uppercase tracking-wider">逐节点求值</p>
                            {#each diagnoseResult.nodes as n}
                                <div class="rounded-lg border px-2.5 py-2 {n.matched > 0 ? 'border-emerald-700/40 bg-emerald-950/20' : 'border-slate-800 bg-slate-900/40'}">
                                    <div class="flex items-center justify-between gap-2">
                                        <span class="font-semibold text-slate-200 truncate">
                                            <i class="fa-solid {n.matched > 0 ? 'fa-circle-check text-emerald-400' : 'fa-circle-xmark text-slate-500'} mr-1.5"></i>{n.label}
                                        </span>
                                        <span class="shrink-0 text-[10px] {n.matched > 0 ? 'text-emerald-300' : 'text-slate-500'}">
                                            {n.matched > 0 ? `命中 ${n.matched} 条` : '未命中'}
                                        </span>
                                    </div>
                                    {#if n.detail?.keys?.length}
                                        <div class="text-[10px] text-slate-500 mt-0.5">匹配键：{n.detail.keys.join(', ')}{n.detail.channel ? ` ｜通道 ${n.detail.channel}${n.detail.channel_name ? `（${n.detail.channel_name}）` : ''}` : ''}</div>
                                    {/if}
                                    {#if n.detail?.found === false}
                                        <div class="text-[10px] text-rose-300 mt-0.5">该任务不在设备快照里</div>
                                    {/if}
                                    {#if n.reason}
                                        <div class="text-[10px] text-amber-300/90 mt-1 leading-relaxed"><i class="fa-solid fa-circle-info mr-1"></i>{n.reason}</div>
                                    {/if}
                                </div>
                            {/each}
                        </div>
                    </div>
                {/if}
            </div>
        {/if}
    </div>
{/if}
