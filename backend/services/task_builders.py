"""三类布控任务的下发 payload 纯函数构造器（无 I/O，便于单测）。

对应设备接口：
- 纯大模型（智能体任务）→ build_agent_task_payload → POST /intelli_manager/task (agent_real_task)
- 纯小模型（算法仓任务）→ build_single_point_task_payload + build_monitor_payload(无 agent_llm)
- 小+大（算法仓+二次大模型）→ build_single_point_task_payload + build_monitor_payload(带 agent_llm)

默认值遵循「合理默认 + 对话可覆盖」：全画面检测区域、间隔 5s、阈值 0.3、目标 PERSON。
"""
from typing import List, Optional


def full_frame_area(area_id: int = 1, name: str = "区域1") -> dict:
    """默认全画面四角多边形检测区（归一化坐标 0~1）。"""
    return {
        "areaId": area_id,
        "areaName": name,
        "areaType": "POLYGON",
        "points": [
            {"x": 0.0, "y": 0.0},
            {"x": 1.0, "y": 0.0},
            {"x": 1.0, "y": 1.0},
            {"x": 0.0, "y": 1.0},
        ],
    }


def roi_area(points) -> dict:
    """给定归一化多边形点则构造检测区（areaName=检测区/POLYGON），为空则回退全画面。"""
    if points:
        return {"areaId": 1, "areaName": "检测区", "areaType": "POLYGON", "points": points}
    return full_frame_area()


def index_agents(data: dict) -> dict:
    """把设备智能体列表响应按 event_id / agent_id 建索引，供存在校验与字段兜底。"""
    index = {}
    for a in data.get("data", {}).get("list", []):
        for key in (a.get("event_id"), a.get("agent_id")):
            if key is not None:
                index[str(key)] = a
    return index


def _default_alarm_condition(alarm_type: Optional[str]) -> str:
    """按智能体报警类型给出默认报警条件：判断型(yesno)→only_yes，描述型(freeform)→none。"""
    return "only_yes" if (alarm_type or "").lower() == "yesno" else "none"


def build_agent_config(agent: dict, area: Optional[dict] = None) -> dict:
    """由一个「已富化 agent 项」构造 agent_real_task 中单个 agent_list[i].agent_config。

    agent 可含：alarm_type / prompt / alarm_condition / filter_enable / filter_keywords。
    - alarm_condition 缺省按 alarm_type 推导；
    - filter_enable 关闭时强制清空 filter_keywords（避免下发无意义的过滤词）；
    - areas 恒为单 ROI（缺省全画面），符合「每个智能体只关联一个检测区」。
    """
    area = area or full_frame_area()
    filter_enable = bool(agent.get("filter_enable", False))
    return {
        "schedule_plan_id": "1",
        "alarm_condition": agent.get("alarm_condition") or _default_alarm_condition(agent.get("alarm_type")),
        "prompt": agent.get("prompt", "") or "",
        "filter_enable": filter_enable,
        "filter_keywords": (agent.get("filter_keywords") or "") if filter_enable else "",
        "areas": [area],
    }


def build_agent_real_task_payload(
    task_name: str,
    channel_device_id: int,
    agents: List[dict],
    analysis_interval: int = 5,
) -> dict:
    """纯大模型智能体任务（agent_real_task），单步下发；支持关联多个智能体（≤4）。

    agents 为已富化的智能体项列表，每项需含 event_id / event_tag，其余字段（prompt /
    alarm_condition / alarm_type / filter_enable / filter_keywords / area）交给 build_agent_config 兜底。
    analysis_interval 为【任务级】全局分析间隔（秒），仅智能体任务有此概念。
    """
    agent_list = [
        {
            "event_id": a.get("event_id"),
            "event_tag": a.get("event_tag"),
            "agent_config": build_agent_config(a, a.get("area")),
        }
        for a in agents
    ]
    return {
        "task_name": task_name,
        "task_type": "agent_real_task",
        "device_list": [{"device_id": channel_device_id}],
        "enable": True,
        "schedule_plan_id": "1",
        "analysis_interval": analysis_interval,
        "agent_list": agent_list,
    }


