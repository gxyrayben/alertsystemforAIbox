"""小模型算法【中文名 ↔ 算法ID】映射目录（单一事实来源）。

背景：设备算法仓卡片（card_cap）返回的是英文算法ID（major_type / minor_type，
其中布控任务使用的 event_type = minor_type，如 INTRUSION / FALL）；而界面呈现与用户
配置任务时用的是中文名称（如 区域入侵 / 摔倒）。本目录维护二者的对应关系，供：
  - 呈现：list_device_algorithms 给每条算法补充中文名 eventName（ID → 中文）；
  - 布控：resolve_algorithm 工具把用户输入的中文名解析为 event_type 算法ID（中文 → ID）。

数据来源：MegCube-B5Z 智能体分析盒常用 API 协议文档（算法仓能力集）。
说明：
  - major_type 是算法大类，minor_type 是具体事件类型（= 下发布控用的 event_type）；
  - 个别 major_type（如 alert_alarm 同时覆盖『周界警戒 / 行为警戒』）会合并其事件集合；
  - 文档中的 (V300) 等版本标注不属于 ID 本身，此处已剔除。
"""

# 每组：(major_type, major_name, [(minor_type, event_name), ...])
# 同一 major_type 出现多次时（如 alert_alarm）会在建索引时自动合并事件集合。
_RAW = [
    ("structure", "结构化", [
        ("face", "人脸抓拍"),
        ("pedestrian", "人体抓拍"),
        ("vehicle", "车辆抓拍"),
        ("non_motor", "非机动车"),
        ("plate", "车牌"),
    ]),
    ("headcount_alarm", "人数统计", [
        ("head_count", "区域人数统计"),
        ("cross_line", "进出口人数统计"),
    ]),
    ("face_basic_business", "脸人", [
        ("face_capture", "人脸抓拍"),
        ("body_capture", "人体抓拍"),
        ("face_comparison_successful", "人脸识别"),
        ("stranger", "陌生人"),
    ]),
    ("goods_alarm", "物品", [
        ("SUNDRY_DETECT", "杂物堆放"),
        ("GOODS_FORGET", "物品遗留"),
        ("GOODS_GUARD", "物品看守"),
        ("NEW_GOODS_DETECT", "新增杂物检测"),
    ]),
    ("diagnosis_alarm", "视频诊断", [
        ("IMAGE_COVER_ALERT", "画面遮挡"),
    ]),
    ("gkpw_alarm", "高空抛物", [
        ("falling_goods", "高空抛物"),
    ]),
    ("mclz_alarm", "明厨亮灶", [
        ("TRASHBIN", "垃圾桶未盖"),
        ("MICE", "老鼠"),
        ("CHEF_CLOTH", "未穿戴厨师服"),
        ("CHEF_HAT", "未佩戴厨师帽"),
        ("CHEF_RESPIRATOR", "未佩戴口罩"),
        ("RUBBER_GLOVE", "未佩戴橡胶手套"),
        ("FLAME_WITHOUT_HUMAN", "动火离人"),
        ("DISH", "光盘检测"),
    ]),
    # alert_alarm 同时覆盖『周界警戒』与『行为警戒』，事件集合合并
    ("alert_alarm", "周界/行为警戒", [
        ("PARK", "车辆禁停"),
        ("EXIT", "车辆离开"),
        ("WANDER", "人员徘徊"),
        ("OVERWALL", "翻墙"),
        ("INTRUSION", "区域入侵"),
        ("CLIMB", "攀爬"),
        ("ELECTRIC_BIKE_IN_ELEVATOR", "电动车进电梯"),
        ("TRIPWIRE", "越界"),
        ("FALL", "摔倒"),
        ("SMOKING", "抽烟"),
        ("CALL", "打电话"),
        ("WATCH_POINE", "看手机"),
        ("RUN", "奔跑"),
        ("FIGHT", "扭打"),
        ("GATHERING", "人员聚众"),
        ("HOLDWEAPON", "持械"),
        ("LEAVE_POST", "人员离岗"),
        ("PERSON_LESS_QUERYING", "少员"),
        ("PERSON_OVER_QUERYING", "超员"),
        ("SLEEP", "睡岗"),
    ]),
    ("safety_alarm", "安监", [
        ("SAFETY_CAP", "未佩戴安全帽"),
        ("SAFETY_UNIFORM", "未穿戴安全工服"),
        ("SAFETY_BELT", "未佩戴安全带"),
        ("FIRE", "火焰"),
        ("SMOKE", "烟雾"),
        ("OIL_SPILL", "油品泄露"),
        ("REFLECTIVE_VEST", "反光衣"),
        ("FIRE_EQUIPMENT", "消防设施"),
        ("RESPIRATOR", "口罩"),
        ("TOUCHED_EEBALL", "触摸静电球"),
        ("INSULATING_GLOVE", "未佩戴绝缘手套"),
    ]),
    ("jyz_alarm", "加油站", [
        ("SAFETY_CAP", "未佩戴安全帽"),
        ("SAFETY_UNIFORM", "未穿戴安全工服"),
        ("FIRE", "火焰"),
        ("SMOKE", "烟雾"),
        ("OIL_SPILL", "油品泄露"),
        ("FIRE_EQUIPMENT", "消防设施"),
        ("INDICATOR_FLAG", "静电线"),
        ("OIL_PIPE", "卸油管检测"),
        ("OILPUMP_DOOR_OPEN", "油机侧盖打开"),
        ("OIL_GUN_DRAG", "油管拉断"),
        ("OIL_TRUCK", "油罐车检测"),
    ]),
    ("edu__alarm", "教学评测", [
        ("HEAD_UP", "抬头"),
        ("HEAD_DOWN", "低头"),
        ("STAND", "站立"),
        ("READ", "阅读"),
        ("WRITE", "书写"),
        ("RAISE_HAND", "举手"),
        ("REST", "趴桌"),
        ("PEACE", "中性"),
        ("LAUGH", "积极"),
        ("CRY", "消极"),
    ]),
    ("uniform_alarm", "工服注册仓", [
        ("UNIFORM_BY_FEATURE", "未穿工服"),
    ]),
    ("city_alarm", "城管", [
        ("HAWKER", "游商小贩"),
        ("OUTSTORE", "店外经营"),
        ("ROADSIDE", "占道经营"),
        ("SUNDRYSTACK", "杂物堆放"),
        ("MUCK", "堆积渣土"),
        ("EXPOSED_GARBAGE", "暴露垃圾"),
        ("OUTDOOR_ADV", "户外广告"),
        ("WATERGATHER", "道路积水"),
    ]),
    ("building_alarm", "工地", [
        ("UNCOVERED_GROUND", "裸土覆盖"),
        ("UNCOVERED_SKIN", "皮肤裸露"),
        ("UNCLEANED_CAR", "车辆未喷淋"),
    ]),
    ("edu__style", "教学风格", [
        ("WRITE_ON_BLACKBOARD", "板书"),
        ("BACK_TO_STUDENT", "背对学生"),
        ("PODIUM_MOVEMENT", "上下讲台"),
        ("PATROL", "巡视"),
        ("WRITE", "书写"),
        ("LECTURE", "讲课"),
    ]),
    ("fire_alarm", "智慧社区", [
        ("OVERFLOWED_GARBAGE", "垃圾满溢"),
        ("EXPOSED_GARBAGE", "垃圾暴漏"),
        ("NO_HELMET", "骑电动车未戴头盔"),
    ]),
]


