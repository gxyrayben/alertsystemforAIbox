"""BOX设备任务管理智能体工具定义与执行层。

工具分两类：
- 平台本地台账：list_devices / list_tasks / create_task / update_task（操作 TaskORM）
- 设备侧能力与布控：get_device_streams / get_device_control_tasks（快照）+
  check_algorithm_authorization / list_device_algorithms / list_agents / create_agent /
  create_smallmodel_task / create_agent_task / create_combined_task（实时调设备 API）
"""
import json, uuid, time
from typing import Optional
import httpx
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from models.orm import DeviceORM, TaskORM, TaskTemplateORM
from services.device_service import DeviceService, MONITOR_LIST_PATH
from services import task_builders as tb
from services import scene_presets

_HTTP_TIMEOUT = 15.0


def _load_json(raw):
    """安全解析 DeviceORM 上以 JSON 字符串存储的字段（channels / device_tasks）。"""
    try:
        return json.loads(raw or "[]")
    except Exception:
        return []


def _err(msg: str) -> str:
    return json.dumps({"error": msg}, ensure_ascii=False)


def _ok(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False)


def _preview(text: str, limit: int = 40) -> str:
    """把长文本（如智能体 prompt）压成单行简短预览，用于依赖校验类查询，避免上下文膨胀。"""
    s = " ".join((text or "").split())
    return s if len(s) <= limit else s[:limit] + "…"


async def _get_device(db: AsyncSession, device_id: str):
    return (await db.execute(
        select(DeviceORM).where(DeviceORM.device_id == device_id)
    )).scalar_one_or_none()


# ── 小模型算法【中文名 ↔ 算法ID】映射目录 ──────────────────────────────────
# 背景：设备算法仓卡片(card_cap)返回英文算法ID（major_type/minor_type，其中布控
# 用的 event_type = minor_type，如 INTRUSION/FALL）；界面呈现与用户配置任务用中文名
# （如 区域入侵/摔倒）。此目录维护二者对应关系：list_device_algorithms 用它补中文名
# eventName（ID→中文）；resolve_algorithm 工具用它把中文名解析为 event_type（中文→ID）。
# 数据来源：MegCube-B5Z 智能体分析盒常用 API 协议文档（算法仓能力集）。
# 每组 (major_type, major_name, [(minor_type, event_name), ...])；同一 major_type 多次
# 出现（如 alert_alarm 覆盖『周界警戒/行为警戒』）会在建索引时合并；(V300) 版本标注非 ID 本身，已剔除。
_ALG_RAW = [
    ("structure", "结构化", [
        ("face", "人脸抓拍"), ("pedestrian", "人体抓拍"), ("vehicle", "车辆抓拍"),
        ("non_motor", "非机动车"), ("plate", "车牌"),
    ]),
    ("headcount_alarm", "人数统计", [
        ("head_count", "区域人数统计"), ("cross_line", "进出口人数统计"),
    ]),
    ("face_basic_business", "脸人", [
        ("face_capture", "人脸抓拍"), ("body_capture", "人体抓拍"),
        ("face_comparison_successful", "人脸识别"), ("stranger", "陌生人"),
    ]),
    ("goods_alarm", "物品", [
        ("SUNDRY_DETECT", "杂物堆放"), ("GOODS_FORGET", "物品遗留"),
        ("GOODS_GUARD", "物品看守"), ("NEW_GOODS_DETECT", "新增杂物检测"),
    ]),
    ("diagnosis_alarm", "视频诊断", [
        ("IMAGE_COVER_ALERT", "画面遮挡"),
    ]),
    ("gkpw_alarm", "高空抛物", [
        ("falling_goods", "高空抛物"),
    ]),
    ("mclz_alarm", "明厨亮灶", [
        ("TRASHBIN", "垃圾桶未盖"), ("MICE", "老鼠"), ("CHEF_CLOTH", "未穿戴厨师服"),
        ("CHEF_HAT", "未佩戴厨师帽"), ("CHEF_RESPIRATOR", "未佩戴口罩"),
        ("RUBBER_GLOVE", "未佩戴橡胶手套"), ("FLAME_WITHOUT_HUMAN", "动火离人"), ("DISH", "光盘检测"),
    ]),
    # alert_alarm 同时覆盖『周界警戒』与『行为警戒』，事件集合合并
    ("alert_alarm", "周界/行为警戒", [
        ("PARK", "车辆禁停"), ("EXIT", "车辆离开"), ("WANDER", "人员徘徊"), ("OVERWALL", "翻墙"),
        ("INTRUSION", "区域入侵"), ("CLIMB", "攀爬"), ("ELECTRIC_BIKE_IN_ELEVATOR", "电动车进电梯"),
        ("TRIPWIRE", "越界"), ("FALL", "摔倒"), ("SMOKING", "抽烟"), ("CALL", "打电话"),
        ("WATCH_POINE", "看手机"), ("RUN", "奔跑"), ("FIGHT", "扭打"), ("GATHERING", "人员聚众"),
        ("HOLDWEAPON", "持械"), ("LEAVE_POST", "人员离岗"), ("PERSON_LESS_QUERYING", "少员"),
        ("PERSON_OVER_QUERYING", "超员"), ("SLEEP", "睡岗"),
    ]),
    ("safety_alarm", "安监", [
        ("SAFETY_CAP", "未佩戴安全帽"), ("SAFETY_UNIFORM", "未穿戴安全工服"), ("SAFETY_BELT", "未佩戴安全带"),
        ("FIRE", "火焰"), ("SMOKE", "烟雾"), ("OIL_SPILL", "油品泄露"), ("REFLECTIVE_VEST", "反光衣"),
        ("FIRE_EQUIPMENT", "消防设施"), ("RESPIRATOR", "口罩"), ("TOUCHED_EEBALL", "触摸静电球"),
        ("INSULATING_GLOVE", "未佩戴绝缘手套"),
    ]),
    ("jyz_alarm", "加油站", [
        ("SAFETY_CAP", "未佩戴安全帽"), ("SAFETY_UNIFORM", "未穿戴安全工服"), ("FIRE", "火焰"),
        ("SMOKE", "烟雾"), ("OIL_SPILL", "油品泄露"), ("FIRE_EQUIPMENT", "消防设施"),
        ("INDICATOR_FLAG", "静电线"), ("OIL_PIPE", "卸油管检测"), ("OILPUMP_DOOR_OPEN", "油机侧盖打开"),
        ("OIL_GUN_DRAG", "油管拉断"), ("OIL_TRUCK", "油罐车检测"),
    ]),
    ("edu__alarm", "教学评测", [
        ("HEAD_UP", "抬头"), ("HEAD_DOWN", "低头"), ("STAND", "站立"), ("READ", "阅读"),
        ("WRITE", "书写"), ("RAISE_HAND", "举手"), ("REST", "趴桌"), ("PEACE", "中性"),
        ("LAUGH", "积极"), ("CRY", "消极"),
    ]),
    ("uniform_alarm", "工服注册仓", [
        ("UNIFORM_BY_FEATURE", "未穿工服"),
    ]),
    ("city_alarm", "城管", [
        ("HAWKER", "游商小贩"), ("OUTSTORE", "店外经营"), ("ROADSIDE", "占道经营"),
        ("SUNDRYSTACK", "杂物堆放"), ("MUCK", "堆积渣土"), ("EXPOSED_GARBAGE", "暴露垃圾"),
        ("OUTDOOR_ADV", "户外广告"), ("WATERGATHER", "道路积水"),
    ]),
    ("building_alarm", "工地", [
        ("UNCOVERED_GROUND", "裸土覆盖"), ("UNCOVERED_SKIN", "皮肤裸露"), ("UNCLEANED_CAR", "车辆未喷淋"),
    ]),
    ("edu__style", "教学风格", [
        ("WRITE_ON_BLACKBOARD", "板书"), ("BACK_TO_STUDENT", "背对学生"), ("PODIUM_MOVEMENT", "上下讲台"),
        ("PATROL", "巡视"), ("WRITE", "书写"), ("LECTURE", "讲课"),
    ]),
    ("fire_alarm", "智慧社区", [
        ("OVERFLOWED_GARBAGE", "垃圾满溢"), ("EXPOSED_GARBAGE", "垃圾暴漏"), ("NO_HELMET", "骑电动车未戴头盔"),
    ]),
]

# 建索引：_ALG_EVENTS 扁平事件表；_ALG_BY_MINOR minor_type(小写)→事件列表；_ALG_MAJOR_NAME 大类ID→中文
_ALG_EVENTS, _ALG_BY_MINOR, _ALG_MAJOR_NAME = [], {}, {}
for _major, _mname, _events in _ALG_RAW:
    _ALG_MAJOR_NAME.setdefault(_major, _mname)
    for _minor, _ename in _events:
        _entry = {"major_type": _major, "major_name": _ALG_MAJOR_NAME[_major],
                  "minor_type": _minor, "event_name": _ename}
        _ALG_EVENTS.append(_entry)
        _ALG_BY_MINOR.setdefault(_minor.lower(), []).append(_entry)


def _alg_norm(s: str) -> str:
    return (s or "").strip().lower()


def _alg_event_name(minor_type: str, major_type: str = "") -> str:
    """算法ID(minor_type/event_type) → 中文事件名；找不到返回空串。
    个别 minor_type 跨大类且中文不同（如 EXPOSED_GARBAGE：城管『暴露垃圾』/ 智慧社区『垃圾暴漏』），
    传 major_type 可精确命中，否则返回首个匹配。"""
    hits = _ALG_BY_MINOR.get(_alg_norm(minor_type))
    if not hits:
        return ""
    if major_type:
        for h in hits:
            if _alg_norm(h["major_type"]) == _alg_norm(major_type):
                return h["event_name"]
    return hits[0]["event_name"]