def build_agent_task_payload(
    task_name: str,
    channel_device_id: int,
    agent: dict,
    prompt: Optional[str] = None,
    alarm_condition: Optional[str] = None,
    analysis_interval: int = 5,
    area: Optional[dict] = None,
) -> dict:
    """纯大模型智能体任务（单智能体便捷入口，供 agent_tools.create_agent_task 复用）。

    agent 为设备 agent_list 中命中的一项，需含 event_id / event_tag / alarm_type / prompt。
    prompt / alarm_condition 缺省时沿用智能体自身配置；内部委托到 build_agent_real_task_payload，
    行为与旧版一致（filter_enable=False / filter_keywords=""）。
    """
    enriched = {
        "event_id": agent.get("event_id"),
        "event_tag": agent.get("event_tag"),
        "alarm_type": agent.get("alarm_type"),
        "prompt": prompt if prompt is not None else agent.get("prompt", ""),
        "alarm_condition": alarm_condition or _default_alarm_condition(agent.get("alarm_type")),
        "filter_enable": False,
        "filter_keywords": "",
        "area": area or full_frame_area(),
    }
    return build_agent_real_task_payload(task_name, channel_device_id, [enriched], analysis_interval)


def build_single_point_task_payload(
    task_name: str,
    channel_device_id: int,
    event_type: str,
    analysis_interval: int = 5,
) -> dict:
    """算法仓任务第一步（single_point_task），返回体含 data.task_id，供 monitor 使用。"""
    return {
        "task_name": task_name,
        "task_type": "single_point_task",
        "device_list": [{"device_id": channel_device_id}],
        "enable": True,
        "schedule_plan_id": "1",
        "analysis_interval": analysis_interval,
        "agent_list": [
            {
                "event_id": event_type,
                "agent_config": {"schedule_plan_id": "1", "alarm_condition": "none"},
            }
        ],
    }


def build_rule(
    event_type: str,
    area: Optional[dict] = None,
    target_types: Optional[List[str]] = None,
    threshold: float = 0.3,
    target_max: int = 1,
    target_min: int = 0,
    duration: int = 3,
    cooldown: int = 600,
    agent_llm: Optional[dict] = None,
    target_expand: Optional[dict] = None,
    rule_id: int = 1,
) -> dict:
    """构造 monitor.warehouse_v20_param.rulesParams 中的【单条规则】(= 一个小模型算法)。

    一个算法的唯一身份 = (算法仓 algoCabinName, eventType)：同一算法仓内可挂多条规则，
    每条对应一个 eventType；build_warehouse_monitor 会把多条规则组装进同一条 monitor。
    agent_llm 非空时该规则为『小+大』：挂 aiotapCustom.agentLLMParam、切 full_analysis、
    带扩图 target_expand（缺省对称默认值）。ruleId 由 build_warehouse_monitor 统一重排为 1..N。
    """
    area = area or full_frame_area()
    target_types = target_types or ["PERSON"]
    extend_params = {
        "targetMax": target_max,
        "targetMin": target_min,
        "duration": duration,
        "cooldownDuration": cooldown,
        "threshold": threshold,
        "targetTypes": target_types,
        "level": "ALARM_LEVEL",
    }
    if agent_llm:
        extend_params["aiotapCustom"] = {"agentLLMParam": agent_llm} ### 这里不对 gxyrayben 
        extend_params["analysis_mode"] = "full_analysis"
        extend_params["target_expand"] = target_expand or {"left": 0.4, "top": 0.5, "right": 0.6, "bottom": 0.3}
    return {
        "areas": [area],
        "eventType": event_type,
        "ruleId": rule_id,
        "extendParams": extend_params,
    }


