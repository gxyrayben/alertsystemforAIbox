"""任务编排规则引擎：把设备已有的算法/智能体告警，按用户画的编排图串联成新的「业务预警」。

执行模型（平台侧、事件驱动 + 时间窗）：
- 每次设备推送一条原始告警（alerts 表新增一行），引擎把这条告警交给所有【启用】的编排任务；
- 引擎取该设备最近 `WINDOW_SECONDS` 内的告警作为"事件集合"，自底向上求每个节点的命中事件；
- 输出节点命中 → 生成一条 OrchestrationAlarm（业务预警），两层去重：
  ① 窗口签名（同一时间窗口只发一条，永久生效）；② 冷却静默期（跨窗口的发送频率上限）。

节点语义（nodes[i].type）：
- task   ：数据源 = 该任务的告警（其算法/智能体 ∩ 其分析通道，来自 device_tasks 快照）
- algo   ：校验节点 = 告警是该算法 ∩ 通道与其上游任务一致（不一致则该分支无效）
- logic  ：多路组合算子（见 LOGIC_OPERATORS），滚动窗/会话窗内「一次窗口只触发一次」
- llm    ：多模态复核——上游命中后用大模型看告警图，放行/拦截
- output ：上游命中即产出业务预警
"""
import base64
import json
import math
import os
import re
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Dict, List, Optional, Set, Tuple

from sqlalchemy import desc, select

import database
from models.db import AsyncSessionLocal
from models.orm import AlertORM, DeviceORM, OrchestrationAlarmORM, OrchestrationTaskORM
from services import llm_client

WINDOW_SECONDS = 600          # 时间窗：只回看最近 10 分钟的原始告警做组合
DEFAULT_DEBOUNCE_SECONDS = 30  # 输出防抖默认值

# ── 基础结构 ────────────────────────────────────────────────────────────
def _json(s) -> object:
    try:
        return json.loads(s or "[]")
    except Exception:
        return [] if isinstance(s, str) and (not s or s[0] == "[") else {}


class HitList(list):
    """某节点命中事件列表，并携带【本次命中的窗口标识】。

    逻辑元件按窗口求值时写入 win_key（如 tumbling:<节点>:<桶起点> / session:<节点>:<开窗时刻>），
    输出元件用它作为业务预警的签名 → 天然实现「同一时间窗口只触发一次对应的告警」。
    普通 list 用法完全兼容（真值、len、迭代、max 都不受影响）。
    """
    __slots__ = ("win_key",)

    def __init__(self, items=(), win_key: str = ""):
        super().__init__(items)
        self.win_key = win_key


def _now_ms() -> int:
    return int(time.time() * 1000)


def _in_schedule(windows: list, now: Optional[datetime] = None) -> bool:
    """排班判断（旧版 windows 数组）：windows=[{start:"HH:MM", end:"HH:MM", weekdays:[0..6]}]，0=周一。"""
    now = now or datetime.now()
    if not windows:
        return True
    hm = now.strftime("%H:%M")
    wd = now.weekday()
    for w in windows:
        days = w.get("weekdays") or list(range(7))
        if wd not in days:
            continue
        start, end = w.get("start", "00:00"), w.get("end", "23:59")
        if start <= hm <= end:
            return True
    return False


def _in_active_range(cfg: dict, now: Optional[datetime] = None) -> bool:
    """排班门控（产品化算子参数）：activeTimeRange 形如 "08:00-18:00,20:00-22:00"。

    兼容旧版 windows 数组（早期编排数据）。
    """
    windows = cfg.get("windows")
    if isinstance(windows, list) and windows:
        return _in_schedule(windows, now)
    rng = str(cfg.get("activeTimeRange") or "").strip()
    if not rng:
        return True
    now = now or datetime.now()
    hm = now.strftime("%H:%M")
    for part in re.split(r"[,，;；\s]+", rng):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            start, end = [x.strip() for x in part.split("-", 1)]
            if start <= hm <= end:
                return True
        elif part == hm:
            return True
    return False


def _match_event_keys_for_algo(config: dict) -> Set[str]:
    """原子算法节点 → 一组 alertType 匹配键。"""
    kind = (config.get("kind") or "warehouse").lower()
    keys = set()
    if kind == "agent":
        for k in ("event_id", "event_tag"):
            v = config.get(k)
            if v:
                keys.add(str(v))
    else:
        for k in ("event_type", "event_name"):
            v = config.get(k)
            if v:
                keys.add(str(v))
    return keys


def _task_info(device_tasks: list, task_id) -> dict:
    """把一个【任务元件】展开成它的算法集合与分析通道。

    返回 {found, keys, channel, channel_name, name, task_type}：
    - keys         ：该任务布控的算法/智能体（alertType 匹配键，来自设备快照 detail）
    - channel      ：该任务的分析通道 id（detail.channel_device_id），用于与算法元件做通道一致性校验
    - channel_name ：通道名（快照 camera_device_name，拿不到时留空）
    """
    info = {"found": False, "keys": set(), "channel": "", "channel_name": "", "name": "", "task_type": ""}
    for t in device_tasks:
        if str(t.get("task_id")) != str(task_id):
            continue
        info["found"] = True
        info["name"] = t.get("task_name") or ""
        info["task_type"] = t.get("task_type") or ""
        info["channel_name"] = str(t.get("camera_device_name") or "").strip()
        detail = t.get("detail") or {}
        info["channel"] = str(detail.get("channel_device_id") or t.get("camera_device_id") or "").strip()
        for a in detail.get("algorithms") or []:
            if a.get("event_type"):
                info["keys"].add(str(a.get("event_type")))
        for ag in detail.get("agents") or []:
            for k in ("event_id", "event_tag"):
                if ag.get(k):
                    info["keys"].add(str(ag.get(k)))
        break
    return info