# ── 建索引 ──────────────────────────────────────────────────────────────────
# EVENTS：全部事件的扁平列表，每项 {major_type, major_name, minor_type, event_name}
# _BY_MINOR：minor_type(小写) → 事件列表（同名 minor_type 可能跨大类，故用列表）
# _MAJOR_NAME：major_type → 中文大类名
EVENTS = []
_BY_MINOR = {}
_MAJOR_NAME = {}

for _major, _mname, _events in _RAW:
    _MAJOR_NAME.setdefault(_major, _mname)
    for _minor, _ename in _events:
        entry = {"major_type": _major, "major_name": _MAJOR_NAME[_major],
                 "minor_type": _minor, "event_name": _ename}
        EVENTS.append(entry)
        _BY_MINOR.setdefault(_minor.lower(), []).append(entry)


def _norm(s: str) -> str:
    return (s or "").strip().lower()


def event_name(minor_type: str, major_type: str = "") -> str:
    """算法ID(minor_type/event_type) → 中文事件名。找不到返回空串。

    个别 minor_type 跨大类且中文不同（如 EXPOSED_GARBAGE：城管『暴露垃圾』/ 智慧社区『垃圾暴漏』）。
    传入 major_type 可精确命中；否则返回首个匹配。"""
    hits = _BY_MINOR.get(_norm(minor_type))
    if not hits:
        return ""
    if major_type:
        for h in hits:
            if _norm(h["major_type"]) == _norm(major_type):
                return h["event_name"]
    return hits[0]["event_name"]


def major_name(major_type: str) -> str:
    """算法大类ID → 中文大类名。找不到返回空串。"""
    for k, v in _MAJOR_NAME.items():
        if _norm(k) == _norm(major_type):
            return v
    return ""


def resolve(query: str) -> list:
    """把用户输入解析为候选算法事件，供布控时取 minor_type 作为 event_type。

    支持四种输入：算法ID(minor_type，精确)、中文事件名(精确/包含)、
    算法大类ID(major_type，返回该类全部事件)、中文大类名(返回该类全部事件)。
    返回去重后的事件列表 [{major_type, major_name, minor_type, event_name}, ...]，
    无匹配返回空列表；调用方据数量判断唯一命中 / 需向用户澄清。"""
    q = _norm(query)
    if not q:
        return []

    exact_id, exact_name, contains = [], [], []
    for e in EVENTS:
        minor = _norm(e["minor_type"])
        ename = _norm(e["event_name"])
        if minor == q or ename == q:
            (exact_id if minor == q else exact_name).append(e)
        elif q in ename or ename in q:
            contains.append(e)

    # 大类匹配（major_type 或 中文大类名）：返回该大类全部事件
    major_hits = []
    for e in EVENTS:
        if _norm(e["major_type"]) == q or _norm(e["major_name"]) == q or q in _norm(e["major_name"]):
            major_hits.append(e)

    # 按优先级合并并去重（同 major_type+minor_type 视为同一项）
    seen, out = set(), []
    for group in (exact_id, exact_name, contains, major_hits):
        for e in group:
            key = (e["major_type"], e["minor_type"])
            if key not in seen:
                seen.add(key)
                out.append(e)
    return out