def build_warehouse_monitor(
    task_id,
    channel_device_id: int,
    algo_cabin_name: str,
    rules: List[dict],
    version: str = "V2.0.0",
    monitor_id: Optional[int] = None,
    monitor_name: Optional[str] = None,
    enable: bool = True,
) -> dict:
    """把【同一算法仓】的多条规则(rulesParams)组装成一条 monitor。

    设备存储模型：一个算法仓 = 一条 monitor，可挂多条 rulesParams（各对应一个 eventType）；
    跨算法仓时则是【共享同一 monitor_id】的多条 monitor（靠 labels.algoCabinName 区分）。
    create_monitor 以 (monitor_id + algoCabinName) 为键覆盖该仓 monitor 的整份 rulesParams，
    故增/改/删单个算法都要把该仓【全部保留的规则】一次性传入。rules 内 ruleId 重排为 1..N。
    enable=False 用于『停用』降级（无硬删除接口时，清空算法/清除任务以覆盖方式停用而非删除）。
    monitor_id 缺省由 task_id 派生（单 BOX 内简化的唯一 id 方案）。
    """
    if monitor_id is None:
        try:
            monitor_id = int(task_id)
        except (TypeError, ValueError):
            monitor_id = 1
    norm_rules = []
    for idx, rule in enumerate(rules or [], start=1):
        r = dict(rule)
        r["ruleId"] = idx
        norm_rules.append(r)
    first_event = (norm_rules[0].get("eventType") if norm_rules else None) or "warehouse"
    return {
        "common_param": {
            "task_id": task_id,
            "alg_type": ["bypass"],
            "channel_id": 0,
            "channel_type": 1,
            "device_id": channel_device_id,
            "enable": enable,
            "monitor_id": monitor_id,
            "monitor_name": monitor_name or f"monitor_{first_event}",
            "warehouse_v20_param": {
                "labels": {"algoCabinName": algo_cabin_name, "version": version},
                "rulesParams": norm_rules,
            },
        },
        "extend_param": {"aiotap_box_param": {"warehouse_param": {"enable": enable}}},
    }


def build_monitor_payload(
    task_id,
    channel_device_id: int,
    event_type: str,
    algo_cabin_name: str,
    version: str = "V2.0.0",
    monitor_id: Optional[int] = None,
    monitor_name: Optional[str] = None,
    area: Optional[dict] = None,
    target_types: Optional[List[str]] = None,
    threshold: float = 0.3,
    target_max: int = 1,
    target_min: int = 0,
    duration: int = 3,
    cooldown: int = 600,
    agent_llm: Optional[dict] = None,
    target_expand: Optional[dict] = None,
) -> dict:
    """算法仓任务第二步 monitor（【单算法】便捷入口，委托到 build_rule + build_warehouse_monitor）。

    agent_llm 非空时挂载 aiotapCustom.agentLLMParam 并切换 analysis_mode=full_analysis，
    即『小+大』任务；为空则是『纯小模型』任务。
    target_expand 为『小+大』任务的扩图策略（缺省对称默认值），仅在 agent_llm 非空分支内生效。
    monitor_id 缺省由 task_id 派生（单 BOX 内简化的唯一 id 方案）。
    需要在同一算法仓挂多条算法、或跨仓增删改时，请直接用 build_rule + build_warehouse_monitor。
    """
    rule = build_rule(
        event_type=event_type,
        area=area,
        target_types=target_types,
        threshold=threshold,
        target_max=target_max,
        target_min=target_min,
        duration=duration,
        cooldown=cooldown,
        agent_llm=agent_llm,
        target_expand=target_expand,
    )
    return build_warehouse_monitor(
        task_id,
        channel_device_id,
        algo_cabin_name,
        [rule],
        version=version,
        monitor_id=monitor_id,
        monitor_name=monitor_name,
    )