def _matches(alert, keys: Set[str], channel: str = "") -> bool:
    """告警是否命中某节点：alertType ∈ keys（keys 为空=不限算法）+ 通道一致（channel 为空=不限通道）。"""
    if keys and str(alert.alertType or "") not in keys:
        return False
    if channel and str(alert.channelid or "").strip() != channel:
        return False
    return True


def _same_channel(a_id: str, a_name: str, b_id: str, b_name: str, ch_name_by_id: dict) -> bool:
    """通道一致性比较：id 相同即一致；id 不同时用名字兜底（设备通道 id 空间不一致时也认得出来）。"""
    a_id, b_id = str(a_id or "").strip(), str(b_id or "").strip()
    if a_id and b_id and a_id == b_id:
        return True
    a_name = str(a_name or "").strip() or ch_name_by_id.get(a_id, "")
    b_name = str(b_name or "").strip() or ch_name_by_id.get(b_id, "")
    return bool(a_name) and a_name == b_name


def _diag(diag: Optional[dict], node_id: str, matched: Optional[list], reason: str = "") -> None:
    """记录节点求值结果与原因（供「校验」接口回显，便于定位为什么没触发）。"""
    if diag is None:
        return
    diag[node_id] = {"matched": len(matched) if matched else 0, "reason": reason}


# ── 图结构与求值上下文 ──────────────────────────────────────────────────
def build_graph(nodes: list, edges: list) -> Tuple[dict, Dict[str, List[str]], Dict[str, List[str]]]:
    """返回 (node_by_id, children_of, parents_of)。"""
    node_by_id = {n["id"]: n for n in nodes if isinstance(n, dict) and n.get("id")}
    children_of: Dict[str, List[str]] = {nid: [] for nid in node_by_id}
    parents_of: Dict[str, List[str]] = {nid: [] for nid in node_by_id}
    for e in edges:
        s, t = e.get("source"), e.get("target")
        if s in node_by_id and t in node_by_id:
            children_of[s].append(t)
            parents_of[t].append(s)
    return node_by_id, children_of, parents_of


@dataclass
class EvalCtx:
    """一次图求值所需的全部只读上下文（把原来递归穿的 9 个参数收成一个对象）。"""
    node_by_id: dict
    parents_of: Dict[str, List[str]]
    alerts: list
    device_tasks: list = field(default_factory=list)
    ch_name_by_id: Dict[str, str] = field(default_factory=dict)
    diag: Optional[dict] = None          # 非 None 时逐步记录命中数与未命中原因（供「校验」回显）

    def inputs(self, node_id: str) -> List[str]:
        return self.parents_of.get(node_id, [])

    def note(self, node_id: str, matched: Optional[list], reason: str = "") -> None:
        # 「连线成环」比后续的门控失败更能说明问题，保留它不被覆盖
        if self.diag is not None and "成环" in str((self.diag.get(node_id) or {}).get("reason") or ""):
            return
        _diag(self.diag, node_id, matched, reason)


def _eval_node(node_id: str, ctx: EvalCtx, memo: dict, stack: Optional[Set[str]] = None) -> Optional[list]:
    """自底向上求某节点的【命中告警列表】；未命中返回 None。

    输入 = 指向本节点的上游节点（ctx.parents_of[node_id]），数据流方向 source→target。
    stack 用于环检测（画布允许任意连线，成环时按未命中处理，避免无限递归）。
    """
    if node_id in memo:
        return memo[node_id]
    if node_id in (stack or set()):
        # 画布允许任意连线：成环时按未命中处理，避免无限递归
        ctx.note(node_id, None, "连线成环，已跳过")
        return None
    stack = (stack or set()) | {node_id}
    node = ctx.node_by_id[node_id]
    cfg = node.get("config") or {}
    ntype = node.get("type")
    input_ids = ctx.inputs(node_id)

    if ntype in ("task", "algo"):
        memo[node_id] = _eval_sources(node, ntype, cfg, input_ids, ctx, memo, stack)
        return memo[node_id]

    results = {cid: _eval_node(cid, ctx, memo, stack) for cid in input_ids}

    if ntype == "logic":
        memo[node_id] = _eval_logic(node, cfg, input_ids, results, ctx)
    elif ntype in ("llm", "output"):
        # 复核/输出：上游命中即透传（真正的大模型复核在输出阶段统一做一次）
        upstream = next((results[cid] for cid in input_ids if results.get(cid)), None)
        memo[node_id] = upstream
        ctx.note(node_id, upstream, "" if upstream else "上游未命中，本节点无输入")
    else:
        memo[node_id] = None
        ctx.note(node_id, None, f"未知节点类型 {ntype}")
    return memo[node_id]