def _alg_resolve(query: str) -> list:
    """把用户输入解析为候选算法事件，供布控取 minor_type 作为 event_type。
    支持：算法ID(minor_type)、中文事件名(精确/包含)、大类ID(major_type)、中文大类名（返回该类全部事件）。
    返回去重事件列表；无匹配返回空列表，调用方据数量判断唯一命中/需澄清。"""
    q = _alg_norm(query)
    if not q:
        return []
    exact_id, exact_name, contains = [], [], []
    for e in _ALG_EVENTS:
        minor, ename = _alg_norm(e["minor_type"]), _alg_norm(e["event_name"])
        if minor == q or ename == q:
            (exact_id if minor == q else exact_name).append(e)
        elif q in ename or ename in q:
            contains.append(e)
    major_hits = [e for e in _ALG_EVENTS
                  if _alg_norm(e["major_type"]) == q or q in _alg_norm(e["major_name"])]
    seen, out = set(), []
    for group in (exact_id, exact_name, contains, major_hits):
        for e in group:
            key = (e["major_type"], e["minor_type"])
            if key not in seen:
                seen.add(key)
                out.append(e)
    return out


# ── 设备能力查询辅助（供创建流程做依赖校验） ──────────────────────────────
async def _authorized_packages(client, device, db):
    """返回 (授权算法包列表, 错误信息)。离线/失败时列表为 None。

    授权是【整机硬件级】能力（一份 license 覆盖整机若干路通道），不与具体通道绑定，
    因此这里按 package_name 去重、只保留『整机是否拥有该授权』所需信息（包名 + 覆盖能力说明），
    不再逐条透出 auth_channel（授权路数），避免让人误以为授权是按通道枚举的。"""
    data = await DeviceService.get_authorization(client, device, db)
    if data is None:
        return None, f"设备「{device.name}」离线或不可达"
    if data.get("code") != 0:
        return None, data.get("message", "查询算法授权失败")
    by_name = {}
    for r in data.get("data", {}).get("list", []):
        for af in r.get("pocket", []):
            for a in af.get("cards", []):
                name = a.get("type", "")
                if not name or name in by_name:
                    continue
                # 设备返回的键为 desc（此前误读为 desp 导致说明恒为空）
                by_name[name] = {"package_name": name, "desp": af.get("name", "")}
    return list(by_name.values()), None


def _is_authorized(pkgs, algo_cabin_name: str) -> bool:
    name = (algo_cabin_name or "").lower()
    if not name:
        return False
    for p in pkgs:
        pn = (p.get("package_name") or "").lower()
        dp = (p.get("desp") or "").lower()
        if pn and (name in pn or pn in name):
            return True
        if name in dp:
            return True
    return False


async def _find_agent(client, device, db, agent_id: str):
    """在设备智能体算法列表中按 agent_id/event_id 定位。返回 (agent, 错误)；未找到时错误为 'NOT_FOUND'。"""
    data = await DeviceService.list_agents(client, device, db)
    if data is None:
        return None, f"设备「{device.name}」离线或不可达"
    if data.get("code") != 0:
        return None, data.get("message", "查询智能体算法失败")
    for a in data.get("data", {}).get("list", []):
        if str(a.get("agent_id")) == str(agent_id) or str(a.get("event_id")) == str(agent_id):
            return a, None
    return None, "NOT_FOUND"


async def _locate_device_task(client, device, db, task_id):
    """按 task_id 在设备任务列表中定位任务，返回 (task, channel_device_id, 错误消息)。

    多算法增删改查共用：拿到原始任务项（含 task_type/device_list/agent_list）与其首个通道 device_id。
    """
    tasks_data = await DeviceService.get_device_tasks(client, device, db)
    if not tasks_data or tasks_data.get("code") != 0:
        return None, None, f"设备「{device.name}」离线或不可达，无法读取任务列表"
    for t in tasks_data.get("data", {}).get("list", []):
        if str(t.get("task_id")) == str(task_id):
            dev_list = t.get("device_list") or []
            channel_device_id = (dev_list[0] or {}).get("device_id") if dev_list else None
            return t, channel_device_id, None
    return None, None, f"设备上未找到任务 task_id={task_id}"


def _locate_warehouse_monitor(param: list, algo_cabin_name: Optional[str]) -> Optional[dict]:
    """在 monitor_list.param（每个算法仓一条 monitor、跨仓共享 monitor_id）中定位目标仓的 monitor。

    给了 algo_cabin_name 则精确匹配 labels.algoCabinName；否则取第一条（单仓任务的简化）。
    """
    mons = param or []
    if not mons:
        return None
    if not algo_cabin_name:
        return mons[0]
    for mon in mons:
        if tb._algo_cabin_name(mon) == algo_cabin_name:
            return mon
    return None


def _find_rule_by_event(rules: list, event_type: Optional[str]) -> Optional[dict]:
    """在一条 monitor 的 rulesParams 中按 eventType 定位规则；不给 event_type 时取第一条（单算法仓的简化）。"""
    rules = rules or []
    if not rules:
        return None
    if not event_type:
        return rules[0]
    for r in rules:
        if str(r.get("eventType")) == str(event_type):
            return r
    return None


def _rule_from_existing(rule: dict, args: dict) -> dict:
    """基于设备上已有的一条 rule，用 args 里【显式给出】的项覆盖，重建这条 rule（未给的沿用原值）。

    用于 update_device_task 的『只改传入项』：threshold/target_max/target_min/duration/cooldown/
    target_types/roiPoints/target_expand/prompt(仅小+大)；eventType 保持不变。
    """
    ep = rule.get("extendParams") or {}
    areas = rule.get("areas") or []
    orig_area = areas[0] if areas and isinstance(areas[0], dict) else None
    roi_points = args.get("roiPoints")
    area = ({"areaId": 1, "areaName": "检测区", "areaType": "POLYGON", "points": roi_points}
            if roi_points else orig_area)
    # 小+大：保留原 agentLLMParam，仅按需覆盖 prompt（纯小模型 orig_agent_llm 为 None）
    orig_agent_llm = (ep.get("aiotapCustom") or {}).get("agentLLMParam")
    agent_llm = None
    if orig_agent_llm:
        agent_llm = dict(orig_agent_llm)
        if args.get("prompt") is not None:
            agent_llm["prompt"] = args.get("prompt")
    return tb.build_rule(
        event_type=rule.get("eventType"),
        area=area,
        target_types=args.get("target_types") or ep.get("targetTypes"),
        threshold=args.get("threshold", ep.get("threshold", 0.3)),
        target_max=args.get("target_max", ep.get("targetMax", 1)),
        target_min=args.get("target_min", ep.get("targetMin", 0)),
        duration=args.get("duration", ep.get("duration", 3)),
        cooldown=args.get("cooldown", ep.get("cooldownDuration", 600)),
        agent_llm=agent_llm,
        target_expand=args.get("target_expand") or ep.get("target_expand"),
    )


