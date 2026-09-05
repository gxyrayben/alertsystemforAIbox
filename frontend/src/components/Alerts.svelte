<script>
    import { createEventDispatcher } from 'svelte';
    import { API_BASE, apiGet, apiPost } from '../lib/api.js';
    import { selectedDevice } from '../lib/controlStore.js';

    // 1. 定义原始映射元组配置 ///////////////////////////////////////////////////////////////////////////////////////////////////////
    const _RAW = [
        ["structure", "结构化", [
            ["face", "人脸抓拍"], ["pedestrian", "人体抓拍"], ["vehicle", "车辆抓拍"],
            ["non_motor", "非机动车"], ["plate", "车牌"]
        ]],
        ["headcount_alarm", "人数统计", [
            ["head_count", "区域人数统计"], ["cross_line", "进出口人数统计"]
        ]],
        ["face_basic_business", "脸人", [
            ["face_capture", "人脸抓拍"], ["body_capture", "人体抓拍"],
            ["face_comparison_successful", "人脸识别"], ["stranger", "陌生人"]
        ]],
        ["goods_alarm", "物品", [
            ["SUNDRY_DETECT", "杂物堆放"], ["GOODS_FORGET", "物品遗留"],
            ["GOODS_GUARD", "物品看守"], ["NEW_GOODS_DETECT", "新增杂物检测"]
        ]],
        ["diagnosis_alarm", "视频诊断", [
            ["IMAGE_COVER_ALERT", "画面遮挡"]
        ]],
        ["gkpw_alarm", "高空抛物", [
            ["falling_goods", "高空抛物"]
        ]],
        ["mclz_alarm", "明厨亮灶", [
            ["TRASHBIN", "垃圾桶未盖"], ["MICE", "老鼠"], ["CHEF_CLOTH", "未穿戴厨师服"],
            ["CHEF_HAT", "未佩戴厨师帽"], ["CHEF_RESPIRATOR", "未佩戴口罩"],
            ["RUBBER_GLOVE", "未佩戴橡胶手套"], ["FLAME_WITHOUT_HUMAN", "动火离人"], ["DISH", "光盘检测"]
        ]],
        ["alert_alarm", "警戒算法", [
            ["PARK", "车辆禁停"], ["EXIT", "车辆离开"], ["WANDER", "人员徘徊"],
            ["OVERWALL", "翻墙"], ["INTRUSION", "区域入侵"], ["CLIMB", "攀爬"],
            ["ELECTRIC_BIKE_IN_ELEVATOR", "电动车进电梯"], ["TRIPWIRE", "越界"], ["FALL", "摔倒"],
            ["SMOKING", "抽烟"], ["CALL", "打电话"], ["WATCH_POINE", "看手机"],
            ["WATCH_PHONE", "看手机"], ["RUN", "奔跑"], ["FIGHT", "扭打"],
            ["GATHERING", "人员聚众"], ["HOLDWEAPON", "持械"], ["LEAVE_POST", "人员离岗"],
            ["PERSON_LESS_QUERYING", "少员"], ["PERSON_OVER_QUERYING", "超员"], ["SLEEP", "睡岗"]
        ]],
        ["safety_alarm", "安监", [
            ["SAFETY_CAP", "未佩戴安全帽"], ["SAFETY_UNIFORM", "未穿戴安全工服"],
            ["SAFETY_BELT", "未佩戴安全带"], ["FIRE", "火焰"], ["SMOKE", "烟雾"],
            ["OIL_SPILL", "油品泄露"], ["REFLECTIVE_VEST", "反光衣"], ["FIRE_EQUIPMENT", "消防设施"],
            ["RESPIRATOR", "口罩"], ["TOUCHED_EEBALL", "触摸静电球"], ["INSULATING_GLOVE", "未佩戴绝缘手套"]
        ]],
        ["jyz_alarm", "加油站", [
            ["SAFETY_CAP", "未佩戴安全帽"], ["SAFETY_UNIFORM", "未穿戴安全工服"],
            ["FIRE", "火焰"], ["SMOKE", "烟雾"], ["OIL_SPILL", "油品泄露"],
            ["FIRE_EQUIPMENT", "消防设施"], ["INDICATOR_FLAG", "静电线"], ["OIL_PIPE", "卸油管检测"],
            ["OILPUMP_DOOR_OPEN", "油机侧盖打开"], ["OIL_GUN_DRAG", "油管拉断"], ["OIL_TRUCK", "油罐车检测"]
        ]],
        ["edu__alarm", "教学评测", [
            ["HEAD_UP", "抬头"], ["HEAD_DOWN", "低头"], ["STAND", "站立"],
            ["READ", "阅读"], ["WRITE", "书写"], ["RAISE_HAND", "举手"],
            ["REST", "趴桌"], ["PEACE", "中性"], ["LAUGH", "积极"], ["CRY", "消极"]
        ]],
        ["uniform_alarm", "工服注册仓", [
            ["UNIFORM_BY_FEATURE", "未穿工服"]
        ]],
        ["city_alarm", "城管", [
            ["HAWKER", "游商小贩"], ["OUTSTORE", "店外经营"], ["ROADSIDE", "占道经营"],
            ["SUNDRYSTACK", "杂物堆放"], ["MUCK", "堆积渣土"], ["EXPOSED_GARBAGE", "暴露垃圾"],
            ["OUTDOOR_ADV", "户外广告"], ["WATERGATHER", "道路积水"]
        ]],
        ["building_alarm", "工地", [
            ["UNCOVERED_GROUND", "裸土覆盖"], ["UNCOVERED_SKIN", "皮肤裸露"], ["UNCLEANED_CAR", "车辆未喷淋"]
        ]],
        ["edu__style", "教学风格", [
            ["WRITE_ON_BLACKBOARD", "板书"], ["BACK_TO_STUDENT", "背对学生"],
            ["PODIUM_MOVEMENT", "上下讲台"], ["PATROL", "巡视"], ["WRITE", "书写"], ["LECTURE", "讲课"]
        ]],
        ["fire_alarm", "智慧社区", [
            ["OVERFLOWED_GARBAGE", "垃圾满溢"], ["EXPOSED_GARBAGE", "垃圾暴漏"], ["NO_HELMET", "骑电动车未戴头盔"]
        ]]
    ];

    // 2. 生成快速查找字典
    const PACKAGE_NAME_MAP = {};
    const CARD_NAME_MAP = {};

    for (const [pkgKey, pkgZh, cards] of _RAW) {
        PACKAGE_NAME_MAP[pkgKey] = pkgZh;
        for (const [cardKey, cardZh] of cards) {
            CARD_NAME_MAP[cardKey] = cardZh;
        }
    }

    // 3. 辅助函数：根据 Key 获取中文，不存在则回退显示原字符
    function getPackageLabel(name) {
        return PACKAGE_NAME_MAP[name] || name;
    }

    function getCardLabel(card) {
        return CARD_NAME_MAP[card] || card;
    }

    ////////////////////////////////////////////////////////////////////////////////////////////////////////

    function getStartOfDay() {
        const d = new Date();
        d.setHours(0, 0, 0, 0);
        // Format to YYYY-MM-DDTHH:mm:ss for datetime-local input
        return new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 19);
    }

    function getEndOfDay() {
        const d = new Date();
        d.setHours(23, 59, 59, 999);
        return new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 19);
    }

    let displayedAlerts = [];
    let alertFilters = { startDate: getStartOfDay(), endDate: getEndOfDay(), channelid: '',channelname: '', alertType: '' };
    let aiLoadingIds = {};
    //const alertTypes = ['区域入侵', '越界检测', '车辆违停', '人员聚集', '烟火检测'];

    // 当前设备（顶栏右上角选择）——预警数据自动按该设备检索
    $: deviceName = $selectedDevice?.name || '';

    /* algorithms_ability = [
        { name: " packageA", cards: ["LEAVE_POST", "SMOKING", "RUN"] },
        { name: "packageB", cards: ["FALL", "SLEEP"] }
        ];

        agents [{
            "agent_id": item.get("agent_id"),
            "agent_name": item.get("agent_name"),
            "event_id": item.get("event_id"),
            "event_tag": item.get("event_tag"),
            "alarm_condition": item.get("alarm_condition"),
            "alarm_type": item.get("alarm_type"),
            "prompt": item.get("prompt", ""),
        }]
    */
    $: algorithmsOptions = parseavailable_algorithms_ability($selectedDevice); // 解析出支持的算法列表
    function parseavailable_algorithms_ability(dev) {
        try {
            const algorithms_ability = JSON.parse(dev?.algorithms_ability || '[]');
            return algorithms_ability;

        } catch (e) {
            console.error('algorithms_ability analysis failed:', e);
            return [];
        }
    }

    $: agentsOptions = parseavailable_agents_ability($selectedDevice); // 解析出支持的agents列表
    function parseavailable_agents_ability(dev) {
        try {
            const agents = JSON.parse(dev?.agents || '[]');
            return agents;

        } catch (e) {
            console.error('agents analysis failed:', e);
            return [];
        }
    }

    // 通道下拉项来自当前设备的通道快照（通道对象的 device_name 即通道名），默认「全通道」
    $: channelOptions = parseChannelsNames($selectedDevice); 
    function parseChannelsNames(dev) {
        try {
            const rawList = JSON.parse(dev?.channels || '[]');
            if (!Array.isArray(rawList)) return [];

            const seenIds = new Set();
            const validChannels = [];

            for (const item of rawList) {
                // 提取唯一通道 ID（兼顾常见的几种后端字段命名）
                const cid = item?.device_id.trim();
                const name = item?.device_name?.trim();

                // 核心校验：必须同时具备通道 ID 和 通道名称
                if (cid && name) {
                    // 去重：如果同一个通道 ID 出现多次，只保留第一条
                    if (!seenIds.has(cid)) {
                        seenIds.add(cid);
                        validChannels.push({
                            ...item,
                            display_name: `${name}-${cid}`, // 预留统一显示字段（后续处理同名区分）
                        });
                    }
                }
            }
            return validChannels;
        } catch (e) {
            console.error('解析通道配置失败:', e);
            return [];
        }
    }



    // 分页状态
    let currentPage = 1;
    const itemsPerPage = 12;
    $: totalPages = Math.ceil(displayedAlerts.length / itemsPerPage);
    $: paginatedAlerts = displayedAlerts.slice((currentPage - 1) * itemsPerPage, currentPage * itemsPerPage);

    // 图片查看器状态
    let viewerImage = null;
    function openViewer(url) {
        viewerImage = url;
    }
    function closeViewer() {
        viewerImage = null;
    }

    async function fetchAlerts() {
        try {
            const params = new URLSearchParams();
            if (deviceName) params.append('deviceName', deviceName);
            if (alertFilters.channelid) params.append('channelid', alertFilters.channelid);
            if (alertFilters.channelname) params.append('channelname', alertFilters.channelname);
            if (alertFilters.alertType) params.append('alertType', alertFilters.alertType);
            if (alertFilters.startDate) params.append('startDate', alertFilters.startDate);
            if (alertFilters.endDate) params.append('endDate', alertFilters.endDate);

            displayedAlerts = await apiGet(`/alerts?${params.toString()}`);
            currentPage = 1;
        } catch (e) { console.error(e); }
    }

    function handleResetAlertFilters() {
        alertFilters = { startDate: getStartOfDay(), endDate: getEndOfDay(), channelid: '', channelname: '',alertType: '' };
        fetchAlerts();
    }

    // 切换顶栏设备时：通道重置为「全通道」并按新设备重新检索（初次挂载也由此触发）
    let lastDevice = null;
    $: if (deviceName !== lastDevice) {
        lastDevice = deviceName;
        alertFilters.channelid = '';
        alertFilters.channelname = '';
        alertFilters.alertType = '';
        fetchAlerts();
    }

    async function handleAIAnalysis(alert) {
        aiLoadingIds[alert.id] = true;
        try {
            const data = await apiPost('/ai/analyze', { alert_id: alert.id });
            alert.remark = data.remark;
            displayedAlerts = [...displayedAlerts];
        } catch (e) {
            console.error(e);
        } finally {
            delete aiLoadingIds[alert.id];
            aiLoadingIds = { ...aiLoadingIds };
        }
    }

    function getAlertStyle(type) {
        switch (type) {
            case 'FIRE':
            case 'SMOKE':
            case 'INTRUSION': return 'bg-rose-500/10 text-rose-400';
            case 'TRIPWIRE': return 'bg-amber-500/10 text-amber-400';
            default: return 'bg-amber-500/10 text-amber-400';
        }
    }