def _eval_sources(node: dict, ntype: str, cfg: dict, input_ids: List[str], ctx: EvalCtx,
                  memo: dict, stack: Set[str]) -> Optional[list]:
    """任务元件（数据源）与算法元件（校验节点）的求值。"""
    if ntype == "task":
        info = _task_info(ctx.device_tasks, cfg.get("task_id"))
        if not info["found"]:
            ctx.note(node["id"], None, f"任务未在设备快照中找到（task_id={cfg.get('task_id')}）：设备未同步或任务已删除")
            return None
        channel = str(cfg.get("channelid") or "").strip() or info["channel"]
        keys = info["keys"]
        if not keys and not channel:
            ctx.note(node["id"], None, "该任务在设备快照里既没有算法/智能体，也没有分析通道信息")
            return None
        hits = [a for a in ctx.alerts if _matches(a, keys, channel)]
        if not hits:
            ctx.note(node["id"], None,
                     f"最近 {WINDOW_SECONDS}s 内该任务没有告警：任务「{info['name'] or cfg.get('task_id')}」"
                     f"算法={sorted(keys) or '不限'} 通道={channel or '不限'}")
        else:
            ctx.note(node["id"], hits)
        return hits or None

    # ── 算法元件：告警必须是本算法，且通道与其上游任务一致（不一致则该分支无效）──
    keys = _match_event_keys_for_algo(cfg)
    if not keys:
        ctx.note(node["id"], None, "算法元件未绑定算法（请从②组元件库重新拖入）")
        return None
    task_channels = _upstream_task_channels(input_ids, ctx)
    channel = str(cfg.get("channelid") or "").strip()
    if task_channels and channel and not any(
            _same_channel(channel, "", cid, cname, ctx.ch_name_by_id) for cid, cname in task_channels):
        detail = "、".join(f"{cid or '—'}（{cname or '未命名'}）" for cid, cname in task_channels)
        ctx.note(node["id"], None,
                 f"通道校验不通过：算法元件绑定通道 {channel}"
                 f"（{ctx.ch_name_by_id.get(channel, '') or '未知通道'}），但上游任务的关联通道是 {detail}")
        return None
    eff_channel = channel or (task_channels[0][0] if len(task_channels) == 1 else "")
    hits = [a for a in ctx.alerts if _matches(a, keys, eff_channel)]
    if not hits:
        ctx.note(node["id"], None,
                 f"最近 {WINDOW_SECONDS}s 内没有匹配告警：算法={sorted(keys)} 通道={eff_channel or '不限'}"
                 + (f"（上游任务通道 {task_channels[0][0]}）" if task_channels else ""))
        return None
    # 上游门控：任务元件必须确实产生了告警（保持「任务→算法」的链条语义）
    for pid in input_ids:
        if not _eval_node(pid, ctx, memo, stack):
            ctx.note(node["id"], None, "上游任务元件未命中：该任务在时间窗内没有产生告警")
            return None
    ctx.note(node["id"], hits)
    return hits


def _upstream_task_channels(input_ids: List[str], ctx: EvalCtx) -> List[Tuple[str, str]]:
    """取上游任务元件的分析通道 [(通道id, 通道名)]。"""
    out: List[Tuple[str, str]] = []
    for pid in input_ids:
        parent = ctx.node_by_id.get(pid) or {}
        if parent.get("type") != "task":
            continue
        info = _task_info(ctx.device_tasks, (parent.get("config") or {}).get("task_id"))
        if (info["channel"] or info["channel_name"]) and info["found"]:
            out.append((info["channel"], info["channel_name"] or info["name"]))
    return out


# 逻辑算子：产品化算子键（1:1 对齐设计表）+ 早期键的兼容映射
LOGIC_ALIASES = {"and": "logic_and", "kn": "logic_vote", "atob": "logic_seq",
                 "dwell": "logic_duration", "debounce": "logic_debounce", "schedule": "logic_schedule"}
# 需要额外数据源、运行时暂未接入的算子（画布上仍可配置，评估时按「放行」处理并打印提示）
LOGIC_UNWIRED = ("logic_autoclose", "logic_iou", "logic_cross_cam")


def _logic_key(cfg: dict) -> str:
    raw = str(cfg.get("logic_type") or "logic_and")
    return LOGIC_ALIASES.get(raw, raw)


def _num(cfg: dict, *keys, default: float = 0) -> float:
    """按优先级取数值参数（兼容新旧参数名）。"""
    for k in keys:
        v = cfg.get(k)
        if v is None or v == "":
            continue
        try:
            return float(v)
        except (TypeError, ValueError):
            continue
    return float(default)


# ── 时间窗口（多路组合算子：AND / K-N）─────────────────────────────────
# 只支持两种窗口模式。两种都是「同一窗口只触发一次」，靠窗口标识做去重，
# 与会话/滚动窗口的边界一样，都是从事件流【确定性重放】出来的（无需持久化状态，重启安全）。
WINDOW_TUMBLING = "滚动时间窗 (Tumbling Window)"
WINDOW_SESSION = "会话时间窗 (Session Window)"
DEFAULT_WINDOW_TYPE = WINDOW_TUMBLING


def _window_is_session(cfg: dict) -> bool:
    raw = str(cfg.get("windowType") or "")
    return "会话" in raw or "session" in raw.lower()