def build_agent_llm_param(agent: dict, prompt: Optional[str] = None,
                          alarm_condition: Optional[str] = None) -> dict:
    """由智能体算法项构造『小+大』任务 monitor 里的 agentLLMParam。

    agent 可含 filter_enable / filter_keywords（仅描述型 freeform 有意义），语义与
    build_agent_config 一致：关闭过滤时强制清空关键词，避免下发无意义的过滤词。
    """
    filter_enable = bool(agent.get("filter_enable", False))
    return {
        "event_id": agent.get("event_id"),
        "event_tag": agent.get("event_tag"),
        "alarm_type": agent.get("alarm_type", "freeform"),
        "prompt": prompt if prompt is not None else agent.get("prompt", ""),
        "alarm_condition": alarm_condition or _default_alarm_condition(agent.get("alarm_type")),
        "filter": "",
        "filter_enable": filter_enable,
        "filter_keywords": (agent.get("filter_keywords") or "") if filter_enable else "",
    }


def _target_type_to_yolo(target_types: Optional[List[str]]) -> str:
    """monitor 的 targetTypes[0] → 面板 yoloTarget（PERSON→human / VEHICLE→vehicle / 其它→any）。"""
    first = (target_types or ["PERSON"])[0]
    up = (first or "").upper()
    if up == "PERSON":
        return "human"
    if up == "VEHICLE":
        return "vehicle"
    return "any"


def _thresh_key(target_types: Optional[List[str]]) -> str:
    """检测目标 → 面板阈值字段名。

    设备侧一条规则只有一个 threshold，面板按『人体/车辆/非机动车』分三个字段存放；
    回填时必须落到与 targetTypes 对应的那个字段，否则车辆算法的阈值会被写进人体阈值里。
    """
    mode = _target_type_to_yolo(target_types)
    if mode == "vehicle":
        return "yoloVehicleThresh"
    if mode == "human":
        return "yoloHumanThresh"
    return "yoloNonMotorThresh"


def _task_identity(task: dict) -> dict:
    """从设备任务项提取面板『编辑保存』所需的身份字段：task_id + 首通道 channel_device_id。

    缺了它们，从列表进入编辑态后无法定位要更新的设备任务（会退化成新建一条重复任务）。
    """
    ident: dict = {}
    if not task:
        return ident
    if task.get("task_id") is not None:
        ident["task_id"] = task.get("task_id")
    dev_list = task.get("device_list") or []
    first = dev_list[0] if dev_list and isinstance(dev_list[0], dict) else {}
    if first.get("device_id") is not None:
        ident["channel_device_id"] = first.get("device_id")
    return ident


def _is_full_frame(points: Optional[List[dict]]) -> bool:
    """近似判定一组归一化点是否为全画面矩形（四角 0/1，容差 0.02）。"""
    pts = points or []
    if len(pts) != 4:
        return False
    corners = {(round(p.get("x", -9)), round(p.get("y", -9))) for p in pts}
    return corners == {(0, 0), (1, 0), (1, 1), (0, 1)} and all(
        abs(p.get("x", 0) - round(p.get("x", 0))) < 0.02 and abs(p.get("y", 0) - round(p.get("y", 0))) < 0.02
        for p in pts
    )


def _task_mode(task: dict, mon: Optional[dict]) -> str:
    """任务类型 → 面板分支标识：agent（纯大模型）/ combined（小+大）/ smallmodel（纯小模型）。"""
    if (task or {}).get("task_type") == "agent_real_task":
        return "agent"
    rule = _first_rule(mon)
    ep = (rule or {}).get("extendParams") or {}
    if (ep.get("aiotapCustom") or {}).get("agentLLMParam"):
        return "combined"
    return "smallmodel"