# ── 工具定义（OpenAI function schema，Gemini 转换时复用） ──────────────────
TOOLS = [
    {
        "name": "list_devices",
        "description": "列出所有已接入的BOX设备，返回设备ID、名称和在线状态",
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "list_tasks",
        "description": "查询平台侧为某设备手动创建的算法分析任务（含状态、优先级、算法配置）。"
                       "注意：这是平台内部任务台账，不是设备实际接入的视频流通道，也不是设备端已布控任务。",
        "parameters": {
            "type": "object",
            "properties": {"device_id": {"type": "string", "description": "设备业务ID，如 M014101762601000001"}},
            "required": ["device_id"],
        },
    },
    {
        "name": "get_device_streams",
        "description": "查询指定BOX设备实际接入的视频流通道（来源于『设备接入-获取详情』同步的通道列表，含 RTSP 取流地址、协议）。"
                       "当用户问『接入了多少个/多少路视频流』『有哪些通道』『视频流地址』时，必须使用本工具，不要用 list_tasks。"
                       "创建布控任务所需的 channel_device_id 就是本工具返回的通道 device_id（整数）。",
        "parameters": {
            "type": "object",
            "properties": {"device_id": {"type": "string", "description": "设备业务ID"}},
            "required": ["device_id"],
        },
    },
    {
        "name": "get_device_control_tasks",
        "description": "查询指定BOX设备端当前已布控的任务（来源于『设备接入-获取详情』同步的任务布控列表，含任务名称、关联通道、智能体算法）。"
                       "当用户问『已布控了哪些任务』『设备上部署了什么任务』时，必须使用本工具，不要用 list_tasks。",
        "parameters": {
            "type": "object",
            "properties": {"device_id": {"type": "string", "description": "设备业务ID"}},
            "required": ["device_id"],
        },
    },
    {
        "name": "check_algorithm_authorization",
        "description": "查询指定BOX设备已获得的小模型算法授权（实时调用设备 authorization_document 接口）。"
                       "创建『纯小模型任务』或『小+大任务』前必须先用本工具确认对应算法已授权。",
        "parameters": {
            "type": "object",
            "properties": {"device_id": {"type": "string", "description": "设备业务ID"}},
            "required": ["device_id"],
        },
    },
    {
        "name": "list_device_algorithms",
        "description": "查询指定BOX设备可布控的小模型算法（合并算法仓 packet_list 与卡片能力 card_cap），"
                       "返回 algoCabinName（算法仓名）、version、eventType（英文事件类型ID）、"
                       "eventName（中文算法名称）、targetTypes（检测目标）。"
                       "创建小模型/小+大任务时据此选择 event_type 与 algo_cabin_name。",
        "parameters": {
            "type": "object",
            "properties": {"device_id": {"type": "string", "description": "设备业务ID"}},
            "required": ["device_id"],
        },
    },
    {
        "name": "resolve_algorithm",
        "description": "把用户输入的中文算法名称解析为设备布控所需的英文算法ID（event_type）。"
                       "设备算法仓返回的是英文ID（如 INTRUSION / FALL），而用户通常说中文（如 区域入侵 / 摔倒）；"
                       "创建小模型/小+大任务前，若只知道中文名，先用本工具拿到对应 event_type 再布控。"
                       "支持中文事件名、英文算法ID、算法大类（如 安监/周界警戒）作为输入。",
        "parameters": {
            "type": "object",
            "properties": {"name": {"type": "string", "description": "算法中文名/英文ID/大类名，如 摔倒、FALL、安监"}},
            "required": ["name"],
        },
    },
    {
        "name": "list_agents",
        "description": "查询指定BOX设备上已有的智能体算法（大模型算法，实时调用 agent_list 接口），"
                       "返回 event_id / event_tag / alarm_type / prompt。"
                       "创建『纯大模型任务』或『小+大任务』前必须先用本工具确认对应智能体算法存在。",
        "parameters": {
            "type": "object",
            "properties": {"device_id": {"type": "string", "description": "设备业务ID"}},
            "required": ["device_id"],
        },
    },
    {
        "name": "create_agent",
        "description": "在BOX设备上新建一个智能体算法（大模型算法）。仅当用户确认要新建时才调用。"
                       "alarm_type：freeform=描述型，yesno=判断型。",
        "parameters": {
            "type": "object",
            "properties": {
                "device_id":  {"type": "string", "description": "设备业务ID"},
                "event_id":   {"type": "string", "description": "事件唯一标识（英文/数字），同时作为 agent_id"},
                "event_tag":  {"type": "string", "description": "事件名称/标签，同时作为 agent_name"},
                "prompt":     {"type": "string", "description": "大模型提示词"},
                "alarm_type": {"type": "string", "description": "报警类型：freeform 或 yesno，默认 freeform"},
                "alarm_condition": {"type": "string", "description": "报警条件，可为空"},
            },
            "required": ["device_id", "event_id", "event_tag", "prompt"],
        },
    },
    {
        "name": "create_smallmodel_task",
        "description": "创建【纯小模型算法任务】：会先校验设备算法授权，再两步下发（task + monitor）。",
        "parameters": {
            "type": "object",
            "properties": {
                "device_id":         {"type": "string", "description": "设备业务ID"},
                "channel_device_id": {"type": "integer", "description": "视频流通道 device_id（来自 get_device_streams）"},
                "task_name":         {"type": "string", "description": "任务名称"},
                "event_type":        {"type": "string", "description": "算法事件类型，如 INTRUSION（来自 list_device_algorithms）"},
                "algo_cabin_name":   {"type": "string", "description": "算法仓名 algoCabinName（来自 list_device_algorithms）"},
                "version":           {"type": "string", "description": "算法仓版本，默认 V2.0.0"},
                "target_types":      {"type": "array", "items": {"type": "string"}, "description": "检测目标类型，默认 [PERSON]"},
                "threshold":         {"type": "number", "description": "报警阈值 0~1，默认 0.3"},
                "target_max":        {"type": "integer", "description": "最大目标数，默认 1"},
                "target_min":        {"type": "integer", "description": "最小目标数，默认 0"},
                "duration":          {"type": "integer", "description": "持续时长(秒)，默认 3"},
                "cooldown":          {"type": "integer", "description": "报警间隔/冷却时长(秒)，默认 600"},
                "roiPoints":         {"type": "array", "items": {"type": "object"}, "description": "ROI检测区归一化多边形点[{x,y}]，默认全画面"},
            },
            "required": ["device_id", "channel_device_id", "task_name", "event_type", "algo_cabin_name"],
        },
    },
    {
        "name": "create_agent_task",
        "description": "创建【纯大模型任务】（agent_real_task）：会先校验对应智能体算法存在（不存在会提示先新建），单步下发。",
        "parameters": {
            "type": "object",
            "properties": {
                "device_id":         {"type": "string", "description": "设备业务ID"},
                "channel_device_id": {"type": "integer", "description": "视频流通道 device_id（来自 get_device_streams）"},
                "task_name":         {"type": "string", "description": "任务名称"},
                "agent_id":          {"type": "string", "description": "智能体算法 agent_id/event_id（来自 list_agents）"},
                "prompt":            {"type": "string", "description": "覆盖提示词，可为空（默认用智能体自带 prompt）"},
                "alarm_condition":   {"type": "string", "description": "报警条件，可为空"},
                "analysis_interval": {"type": "integer", "description": "分析间隔秒，默认 5（仅智能体任务有此概念）"},
                "filter_enable":     {"type": "boolean", "description": "是否开启结果过滤（仅描述型 freeform 智能体生效），默认关闭"},
                "filter_keywords":   {"type": "string", "description": "过滤关键词（filter_enable 开启时生效），可为空"},
            },
            "required": ["device_id", "channel_device_id", "task_name", "agent_id"],
        },
    },
    {
        "name": "create_combined_task",
        "description": "创建【小+大任务】：小模型报警后再经大模型二次分析。会同时校验算法授权与智能体算法，两步下发（monitor 挂载 agentLLMParam）。",
        "parameters": {
            "type": "object",
            "properties": {
                "device_id":         {"type": "string", "description": "设备业务ID"},
                "channel_device_id": {"type": "integer", "description": "视频流通道 device_id（来自 get_device_streams）"},
                "task_name":         {"type": "string", "description": "任务名称"},
                "event_type":        {"type": "string", "description": "小模型算法事件类型（来自 list_device_algorithms）"},
                "algo_cabin_name":   {"type": "string", "description": "算法仓名 algoCabinName（来自 list_device_algorithms）"},
                "agent_id":          {"type": "string", "description": "智能体算法 agent_id/event_id（来自 list_agents）"},
                "prompt":            {"type": "string", "description": "覆盖大模型提示词，可为空"},
                "version":           {"type": "string", "description": "算法仓版本，默认 V2.0.0"},
                "target_types":      {"type": "array", "items": {"type": "string"}, "description": "检测目标类型，默认 [PERSON]"},
                "threshold":         {"type": "number", "description": "报警阈值 0~1，默认 0.3"},
                "target_max":        {"type": "integer", "description": "最大目标数，默认 1"},
                "target_min":        {"type": "integer", "description": "最小目标数，默认 0"},
                "duration":          {"type": "integer", "description": "持续时长(秒)，默认 3"},
                "cooldown":          {"type": "integer", "description": "报警间隔/冷却时长(秒)，默认 600"},
                "roiPoints":         {"type": "array", "items": {"type": "object"}, "description": "ROI检测区归一化多边形点[{x,y}]，默认全画面"},
                "target_expand":     {"type": "object", "description": "扩图策略{top,bottom,left,right}(0~1)，仅小+大生效，默认对称扩图"},
            },
            "required": ["device_id", "channel_device_id", "task_name", "event_type", "algo_cabin_name", "agent_id"],
        },
    },
    {
        "name": "propose_deployment",
        "description": "生成一份【布控方案预览】并推送到界面：会先做依赖校验（小模型任务校验算法授权、"
                       "大模型任务校验智能体算法存在），通过后返回一组推荐参数供前端填充到"
                       "『AI级联提取与细化控制面板』，并在视频流展示区载入当前设备最新报警大图供用户画 ROI。"
                       "当用户想创建布控任务、希望先在界面上预览/调参/画检测区时调用本工具；"
                       "真正下发到设备仍使用 create_smallmodel_task / create_agent_task / create_combined_task。",
        "parameters": {
            "type": "object",
            "properties": {
                "device_id":         {"type": "string", "description": "设备业务ID"},
                "task_type":         {"type": "string", "description": "smallmodel（纯小模型）/ agent（纯大模型）/ combined（小+大）"},
                "task_name":         {"type": "string", "description": "推荐任务名称"},
                "channel_device_id": {"type": "integer", "description": "视频流通道 device_id（来自 get_device_streams），可为空"},
                "event_type":        {"type": "string", "description": "小模型算法事件类型（smallmodel/combined 必填）"},
                "algo_cabin_name":   {"type": "string", "description": "算法仓名 algoCabinName（smallmodel/combined 必填）"},
                "agent_id":          {"type": "string", "description": "智能体算法 agent_id/event_id（agent/combined 必填）"},
            },
            "required": ["device_id", "task_type", "task_name"],
        },
    },
    {
        "name": "update_device_task",
        "description": "修改【已下发到设备】的纯小模型/小+大布控任务中【某一个算法】的参数（阈值/目标数/持续时长/报警间隔/检测目标/ROI/扩图/二次大模型提示词）。"
                       "一个任务、同一类型可布控多个算法（算法身份=算法仓 algo_cabin_name + 事件类型 event_type）；"
                       "通过 algo_cabin_name + event_type 定位要改的那一个，同任务/同仓的其它算法原样保留、不受影响；"
                       "任务只有单个算法时二者可不填（默认取第一个）。底层读回该任务的 monitor，用传入项覆盖后以相同 monitor_id 重新下发"
                       "（设备无 monitor 更新接口）；只传需要修改的项，未传的沿用设备上的原值。改完建议再用 get_device_control_tasks 复查。"
                       "注意：纯大模型任务(agent_real_task)的算法(智能体)增删改请用 add_task_algorithm / remove_task_algorithm；抽帧间隔不在本工具范围。",
        "parameters": {
            "type": "object",
            "properties": {
                "device_id":       {"type": "string", "description": "设备业务ID"},
                "task_id":         {"type": "string", "description": "要修改的设备任务 task_id（来自 get_device_control_tasks）"},
                "algo_cabin_name": {"type": "string", "description": "可选，要修改算法所在的算法仓名（多算法/跨仓时用于定位；单算法任务可省略）"},
                "event_type":      {"type": "string", "description": "可选，要修改的算法事件类型（同仓多算法时用于定位；单算法任务可省略）"},
                "threshold":       {"type": "number", "description": "报警阈值 0~1"},
                "target_max":      {"type": "integer", "description": "最大目标数"},
                "target_min":      {"type": "integer", "description": "最小目标数"},
                "duration":        {"type": "integer", "description": "持续时长(秒)"},
                "cooldown":        {"type": "integer", "description": "报警间隔/冷却时长(秒)"},
                "target_types":    {"type": "array", "items": {"type": "string"}, "description": "检测目标类型，如 [PERSON]"},
                "roiPoints":       {"type": "array", "items": {"type": "object"}, "description": "ROI检测区归一化多边形点[{x,y}]"},
                "target_expand":   {"type": "object", "description": "扩图策略{top,bottom,left,right}（仅小+大生效）"},
                "prompt":          {"type": "string", "description": "覆盖二次大模型提示词（仅小+大生效）"},
            },
            "required": ["device_id", "task_id"],
        },
    },
    {
        "name": "add_task_algorithm",
        "description": "向【已下发到设备的任务】新增一个算法（同一任务、同一类型可布控多个算法，支持增删改查）。"
                       "小模型/小+大任务：算法身份=算法仓 algo_cabin_name + 事件类型 event_type（二者必填，来自 list_device_algorithms）；"
                       "若目标算法仓已在该任务中则往其追加一条规则，否则以相同 monitor_id 新建该算法仓的 monitor（跨仓算法共享 monitor_id）；"
                       "传了 agent_id 时该算法为『小+大』（挂二次大模型）。纯大模型任务(agent_real_task)：算法=智能体，用 agent_id 指定，"
                       "追加到任务的智能体列表（上限4个）。新增前建议先 list_device_algorithms 确认算法/仓名，再 get_device_control_tasks 确认任务。",
        "parameters": {
            "type": "object",
            "properties": {
                "device_id":       {"type": "string", "description": "设备业务ID"},
                "task_id":         {"type": "string", "description": "要新增算法的设备任务 task_id（来自 get_device_control_tasks）"},
                "event_type":      {"type": "string", "description": "小模型/小+大必填：要新增的算法事件类型（来自 list_device_algorithms）"},
                "algo_cabin_name": {"type": "string", "description": "小模型/小+大必填：算法所在的算法仓名（来自 list_device_algorithms）"},
                "agent_id":        {"type": "string", "description": "纯大模型必填=要关联的智能体；小+大可选=挂二次大模型的智能体"},
                "version":         {"type": "string", "description": "可选，算法版本，默认 V2.0.0"},
                "target_types":    {"type": "array", "items": {"type": "string"}, "description": "检测目标类型，如 [PERSON]，默认 [PERSON]"},
                "threshold":       {"type": "number", "description": "报警阈值 0~1，默认0.3"},
                "target_max":      {"type": "integer", "description": "最大目标数，默认1"},
                "target_min":      {"type": "integer", "description": "最小目标数，默认0"},
                "duration":        {"type": "integer", "description": "持续时长(秒)，默认3"},
                "cooldown":        {"type": "integer", "description": "报警间隔/冷却时长(秒)，默认600"},
                "roiPoints":       {"type": "array", "items": {"type": "object"}, "description": "ROI检测区归一化多边形点[{x,y}]，为空则全画面"},
                "target_expand":   {"type": "object", "description": "扩图策略{top,bottom,left,right}（仅小+大生效）"},
                "prompt":          {"type": "string", "description": "二次大模型/智能体提示词（小+大或纯大模型）"},
                "filter_enable":   {"type": "boolean", "description": "纯大模型描述型智能体：是否启用关键词过滤"},
                "filter_keywords": {"type": "string", "description": "纯大模型描述型智能体：过滤关键词"},
                "alarm_condition": {"type": "string", "description": "可选，报警条件（智能体），缺省按类型推导"},
            },
            "required": ["device_id", "task_id"],
        },
    },
    {
        "name": "remove_task_algorithm",
        "description": "从【已下发到设备的任务】删除一个算法（同一任务、同一类型多算法时按算法逐个删）。"
                       "小模型/小+大：算法身份=算法仓 algo_cabin_name + 事件类型 event_type，从该算法仓移除这条规则。"
                       "纯大模型：算法=智能体，用 agent_id 指定并从任务智能体列表移除。"
                       "重要：设备暂无硬删除接口，故【删除】统一降级为【停用】(enable=False，可再启用/覆盖恢复)——"
                       "删到某算法仓为空则停用该仓 monitor；删除任务的最后一个算法、或不指定任何算法标识（视为『清除整个任务』）则停用整个任务(PUT enable=False)。"
                       "真正的硬删除后续再做。",
        "parameters": {
            "type": "object",
            "properties": {
                "device_id":       {"type": "string", "description": "设备业务ID"},
                "task_id":         {"type": "string", "description": "要删除算法的设备任务 task_id（来自 get_device_control_tasks）"},
                "event_type":      {"type": "string", "description": "小模型/小+大：要删除的算法事件类型；不填=清除整个任务(降级为停用)"},
                "algo_cabin_name": {"type": "string", "description": "可选，要删除算法所在的算法仓名（多仓时用于定位；单仓可省略）"},
                "agent_id":        {"type": "string", "description": "纯大模型：要删除的智能体标识(event_id/event_tag)；不填=清除整个任务(降级为停用)"},
            },
            "required": ["device_id", "task_id"],
        },
    },
    {
        "name": "create_task",
        "description": "在平台本地台账登记一条算法分析任务（不下发到设备）。仅用于平台内部记录，"
                       "布控到设备请使用 create_smallmodel_task / create_agent_task / create_combined_task。",
        "parameters": {
            "type": "object",
            "properties": {
                "name":        {"type": "string", "description": "任务名称"},
                "device_id":   {"type": "string", "description": "设备业务ID"},
                "channel":     {"type": "string", "description": "视频流通道名称"},
                "device_task": {"type": "string", "description": "关联的设备任务名称，可为空"},
                "algorithms":  {"type": "string", "description": "算法ID列表JSON字符串，如 [\"32\",\"33\"]"},
                "task_type":   {"type": "string", "description": "任务类型：Prompt调优 或 警戒分析，默认Prompt调优"},
                "priority":    {"type": "string", "description": "优先级：高/中/低，默认中"},
            },
            "required": ["name", "device_id", "channel", "algorithms"],
        },
    },
    {
        "name": "update_task",
        "description": "修改平台本地台账任务的字段（名称、通道、算法、优先级、状态等）",
        "parameters": {
            "type": "object",
            "properties": {
                "task_id":    {"type": "string", "description": "任务ID，如 TASK-XXXXXXXX"},
                "name":       {"type": "string"},
                "channel":    {"type": "string"},
                "device_task":{"type": "string"},
                "algorithms": {"type": "string"},
                "priority":   {"type": "string"},
                "status":     {"type": "string"},
            },
            "required": ["task_id"],
        },
    },
    {
        "name": "list_task_templates",
        "description": "列出【参数模板库】中已保存的布控参数模板（只返回 id/名称/任务类型/事件类型/说明，不含完整参数快照，省上下文）。"
                       "当用户问「有哪些模板」或想「套用某个模板」时先用本工具列出，再用 apply_task_template 套用。",
        "parameters": {
            "type": "object",
            "properties": {
                "task_mode": {"type": "string", "description": "可选，按任务类型过滤：smallmodel（纯小模型）/ agent（纯大模型）/ combined（小+大）"},
            },
            "required": [],
        },
    },
    {
        "name": "apply_task_template",
        "description": "套用【参数模板库】中的一个模板：读取其参数快照，合并当前设备上下文后填充到右侧『AI级联提取与细化控制面板』，"
                       "并载入设备最新报警大图供用户绘制 ROI。套用后【不自动下发】——需用户在界面确认参数、画好检测区再点部署"
                       "（真正下发仍走 create_smallmodel_task / create_agent_task / create_combined_task）。template_id 来自 list_task_templates。",
        "parameters": {
            "type": "object",
            "properties": {
                "template_id":       {"type": "string", "description": "要套用的模板 id（来自 list_task_templates）"},
                "device_id":         {"type": "string", "description": "可选，绑定的设备业务ID（默认当前会话设备）"},
                "channel_device_id": {"type": "integer", "description": "可选，视频流通道 device_id（来自 get_device_streams）"},
                "task_name":         {"type": "string", "description": "可选，覆盖模板中的任务名称"},
            },
            "required": ["template_id"],
        },
    },
]


