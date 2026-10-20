/**
 * 编排元件参数的单一元数据源。
 *
 * 背景：之前参数的 Label、下拉选项、控件类型分散在 5 个并行 Map 里
 * （FIELD_LABELS / SELECT_OPTIONS / TEXTAREA_KEYS / NUMERIC_KEYS / PARAM_HIDDEN），
 * 同一个 key 要在多处维护，已经因此出过两次事故（severity 删除后仍在表单里显示）。
 * 现在统一成一张表：新增/删除/改名只改这里。
 *
 * 字段结构：{ label, type?: 'select'|'textarea'|'number'|'text', options?: string[], hidden?: boolean }
 * - 未写 type 时为文本输入；value 是布尔时由渲染层优先按开关渲染。
 * - hidden: true 表示该键已废弃：不再渲染，也不再回写（保留仅为兜底历史编排里的残留键）。
 */

export const PARAM_FIELDS = {
    // ── 时间窗口（AND / K-N 共用）──
    windowType: {
        label: '时间窗口滑动模式',
        type: 'select',
        options: ['滚动时间窗 (Tumbling Window)', '会话时间窗 (Session Window)'],
    },
    windowSec: { label: '时间窗口大小 ΔT (秒)', type: 'number' },
    watermarkToleranceSec: { label: '乱序容忍水位线 Watermark (秒)', type: 'number' },

    // ── K-of-N 投票门 ──
    voteMode: {
        label: '多路表决计算模式',
        type: 'select',
        options: ['至少命中 K 路 (K-of-N Majority)', '按各分支权重累加积分 (Weighted Score)'],
    },
    minRequiredBranches: { label: '最少同时命中分支数 (K值)', type: 'number' },
    weightConfig: { label: '各算法分支权重赋分规则', type: 'textarea' },

    // ── 互斥抑制 A AND NOT B ──
    primaryStreamDesc: { label: '端口A [主触发流] 绑定说明' },
    inhibitorStreamDesc: { label: '端口B [抑制豁免流] 绑定说明' },
    preLookbackSec: { label: '前向回溯查找抑制流时间 (秒)', type: 'number' },
    postWaitSec: { label: '后向延迟等待抑制流时间 (秒)', type: 'number' },
    onSuppressedAction: { label: '被抑制拦截后的审计动作', type: 'textarea' },

    // ── 时序跟随 A→B ──
    stepADesc: { label: '前置事件 A (状态机起点)' },
    stepBDesc: { label: '后置事件 B (状态机终点)' },
    minWaitSec: { label: '串联最小间隔等待时长 (秒)', type: 'number' },
    maxWindowSec: { label: '串联最大有效等待时长 (秒)', type: 'number' },
    continuityPolicy: {
        label: '时序连续性策略',
        type: 'select',
        options: ['宽松跟随 (忽略中间无关事件)', '严格紧邻跟随 (中间不允许其它事件)'],
    },

    // ── 状态持续驻留 HOLD ──
    holdDurationSec: { label: '要求连续保持时长 (秒)', type: 'number' },
    maxHeartbeatGapSec: { label: '最大允许遮挡闪断间隔 (秒)', type: 'number' },
    note: { label: '算子产品化说明', type: 'textarea' },

    // ── 状态恢复自动消警 AUTO-CLR ──
    recoveryCondition: { label: '自动消警触发条件' },
    recoveryConfirmSec: { label: '恢复状态稳定确认时长 (秒)', type: 'number' },
    autoCloseTimeoutMin: { label: '超时未恢复兜底转人工时长 (分)', type: 'number' },
    notifyOnResolve: { label: '消警闭环后同步推送恢复通知' },

    // ── 同画面目标框 IoU 绑定 ──
    spatialMatchMode: {
        label: '空间几何匹配模式',
        type: 'select',
        options: ['框包含或相交 (父框:人体闯入 ⊃ 子框:未戴安全帽/抽烟)', '严格交并比 (IoU ≥ 阈值)', '底部中心点落入同一网格'],
    },
    iouThreshold: { label: '目标框交并比阈值 (IoU 0~1)', type: 'number' },
    maxTimeDiffMs: { label: '多算法抓拍帧时间对齐容差 (毫秒)', type: 'number' },
    sameCameraRequired: { label: '强制要求同一摄像头通道画面' },
    coordinateNormalize: { label: '坐标归一化处理方式', type: 'textarea' },

    // ── 跨摄像头防区拓扑绑定 ──
    topologyJoinKey: { label: '跨设备空间关联主键' },
    boundDevicesGroup: { label: '已绑定防区通道拓扑组', type: 'textarea' },
    enableReIdFeature: { label: '启用跨镜行人/车辆 ReID 特征比对' },
    reIdSimilarityThreshold: { label: 'ReID 外观特征余弦相似度阈值', type: 'number' },

    // ── 频次防抖聚合 ──
    minHitCount: { label: '窗口内最少累计触发次数 (M次)', type: 'number' },
    mergeSnapshotPolicy: {
        label: '多帧抓拍图证据合并策略',
        type: 'select',
        options: ['抽样3张代表图 (首帧 + 最高置信度帧 + 尾帧)', '仅保留最高置信度单张抓拍', '合成 GIF/短视频片段'],
    },
    suppressDuplicateSec: { label: '触发后防抖去重静默时间 (秒)', type: 'number' },

    // ── 排班与作业票门控 ──
    scheduleMode: { label: '排班与作业票门控模式' },
    activeTimeRange: { label: '规则生效时间段 (如 08:00-18:00,20:00-22:00)' },
    workPermitCheck: { label: '外部安全生产作业票联动校验', type: 'textarea' },
    holidayOverride: { label: '节假日自动切换为全严封场模式' },

    // ── 多模态大模型复核 ──
    model: { label: '复核多模态大模型/智能体' },
    imageStitchMode: { label: '多路告警抓拍图送审拼接方式' },
    prompt: { label: '二次复核系统提示词 (System Prompt)', type: 'textarea' },
    passThreshold: { label: '大模型复核通过置信度阈值', type: 'number' },
    fallbackOnTimeout: { label: '大模型推理超时安全兜底策略' },

    // ── 业务预警输出 ──
    ruleName: { label: '生成的新复合预警名称' },
    output_id: { label: '输出 ID（业务标识）' },
    cooldownSec: { label: '预警冷却静默期 Cooldown (秒)', type: 'number' },
    cooldownScope: {
        label: '冷却静默锁作用粒度',
        type: 'select',
        // 防区粒度需要防区拓扑数据（系统暂无），故不提供该选项
        options: ['按 [规则ID + 通道设备ID] 冷却静默', '全局规则冷却静默'],
    },
    actions: { label: '触发后多通道联动动作', type: 'textarea' },

    // ── 已废弃的装饰性配置项（不再渲染 / 不再回写）──
    logic_type: { hidden: true },          // 算子身份，由拖入的元件决定；必须保留取值
    groupByKey: { hidden: true },
    consumePolicy: { hidden: true },
    dynamicSeverity: { hidden: true },
    countOutputField: { hidden: true },
    sampleCheckIntervalSec: { hidden: true },
    resetOnNormalFrame: { hidden: true },
    cancelIfTargetLeave: { hidden: true },
    severity: { hidden: true },
};