def _agent_task_panel(task: dict) -> dict:
    """纯大模型任务(agent_real_task) → 面板 config 的 agents[] / rois[] / activeAgentIndex 还原。

    每个 agent 的检测区在其 agent_config.areas[0]；全画面归一化到共享的 'full' 项，
    其余各自生成 '检测区N' 并让该 agent 的 roiId 指向它（每 agent 单 ROI）。
    注意：task_list 无 alarm_type，故 agents[].alarm_type 缺省，属性型开关在查看模式 best-effort。
    """
    rois = [{"id": "full", "name": "全屏检测", "points": []}]
    agents = []
    for i, item in enumerate((task or {}).get("agent_list") or []):
        item = item or {}
        cfg = item.get("agent_config") or {}
        areas = cfg.get("areas") or []
        points = (areas[0].get("points") if areas and isinstance(areas[0], dict) else None) or []
        if points and not _is_full_frame(points):
            roi_id = f"roi_{i}"
            rois.append({"id": roi_id, "name": f"检测区{len(rois)}", "points": points})
        else:
            roi_id = "full"
        agents.append({
            "event_id": item.get("event_id"),
            "event_tag": item.get("event_tag"),
            "prompt": cfg.get("prompt", ""),
            "alarm_condition": cfg.get("alarm_condition"),
            "filter_enable": bool(cfg.get("filter_enable", False)),
            "filter_keywords": cfg.get("filter_keywords", "") or "",
            "roiId": roi_id,
        })
    return {"agents": agents, "rois": rois, "activeAgentIndex": 0}


def monitor_to_panel_config(task: dict, mon: Optional[dict]) -> dict:
    """build_monitor_payload 的逆映射：把设备任务 + monitor 还原为右侧控制面板可直接回填的 config。

    纯函数、无 I/O，与 build_monitor_payload 结构对称，便于单测。
    - task：设备 task_list 中的一项（提供 task_name / analysis_interval / agent_list）；
    - mon：对应 monitor（common_param.warehouse_v20_param.rulesParams[0] 提供 eventType/areas/extendParams）；
      为 None 时（纯大模型任务无 monitor）只回填 task + agent_list 能提供的字段。
    与前端 defaultConfig 未覆盖的键由前端 `{...defaultConfig, ...detail}` 兜底，故此处只输出确有依据的键。
    """
    cfg: dict = {}
    cfg["taskMode"] = _task_mode(task, mon)
    cfg.update(_task_identity(task))
    if task:
        if task.get("task_name"):
            cfg["name"] = task.get("task_name")

    # 纯大模型任务：无 monitor，从 agent_list 还原多智能体 + 每智能体 ROI 绑定
    if cfg["taskMode"] == "agent":
        # 分析间隔仅【智能体任务】有此概念（小模型/小+大为实时分析，无分析间隔）
        if task and task.get("analysis_interval") is not None:
            cfg["interval"] = task.get("analysis_interval")
        cfg.update(_agent_task_panel(task))
        agent_list = (task or {}).get("agent_list") or []
        if agent_list:
            first_agent = agent_list[0] or {}
            if first_agent.get("event_tag"):
                cfg["agentType"] = first_agent.get("event_tag")
        return cfg

    rule = _first_rule(mon)
    if not rule:
        return cfg

    if rule.get("eventType"):
        cfg["alertType"] = rule.get("eventType")
    areas = rule.get("areas") or []
    if areas and isinstance(areas[0], dict):
        cfg["roiPoints"] = areas[0].get("points") or []

    ep = rule.get("extendParams") or {}
    if "targetMax" in ep:
        cfg["maxTarget"] = ep.get("targetMax")
    if "targetMin" in ep:
        cfg["minTarget"] = ep.get("targetMin")
    if "duration" in ep:
        cfg["intrusionDuration"] = ep.get("duration")
    if "cooldownDuration" in ep:
        cfg["alarmInterval"] = ep.get("cooldownDuration")
    if ep.get("targetTypes"):
        cfg["yoloTarget"] = _target_type_to_yolo(ep.get("targetTypes"))
        # 面板检测目标支持多选：原样带回设备的 targetTypes
        cfg["yoloTargets"] = list(ep.get("targetTypes") or [])
    if "threshold" in ep:
        # payload 仅一个 threshold，按 targetTypes 落到对应的面板阈值字段（其余阈值无来源，保持默认）
        cfg[_thresh_key(ep.get("targetTypes"))] = ep.get("threshold")

    # 扩图区域仅『小+大』任务的 monitor 才有 target_expand
    expand = ep.get("target_expand") or {}
    if expand:
        if "top" in expand:
            cfg["cropUp"] = expand.get("top")
        if "bottom" in expand:
            cfg["cropDown"] = expand.get("bottom")
        if "left" in expand:
            cfg["cropLeft"] = expand.get("left")
        if "right" in expand:
            cfg["cropRight"] = expand.get("right")

    return cfg


