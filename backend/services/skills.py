"""智能体技能注册表（Skill Registry）—— 单一事实来源。

每个 SKILL = 名称 + 描述 + 图标 + 拥有的工具（引用 agent_tools.TOOLS 中的工具名）+ 使用指引。
系统提示词（发给大模型）与前端技能面板都由本注册表生成，新增技能只需在此登记。

底层工具实现仍在 services/agent_tools.py，本模块只做「能力编排/呈现」，不重复实现工具逻辑。
"""
from services.agent_tools import TOOLS

# ── 技能定义 ────────────────────────────────────────────────────────────────
SKILLS = [
    {
        "id": "channels",
        "name": "设备通道查询",
        "icon": "📹",
        "description": "获取设备接入的视频流通道列表，包含通道ID、名称、协议、取流地址及在线状态。",
        "tools": ["list_devices", "get_device_streams"],
        "preset": "帮我查询当前设备接入了哪些视频流通道，并给出每个通道的在线状态。",
        "guidance": (
            "【技能①·设备通道查询】\n"
            "- 用户问『接入了多少路/哪些视频流通道』『通道在线状态』『取流地址』时，使用本技能。\n"
            "- 先用 list_devices 确认设备与其在线状态；再用 get_device_streams 列出该设备的通道"
            "（device_id/通道名称/协议/RTSP取流地址/在线状态）。\n"
            "- 若设备离线，如实告知无法获取实时通道，不要编造。"
        ),
    },
    {
        "id": "view_tasks",
        "name": "布控任务查看",
        "icon": "📋",
        "description": "查看设备端已布控的任务，展示任务ID、任务名称、任务类型、通道名称、任务状态、关联智能体/算法，并按『小模型 / 大模型 / 小+大』归类。",
        "tools": ["get_device_control_tasks"],
        "preset": "帮我查看当前设备已经布控了哪些任务，并按小模型、大模型、小+大分类。",
        "guidance": (
            "【技能②·布控任务查看】\n"
            "- 用户问『已布控了哪些任务』『设备上部署了什么任务』时，使用 get_device_control_tasks。\n"
            "- 每条任务至少包含以下字段，务必完整呈现：任务ID(task_id)、任务名称(task_name)、"
            "任务类型(category：小模型任务/大模型任务/小+大任务)、通道名称(device_name)、"
            "任务状态(status：启用/停用)、关联智能体/算法(agent_name)。\n"
            "- 小模型任务(single_point_task)通常无关联智能体，关联智能体/算法可为空，属正常情况。\n"
            "- 总结时按小模型/大模型/小+大三类分组说明数量与代表任务，不要逐条罗列（表格已展示明细）。"
        ),
    },
    {
        "id": "deploy_tasks",
        "name": "任务布控",
        "icon": "🚀",
        "description": "创建布控任务，支持小模型任务、大模型任务、小+大任务；下发前可先在界面预览参数并绘制检测区(ROI)。",
        "tools": [
            "check_algorithm_authorization", "list_device_algorithms", "resolve_algorithm", "list_agents",
            "create_agent", "propose_deployment",
            "create_smallmodel_task", "create_agent_task", "create_combined_task",
            "update_device_task", "add_task_algorithm", "remove_task_algorithm",
        ],
        "preset": "我想在当前设备上新建一个布控任务，请先帮我做依赖校验并生成一份布控方案预览。",
        "guidance": (
            "【技能③·任务布控】布控任务分三大类，均依赖设备能力，务必先做依赖校验再创建：\n"
            "A. 纯小模型任务（create_smallmodel_task）\n"
            "   - 先 check_algorithm_authorization / list_device_algorithms 确认算法已授权、拿到 eventType 与 algoCabinName；未授权则明确告知无法创建。\n"
            "   - 【中文名→算法ID】设备返回的是英文算法ID（event_type，如 INTRUSION/FALL），用户通常说中文（如 区域入侵/摔倒）。"
            "list_device_algorithms 已给每条算法附中文名 eventName，据此对齐用户意图；若仅凭中文名不确定对应的 event_type，"
            "先用 resolve_algorithm 把中文名解析为算法ID，再用其 minor_type 作为 event_type 布控。"
            "务必确保该 event_type 确实存在于本机 list_device_algorithms 的返回中，不要凭映射表臆造设备没有的算法。\n"
            "B. 纯大模型任务（create_agent_task）\n"
            "   - 先 list_agents 确认对应智能体算法存在；不存在时提示用户『是否新建？』，"
            "确认后 create_agent 新建成功再 create_agent_task。未经确认不要擅自新建。\n"
            "C. 小+大任务（create_combined_task）\n"
            "   - 同时依赖 A 的算法授权与 B 的智能体算法，两者都校验通过后再创建。\n"
            "- 【重要】算法授权与智能体算法都是【整机硬件级】能力，与具体通道/路数无关：依赖校验时只需确认"
            "『整机是否拥有该授权/该智能体』，用一句话说明有或没有即可；不要按通道/路数逐条罗列，也不要"
            "把智能体的完整提示词整段复述给用户。\n"
            "- 创建需要 channel_device_id（整数，来自技能①的通道 device_id）；不清楚时先查通道并与用户确认。\n"
            "- 用户希望先在界面预览参数/画检测区(ROI)时，依赖校验通过后先调 propose_deployment 生成方案，"
            "系统会把推荐参数填充到右侧『AI级联提取与细化控制面板』并在视频区载入该设备最新报警大图；"
            "用户确认后再用上面三个创建工具真正下发。\n"
            "- 复杂参数（检测区域、目标类型、阈值、分析间隔）采用合理默认，除非用户指定；下发前用简短中文确认关键项。\n"
            "- 【创建成功后必做】任一创建工具（create_smallmodel_task / create_agent_task / create_combined_task）"
            "返回 success 后，必须紧接着调用 get_device_control_tasks 重新拉取该设备的全部布控任务，"
            "让系统把最新任务列表以表格形式展示给用户；随后用一句话确认『任务已创建，当前设备共 N 个布控任务』。"
            "追加智能体到已有任务的情况同样适用（复查以体现该任务已多关联一个智能体）。\n"
            "- 【修改已下发任务的某个算法参数】用户想调整某个【已布控】任务里【某一个算法】的阈值/目标数/持续时长/"
            "报警间隔/检测目标/ROI/扩图/二次大模型提示词时，用 update_device_task（传 task_id + 仅需修改的项），"
            "底层对该任务的 monitor 以相同 id 覆盖下发。\n"
            "- 【同一任务多算法·增删改查】同一个任务、同一类型可以布控多个算法，支持增删改查：\n"
            "   · 算法身份：小模型/小+大 = 算法仓 algo_cabin_name + 事件类型 event_type；纯大模型 = 智能体(agent_id)。\n"
            "   · 查：get_device_control_tasks 返回的任务明细已按『算法仓/规则』或『智能体列表』展开每个算法。\n"
            "   · 增：add_task_algorithm（往已有任务加一个算法；小模型/小+大传 event_type+algo_cabin_name，"
            "纯大模型传 agent_id），同任务已有算法保留。\n"
            "   · 改：update_device_task；任务含多个算法时用 algo_cabin_name+event_type 定位要改的那个，其它算法不受影响；"
            "单算法任务可不填定位项。\n"
            "   · 删：remove_task_algorithm（按 event_type / agent_id 删一个算法）。注意设备暂无硬删除接口，"
            "【删除】统一降级为【停用】(enable=False，可再启用/覆盖恢复)：删到某算法仓为空则停用该仓；"
            "删除最后一个算法、或不指定任何算法标识（=清除整个任务）则停用整个任务(PUT enable=False)；硬删除后续再做。\n"
            "- 上述增删改仅针对有 monitor 的小模型/小+大按算法仓+规则操作，纯大模型按智能体列表操作；抽帧间隔不在此范围。"
            "改/增/删完照例调 get_device_control_tasks 复查最新算法清单。"
        ),
    },
    {
        "id": "task_templates",
        "name": "参数模板库",
        "icon": "🗂️",
        "description": "复用已保存的布控参数模板：列出模板、把模板参数一键套用到控制面板，确认后即可部署，免去重复调参。",
        "tools": ["list_task_templates", "apply_task_template"],
        "preset": "帮我列出参数模板库里有哪些布控模板。",
        "guidance": (
            "【技能④·参数模板库】把常用布控参数（阈值/目标数/时长/报警间隔/扩图/检测目标等）存成模板，随用随取：\n"
            "- 用户问『有哪些模板』『用/套用某个模板』时，先用 list_task_templates 列出（可按 task_mode 过滤），"
            "让用户确认要套用哪一个；仅凭模板名不确定时先列出再匹配。\n"
            "- 确定后用 apply_task_template（传 template_id；可选 device_id/channel_device_id/task_name），"
            "系统会把模板参数填充到右侧『AI级联提取与细化控制面板』并载入该设备最新报警大图供画 ROI。\n"
            "- 【重要】套用【不会自动下发】：套用只是把参数灌到界面，需用户确认参数、绘制检测区(ROI)后，"
            "再用技能③的 create_smallmodel_task / create_agent_task / create_combined_task 真正下发到设备。\n"
            "- 套用后若用户要求微调某项参数，直接在对话里说明即可，系统会更新面板对应项。"
        ),
    },
]

