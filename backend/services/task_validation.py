"""下发前【按任务类型的参数校验】纯函数（无 I/O，便于单测与复用）。

三条提交路径（界面手动 / 面板选模板 / 对话选模板）下发时都在路由层调用本模块，
作为『布控智能体校验』的统一 choke point：校验通过才继续下发。
仅做结构/取值范围校验；设备存在性（算法授权 / 智能体是否存在）是 I/O，仍在路由层完成。
"""
from typing import List


def validate_agent_deploy(body) -> List[str]:
    """纯大模型智能体任务(agent_real_task)下发校验，返回中文错误串列表（空=通过）。

    规则：关联 1~4 个智能体；每个智能体须有 event_id；分析间隔 analysis_interval≥1（仅智能体任务有此概念）。
    """
    errors: List[str] = []
    agents = list(getattr(body, "agents", None) or [])
    if not (1 <= len(agents) <= 4):
        errors.append("智能体任务需关联 1~4 个智能体算法")
    for i, a in enumerate(agents, 1):
        if not getattr(a, "event_id", None):
            errors.append(f"第 {i} 个智能体缺少 event_id（算法标识）")
    interval = getattr(body, "analysis_interval", 5)
    if interval is None or interval < 1:
        errors.append("分析间隔(analysis_interval)须 ≥1 秒")
    return errors


def validate_warehouse_deploy(body) -> List[str]:
    """算法仓任务（纯小模型 / 小+大 / 混合）多算法下发校验，返回中文错误串列表（空=通过）。

    规则：至少 1 条算法；每条须有 event_type 与 algo_cabin_name；阈值 0<threshold≤1；
    target_min≤target_max；duration≥0；cooldown≥0；同一算法仓内 event_type 不得重复
    （设备按仓覆盖 rulesParams、规则身份=eventType，同仓重复会互相顶掉）；
    combined 算法另需 agent_id（二次大模型智能体标识）。
    """
    errors: List[str] = []
    algorithms = list(getattr(body, "algorithms", None) or [])
    if not algorithms:
        errors.append("算法仓任务至少需要 1 个算法")
        return errors

    seen: dict = {}  # algo_cabin_name -> set(event_type)，检测同仓 eventType 重复
    for i, algo in enumerate(algorithms, 1):
        label = f"第 {i} 个算法"
        event_type = getattr(algo, "event_type", None)
        cabin = getattr(algo, "algo_cabin_name", None)
        if not event_type:
            errors.append(f"{label}缺少 event_type（算法事件类型）")
        if not cabin:
            errors.append(f"{label}缺少 algo_cabin_name（算法仓）")

        threshold = getattr(algo, "threshold", 0.3)
        if threshold is None or not (0 < threshold <= 1):
            errors.append(f"{label}的阈值(threshold)须在 (0, 1] 区间")

        target_min = getattr(algo, "target_min", 0)
        target_max = getattr(algo, "target_max", 1)
        if target_min is not None and target_max is not None and target_min > target_max:
            errors.append(f"{label}的最小目标数(target_min)不能大于最大目标数(target_max)")

        duration = getattr(algo, "duration", 3)
        if duration is not None and duration < 0:
            errors.append(f"{label}的持续时长(duration)不能为负")
        cooldown = getattr(algo, "cooldown", 600)
        if cooldown is not None and cooldown < 0:
            errors.append(f"{label}的报警间隔(cooldown)不能为负")

        if (getattr(algo, "kind", "small") or "small") == "combined" and not getattr(algo, "agent_id", None):
            errors.append(f"{label}为『小+大』但缺少 agent_id（二次大模型智能体）")

        if event_type and cabin:
            if event_type in seen.setdefault(cabin, set()):
                errors.append(f"算法仓「{cabin}」中 event_type={event_type} 重复，同仓算法事件类型须唯一")
            seen[cabin].add(event_type)

    return errors