/** 不参与表单渲染的键（历史编排里可能还留着）。 */
export const PARAM_HIDDEN = Object.keys(PARAM_FIELDS).filter((k) => PARAM_FIELDS[k].hidden);

/** 打开编排时直接从 config 里剔除的键（logic_type 是算子身份，必须保留）。 */
export const PARAM_STRIP = PARAM_HIDDEN.filter((k) => k !== 'logic_type');

/** 取某参数的控件元数据（未登记的键按普通文本处理）。 */
export function fieldMeta(key) {
    return PARAM_FIELDS[key] || { label: key };
}

/** 某节点需要渲染的 [key, value] 列表（已过滤废弃键）。 */
export function visibleParams(node) {
    return Object.entries((node && node.config) || {}).filter(([k]) => !PARAM_HIDDEN.includes(k));
}

/** 剔除废弃键并归一化历史取值；用于打开编辑器时清洗历史编排。 */
export function normalizeConfig(config) {
    const cfg = { ...(config || {}) };
    PARAM_STRIP.forEach((k) => { delete cfg[k]; });
    // 早期输出元件默认「防区Tag」粒度，但系统无防区拓扑、引擎实际按通道冷却 → 改写成等价选项
    if (typeof cfg.cooldownScope === 'string' && cfg.cooldownScope.includes('防区')) {
        cfg.cooldownScope = '按 [规则ID + 通道设备ID] 冷却静默';
    }
    return cfg;
}
