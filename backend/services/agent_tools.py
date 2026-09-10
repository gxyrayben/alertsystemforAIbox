"""BOX设备任务管理智能体工具定义与执行层。

工具分两类：
- 平台本地台账：list_devices / list_tasks / create_task / update_task（操作 TaskORM）
- 设备侧能力与布控：get_device_streams / get_device_control_tasks（快照）+
  check_algorithm_authorization / list_device_algorithms / list_agents / create_agent /
  create_smallmodel_task / create_agent_task / create_combined_task（实时调设备 API）
"""
import json, uuid, time
import httpx
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from models.orm import DeviceORM, TaskORM
from services.device_service import DeviceService
from services import task_builders as tb

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
                "analysis_interval": {"type": "integer", "description": "分析间隔秒，默认 5"},
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
                "analysis_interval": {"type": "integer", "description": "分析间隔秒，默认 5"},
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
                "analysis_interval": {"type": "integer", "description": "分析间隔秒，默认 5"},
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
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            agent, err = await _find_agent(client, device, db, args["agent_id"])
            if err == "NOT_FOUND":
                return _err(f"设备上不存在智能体算法「{args['agent_id']}」。"
                            f"如需使用，请先确认是否新建该智能体算法（create_agent）。")
            if err:
                return _err(f"创建失败：{err}")
            payload = tb.build_agent_task_payload(
                args["task_name"], int(args["channel_device_id"]), agent,
                prompt=args.get("prompt"), alarm_condition=args.get("alarm_condition"),
                analysis_interval=args.get("analysis_interval", 5))
            data = await DeviceService.create_task(client, device, db, payload)
        if data is None:
            return _err(f"设备「{device.name}」离线或不可达，任务下发失败")
        if data.get("code") != 0:
            return _err(f"任务下发失败：{data.get('message')}")
        return _ok({"success": True, "task_id": data.get("data", {}).get("task_id"),
                    "message": f"纯大模型任务「{args['task_name']}」已下发"})

    if name in ("create_smallmodel_task", "create_combined_task"):
        return await _create_warehouse_task(name, args, db)

    if name == "propose_deployment":
        return await _propose_deployment(args, db)

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

        # 小+大：额外校验智能体算法存在
        agent_llm = None
        if combined:
            agent, aerr = await _find_agent(client, device, db, args["agent_id"])
            if aerr == "NOT_FOUND":
                return _err(f"设备上不存在智能体算法「{args['agent_id']}」，请先确认是否新建（create_agent）。")
            if aerr:
                return _err(f"创建失败：{aerr}")
            agent_llm = tb.build_agent_llm_param(agent, prompt=args.get("prompt"))

        # 2) 第一步：创建 single_point_task
        task_payload = tb.build_single_point_task_payload(
            args["task_name"], int(args["channel_device_id"]), args["event_type"],
            analysis_interval=args.get("analysis_interval", 5))
        task_data = await DeviceService.create_task(client, device, db, task_payload)
        if task_data is None:
            return _err(f"设备「{device.name}」离线或不可达，任务下发失败")
        if task_data.get("code") != 0:
            return _err(f"任务创建失败：{task_data.get('message')}")
        task_id = task_data.get("data", {}).get("task_id")

        # 3) 第二步：下发 monitor
        monitor_payload = tb.build_monitor_payload(
            task_id, int(args["channel_device_id"]), args["event_type"], args["algo_cabin_name"],
            version=args.get("version", "V2.0.0"),
            target_types=args.get("target_types"),
            threshold=args.get("threshold", 0.3),
            monitor_name=args["task_name"], agent_llm=agent_llm)
        mon_data = await DeviceService.create_monitor(client, device, db, monitor_payload)

    if mon_data is None:
        return _err(f"任务已创建(task_id={task_id})，但 monitor 下发时设备不可达，请重试")
    if mon_data.get("code") != 0:
        return _err(f"任务已创建(task_id={task_id})，但 monitor 下发失败：{mon_data.get('message')}")
    kind = "小+大" if combined else "纯小模型"
    return _ok({"success": True, "task_id": task_id,
                "message": f"{kind}任务「{args['task_name']}」已下发"})


# 推荐参数默认值：与 task_builders 的下发默认对齐（threshold/target_expand/duration），
# 键名与前端 AIControl 的 config 形状一致，供界面直接填充。
def _recommended_config(task_name: str) -> dict:
    return {
        "name": task_name,
        "yoloTarget": "human",
        "yoloHumanThresh": 0.31,
        "yoloVehicleThresh": 0.32,
        "yoloNonMotorThresh": 0.37,
        "maxTarget": 1.0,
        "minTarget": 0.0,
        "intrusionDuration": 3,
        "alarmInterval": 10,
        "cropUp": 0.5,
        "cropDown": 0.3,
        "cropLeft": 0.4,
        "cropRight": 0.6,
    }


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

    cfg = _recommended_config(args.get("task_name", "") or "AI布控任务")
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