def _bucket_key(ts: int, win_ms: int, node_id: str) -> Tuple[int, str]:
    """滚动窗：按 epoch 对齐切桶（t // winSec 的整数倍为桶起点），返回 (桶起点, 去重键)。"""
    start = (ts // win_ms) * win_ms
    return start, f"tumbling:{node_id}:{start}"


def _sessions(tagged: List[Tuple[int, int, object]], win_ms: int) -> List[dict]:
    """会话窗切分：首个事件开窗；窗有效期(=win_ms)内到达的事件都并入本窗、不新开窗；
    超出有效期的下一个事件再开新窗。tagged = [(timestamp, 分支下标, 事件)] 已按时间升序。
    """
    out: List[dict] = []
    cur = None
    for ts, bi, ev in tagged:
        if cur is None or ts > cur["t0"] + win_ms:
            cur = {"t0": ts, "events": [], "branches": set()}
            out.append(cur)
        cur["events"].append(ev)
        cur["branches"].add(bi)
    return out


def _window_eval(cfg: dict, input_ids: List[str], results: List[Optional[list]],
                 node_id: str, need_k: int) -> Tuple[Optional[list], str, str]:
    """按窗口模式求多路组合条件。返回 (命中事件, 窗口去重键, 未命中原因)。

    need_k = 0 表示「所有分支都要命中」(AND)；need_k > 0 表示「至少 K 路」(K/N)。

    窗口消费策略是**固定**的「同一窗口只触发一次」，不再做成配置项：
    去重键只由窗口本身决定（滚动=桶起点 / 会话=开窗时刻），所以同一窗口内无论再到达多少事件，
    签名都不变 → 永远只发一条业务预警。早期那个可切换的 consumePolicy 允许「同窗口对新事件再报」，
    与「窗口内仅触发一次」的定义直接冲突，且正是"频繁报警"的来源，已移除。
    """
    win_s = _num(cfg, "windowSec", "window_seconds", default=15)
    win_ms = max(1, int(win_s * 1000))
    watermark_ms = int(_num(cfg, "watermarkToleranceSec", default=0) * 1000)

    active = [i for i in range(len(input_ids)) if results[i]]
    need = len(input_ids) if need_k <= 0 else int(need_k)
    if not active:
        return None, "", "所有分支都未命中"

    tagged = sorted(((a.timestamp, i, a) for i in active for a in results[i]), key=lambda x: x[0])
    if not tagged:
        return None, "", "所有分支都未命中"

    if _window_is_session(cfg):
        sessions = _sessions(tagged, win_ms)
        complete = [s for s in sessions if len(s["branches"]) >= need]
        if not complete:
            last = sessions[-1]
            return None, "", (f"会话窗未满足：最近一次会话于 {_fmt_ts(last['t0'])} 开窗、有效期 {win_s:g}s，"
                              f"窗口内只到达 {len(last['branches'])}/{need} 路，已关闭")
        s = complete[-1]
        return s["events"], f"session:{node_id}:{s['t0']}", ""

    # 滚动窗：以「最新命中事件」所在桶为当前窗口（按 epoch 对齐，桶宽 = windowSec）
    latest_ts = tagged[-1][0]
    bstart, key = _bucket_key(latest_ts, win_ms, node_id)
    lo, hi = bstart - watermark_ms, bstart + win_ms
    in_bucket = {i: [a for a in results[i] if lo <= a.timestamp < hi] for i in active}
    got = [i for i in active if in_bucket.get(i)]
    if len(got) < need:
        missing = [input_ids[i] for i in active if i not in got]
        return None, "", (f"当前滚动窗 [{_fmt_ts(bstart)} ~ {_fmt_ts(hi)}) 内只命中 {len(got)}/{need} 路，"
                          f"缺 {missing or '—'}")
    return [a for i in got for a in in_bucket[i]], key, ""


def _fmt_ts(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000).strftime("%H:%M:%S")


# 逻辑算子：统一签名 (cfg, 上游节点id, 上游命中列表, 本节点id) → (命中事件, 窗口签名, 未命中原因)
LogicOp = Callable[[dict, List[str], List[Optional[list]], str], Tuple[Optional[list], str, str]]


def _pick(seq, i):
    """安全取第 i 项（不足时返回 None）。"""
    return seq[i] if len(seq) > i else None


def _in_inhibit_window(t_a: int, t_b: int, pre_s: float, post_s: float) -> bool:
    """B 是否落在 A 的抑制窗口内（A 之前 pre_s 秒 ~ A 之后 post_s 秒）。"""
    delta = t_b - t_a
    return -pre_s * 1000 <= delta <= post_s * 1000


def _op_and(cfg, input_ids, hits, nid):
    """多路并联与校验：所选时间窗（滚动/会话）内全部分支都要命中。"""
    missed = [input_ids[i] for i, h in enumerate(hits) if not h]
    if missed:
        return None, "", f"未命中分支 {len(missed)}/{len(input_ids)} 路：{missed}（AND 需要全部命中）"
    return _window_eval(cfg, input_ids, hits, nid, need_k=0)


def _op_vote(cfg, input_ids, hits, nid):
    """K-of-N 投票门：同一时间窗内至少 K 路命中。"""
    k = int(_num(cfg, "minRequiredBranches", "k", default=2))
    if not any(hits):
        return None, "", f"所有分支都未命中（需要 {k} 路命中）"
    return _window_eval(cfg, input_ids, hits, nid, need_k=k)


def _op_not(cfg, input_ids, hits, nid):
    """互斥抑制 A AND NOT B：A 命中，且其前后窗口内无抑制流 B。"""
    pre, post = _num(cfg, "preLookbackSec", default=10), _num(cfg, "postWaitSec", default=5)
    a_hits, b_hits = _pick(hits, 0), _pick(hits, 1)
    if not a_hits:
        return None, "", f"主流 A 未命中（{_pick(input_ids, 0) or '—'}）；B 命中={'是' if b_hits else '否'}"
    if not b_hits:
        return a_hits, "", ""
    kept = [a for a in a_hits
            if not any(_in_inhibit_window(a.timestamp, b.timestamp, pre, post) for b in b_hits)]
    return kept or None, "", "" if kept else f"主流 A 全部被抑制流 B 拦截（-{pre:g}s ~ +{post:g}s）"


def _op_seq(cfg, input_ids, hits, nid):
    """时序跟随 A→B：A 之后 [minWaitSec, maxWindowSec] 内出现 B。"""
    lo = _num(cfg, "minWaitSec", default=0)
    hi = _num(cfg, "maxWindowSec", "window_seconds", default=300)
    a_hits, b_hits = _pick(hits, 0), _pick(hits, 1)
    if not (a_hits and b_hits):
        return None, "", f"前置 A 命中={'是' if a_hits else '否'}、后置 B 命中={'是' if b_hits else '否'}（两者都要有）"
    out = [b for b in b_hits if any(lo * 1000 <= b.timestamp - a.timestamp <= hi * 1000 for a in a_hits)]
    return out or None, "", "" if out else f"A、B 都命中，但时间差不满足 [{lo:g}s, {hi:g}s]"


def _op_duration(cfg, input_ids, hits, nid):
    """状态持续驻留：跨度 ≥ holdDurationSec，且相邻命中间隔 ≤ maxHeartbeatGapSec。"""
    hold = _num(cfg, "holdDurationSec", "seconds", default=60)
    gap = _num(cfg, "maxHeartbeatGapSec", default=3)
    target = next((h for h in hits if h), None)
    if not target:
        return None, "", "上游未命中"
    ts = sorted(a.timestamp for a in target)
    span = (ts[-1] - ts[0]) / 1000.0
    gaps_ok = len(ts) > 1 and all(ts[i + 1] - ts[i] <= gap * 1000 for i in range(len(ts) - 1))
    if span >= hold and gaps_ok:
        return target, "", ""
    why = f"持续时长不足：跨度 {span:.1f}s（要求 ≥{hold:g}s）"
    if span >= hold and not gaps_ok:
        why += "，且存在超容忍闪断"
    if len(ts) < 2:
        why += f"，命中 {len(ts)} 次不足以判定持续"
    return None, "", why


def _op_debounce(cfg, input_ids, hits, nid):
    """频次聚合：窗口内累计触发 ≥ minHitCount 才放行（抑制刷屏）。"""
    win = _num(cfg, "windowSec", "seconds", default=20)
    need = int(_num(cfg, "minHitCount", default=3))
    target = next((h for h in hits if h), None)
    if not target:
        return None, "", "上游未命中"
    latest = max(a.timestamp for a in target)
    count = sum(1 for a in target if latest - a.timestamp <= win * 1000)
    if count >= need:
        return target, "", ""
    return None, "", f"{win:g}s 内累计触发 {count} 次 < {need} 次"


def _op_schedule(cfg, input_ids, hits, nid):
    """排班门控：仅在 activeTimeRange 内放行。"""
    target = next((h for h in hits if h), None)
    if not target:
        return None, "", "上游未命中"
    if _in_active_range(cfg):
        return target, "", ""
    return None, "", f"当前不在生效时段 {cfg.get('activeTimeRange') or '（未配置）'}"


def _op_unwired(cfg, input_ids, hits, nid):
    """运行时暂未接入的算子（消警需告警生命周期 / IoU 需 BBox / 跨镜需防区拓扑）：按放行处理。"""
    target = next((h for h in hits if h), None)
    if target:
        print(f"[Orchestration] 算子 {_logic_key(cfg)} 运行时暂未接入（需额外数据源），本节点按放行处理")
    return target, "", "" if target else "上游未命中"


LOGIC_OPERATORS: Dict[str, LogicOp] = {
    "logic_and": _op_and,
    "logic_vote": _op_vote,
    "logic_not": _op_not,
    "logic_seq": _op_seq,
    "logic_duration": _op_duration,
    "logic_debounce": _op_debounce,
    "logic_schedule": _op_schedule,
    **{key: _op_unwired for key in LOGIC_UNWIRED},
}


def _eval_logic(node: dict, cfg: dict, input_ids: List[str], results: dict, ctx: EvalCtx) -> Optional[list]:
    """逻辑算子统一入口：查注册表 → 求值 → 记录诊断（新增算子只需加 _op_xxx 并注册）。"""
    key = _logic_key(cfg)
    nid = node["id"]
    op = LOGIC_OPERATORS.get(key)
    if op is None:
        ctx.note(nid, None, f"未知逻辑算子 {key}")
        return None
    events, win_key, reason = op(cfg, input_ids, [results[c] for c in input_ids], nid)
    out = HitList(events, win_key) if events else None
    ctx.note(nid, out, reason)
    return out


# ── 输出与去重 ──────────────────────────────────────────────────────────
async def _recent_alerts(db, device_name: Optional[str] = None,
                         window_seconds: int = WINDOW_SECONDS, limit: int = 5000) -> List[AlertORM]:
    """取设备在【时间窗】内的告警（按 timestamp 过滤，而非只取最近 N 条）。

    修复点：早期实现是「按 timestamp desc 取 200 条」，在单通道高频上报时
    200 条可能只覆盖几十秒，导致跨通道 AND 永远等不到另一条分支。
    limit 仅作安全上限。
    """
    since = _now_ms() - int(window_seconds) * 1000
    q = (select(AlertORM)
         .where(AlertORM.timestamp >= since)
         .order_by(desc(AlertORM.timestamp))
         .limit(limit))
    if device_name:
        q = q.where(AlertORM.deviceName == device_name)
    return list((await db.execute(q)).scalars().all())


async def _llm_recheck(alert: AlertORM, prompt: Optional[str]) -> bool:
    """多模态复核：用大模型看告警图，返回是否「确认告警」（放行）。异常/无配置时放行。"""
    cfg = dict(database.llm_config or {})
    if not cfg.get("api_key"):
        return True
    image_url = alert.imageUrl or alert.imageUrlCrop
    text = (prompt or "").strip() or "你是安防复核助手。判断这张监控告警图片是否为真实异常事件，仅回答「是」或「否」。"
    image_part = None
    if image_url:
        path = image_url.lstrip("/")
        if os.path.isfile(path):
            try:
                with open(path, "rb") as f:
                    b64 = base64.b64encode(f.read()).decode()
                ext = os.path.splitext(path)[1].lstrip(".").lower() or "jpeg"
                image_part = {"type": "image_url",
                              "image_url": {"url": f"data:image/{ext};base64,{b64}"}}
            except OSError:
                image_part = None
    content = [{"type": "text", "text": text}]
    if image_part:
        content.append(image_part)
    messages = [{"role": "user", "content": content}]
    try:
        reply = await llm_client.openai_completion(cfg, messages, timeout=30.0)
        return "否" not in reply and "正常" not in reply
    except Exception as e:  # noqa: BLE001
        print(f"[Orchestration] 智能复核调用失败，放行：{e}")
        return True


def _output_scope(cfg: dict, hit) -> Tuple[str, Optional[str]]:
    """解析输出元件的【冷却静默锁作用粒度】→ (粒度说明, 通道过滤值)。

    - 全局规则冷却静默            → ("全局", None)
    - 按 [规则ID + 通道设备ID]     → ("按通道", 通道名)

    兼容历史数据：早期元件默认值是「按 [规则ID + 防区Tag] 独立冷却静默」，但系统没有防区拓扑，
    当时实际就是按通道冷却 —— 这里保持同样的等价行为（前端打开编排时会把该旧值改写成按通道）。
    """
    scope = str(cfg.get("cooldownScope") or "")
    if "防区" in scope:
        return "按通道（原防区粒度等价）", (hit.channelname or hit.channelid or "")
    if "通道" in scope:
        return "按通道", (hit.channelname or hit.channelid or "")
    return "全局", None


async def _last_emit(orch_id: str, output_id: str, channel: Optional[str]):
    """取该（编排, 输出[, 通道]）最近一次业务预警。"""
    async with AsyncSessionLocal() as db:
        q = (select(OrchestrationAlarmORM)
             .where(OrchestrationAlarmORM.orchestration_id == orch_id,
                    OrchestrationAlarmORM.output_id == output_id)
             .order_by(desc(OrchestrationAlarmORM.created_at)).limit(1))
        if channel is not None:
            q = q.where(OrchestrationAlarmORM.channelname == channel)
        return (await db.execute(q)).scalars().first()


async def cooldown_state(orch, node, hit) -> dict:
    """计算输出节点的冷却状态：{sec, scope, remaining, last_fire_at}。remaining=0 表示可以发。"""
    cfg = node.get("config") or {}
    sec = int(_num(cfg, "cooldownSec", "debounce_seconds", default=DEFAULT_DEBOUNCE_SECONDS))
    scope_name, channel = _output_scope(cfg, hit)
    state = {"sec": sec, "scope": scope_name, "remaining": 0, "last_fire_at": 0}
    if sec <= 0:
        return state
    output_id = str(cfg.get("output_id") or node.get("id"))
    last = await _last_emit(orch.id, output_id, channel)
    if not last:
        return state
    state["last_fire_at"] = int(last.created_at or 0)
    elapsed = (_now_ms() - int(last.created_at or 0)) / 1000.0
    state["remaining"] = max(0, int(math.ceil(sec - elapsed)))
    return state


async def _emit_output(orch, node, hit: AlertORM, chain_summary: str, dedup_key: str = "") -> bool:
    """输出节点触发：生成业务预警。

    两层去重：
    1) 窗口签名（dedup_key：滚动桶 / 会话开窗时刻）→ **同一时间窗口只发一条**（永久生效）；
    2) 冷却静默期（cooldownSec + cooldownScope）→ 跨窗口的发送频率上限。
    这取代了早期「按告警ID去重」的做法 —— 那种做法在告警高频上报时完全挡不住刷屏，
    因为每条新告警的签名都不同。
    """
    cfg = node.get("config") or {}
    output_id = str(cfg.get("output_id") or node.get("id"))
    output_name = str(cfg.get("ruleName") or cfg.get("name") or cfg.get("output_name") or node.get("id"))
    signature = dedup_key or hit.id
    scope_name, channel = _output_scope(cfg, hit)

    # 冷却静默判断
    st = await cooldown_state(orch, node, hit)
    if st["remaining"] > 0:
        return False

    async with AsyncSessionLocal() as db:
        # 二次保险：完全相同的触发事件（同一条告警）不重复落库
        dup = (await db.execute(
            select(OrchestrationAlarmORM).where(
                OrchestrationAlarmORM.orchestration_id == orch.id,
                OrchestrationAlarmORM.output_id == output_id,
                OrchestrationAlarmORM.signature == signature,
            ).limit(1)
        )).scalars().first()
        if dup:
            return False
        images = [u for u in (hit.imageUrl, hit.imageUrlCrop) if u]
        summary = f"{chain_summary}｜冷却锁[{scope_name} {st['sec']}s]"
        if dedup_key:
            summary = f"{summary}｜窗口签名 {dedup_key.split(':', 1)[0]}"
        db.add(OrchestrationAlarmORM(
            id=f"oa-{uuid.uuid4()}",
            orchestration_id=orch.id,
            orchestration_name=orch.name,
            output_id=output_id,
            output_name=output_name,
            device_name=hit.deviceName or "",
            channelname=hit.channelname or "",
            alert_types=json.dumps([hit.alertType] if hit.alertType else [], ensure_ascii=False),
            summary=summary,
            images=json.dumps(images, ensure_ascii=False),
            signature=signature,
            created_at=_now_ms(),
        ))
        await db.commit()
    return True


async def _load_device_context(orch) -> Tuple[list, dict]:
    """取编排绑定设备的快照：返回 (device_tasks, {通道id: 通道名})。"""
    device_tasks: list = []
    ch_name_by_id: dict = {}
    async with AsyncSessionLocal() as db:
        if orch.device_id:
            devs = [(await db.execute(
                select(DeviceORM).where(DeviceORM.device_id == orch.device_id))).scalars().first()]
            devs = [d for d in devs if d]
        else:
            devs = list((await db.execute(select(DeviceORM))).scalars().all())
    for dev in devs:
        device_tasks += _json(dev.device_tasks)
        for c in _json(dev.channels):
            if isinstance(c, dict) and c.get("device_id") is not None:
                ch_name_by_id[str(c.get("device_id"))] = str(c.get("device_name") or "")
    return device_tasks, ch_name_by_id


def _node_label(n: dict) -> str:
    """节点的人读标签（诊断面板与连线校验共用）。"""
    cfg = n.get("config") or {}
    ntype = n.get("type")
    if ntype == "task":
        return f"任务元件 · {cfg.get('task_name') or cfg.get('task_id') or '未选任务'}"
    if ntype == "algo":
        key = cfg.get("event_id") if cfg.get("kind") == "agent" else cfg.get("event_type")
        return f"算法元件 · {cfg.get('event_name') or cfg.get('event_tag') or key or '未绑定'}"
    if ntype == "logic":
        return f"逻辑元件 · {_logic_key(cfg)}"
    if ntype == "llm":
        return "智能复核 · VLM"
    if ntype == "output":
        return f"输出元件 · {cfg.get('ruleName') or cfg.get('name') or ''}"
    return str(ntype)


async def _eval_outputs(orch, alerts: List[AlertORM], *, emit: bool,
                        diag: Optional[dict] = None) -> List[dict]:
    """对所有输出节点求值，返回每个输出的报告（实跑落库与「校验」共用这一份实现）。

    emit=True ：命中且不在冷却静默期 → 先做大模型复核（存在复核节点时），再落一条业务预警；
    emit=False：只求值、不落库（供「校验」回显）。
    """
    nodes = _json(orch.nodes)
    edges = _json(orch.edges)
    if not isinstance(nodes, list) or not nodes:
        return []
    node_by_id, _, parents_of = build_graph(nodes, edges)
    device_tasks, ch_name_by_id = await _load_device_context(orch)
    ctx = EvalCtx(node_by_id=node_by_id, parents_of=parents_of, alerts=alerts,
                  device_tasks=device_tasks, ch_name_by_id=ch_name_by_id, diag=diag)
    # 存在复核节点时取第一个的提示词（其余参数暂未接入）
    llm_prompts = [((n.get("config") or {}).get("prompt")) for n in nodes if n.get("type") == "llm"]

    reports: List[dict] = []
    for out in (n for n in nodes if n.get("type") == "output"):
        cfg = out.get("config") or {}
        hit_list = _eval_node(out["id"], ctx, {})
        report = {
            "node_id": out["id"],
            "name": cfg.get("ruleName") or cfg.get("name") or "",
            "output_id": cfg.get("output_id") or "",
            "fired": bool(hit_list),
            "cooldown": None,
            "emitted": False,
        }
        if hit_list:
            hit = max(hit_list, key=lambda a: a.timestamp)
            state = await cooldown_state(orch, out, hit)      # 先判冷却，避免冷却期白烧一次复核
            report["cooldown"] = state
            if state["remaining"] > 0:
                report["fired"] = False
                report["cooldown_silenced"] = True
                if diag is not None:
                    diag.setdefault(out["id"], {})["reason"] = (
                        f"已命中，但处于冷却静默期（{state['scope']} {state['sec']}s），"
                        f"剩余 {state['remaining']}s 不再重复报警")
            elif emit:
                if llm_prompts and not await _llm_recheck(hit, llm_prompts[0]):
                    report["fired"] = False
                    report["llm_rejected"] = True
                else:
                    summary = (f"命中算法：{hit.alertType or '未知'}；通道：{hit.channelname or '—'}；"
                               f"时间：{datetime.fromtimestamp(hit.timestamp / 1000).strftime('%m-%d %H:%M:%S')}")
                    report["emitted"] = await _emit_output(
                        orch, out, hit, summary, getattr(hit_list, "win_key", "") or "")
        reports.append(report)
    return reports


async def evaluate_orchestration(orch, alerts: List[AlertORM]) -> int:
    """对一条编排求值并落库，返回新产生的业务预警条数。"""
    reports = await _eval_outputs(orch, alerts, emit=True)
    return sum(1 for r in reports if r.get("emitted"))


async def on_new_alert(alert: AlertORM) -> int:
    """告警入库后调用：让所有启用且匹配设备的编排任务评估这一条。返回新产生的业务预警数。

    匹配口径：编排绑定的是设备【业务ID】(device_id)，告警里只有【设备名】(deviceName)，
    故先按名称解析出业务ID；解析不到时只跑「不限设备」的编排。
    """
    total = 0
    async with AsyncSessionLocal() as db:
        bound_device_id = ""
        if alert.deviceName:
            dev = (await db.execute(
                select(DeviceORM).where(DeviceORM.name == alert.deviceName))).scalars().first()
            bound_device_id = (dev.device_id if dev else "") or ""
        q = select(OrchestrationTaskORM).where(OrchestrationTaskORM.status == "enabled")
        q = q.where(OrchestrationTaskORM.device_id.in_(["", bound_device_id] if bound_device_id else [""]))
        orchs = list((await db.execute(q)).scalars().all())
        # 取一次最近告警即可复用给所有编排（都是同一设备的时间窗）
        alerts = await _recent_alerts(db, alert.deviceName)
    for orch in orchs:
        try:
            total += await evaluate_orchestration(orch, alerts)
        except Exception as e:  # noqa: BLE001
            print(f"[Orchestration] 编排「{orch.name}」评估失败：{e}")
    return total


async def run_all_enabled() -> Dict[str, int]:
    """手动/定时全量评估所有启用编排（用于补算与测试）。返回 {编排名: 新增条数}。"""
    out: Dict[str, int] = {}
    async with AsyncSessionLocal() as db:
        orchs = list((await db.execute(
            select(OrchestrationTaskORM).where(OrchestrationTaskORM.status == "enabled"))).scalars().all())
    for orch in orchs:
        async with AsyncSessionLocal() as db:
            alerts = await _recent_alerts(db, None)
        out[orch.name] = await evaluate_orchestration(orch, alerts)
    return out


async def diagnose_orchestration(orch, hours: int = 24) -> dict:
    """「校验」：按编排图逐节点求值并回显命中情况与未命中原因。

    同时给出【该设备时间窗内实际出现过的告警类型】——多数"没触发"都是
    算法元件绑定的算法与设备实际上报的 alertType 对不上（例如配了算法仓 LEAVE_POST，
    但设备上报的是智能体 event_id）。
    """
    from sqlalchemy import func as _func  # 局部导入避免顶部噪声

    nodes = _json(orch.nodes)
    device_tasks, ch_name_by_id = await _load_device_context(orch)

    # 设备名（快照里按业务ID反查）+ 时间窗内该设备实际出现的告警类型统计
    device_name = ""
    async with AsyncSessionLocal() as db:
        if orch.device_id:
            dev = (await db.execute(
                select(DeviceORM).where(DeviceORM.device_id == orch.device_id))).scalars().first()
            device_name = (dev.name if dev else "") or ""
        since = _now_ms() - hours * 3600 * 1000
        q = (select(AlertORM.alertType, _func.count())
             .where(AlertORM.timestamp >= since)
             .group_by(AlertORM.alertType).order_by(desc(_func.count())))
        if device_name:
            q = q.where(AlertORM.deviceName == device_name)
        type_rows = (await db.execute(q)).all()
        alerts = await _recent_alerts(db, device_name or None)

    # 与实跑共用同一份求值实现（emit=False：只求值不落库）
    diag: dict = {}
    output_results = await _eval_outputs(orch, alerts, emit=False, diag=diag)
    node_by_id, _, parents_of = build_graph(nodes, _json(orch.edges))

    node_reports = []
    for n in nodes:
        d = diag.get(n["id"]) or {}
        cfg = n.get("config") or {}
        extra = {}
        if n["type"] == "task":
            info = _task_info(device_tasks, cfg.get("task_id"))
            extra = {"found": info["found"], "keys": sorted(info["keys"]),
                     "channel": info["channel"], "channel_name": info["channel_name"] or ch_name_by_id.get(info["channel"], "")}
        elif n["type"] == "algo":
            extra = {"keys": sorted(_match_event_keys_for_algo(cfg)),
                     "channel": str(cfg.get("channelid") or ""),
                     "channel_name": ch_name_by_id.get(str(cfg.get("channelid") or ""), "")}
        node_reports.append({
            "node_id": n["id"], "type": n["type"], "label": _node_label(n),
            "matched": d.get("matched", 0), "reason": d.get("reason", ""),
            "parents": parents_of.get(n["id"], []), "detail": extra,
        })

    # ── 静态连线校验（不依赖数据，直接指出画布结构问题）──
    warnings: List[str] = []
    for n in nodes:
        ins = parents_of.get(n["id"], [])
        cfg = n.get("config") or {}
        lb = _node_label(n)
        if n["type"] == "logic":
            key = _logic_key(cfg)
            if not ins:
                warnings.append(f"「{lb}」没有任何上游输入，不会参与判断。")
            elif key in ("logic_and", "logic_vote") and len(ins) < 2:
                warnings.append(
                    f"「{lb}」只有 {len(ins)} 个上游输入：{key} 是「多路」校验算子，"
                    "单输入时会恒成立（等于没校验）。请把其余分支也连到本元件。")
        if n["type"] == "output" and len(ins) > 1:
            others = "、".join(_node_label(node_by_id[p]) for p in ins[1:] if p in node_by_id)
            warnings.append(
                f"「{lb}」接了 {len(ins)} 个上游：输出元件只取「第一个命中」的上游（{_node_label(node_by_id[ins[0]])}），"
                f"其余分支（{others}）不会参与判断。请先把所有分支汇入逻辑元件，再连到输出元件。")
        if n["type"] == "algo" and not ins and not _match_event_keys_for_algo(cfg):
            warnings.append(f"「{lb}」未绑定算法。")

    return {
        "orchestration_id": orch.id,
        "orchestration_name": orch.name,
        "status": orch.status,
        "device_id": orch.device_id,
        "device_name": device_name,
        "window_seconds": WINDOW_SECONDS,
        "hours": hours,
        "alert_types_in_window": [{"alertType": t or "(空)", "count": c} for t, c in type_rows],
        "alerts_scanned": len(alerts),
        "nodes": node_reports,
        "outputs": output_results,
        "warnings": warnings,
        "fired": any(o["fired"] for o in output_results),
    }


async def alert_type_stats(hours: int = 24, device_name: str = "") -> List[dict]:
    """该时间窗内各 alertType 的告警条数（前端元件库标注「近 N 小时是否有告警」用）。"""
    from sqlalchemy import func as _func
    since = _now_ms() - hours * 3600 * 1000
    async with AsyncSessionLocal() as db:
        q = (select(AlertORM.alertType, _func.count())
             .where(AlertORM.timestamp >= since)
             .group_by(AlertORM.alertType).order_by(desc(_func.count())))
        if device_name:
            q = q.where(AlertORM.deviceName == device_name)
        rows = (await db.execute(q)).all()
    return [{"alertType": t or "(空)", "count": c} for t, c in rows]