def _rule_to_algorithm(rule: dict, algo_cabin_name: Optional[str], version: str, rois: List[dict]) -> dict:
    """把一条 rulesParams 规则抽取为面板 algorithms[] 中的一项，并把其 ROI 归入共享池 rois。

    字段抽取与 monitor_to_panel_config 一致（阈值/目标/时长/冷却/扩图/二次大模型），但产出【逐算法】形状：
    kind + event_type + algo_cabin_name + 各参数 + 绑定池 ROI 的 roiId（全画面归一化到 'full'）。
    rois 为共享池，就地追加非全画面 ROI（每条算法各自一个 ROI，直接兑现『不同算法不同 ROI』）。
    """
    ep = rule.get("extendParams") or {}
    agent_llm = (ep.get("aiotapCustom") or {}).get("agentLLMParam") or {}
    kind = "combined" if agent_llm else "small"

    areas = rule.get("areas") or []
    points = (areas[0].get("points") if areas and isinstance(areas[0], dict) else None) or []
    if points and not _is_full_frame(points):
        roi_id = f"roi_{len(rois)}"
        rois.append({"id": roi_id, "name": f"检测区{len(rois)}", "points": points})
        use_full = False
    else:
        roi_id = "full"
        use_full = True

    item: dict = {
        "kind": kind,
        "event_type": rule.get("eventType"),
        "algo_cabin_name": algo_cabin_name,
        "version": version,
        "roiId": roi_id,
        "useFullFrame": use_full,
    }
    if "targetMax" in ep:
        item["maxTarget"] = ep.get("targetMax")
    if "targetMin" in ep:
        item["minTarget"] = ep.get("targetMin")
    if "duration" in ep:
        item["intrusionDuration"] = ep.get("duration")
    if "cooldownDuration" in ep:
        item["alarmInterval"] = ep.get("cooldownDuration")
    if ep.get("targetTypes"):
        item["yoloTarget"] = _target_type_to_yolo(ep.get("targetTypes"))
        # 面板检测目标支持多选：原样带回设备的 targetTypes（yoloTarget 为其首项推导出的主目标）
        item["yoloTargets"] = list(ep.get("targetTypes") or [])
    if "threshold" in ep:
        # payload 仅一个 threshold，按 targetTypes 落到对应的面板阈值字段（其余阈值无来源，保持默认）
        item[_thresh_key(ep.get("targetTypes"))] = ep.get("threshold")

    # 扩图区域仅『小+大』规则才有 target_expand
    expand = ep.get("target_expand") or {}
    if expand:
        if "top" in expand:
            item["cropUp"] = expand.get("top")
        if "bottom" in expand:
            item["cropDown"] = expand.get("bottom")
        if "left" in expand:
            item["cropLeft"] = expand.get("left")
        if "right" in expand:
            item["cropRight"] = expand.get("right")

    # 『小+大』规则的二次大模型参数（面板第③步「级联后置多模态 Agent」展示的全量字段）
    if agent_llm.get("event_id"):
        item["agent_id"] = agent_llm.get("event_id")
        # agentType 是面板下拉的选中值，其 option value 为 event_id，故必须回填 event_id 而非 event_tag
        item["agentType"] = agent_llm.get("event_id")
    if agent_llm.get("event_tag"):
        item["event_tag"] = agent_llm.get("event_tag")
    if agent_llm.get("prompt"):
        item["prompt"] = agent_llm.get("prompt")
    if agent_llm.get("alarm_type"):
        item["alarm_type"] = agent_llm.get("alarm_type")
    if agent_llm.get("alarm_condition"):
        item["alarm_condition"] = agent_llm.get("alarm_condition")
    if "filter_enable" in agent_llm:
        item["filter_enable"] = bool(agent_llm.get("filter_enable"))
    if agent_llm.get("filter_keywords"):
        item["filter_keywords"] = agent_llm.get("filter_keywords")

    return item