# ── 执行分发 ──────────────────────────────────────────────────────────────
async def execute_tool(name: str, args: dict, db: AsyncSession) -> str:
    if name == "list_devices":
        rows = (await db.execute(select(DeviceORM))).scalars().all()
        return json.dumps(
            [{"device_id": d.device_id, "name": d.name, "status": d.status} for d in rows],
            ensure_ascii=False)

    """
    if name == "list_tasks":
        device_id = args.get("device_id", "")
        rows = (await db.execute(select(TaskORM).where(TaskORM.device_id == device_id))).scalars().all()
        return json.dumps(
            [{"id": t.id, "name": t.name, "channel": t.channel,
              "device_task": t.device_task, "algorithms": t.algorithms,
              "status": t.status, "priority": t.priority, "task_type": t.task_type}
             for t in rows],
            ensure_ascii=False,
        )
    """

    if name == "list_tasks":
        device = await _get_device(db, args.get("device_id", ""))
        if not device:
            return _err(f"未找到设备 {args.get('device_id') or '(未指定)'}，请先在『设备接入』添加设备并执行『获取详情』")
        
        devices_tasks = _load_json(device.device_tasks)
        #return _ok({"device_id": device.device_id, "device_name": device.name,
        #            "count": len(channels), "channels": channels})
        return json.dumps(
            [{"id": t.id, "name": t.name, "channel": t.channel,
                "device_task": t.device_task, "algorithms": t.algorithms,
                "status": t.status, "priority": t.priority, "task_type": t.task_type}
                for t in rows],
            ensure_ascii=False,
        )

    if name == "resolve_algorithm":
        query = args.get("name", "")
        matches = _alg_resolve(query)
        return _ok({"query": query, "count": len(matches), "matches": matches})

    if name in ("get_device_streams", "get_device_control_tasks"):
        device = await _get_device(db, args.get("device_id", ""))
        if not device:
            return _err(f"未找到设备 {args.get('device_id') or '(未指定)'}，请先在『设备接入』添加设备并执行『获取详情』")
        if name == "get_device_streams":
            channels = _load_json(device.channels)
            return _ok({"device_id": device.device_id, "device_name": device.name,
                        "count": len(channels), "channels": channels})
        tasks = _load_json(device.device_tasks)
        return _ok({"device_id": device.device_id, "device_name": device.name,
                    "count": len(tasks), "tasks": tasks})

    # ── 设备侧能力查询 ────────────────────────────────────────────────
    if name == "check_algorithm_authorization":
        device = await _get_device(db, args.get("device_id", ""))
        if not device:
            return _err("未找到设备，请先在『设备接入』添加并获取详情")
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            pkgs, err = await _authorized_packages(client, device, db)
        if err:
            return _err(f"查询算法授权失败：{err}")
        return _ok({"device_id": device.device_id, "count": len(pkgs), "authorizations": pkgs})

    if name == "list_device_algorithms":
        device = await _get_device(db, args.get("device_id", ""))
        if not device:
            return _err("未找到设备，请先在『设备接入』添加并获取详情")
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            packet = await DeviceService.list_alg_warehouses(client, device, db)
            cards = await DeviceService.list_alg_cards(client, device, db)
        if packet is None:
            return _err(f"设备「{device.name}」离线或不可达，无法查询算法仓")
        if packet.get("code") != 0:
            return _err(f"查询算法仓失败：{packet.get('message')}")
        warehouses = packet.get("data", {}).get("list", [])
        wh_by_file = {w.get("file_id"): w for w in warehouses if w.get("file_id") is not None}
        rows = []
        card_list = (cards or {}).get("data", {}).get("cards", []) if isinstance(cards, dict) else []
        for c in card_list:
            w = wh_by_file.get(c.get("file_id")) or (warehouses[0] if warehouses else {})
            for at in c.get("alertor_type", []):
                event_type = at.get("alertor_type", "")
                rows.append({
                    "algoCabinName": w.get("alg_name", ""),
                    "version": w.get("alg_version", "V2.0.0"),
                    "eventType": event_type,
                    "eventName": _alg_event_name(event_type),  # 英文算法ID → 中文事件名
                    "targetTypes": at.get("target_type", []),
                    "description": w.get("status", ""),
                })
        if not rows:  # card_cap 无数据时至少列出算法仓
            rows = [{"algoCabinName": w.get("alg_name", ""), "version": w.get("alg_version", "V2.0.0"),
                     "eventType": "", "eventName": "", "targetTypes": [], "description": w.get("status", "")}
                    for w in warehouses]
        return _ok({"device_id": device.device_id, "count": len(rows), "algorithms": rows})

    if name == "list_agents":
        device = await _get_device(db, args.get("device_id", ""))
        if not device:
            return _err("未找到设备，请先在『设备接入』添加并获取详情")
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            data = await DeviceService.list_agents(client, device, db)
        if data is None:
            return _err(f"设备「{device.name}」离线或不可达，无法查询智能体算法")
        if data.get("code") != 0:
            return _err(f"查询智能体算法失败：{data.get('message')}")
        # 智能体是【整机级】资产，此处仅用于确认整机是否拥有该智能体，无需回传完整 prompt
        # （完整提示词在『智能体资产库』界面查看）。prompt 截断为简短预览，避免上下文膨胀。
        agents = [{"agent_id": a.get("agent_id"), "event_id": a.get("event_id"),
                   "event_tag": a.get("event_tag"), "alarm_type": a.get("alarm_type"),
                   "prompt_preview": _preview((a.get("prompt") or ""))}
                  for a in data.get("data", {}).get("list", [])]
        return _ok({"device_id": device.device_id, "count": len(agents), "agents": agents})

    # ── 设备侧创建 ────────────────────────────────────────────────────
    if name == "create_agent":
        device = await _get_device(db, args.get("device_id", ""))
        if not device:
            return _err("未找到设备，请先在『设备接入』添加并获取详情")
        body = tb.build_agent_item_payload(
            args["event_id"], args["event_tag"], args["prompt"],
            args.get("alarm_type", "freeform"), args.get("alarm_condition"))
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            data = await DeviceService.create_agent(client, device, db, body)
        if data is None:
            return _err(f"设备「{device.name}」离线或不可达，无法新建智能体算法")
        if data.get("code") != 0:
            return _err(f"新建智能体算法失败：{data.get('message')}")
        return _ok({"success": True, "id": data.get("data", {}).get("id"),
                    "message": f"智能体算法「{args['event_tag']}」已创建"})

    if name == "create_agent_task":
        device = await _get_device(db, args.get("device_id", ""))
        if not device:
            return _err("未找到设备，请先在『设备接入』添加并获取详情")
        channel_id = int(args["channel_device_id"])
        existing = None  # 命中的同通道现有大模型任务（若有）
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            agent, err = await _find_agent(client, device, db, args["agent_id"])
            if err == "NOT_FOUND":
                return _err(f"设备上不存在智能体算法「{args['agent_id']}」。"
                            f"如需使用，请先确认是否新建该智能体算法（create_agent）。")
            if err:
                return _err(f"创建失败：{err}")

            # 本次要挂载的智能体项：过滤仅对描述型(freeform)智能体生效（镜像 deploy_agent_task 的兜底）
            is_attr = (agent.get("alarm_type") or "").lower() == "freeform"
            new_item = {
                "event_id": agent.get("event_id"),
                "event_tag": agent.get("event_tag"),
                "agent_config": tb.build_agent_config({
                    **agent,
                    "prompt": args.get("prompt") if args.get("prompt") is not None else agent.get("prompt", ""),
                    "alarm_condition": args.get("alarm_condition"),
                    "filter_enable": bool(args.get("filter_enable", False)) if is_attr else False,
                    "filter_keywords": (args.get("filter_keywords", "") if is_attr else ""),
                }),
            }

            # 该通道是否已有大模型任务(agent_real_task)：有则追加智能体，无则新建
            tasks_data = await DeviceService.get_device_tasks(client, device, db)
            if tasks_data and tasks_data.get("code") == 0:
                for t in tasks_data.get("data", {}).get("list", []):
                    if t.get("task_type") != "agent_real_task":
                        continue
                    if any(int(d.get("device_id", -1)) == channel_id for d in t.get("device_list", [])):
                        existing = t
                        break

            if existing:
                cur = existing.get("agent_list", []) or []
                # 幂等：同一智能体已在任务中，直接返回成功，不重复添加
                if any(str(a.get("event_id")) == str(new_item["event_id"]) for a in cur):
                    return _ok({"success": True, "task_id": existing.get("task_id"),
                                "message": f"通道已在任务「{existing.get('task_name')}」中关联智能体"
                                           f"「{agent.get('event_tag')}」，无需重复添加"})
                # 上限保护：一个任务最多关联 4 个智能体算法
                if len(cur) >= 4:
                    return _err(f"任务「{existing.get('task_name')}」已关联 {len(cur)} 个智能体算法，"
                                f"达上限 4，无法再新增。")
                existing["agent_list"] = cur + [new_item]
                payload = DeviceService.build_task_payload(existing)  # 白名单保留 task_id/task_name/agent_list…
                data = await DeviceService.update_task(client, device, db, payload)
            else:
                payload = tb.build_agent_task_payload(
                    args["task_name"], channel_id, agent,
                    prompt=args.get("prompt"), alarm_condition=args.get("alarm_condition"),
                    analysis_interval=args.get("analysis_interval", 5))
                data = await DeviceService.create_task(client, device, db, payload)

        if data is None:
            return _err(f"设备「{device.name}」离线或不可达，任务下发失败")
        if data.get("code") != 0:
            return _err(f"任务下发失败：{data.get('message')}")
        if existing:
            return _ok({"success": True, "task_id": existing.get("task_id"),
                        "message": f"智能体算法「{agent.get('event_tag')}」已追加至任务"
                                   f"「{existing.get('task_name')}」（现关联 {len(existing['agent_list'])} 个）"})
        return _ok({"success": True, "task_id": data.get("data", {}).get("task_id"),
                    "message": f"纯大模型任务「{args['task_name']}」已下发"})

    if name in ("create_smallmodel_task", "create_combined_task"):
        return await _create_warehouse_task(name, args, db)

    if name == "propose_deployment":
        return await _propose_deployment(args, db)

    if name == "update_device_task":
        return await _update_device_task(args, db)

    if name == "add_task_algorithm":
        return await _add_task_algorithm(args, db)

    if name == "remove_task_algorithm":
        return await _remove_task_algorithm(args, db)

    if name == "list_task_templates":
        return await _list_task_templates(args, db)

    if name == "apply_task_template":
        return await _apply_task_template(args, db)

    if name == "create_task":
        now = int(time.time() * 1000)
        task = TaskORM(
            id=f"TASK-{str(uuid.uuid4())[:8].upper()}",
            name=args["name"], device_id=args["device_id"], channel=args["channel"],
            device_task=args.get("device_task", ""), algorithms=args.get("algorithms", "[]"),
            task_type=args.get("task_type", "Prompt调优"), priority=args.get("priority", "中"),
            status="未布控", assignee="", due_date=None, created_at=now, last_processed_time=now,
        )
        db.add(task)
        await db.commit()
        return _ok({"success": True, "task_id": task.id,
                    "message": f"任务「{args['name']}」已登记，ID: {task.id}"})

    if name == "update_task":
        task_id = args.pop("task_id")
        task = (await db.execute(select(TaskORM).where(TaskORM.id == task_id))).scalar_one_or_none()
        if not task:
            return _ok({"success": False, "message": f"任务 {task_id} 不存在"})
        for k, v in args.items():
            if hasattr(task, k):
                setattr(task, k, v)
        await db.commit()
        return _ok({"success": True, "message": f"任务 {task_id} 已更新"})

    return _err(f"未知工具: {name}")