# ── 非技能类工具（平台本地台账，仍可用但不作为主推技能） ──────────────────────
_LEDGER_TOOLS = ["list_tasks", "create_task", "update_task"]

# 导入期校验：技能引用的工具名必须真实存在于 TOOLS，避免注册表与实现漂移。
_TOOL_NAMES = {t["name"] for t in TOOLS}
for _skill in SKILLS:
    for _tool in _skill["tools"]:
        assert _tool in _TOOL_NAMES, f"技能 {_skill['id']} 引用了不存在的工具: {_tool}"


def skill_tool_names() -> set:
    """汇总所有技能拥有的工具名集合。"""
    names = set()
    for skill in SKILLS:
        names.update(skill["tools"])
    return names


def build_skills_prompt() -> str:
    """由技能注册表生成系统提示词的技能段落（角色 intro + 各技能指引 + 全局约束）。"""
    lines = [
        "你是一个设备视频流通道算法任务管理【智能体】，具备下列技能（SKILLS）。"
        "请根据用户意图选择合适的技能与工具完成任务。",
        "",
        "【已具备的技能】",
    ]
    for i, skill in enumerate(SKILLS, 1):
        tools = "、".join(skill["tools"])
        lines.append(f"{i}. {skill['icon']} {skill['name']}：{skill['description']}（工具：{tools}）")
    lines.append("")
    for skill in SKILLS:
        lines.append(skill["guidance"])
        lines.append("")
    lines.append(
        "【其它能力】list_tasks / create_task / update_task 仅用于平台本地任务台账登记，"
        "不下发到设备；真正布控到设备请用技能③的三个创建工具。"
    )
    lines.append(
        "【通用约束】系统会自动将查询类工具的结果以表格形式展示给用户，你只需用中文给出简洁总结，"
        "无需在文字里重复罗列表格内容。涉及创建/下发的动作，务必先做依赖校验并向用户确认关键项。"
    )
    return "\n".join(lines)


def public_skills() -> list:
    """给前端技能面板的精简元数据（隐藏内部 guidance）。"""
    return [
        {
            "id": s["id"],
            "name": s["name"],
            "icon": s["icon"],
            "description": s["description"],
            "tools": s["tools"],
            "preset": s.get("preset", ""),
        }
        for s in SKILLS
    ]