def monitors_to_panel_config(task: dict, monitors: Optional[List[dict]]) -> dict:
    """把设备任务 + 其【全部 monitor / 全部 rulesParams】逆映射为面板可回填 config（多算法版）。

    与 _agent_task_panel 对称：产出共享 ROI 池 rois[] + 逐算法 algorithms[]（每条算法各自绑定池 ROI）。
    - 纯大模型任务（无 monitor）→ 委托 monitor_to_panel_config 走 agent 分支（agents[]/rois[]）。
    - 算法仓任务 → 遍历所有 monitor 的所有 rulesParams，每条规则一项 algorithms[]，
      taskMode=任一规则含 agentLLMParam 即 combined 否则 smallmodel。
    纯函数、无 I/O，供快照 detail 烘焙使用（替代只读 rulesParams[0] 的旧单算法逆映射）。
    与前端 defaultConfig 未覆盖的键由前端 `{...defaultConfig, ...detail}` 兜底。
    """
    if (task or {}).get("task_type") == "agent_real_task":
        return monitor_to_panel_config(task, None)

    cfg: dict = {}
    cfg.update(_task_identity(task))
    if task and task.get("task_name"):
        cfg["name"] = task.get("task_name")

    rois: List[dict] = [{"id": "full", "name": "全屏检测", "points": []}]
    algorithms: List[dict] = []
    mode = "smallmodel"
    for mon in monitors or []:
        cabin = _algo_cabin_name(mon)
        warehouse = (mon.get("common_param") or {}).get("warehouse_v20_param") or {}
        version = (warehouse.get("labels") or {}).get("version") or "V2.0.0"
        for rule in _warehouse_rules(mon):
            item = _rule_to_algorithm(rule, cabin, version, rois)
            if item.get("kind") == "combined":
                mode = "combined"
            algorithms.append(item)

    cfg["taskMode"] = mode
    cfg["algorithms"] = algorithms
    cfg["rois"] = rois
    cfg["activeAlgorithmIndex"] = 0
    return cfg


def _first_rule(mon: Optional[dict]) -> Optional[dict]:
    """从 monitor 取 common_param.warehouse_v20_param.rulesParams[0]，任意层缺失返回 None。"""
    if not mon:
        return None
    warehouse = (mon.get("common_param") or {}).get("warehouse_v20_param") or {}
    rules = warehouse.get("rulesParams") or []
    return rules[0] if rules else None


def _warehouse_rules(mon: Optional[dict]) -> List[dict]:
    """从 monitor 取整份 common_param.warehouse_v20_param.rulesParams（多算法同仓时不止一条）。缺失返回 []。"""
    if not mon:
        return []
    warehouse = (mon.get("common_param") or {}).get("warehouse_v20_param") or {}
    return warehouse.get("rulesParams") or []


def _algo_cabin_name(mon: Optional[dict]) -> Optional[str]:
    """从 monitor 取算法仓名 common_param.warehouse_v20_param.labels.algoCabinName（缺失返回 None）。"""
    if not mon:
        return None
    warehouse = (mon.get("common_param") or {}).get("warehouse_v20_param") or {}
    return (warehouse.get("labels") or {}).get("algoCabinName")


def build_agent_item_payload(event_id: str, event_tag: str, prompt: str,
                             alarm_type: str = "freeform",
                             alarm_condition: Optional[str] = None) -> dict:
    """新建智能体算法（agent_item）请求体。agent_id=event_id, agent_name=event_tag。"""
    return {
        "event_id": event_id,
        "event_tag": event_tag,
        "agent_id": event_id,
        "agent_name": event_tag,
        "prompt": prompt,
        "alarm_type": alarm_type,
        "alarm_condition": alarm_condition or _default_alarm_condition(alarm_type),
    }
