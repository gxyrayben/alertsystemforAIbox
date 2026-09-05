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
    analysis_interval 为【任务级】全局分析间隔（秒）。
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
) -> dict:
    """算法仓任务第二步 monitor。

    agent_llm 非空时挂载 aiotapCustom.agentLLMParam 并切换 analysis_mode=full_analysis，
    即『小+大』任务；为空则是『纯小模型』任务。
    monitor_id 缺省由 task_id 派生（单 BOX 内简化的唯一 id 方案）。
    """
    area = area or full_frame_area()
    target_types = target_types or ["PERSON"]
    if monitor_id is None:
        try:
            monitor_id = int(task_id)
        except (TypeError, ValueError):
            monitor_id = 1

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
        extend_params["aiotapCustom"] = {"agentLLMParam": agent_llm}
        extend_params["analysis_mode"] = "full_analysis"
        extend_params["target_expand"] = {"left": 0.4, "top": 0.5, "right": 0.6, "bottom": 0.3}

    return {
        "common_param": {
            "task_id": task_id,
            "alg_type": ["bypass"],
            "channel_id": 0,
            "channel_type": 1,
            "device_id": channel_device_id,
            "enable": True,
            "monitor_id": monitor_id,
            "monitor_name": monitor_name or f"monitor_{event_type}",
            "warehouse_v20_param": {
                "labels": {"algoCabinName": algo_cabin_name, "version": version},
                "rulesParams": [
                    {
                        "areas": [area],
                        "eventType": event_type,
                        "ruleId": 1,
                        "extendParams": extend_params,
                    }
                ],
            },
        },
        "extend_param": {"aiotap_box_param": {"warehouse_param": {"enable": True}}},
    }


def build_agent_llm_param(agent: dict, prompt: Optional[str] = None,
                          alarm_condition: Optional[str] = None) -> dict:
    """由智能体算法项构造『小+大』任务 monitor 里的 agentLLMParam。"""
    return {
        "event_id": agent.get("event_id"),
        "event_tag": agent.get("event_tag"),
        "alarm_type": agent.get("alarm_type", "freeform"),
        "prompt": prompt if prompt is not None else agent.get("prompt", ""),
        "alarm_condition": alarm_condition or _default_alarm_condition(agent.get("alarm_type")),
        "filter": "",
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
    if task:
        if task.get("task_name"):
            cfg["name"] = task.get("task_name")
        if task.get("analysis_interval") is not None:
            cfg["interval"] = task.get("analysis_interval")

    # 纯大模型任务：无 monitor，从 agent_list 还原多智能体 + 每智能体 ROI 绑定
    if cfg["taskMode"] == "agent":
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
    if "threshold" in ep:
        # payload 仅一个 threshold，对齐前端人体阈值（车辆/非机动车阈值无来源，前端保持默认）
        cfg["yoloHumanThresh"] = ep.get("threshold")
    if ep.get("targetTypes"):
        cfg["yoloTarget"] = _target_type_to_yolo(ep.get("targetTypes"))

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

    # 小+大任务的二次大模型参数
    agent_llm = (ep.get("aiotapCustom") or {}).get("agentLLMParam") or {}
    if agent_llm.get("event_tag"):
        cfg["agentType"] = agent_llm.get("event_tag")
    if agent_llm.get("prompt"):
        cfg["prompt"] = agent_llm.get("prompt")

    return cfg


def _first_rule(mon: Optional[dict]) -> Optional[dict]:
    """从 monitor 取 common_param.warehouse_v20_param.rulesParams[0]，任意层缺失返回 None。"""
    if not mon:
        return None
    warehouse = (mon.get("common_param") or {}).get("warehouse_v20_param") or {}
    rules = warehouse.get("rulesParams") or []
    return rules[0] if rules else None


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