async def _create_warehouse_task(name: str, args: dict, db: AsyncSession) -> str:
    """算法仓任务（纯小模型 / 小+大）共享的两步下发流程。"""
    combined = name == "create_combined_task"
    device = await _get_device(db, args.get("device_id", ""))
    if not device:
        return _err("未找到设备，请先在『设备接入』添加并获取详情")

    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
        # 1) 算法授权校验
        pkgs, err = await _authorized_packages(client, device, db)
        if err:
            return _err(f"无法校验算法授权：{err}")
        if not _is_authorized(pkgs, args["algo_cabin_name"]):
            available = "、".join(p.get("package_name", "") for p in pkgs) or "（无）"
            return _err(f"设备未授权算法「{args['algo_cabin_name']}」，无法创建任务。当前已授权：{available}")

        # 小+大：额外校验智能体算法存在，构造二次大模型参数（LLM 层职责，故留在此处）
        agent_llm = None
        if combined:
            agent, aerr = await _find_agent(client, device, db, args["agent_id"])
            if aerr == "NOT_FOUND":
                return _err(f"设备上不存在智能体算法「{args['agent_id']}」，请先确认是否新建（create_agent）。")
            if aerr:
                return _err(f"创建失败：{aerr}")
            agent_llm = tb.build_agent_llm_param(agent, prompt=args.get("prompt"))

        # ROI：给了 roiPoints 用其构造检测区，否则全画面
        roi_points = args.get("roiPoints")
        area = ({"areaId": 1, "areaName": "检测区", "areaType": "POLYGON", "points": roi_points}
                if roi_points else tb.full_frame_area())

        # 2) 两步下发（create_task → monitor）交给共享 helper，统一失败/孤儿语义
        ok, msg, task_id = await DeviceService.deploy_warehouse_task(
            client, device, db,
            task_name=args["task_name"], channel_device_id=int(args["channel_device_id"]),
            event_type=args["event_type"], algo_cabin_name=args["algo_cabin_name"],
            version=args.get("version", "V2.0.0"), monitor_name=args["task_name"], area=area,
            target_types=args.get("target_types"), threshold=args.get("threshold", 0.3),
            target_max=args.get("target_max", 1), target_min=args.get("target_min", 0),
            duration=args.get("duration", 3), cooldown=args.get("cooldown", 600),
            agent_llm=agent_llm, target_expand=args.get("target_expand"))

    if not ok:
        return _err(msg)
    kind = "小+大" if combined else "纯小模型"
    return _ok({"success": True, "task_id": task_id,
                "message": f"{kind}任务「{args['task_name']}」已下发（task_id={task_id}）"})


