"""布控任务【场景化推荐参数】预设（PURE，无 I/O）。

按小模型算法事件类型（event_type，如 INTRUSION/FALL/FIRE）给出差异化的面板推荐默认值，
供 agent_tools._recommended_config / propose_deployment 生成布控方案预览时填充右侧控制面板。
键名与前端 AIControl 的 config 形状一致；场景未命中时回落到 _GENERIC 通用默认。

注意：这是【界面推荐默认】。用户在对话里显式给的参数仍以其为准，预设只影响 propose 预览的起始值。
"""
from typing import Dict, Optional

# 通用默认（与 task_builders 的下发默认对齐：阈值 ~0.3 / 单目标 / 时长 3 / 对称扩图）
_GENERIC: dict = {
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

# 按 event_type（大写）差异化的场景预设；仅列与通用默认不同的键，其余由 _GENERIC 兜底。
_PRESETS: Dict[str, dict] = {
    # 区域入侵：盯人；讲求快速触发（低时长）+ 抑制重复报警（较高冷却）
    "INTRUSION": {
        "yoloTarget": "human",
        "intrusionDuration": 2,
        "alarmInterval": 30,
    },
    # 越界：同入侵思路，盯人快触发
    "TRIPWIRE": {
        "yoloTarget": "human",
        "intrusionDuration": 2,
        "alarmInterval": 30,
    },
    # 摔倒：盯人；短时长以免错过瞬时姿态
    "FALL": {
        "yoloTarget": "human",
        "intrusionDuration": 1,
        "alarmInterval": 20,
    },
    # 火焰：目标不限于人(any)；阈值偏低以免漏报；扩图偏大给二次大模型更多上下文
    "FIRE": {
        "yoloTarget": "any",
        "yoloHumanThresh": 0.25,
        "intrusionDuration": 1,
        "alarmInterval": 15,
        "cropUp": 0.6,
        "cropDown": 0.5,
        "cropLeft": 0.6,
        "cropRight": 0.6,
    },
    # 烟雾：同火焰，阈值更低（烟雾更弥散、更易漏检）
    "SMOKE": {
        "yoloTarget": "any",
        "yoloHumanThresh": 0.22,
        "intrusionDuration": 1,
        "alarmInterval": 15,
        "cropUp": 0.6,
        "cropDown": 0.5,
        "cropLeft": 0.6,
        "cropRight": 0.6,
    },
}


def preset_for(event_type: Optional[str] = None) -> dict:
    """按 event_type 返回推荐参数（通用默认 + 场景覆盖）；event_type 为空/未命中返回通用默认副本。"""
    base = dict(_GENERIC)
    base.update(_PRESETS.get((event_type or "").upper(), {}))
    return base