</script>

<div class="flex flex-col h-full space-y-6">
    <div class="flex items-center gap-2 text-xs text-slate-400 shrink-0">
        <i class="fa-solid fa-video text-indigo-400"></i>
        当前设备：<strong class="text-slate-200">{deviceName || '未选择'}</strong>
        <span class="text-slate-600">·</span>
        预警数据已自动关联右上角所选设备
    </div>
    <div class="bg-slate-950 border border-slate-800 rounded-2xl p-5 shrink-0">
        <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-5 gap-4 items-end">
            <div class="flex flex-col space-y-1">
                <label class="text-xs text-slate-400 font-medium" for="start">开始时间</label>
                <input type="datetime-local" step="1" id="start" bind:value={alertFilters.startDate} class="bg-slate-900 border border-slate-800 text-slate-100 rounded-xl px-3 h-[38px] text-sm placeholder-slate-500 outline-none focus:border-indigo-500 w-full box-border" />
            </div>
            <div class="flex flex-col space-y-1">
                <label class="text-xs text-slate-400 font-medium" for="end">结束时间</label>
                <input type="datetime-local" step="1" id="end" bind:value={alertFilters.endDate} class="bg-slate-900 border border-slate-800 text-slate-100 rounded-xl px-3 h-[38px] text-sm placeholder-slate-500 outline-none focus:border-indigo-500 w-full box-border" />
            </div>
            <div class="flex flex-col space-y-1">
                <label class="text-xs text-slate-400 font-medium" for="chan">通道名称</label>
                <select id="chan" bind:value={alertFilters.channelid} class="bg-slate-900 border border-slate-800 text-slate-100 rounded-xl px-3 h-[38px] text-sm placeholder-slate-500 outline-none focus:border-indigo-500 w-full box-border">
                    <option value="">全通道</option>
                    {#each channelOptions as ch}<option value={ch.device_id}>{ch.display_name}</option>{/each}
                </select>
            </div>
            <div class="flex flex-col space-y-1">
                <label class="text-xs text-slate-400 font-medium" for="type">预警类型</label>
                <select id="type" bind:value={alertFilters.alertType} class="bg-slate-900 border border-slate-800 text-slate-100 rounded-xl px-3 h-[38px] text-sm placeholder-slate-500 outline-none focus:border-indigo-500 w-full box-border">
                    <option value="">全部类型</option>
                    
                    {#each algorithmsOptions as opt}
                        <optgroup label={getPackageLabel(opt.name)}>
                            {#each opt.cards || [] as t}<option value={t}>{getCardLabel(t)}</option>{/each}
                        </optgroup>
                    {/each}
                    {#if agentsOptions.length > 0}
                        <optgroup label="Agents">
                            {#each agentsOptions as ag}
                                <option value={ag.agent_id}>{ag.agent_name}</option>
                            {/each}
                        </optgroup>
                    {/if}
                </select>
            </div>
            <div class="flex space-x-3 lg:justify-end">
                <button on:click={handleResetAlertFilters} class="bg-slate-900 hover:bg-slate-800 text-slate-300 border border-slate-800 rounded-xl h-[38px] px-4 text-sm font-medium flex items-center justify-center flex-1 lg:flex-none box-border">
                    <i class="fa-solid fa-arrows-rotate text-sm mr-2"></i> 重置
                </button>
                <button on:click={fetchAlerts} class="bg-indigo-600 hover:bg-indigo-700 text-white rounded-xl h-[38px] px-4 text-sm font-bold shadow-sm flex items-center justify-center flex-1 lg:flex-none box-border">
                    <i class="fa-solid fa-magnifying-glass text-sm mr-2"></i> 检索
                </button>
            </div>
        </div>
    </div>

    <div class="flex-1 overflow-auto pb-4">
        {#if displayedAlerts.length > 0}
            <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-6">
                {#each paginatedAlerts as alert}
                    <div class="bg-slate-950 border border-slate-800 rounded-2xl overflow-hidden flex flex-col">
                        <div class="relative aspect-video bg-slate-900 flex items-center justify-center border-b border-slate-800 overflow-hidden group">
                            {#if alert.imageUrl}
                                <img src="{API_BASE}{alert.imageUrl}" alt="抓拍图片" class="w-full h-full object-cover object-center cursor-zoom-in transition-transform duration-300 group-hover:scale-105" on:dblclick={() => openViewer(`${API_BASE}${alert.imageUrl}`)} title="双击查看大图" />
                            {:else}
                                <div class="flex flex-col items-center text-slate-500">
                                    <i class="fa-solid fa-camera text-3xl mb-2 opacity-50"></i>
                                    <span class="text-xs">无实时抓拍图像</span>
                                </div>
                            {/if}
                            <div class="absolute top-3 right-3 px-2 py-1 rounded text-xs font-bold {getAlertStyle(alert.alertType)}">{alert.alertType}</div>
                        </div>
                        <div class="p-4 flex flex-col flex-1">
                            <h3 class="text-sm font-bold text-slate-100 mb-2 truncate" title={alert.deviceName}>{alert.deviceName}</h3>
                            <div class="flex items-center text-xs text-slate-500 mb-3"><i class="fa-solid fa-clock text-xs mr-1.5"></i>{alert.time}</div>
                            <div class="mt-auto pt-3 border-t border-slate-800">
                                <div class="flex justify-between items-start mb-1">
                                    <span class="text-xs font-medium text-slate-500">备注与建议：</span>
                                    <button on:click={() => handleAIAnalysis(alert)} disabled={aiLoadingIds[alert.id]} class="text-xs flex items-center text-indigo-400 bg-indigo-500/10 hover:bg-indigo-500/20 px-2 py-1 rounded-lg disabled:opacity-50">
                                        <i class="fa-solid {aiLoadingIds[alert.id] ? 'fa-arrows-rotate animate-spin' : 'fa-wand-magic-sparkles'} text-[10px] mr-1"></i>
                                        {aiLoadingIds[alert.id] ? 'AI思考中' : 'AI 分析'}
                                    </button>
                                </div>
                                <p class="text-sm text-slate-300 min-h-[40px] bg-slate-900 border border-slate-800 p-2 rounded-lg cursor-default" title={alert.remark || ''}>
                                    {alert.remark ? (alert.remark.length > 24 ? alert.remark.slice(0, 24) + '...' : alert.remark) : ''}
                                </p>
                            </div>
                        </div>
                    </div>
                {/each}
            </div>

            {#if totalPages > 1}
            <div class="flex justify-center items-center space-x-4 mt-8 pb-4">
                <button
                    disabled={currentPage === 1}
                    on:click={() => currentPage--}
                    class="bg-slate-900 hover:bg-slate-800 border border-slate-800 text-slate-300 rounded-xl px-4 py-2 text-sm font-medium disabled:opacity-50 disabled:cursor-not-allowed flex items-center"
                >
                    <i class="fa-solid fa-chevron-left text-sm mr-1"></i> 上一页
                </button>
                <span class="text-sm font-medium text-slate-400">第 {currentPage} 页 / 共 {totalPages} 页</span>
                <button
                    disabled={currentPage === totalPages}
                    on:click={() => currentPage++}
                    class="bg-slate-900 hover:bg-slate-800 border border-slate-800 text-slate-300 rounded-xl px-4 py-2 text-sm font-medium disabled:opacity-50 disabled:cursor-not-allowed flex items-center"
                >
                    下一页 <i class="fa-solid fa-chevron-right text-sm ml-1"></i>
                </button>
            </div>
            {/if}
        {:else}
            <div class="h-full flex flex-col items-center justify-center text-slate-500"><i class="fa-solid fa-magnifying-glass text-5xl mb-4 opacity-30"></i><p>未检索到相关的预警抓拍数据</p></div>
        {/if}
    </div>
</div>

{#if viewerImage}
<!-- svelte-ignore a11y-click-events-have-key-events -->
<!-- svelte-ignore a11y-no-static-element-interactions -->
<div class="fixed inset-0 z-[100] flex items-center justify-center bg-black/80 backdrop-blur-sm" on:click={closeViewer}>
    <div class="relative max-w-[90vw] max-h-[90vh]">
        <img src={viewerImage} alt="大图" class="max-w-full max-h-[90vh] object-contain rounded-lg shadow-2xl" on:click|stopPropagation />
        <button class="absolute -top-12 right-0 text-white/70 hover:text-white transition-colors" on:click={closeViewer} title="关闭">
            <i class="fa-solid fa-xmark text-2xl"></i>
        </button>
    </div>
</div>
{/if}