async def _update_device_task(args: dict, db: AsyncSession) -> str:
    """覆盖更新已下发【小模型/小+大】任务中【某一个算法】的参数（设备无 monitor 更新 API → 同 monitor_id 覆盖重下）。

    定位目标算法 = (algo_cabin_name, event_type)，二者可省：省 algo_cabin_name 取第一条 monitor，
    省 event_type 取该仓第一条规则（单算法任务无需指定）。同仓内其它算法(规则)原样保留一起重下，
    不会被覆盖丢失。未在 args 指定的参数沿用原值（只改传入项）。纯大模型任务(agent_real_task)无 monitor，
    其算法(智能体)增删走 add_task_algorithm/remove_task_algorithm；抽帧间隔属 task 级、不在 monitor 内，本工具不改。
    """
    device = await _get_device(db, args.get("device_id", ""))
    if not device:
        return _err("未找到设备，请先在『设备接入』添加并获取详情")
    task_id = args.get("task_id")
    if not task_id:
        return _err("缺少 task_id，无法定位要更新的任务")

    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
        # 1) 定位任务：取通道 device_id 与任务类型（agent_real_task 无 monitor，拒绝）
        task, channel_device_id, err = await _locate_device_task(client, device, db, task_id)
        if err:
            return _err(err)
        if task.get("task_type") == "agent_real_task":
            return _err("该任务为纯大模型任务(agent_real_task)，无 monitor，其算法(智能体)增删请用 "
                        "add_task_algorithm / remove_task_algorithm")
        if channel_device_id is None:
            return _err(f"任务 task_id={task_id} 缺少通道信息，无法更新")

        # 2) 读取该任务的全部 monitor（每个算法仓一条），定位目标仓与目标规则
        mon_res = await DeviceService.authed_post(
            client, device, db, MONITOR_LIST_PATH,
            {"device_id": channel_device_id, "task_id": task_id})
        param = ((mon_res or {}).get("data") or {}).get("param") or []
        mon = _locate_warehouse_monitor(param, args.get("algo_cabin_name"))
        if not mon:
            return _err(f"未在任务 task_id={task_id} 中找到算法仓「{args.get('algo_cabin_name') or '(第一条)'}」"
                        f"的 monitor（可能离线或该任务无 monitor），无法更新")
        rules = tb._warehouse_rules(mon)
        target = _find_rule_by_event(rules, args.get("event_type"))
        if not target:
            return _err(f"未在算法仓中找到算法 eventType={args.get('event_type') or '(第一条)'}，无法更新")

        # 3) 只重建目标规则、其余规则原样保留，一起用相同 monitor_id + algoCabinName 覆盖下发
        common = mon.get("common_param") or {}
        labels = (common.get("warehouse_v20_param") or {}).get("labels") or {}
        new_rules = [_rule_from_existing(r, args) if r is target else r for r in rules]
        monitor_payload = tb.build_warehouse_monitor(
            task_id, int(channel_device_id), labels.get("algoCabinName", ""),
            new_rules, version=labels.get("version", "V2.0.0"),
            monitor_id=common.get("monitor_id"), monitor_name=common.get("monitor_name"))
        mon_data = await DeviceService.create_monitor(client, device, db, monitor_payload)

    if mon_data is None:
        return _err(f"任务 task_id={task_id} 参数更新时设备不可达，请重试")
    if mon_data.get("code") != 0:
        return _err(f"任务 task_id={task_id} 参数更新失败：{mon_data.get('message')}")
    return _ok({"success": True, "task_id": task_id,
                "message": f"任务 task_id={task_id} 中算法「{target.get('eventType')}」的参数已更新"
                           f"（同仓其它算法保留）"})


async def _disable_whole_task(client, device, db, task, task_id, channel_device_id, param, *, reason: str) -> str:
    """『清除整个任务』的降级实现：停用整个任务(PUT enable=False) + best-effort 停用其名下各算法仓 monitor。

    设备无硬删除接口，故本轮统一降级为【停用】（可再次启用/覆盖恢复）。任务级 PUT enable=False 是主判据；
    各仓 monitor 停用保留原规则、仅置 enable=False。
    """
    task["enable"] = False
    payload = DeviceService.build_task_payload(task)
    data = await DeviceService.update_task(client, device, db, payload)
    if data is None:
        return _err(f"任务 task_id={task_id} 停用时设备不可达，请重试")
    if data.get("code") != 0:
        return _err(f"任务 task_id={task_id} 停用失败：{data.get('message')}")
    disabled = 0
    for m in param or []:
        common = m.get("common_param") or {}
        labels = (common.get("warehouse_v20_param") or {}).get("labels") or {}
        rules = tb._warehouse_rules(m)
        mon_payload = tb.build_warehouse_monitor(
            task_id, int(channel_device_id), labels.get("algoCabinName", ""), rules,
            version=labels.get("version", "V2.0.0"),
            monitor_id=common.get("monitor_id"), monitor_name=common.get("monitor_name"), enable=False)
        r = await DeviceService.create_monitor(client, device, db, mon_payload)
        if r and r.get("code") == 0:
            disabled += 1
    return _ok({"success": True, "task_id": task_id, "disabled_task": True,
                "message": f"{reason}：已按约定将整个任务停用(enable=False)"
                           f"（同时停用 {disabled} 个算法仓 monitor）。硬删除后续再做，可再次启用恢复。"})


async def _remove_agent_algorithm(client, device, db, task, task_id, args) -> str:
    """纯大模型任务删除一个智能体：从 agent_list 移除后 PUT；删空(或不指定)则降级停用整个任务。"""
    agent_key = args.get("agent_id") or args.get("event_type")  # 兼容用 event_id/event_tag 指定
    cur = task.get("agent_list", []) or []
    if not agent_key:
        # 不指定算法 → 清除整个任务（降级停用）
        return await _disable_whole_task(client, device, db, task, task_id, 0, [], reason="按请求清除整个任务")
    remaining = [a for a in cur
                 if str(a.get("event_id")) != str(agent_key) and str(a.get("event_tag")) != str(agent_key)]
    if len(remaining) == len(cur):
        return _err(f"任务中未找到智能体「{agent_key}」，无需删除")
    if not remaining:
        # 删空 → 清除整个任务（降级停用）
        return await _disable_whole_task(client, device, db, task, task_id, 0, [],
                                         reason=f"删除的是任务最后一个智能体「{agent_key}」")
    task["agent_list"] = remaining
    payload = DeviceService.build_task_payload(task)
    data = await DeviceService.update_task(client, device, db, payload)
    if data is None:
        return _err(f"任务 task_id={task_id} 删除智能体时设备不可达，请重试")
    if data.get("code") != 0:
        return _err(f"任务 task_id={task_id} 删除智能体失败：{data.get('message')}")
    return _ok({"success": True, "task_id": task_id,
                "message": f"已从任务 task_id={task_id} 删除智能体「{agent_key}」（现关联 {len(remaining)} 个）"})


async def _add_task_algorithm(args: dict, db: AsyncSession) -> str:
    """向【已下发任务】增加一个算法（增）。

    - 小模型/小+大任务(single_point_task)：算法 = (algo_cabin_name, event_type)。
      · 目标算法仓已在任务中 → 往该仓 rulesParams 追加一条规则（连同原有规则一起覆盖重下）；
      · 目标算法仓不在任务中 → 用【相同 monitor_id】新建该仓 monitor（跨仓算法共享 monitor_id）。
      给了 agent_id 时该算法为『小+大』，挂二次大模型。
    - 纯大模型任务(agent_real_task)：算法 = 智能体，用 agent_id 指定，追加到 agent_list 后 PUT（上限 4）。
    """
    device = await _get_device(db, args.get("device_id", ""))
    if not device:
        return _err("未找到设备，请先在『设备接入』添加并获取详情")
    task_id = args.get("task_id")
    if not task_id:
        return _err("缺少 task_id，无法定位要新增算法的任务")

    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
        task, channel_device_id, err = await _locate_device_task(client, device, db, task_id)
        if err:
            return _err(err)
        if channel_device_id is None:
            return _err(f"任务 task_id={task_id} 缺少通道信息，无法新增算法")

        # ── 纯大模型任务：追加智能体到 agent_list（复用『同任务多智能体』范式）──
        if task.get("task_type") == "agent_real_task":
            agent_id = args.get("agent_id")
            if not agent_id:
                return _err("纯大模型任务新增算法需提供 agent_id（要关联的智能体算法）")
            agent, aerr = await _find_agent(client, device, db, agent_id)
            if aerr == "NOT_FOUND":
                return _err(f"设备上不存在智能体算法「{agent_id}」，请先确认是否新建（create_agent）。")
            if aerr:
                return _err(f"新增失败：{aerr}")
            cur = task.get("agent_list", []) or []
            if any(str(a.get("event_id")) == str(agent.get("event_id")) for a in cur):
                return _ok({"success": True, "task_id": task_id,
                            "message": f"任务已关联智能体「{agent.get('event_tag')}」，无需重复添加"})
            if len(cur) >= 4:
                return _err(f"任务已关联 {len(cur)} 个智能体算法，达上限 4，无法再新增")
            is_attr = (agent.get("alarm_type") or "").lower() == "freeform"
            new_item = {
                "event_id": agent.get("event_id"),
                "event_tag": agent.get("event_tag"),
                "agent_config": tb.build_agent_config({
                    **agent,
                    "prompt": args.get("prompt") if args.get("prompt") is not None else agent.get("prompt", ""),
                    "alarm_condition": args.get("alarm_condition"),
                    "filter_enable": bool(args.get("filter_enable", False)) if is_attr else False,
                    "filter_keywords": (args.get("filter_keywords", "") if is_attr else ""),
                }),
            }
            task["agent_list"] = cur + [new_item]
            payload = DeviceService.build_task_payload(task)
            data = await DeviceService.update_task(client, device, db, payload)
            if data is None:
                return _err(f"设备「{device.name}」离线或不可达，新增失败")
            if data.get("code") != 0:
                return _err(f"新增失败：{data.get('message')}")
            return _ok({"success": True, "task_id": task_id,
                        "message": f"智能体「{agent.get('event_tag')}」已追加至任务"
                                   f"（现关联 {len(task['agent_list'])} 个）"})

        # ── 小模型/小+大任务：往算法仓增加一条规则 ──
        event_type = args.get("event_type")
        algo_cabin_name = args.get("algo_cabin_name")
        if not event_type or not algo_cabin_name:
            return _err("小模型/小+大任务新增算法需提供 event_type 与 algo_cabin_name（来自 list_device_algorithms）")

        # 算法授权校验（整机级）
        pkgs, aerr = await _authorized_packages(client, device, db)
        if aerr:
            return _err(f"无法校验算法授权：{aerr}")
        if not _is_authorized(pkgs, algo_cabin_name):
            available = "、".join(p.get("package_name", "") for p in pkgs) or "（无）"
            return _err(f"设备未授权算法「{algo_cabin_name}」，无法新增。当前已授权：{available}")

        # combined：校验智能体、构造二次大模型参数
        agent_llm = None
        if args.get("agent_id"):
            agent, aerr = await _find_agent(client, device, db, args["agent_id"])
            if aerr == "NOT_FOUND":
                return _err(f"设备上不存在智能体算法「{args['agent_id']}」，请先确认是否新建（create_agent）。")
            if aerr:
                return _err(f"新增失败：{aerr}")
            agent_llm = tb.build_agent_llm_param(agent, prompt=args.get("prompt"))

        roi_points = args.get("roiPoints")
        area = ({"areaId": 1, "areaName": "检测区", "areaType": "POLYGON", "points": roi_points}
                if roi_points else tb.full_frame_area())
        new_rule = tb.build_rule(
            event_type=event_type, area=area,
            target_types=args.get("target_types"), threshold=args.get("threshold", 0.3),
            target_max=args.get("target_max", 1), target_min=args.get("target_min", 0),
            duration=args.get("duration", 3), cooldown=args.get("cooldown", 600),
            agent_llm=agent_llm, target_expand=args.get("target_expand"))

        # 读取任务全部 monitor，判断目标仓是否已存在
        mon_res = await DeviceService.authed_post(
            client, device, db, MONITOR_LIST_PATH,
            {"device_id": channel_device_id, "task_id": task_id})
        param = ((mon_res or {}).get("data") or {}).get("param") or []
        target_mon = _locate_warehouse_monitor(param, algo_cabin_name)

        if target_mon:
            # 同仓追加：去重同 eventType，连同原规则一起覆盖重下
            common = target_mon.get("common_param") or {}
            labels = (common.get("warehouse_v20_param") or {}).get("labels") or {}
            rules = tb._warehouse_rules(target_mon)
            if any(str(r.get("eventType")) == str(event_type) for r in rules):
                return _err(f"算法仓「{algo_cabin_name}」中已存在算法 eventType={event_type}，"
                            f"如需改参数请用 update_device_task")
            monitor_id = common.get("monitor_id")
            monitor_name = common.get("monitor_name")
            version = labels.get("version") or args.get("version", "V2.0.0")
            new_rules = list(rules) + [new_rule]
        else:
            # 跨仓新增：与任务已有 monitor【共享同一 monitor_id】，新建该仓 monitor
            monitor_id = None
            for m in param:
                mid = (m.get("common_param") or {}).get("monitor_id")
                if mid is not None:
                    monitor_id = mid
                    break
            monitor_name = None
            version = args.get("version", "V2.0.0")
            new_rules = [new_rule]

        monitor_payload = tb.build_warehouse_monitor(
            task_id, int(channel_device_id), algo_cabin_name, new_rules,
            version=version, monitor_id=monitor_id, monitor_name=monitor_name)
        mon_data = await DeviceService.create_monitor(client, device, db, monitor_payload)

    if mon_data is None:
        return _err(f"任务 task_id={task_id} 新增算法时设备不可达，请重试")
    if mon_data.get("code") != 0:
        return _err(f"任务 task_id={task_id} 新增算法失败：{mon_data.get('message')}")
    kind = "小+大" if agent_llm else "小模型"
    return _ok({"success": True, "task_id": task_id,
                "message": f"已向任务 task_id={task_id} 的算法仓「{algo_cabin_name}」新增{kind}算法「{event_type}」"})


async def _remove_task_algorithm(args: dict, db: AsyncSession) -> str:
    """从【已下发任务】删除一个算法（删）。设备无硬删除接口 → 覆盖重下 / 降级停用(enable:False)。

    - 小模型/小+大：算法 = (algo_cabin_name, event_type)。从目标仓 rulesParams 移除该规则：
      · 该仓仍有其它规则 → 用剩余规则覆盖重下该仓；
      · 该仓被删空但任务其它仓仍有算法 → 停用该仓 monitor(enable=False)，任务其余算法继续运行；
      · 删的是任务最后一个算法 → 按约定『整个任务清除』降级为【停用整个任务】(PUT enable=False + 停用各仓)。
    - 纯大模型：算法 = 智能体，从 agent_list 移除后 PUT；删空则停用整个任务。
    - 不指定算法标识（event_type / agent_id 均空）= 清除整个任务 → 停用整个任务。
    真正的硬删除后续再做（本轮统一降级为停用，可再次启用/覆盖恢复）。
    """
    device = await _get_device(db, args.get("device_id", ""))
    if not device:
        return _err("未找到设备，请先在『设备接入』添加并获取详情")
    task_id = args.get("task_id")
    if not task_id:
        return _err("缺少 task_id，无法定位要删除算法的任务")

    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
        task, channel_device_id, err = await _locate_device_task(client, device, db, task_id)
        if err:
            return _err(err)
        if channel_device_id is None:
            return _err(f"任务 task_id={task_id} 缺少通道信息，无法删除算法")

        # ── 纯大模型任务：从 agent_list 移除 ──
        if task.get("task_type") == "agent_real_task":
            return await _remove_agent_algorithm(client, device, db, task, task_id, args)

        # ── 小模型/小+大：从算法仓 rulesParams 移除 ──
        mon_res = await DeviceService.authed_post(
            client, device, db, MONITOR_LIST_PATH,
            {"device_id": channel_device_id, "task_id": task_id})
        param = ((mon_res or {}).get("data") or {}).get("param") or []
        if not param:
            return _err(f"未取到任务 task_id={task_id} 的 monitor（可能离线或该任务无 monitor），无法删除算法")

        event_type = args.get("event_type")
        # 不指定算法 → 清除整个任务（降级停用）
        if not event_type:
            return await _disable_whole_task(
                client, device, db, task, task_id, int(channel_device_id), param, reason="按请求清除整个任务")

        target_mon = _locate_warehouse_monitor(param, args.get("algo_cabin_name"))
        if not target_mon:
            return _err(f"未在任务 task_id={task_id} 中找到算法仓「{args.get('algo_cabin_name') or '(第一条)'}」的 monitor")
        rules = tb._warehouse_rules(target_mon)
        if not any(str(r.get("eventType")) == str(event_type) for r in rules):
            return _err(f"算法仓中未找到算法 eventType={event_type}，无需删除")
        remaining = [r for r in rules if str(r.get("eventType")) != str(event_type)]

        # 删除该算法后，任务跨所有仓是否还有算法
        others_have = any(m is not target_mon and len(tb._warehouse_rules(m)) > 0 for m in param)
        if (not remaining) and (not others_have):
            return await _disable_whole_task(
                client, device, db, task, task_id, int(channel_device_id), param,
                reason=f"删除的是任务最后一个算法「{event_type}」")

        common = target_mon.get("common_param") or {}
        labels = (common.get("warehouse_v20_param") or {}).get("labels") or {}
        monitor_id = common.get("monitor_id")
        monitor_name = common.get("monitor_name")
        version = labels.get("version", "V2.0.0")
        algo_cabin_name = labels.get("algoCabinName", "")

        if remaining:
            # 该仓仍有其它算法 → 用剩余规则覆盖重下
            monitor_payload = tb.build_warehouse_monitor(
                task_id, int(channel_device_id), algo_cabin_name, remaining,
                version=version, monitor_id=monitor_id, monitor_name=monitor_name, enable=True)
            note = f"（该算法仓仍保留 {len(remaining)} 个算法）"
        else:
            # 该仓被删空、但任务其它仓仍有算法 → 停用该仓 monitor（保留原规则、仅 enable=False）
            monitor_payload = tb.build_warehouse_monitor(
                task_id, int(channel_device_id), algo_cabin_name, rules,
                version=version, monitor_id=monitor_id, monitor_name=monitor_name, enable=False)
            note = "（该算法仓已无算法，已停用该仓；任务其它算法仓继续运行）"

        mon_data = await DeviceService.create_monitor(client, device, db, monitor_payload)
        if mon_data is None:
            return _err(f"任务 task_id={task_id} 删除算法时设备不可达，请重试")
        if mon_data.get("code") != 0:
            return _err(f"任务 task_id={task_id} 删除算法失败：{mon_data.get('message')}")
        return _ok({"success": True, "task_id": task_id,
                    "message": f"已从任务 task_id={task_id} 删除算法「{event_type}」{note}"})


async def _list_task_templates(args: dict, db: AsyncSession) -> str:
    """列出参数模板库（仅元数据，不回传完整 config 快照以省上下文）。可选按 task_mode 过滤。"""
    q = select(TaskTemplateORM).order_by(TaskTemplateORM.updated_at.desc())
    mode = args.get("task_mode")
    if mode:
        q = q.where(TaskTemplateORM.task_mode == mode)
    rows = (await db.execute(q)).scalars().all()
    templates = [{
        "id": t.id, "name": t.name, "task_mode": t.task_mode,
        "event_type": t.event_type, "description": t.description,
    } for t in rows]
    return _ok({"count": len(templates), "templates": templates})


async def _apply_task_template(args: dict, db: AsyncSession) -> str:
    """套用参数模板：读模板 config 快照 → 合并设备上下文 → 以 proposal 形式回传。

    复用前端 applyProposal 灌面板（proposal 携带 taskMode/alertType 等面板键），**不在服务端自动下发**
    （避免重复实现面板→设备映射，见计划 R1）；用户在界面确认参数、绘制 ROI 后再点部署走 create_* 工具。
    """
    template_id = args.get("template_id")
    if not template_id:
        return _err("缺少 template_id，无法套用模板")
    tpl = await db.get(TaskTemplateORM, template_id)
    if not tpl:
        return _err(f"未找到参数模板 template_id={template_id}，可先用 list_task_templates 查看可用模板")
    try:
        cfg = json.loads(tpl.config or "{}")
    except Exception:
        cfg = {}
    if not isinstance(cfg, dict):
        cfg = {}

    # 设备上下文（可选）：绑定设备/通道/任务名便于用户确认后直接部署；未给则沿用模板快照内的值
    ctx: dict = {}
    device_id = args.get("device_id")
    if device_id:
        device = await _get_device(db, device_id)
        if not device:
            return _err("未找到设备，请先在『设备接入』添加并获取详情")
        ctx["device_id"] = device.device_id
        ctx["device_name"] = device.name
    if args.get("channel_device_id") is not None:
        ctx["channel_device_id"] = args.get("channel_device_id")
    if args.get("task_name"):
        ctx["name"] = args.get("task_name")
    # 报警大图匹配用 alertType：模板快照优先，回落模板 event_type
    ctx["alertType"] = cfg.get("alertType") or tpl.event_type or None

    # fromTemplate 标记：前端据此区分『套用模板』(免 ROI 门禁) 与普通 propose_deployment 草案(需画 ROI)
    proposal = {**cfg, **ctx, "fromTemplate": True}
    return _ok({"success": True, "proposal": proposal,
                "message": f"已套用参数模板「{tpl.name}」到界面，请确认参数并绘制检测区(ROI)后点击部署。"})


# 推荐参数默认值：按 event_type 场景化（见 services/scene_presets），未命中回落通用默认；
# 键名与前端 AIControl 的 config 形状一致，供界面直接填充。
def _recommended_config(task_name: str, event_type: Optional[str] = None) -> dict:
    return {**scene_presets.preset_for(event_type), "name": task_name}


async def _propose_deployment(args: dict, db: AsyncSession) -> str:
    """依赖校验通过后，产出前端可直接填充的布控方案（推荐参数 + 元数据）。

    - smallmodel/combined：校验算法授权（落实『在有授权的情况下』）；
    - agent/combined：校验智能体算法存在，并借其 event_tag/prompt 作为推荐值。
    方案本身不下发设备，真正布控仍走 create_* 工具。
    """
    task_type = (args.get("task_type") or "").lower()
    if task_type not in ("smallmodel", "agent", "combined"):
        return _err("task_type 必须是 smallmodel / agent / combined 之一")

    device = await _get_device(db, args.get("device_id", ""))
    if not device:
        return _err("未找到设备，请先在『设备接入』添加并获取详情")

    cfg = _recommended_config(args.get("task_name", "") or "AI布控任务", args.get("event_type"))
    agent = None
    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
        # 小模型 / 小+大：授权门禁
        if task_type in ("smallmodel", "combined"):
            algo = args.get("algo_cabin_name")
            if not algo:
                return _err("创建小模型/小+大布控方案需要 algo_cabin_name（来自 list_device_algorithms）")
            pkgs, err = await _authorized_packages(client, device, db)
            if err:
                return _err(f"无法校验算法授权：{err}")
            if not _is_authorized(pkgs, algo):
                available = "、".join(p.get("package_name", "") for p in pkgs) or "（无）"
                return _err(f"设备未授权算法「{algo}」，无法生成布控方案。当前已授权：{available}")

        # 大模型 / 小+大：智能体算法存在校验
        if task_type in ("agent", "combined"):
            agent_id = args.get("agent_id")
            if not agent_id:
                return _err("创建大模型/小+大布控方案需要 agent_id（来自 list_agents）")
            agent, aerr = await _find_agent(client, device, db, agent_id)
            if aerr == "NOT_FOUND":
                return _err(f"设备上不存在智能体算法「{agent_id}」，请先确认是否新建（create_agent）。")
            if aerr:
                return _err(f"生成布控方案失败：{aerr}")

    if agent:
        cfg["agentType"] = agent.get("event_tag") or str(args.get("agent_id"))
        cfg["prompt"] = agent.get("prompt", "")

    proposal = {
        **cfg,
        "task_type": task_type,
        "event_type": args.get("event_type"),
        "algo_cabin_name": args.get("algo_cabin_name"),
        "agent_id": args.get("agent_id"),
        "channel_device_id": args.get("channel_device_id"),
        "alertType": args.get("event_type"),  # 前端按此优先匹配报警大图
        "device_id": device.device_id,
        "device_name": device.name,
    }

    # 纯大模型任务：补齐面板所需的多智能体 / ROI 结构 + 可选智能体下拉（离线用快照）
    if task_type == "agent":
        available = _load_json(device.agents)
        proposal.update({
            "taskMode": "agent",
            "interval": 5,
            "agents": [{
                "event_id": (agent or {}).get("event_id") or args.get("agent_id"),
                "event_tag": (agent or {}).get("event_tag") or str(args.get("agent_id")),
                "alarm_type": (agent or {}).get("alarm_type") or "freeform",
                "prompt": (agent or {}).get("prompt", ""),
                "alarm_condition": tb._default_alarm_condition((agent or {}).get("alarm_type")),
                "filter_enable": False,
                "filter_keywords": "",
                "roiId": "full",
            }],
            "rois": [{"id": "full", "name": "全屏检测", "points": []}],
            "activeAgentIndex": 0,
            "available_agents": available,
        })
    return _ok({"success": True, "proposal": proposal,
                "message": f"已为设备「{device.name}」生成布控方案预览，请在右侧界面确认参数并绘制检测区(ROI)。"})

