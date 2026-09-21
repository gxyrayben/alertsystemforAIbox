import httpx
import hashlib
import json
from typing import Optional, Tuple, List
from models.orm import DeviceORM
from sqlalchemy.ext.asyncio import AsyncSession
from services import algorithm_catalog, task_builders

TASK_LIST_BODY = {"offset": 0, "size": 100, "condition": {}}
# monitor 列表接口（MegCube 协议路径未在文档核实，best-effort；失败自动降级为空，不影响主流程）
MONITOR_LIST_PATH = "/intelli_manager/monitor_list"
MONITOR_LIST_BODY = {"offset": 0, "size": 100}


def apply_device_snapshot(device_obj: DeviceORM, channels, device_tasks, algorithms, status, session_id, algorithms_ability, agents=None ) -> None:
    """把 fetch_device_data 的结果写回设备 ORM（channels/tasks/algorithms/agents 转 JSON 字符串）。
    消除 devices 路由中 create/fetch/update 三处重复的赋值块。"""
    device_obj.status = status
    device_obj.session_id = session_id
    device_obj.channels = json.dumps(channels)
    device_obj.device_tasks = json.dumps(device_tasks)
    device_obj.available_algorithms = json.dumps(algorithms)
    device_obj.algorithms_ability = json.dumps(algorithms_ability)
    device_obj.agents = json.dumps(agents or [], ensure_ascii=False)


async def challenge_login(
    client: httpx.AsyncClient, base_url: str, username: str, password: str
) -> Tuple[bool, str, str]:
    """SHA256 挑战/应答登录。

    返回 (成功?, session_id, 状态)，状态取值：在线 / 密码错误 / 异常 / 离线。
    统一了原先 do_login 与 fetch_device_data 内部的重复实现。
    """
    if not username or not password:
        return False, "", "密码错误"

    try:
        challenge_res = await client.get(
            f"{base_url}/auth/login/challenge", params={"username": username}
        )
        if challenge_res.status_code != 200:
            return False, "", "离线"

        c_data = challenge_res.json()
        if c_data.get("code") != 0:
            return False, "", "异常"

        data = c_data.get("data", {})
        session_id = data.get("session_id", "")
        pwd_str = f"{password}{data.get('salt', '')}{data.get('challenge', '')}"
        hashed_pwd = hashlib.sha256(pwd_str.encode("utf-8")).hexdigest()

        login_res = await client.post(
            f"{base_url}/auth/login",
            json={
                "session_id": session_id,
                "username": username,
                "password": hashed_pwd,
                "aiotap_flag": 1,
            },
        )
        if login_res.status_code == 200 and login_res.json().get("code") == 0:
            client.cookies.set("sessionID", session_id)
            return True, session_id, "在线"
        return False, "", "密码错误"
    except Exception as e:
        print(f"Error during login process for {base_url}: {e}")
        return False, "", "离线"


def _parse_channels(items: list) -> List[dict]:
    return [
        {
            "device_id": str(item.get("device_id")),
            "device_name": item.get("device_name"),
            "proto": item.get("proto"),
            "rtsp": item.get("rtsp_param", {}).get("url"),
            "gbid": item.get("gb28181_param", {}).get("DeviceID"),
        }
        for item in items
    ]

def algorithm_rows_from_ability(algorithms_ability) -> List[dict]:
    """设备快照 algorithms_ability([{name, cards[]}]) → 算法目录行（设备离线时的兜底）。

    快照只有算法仓名与事件类型，缺 alg_version/目标类型，故 version 退回 V2.0.0、targetTypes 留空；
    中文事件名仍走 algorithm_catalog 映射，保证与实时目录显示一致。
    """
    rows: List[dict] = []
    for pocket in algorithms_ability or []:
        if not isinstance(pocket, dict):
            continue
        cabin = pocket.get("name") or ""
        for event_type in pocket.get("cards") or []:
            if not event_type:
                continue
            rows.append({
                "algoCabinName": cabin,
                "version": "V2.0.0",
                "eventType": event_type,
                "eventName": algorithm_catalog.event_name(event_type),
                "targetTypes": [],
                "description": "",
            })
    return rows


def _parse_algorithms(items: list) -> List[dict]:
    results = []
    for item in items:
        pockets = item.get("pocket") or item.get("pockets", [])
        for pocket in pockets:
            name = pocket.get("name", "")
            # 提取 cards 中每个对象的 type
            cards = [
                card.get("type") 
                for card in pocket.get("cards", []) 
                if "type" in card
            ]
            
            results.append({
                "name": name,
                "cards": cards
            })

        
    return results


def _parse_agents(items: list) -> List[dict]:
    """把设备 agent_list 原始项归一化为前端/快照统一形状（与 agent_tools.list_agents 对齐）。"""
    return [
        {
            "agent_id": item.get("agent_id"),
            "agent_name": item.get("agent_name"),
            "event_id": item.get("event_id"),
            "event_tag": item.get("event_tag"),
            "alarm_condition": item.get("alarm_condition"),
            "alarm_type": item.get("alarm_type"),
            "prompt": item.get("prompt", ""),
        }
        for item in items
    ]


def categorize_task(task: dict) -> str:
    """把设备原始任务归类为『小模型任务 / 大模型任务 / 小+大任务』。

    判定（best-effort，基于 task_list 可见字段）：
    - task_type == agent_real_task            → 大模型任务（纯大模型）
    - task_type == single_point_task 且带智能体二次分析 → 小+大任务
    - task_type == single_point_task 无智能体 → 小模型任务
    - 其它/未知                                → 其它任务
    """
    task_type = (task.get("task_type") or "").strip()
    agent_list = task.get("agent_list") or []
    if task_type == "agent_real_task":
        return "agent_task"
    if task_type == "single_point_task":
        # single_point_task 挂载了智能体（monitor 的 agentLLMParam 会体现在 agent_list）→ 小+大
        return "small_and_agent_task" if agent_list else "small_task"
    return "unknown_task"


def _task_status(task: dict) -> str:
    """任务状态：基于设备返回的 enable 使能标志（协议文档明确定义），映射为 启用/停用。"""
    return "启用" if task.get("enable") else "停用"


def _task_state_label(task: dict) -> str:
    """设备 task_state → 任务状态展示值：0=未启用 / 1=正常 / 其它(含缺失)=异常。

    列表页三态『正常/异常/未启用』的唯一判据，纯大模型任务与算法仓任务共用，避免两处映射漂移。
    """
    raw = (task or {}).get("task_state")
    if raw == 0:
        return "未启用"
    if raw == 1:
        return "正常"
    return "异常"


def _algorithms_label(packages: list) -> str:
    """算法仓任务的『关联智能体/算法』中文展示串。

    每条规则取中文事件名（algorithm_catalog 查不到时退回英文 eventType）；『小+大协同』规则
    追加 /二次大模型智能体名；多条以『、』连接并去重保序。
    """
    labels: List[str] = []
    for pkg in packages or []:
        minor = pkg.get("minor_type") or ""
        name = algorithm_catalog.event_name(minor, pkg.get("major_type") or "") or minor
        agent_tag = pkg.get("agent_event_tag")
        label = f"{name}/{agent_tag}" if agent_tag else name
        if label and label not in labels:
            labels.append(label)
    return "、".join(labels)


def _index_monitors(monitor_list: list) -> tuple[list, str, set]:
    """把 monitor 列表按其归属的 task_id（字符串）建索引，供任务摘要富化小模型算法信息。

    每项值保留原始 monitor（供 task_builders.monitor_to_panel_config 做逆映射）并预取
    展示所需的 event_type / algo_cabin_name（best-effort，结构缺失时跳过该项，不抛异常）。
    返回 (逐 monitor 摘要, 任务级类型, 算法 id 集合)；任务级类型按【全部规则聚合】：
    任一规则挂了 agentLLMParam 即整个任务为『小+大协同』，否则为纯小模型。
    """
    results = []
    algorithms: set = set()
    task_type = "small_task"
    for mon in monitor_list or []:
        # 逐 monitor 重置：算法包清单属于单个算法仓，放在循环外会跨仓累积（同任务多仓互相污染）
        algorithms_packages = []
        common = mon.get("common_param") or {}
        monitor_id = common.get("monitor_id")
        channel_device_id = common.get("channel_id")
        if monitor_id is None:
            continue
        warehouse = common.get("warehouse_v20_param") or {}
        algoCabinName = (warehouse.get("labels") or {}).get("algoCabinName")
        rules = warehouse.get("rulesParams") or []
        for r in rules:
            agentLLMParam = ((r.get("extendParams") or {}).get("aiotapCustom") or {}).get("agentLLMParam") or {}
            event_type = r.get("eventType")
            if agentLLMParam:
                # 聚合语义：只要有一条规则挂了二次大模型，整个任务即为协同任务（不被后续纯小模型规则覆盖）
                task_type = "small_and_agent_task"
                algorithms.add(f"SM-{event_type}-AG-{agentLLMParam.get('event_tag')}")
            else:
                algorithms.add(f"SM-{event_type}")
            algorithms_packages.append({
                "major_type": algoCabinName,
                "minor_type": event_type,
                "agent_alarm_type": agentLLMParam.get("alarm_type"),
                "agent_event_id": agentLLMParam.get("event_id"),
                "agent_event_tag": agentLLMParam.get("event_tag"),
                "filter_enable": agentLLMParam.get("filter_enable"),
                "filter_keywords": agentLLMParam.get("filter_keywords"),
                "agent_prompt": agentLLMParam.get("prompt"),
            })

        results.append({
            "monitor_id": monitor_id,
            "task_type": task_type,
            "camera_device_id": channel_device_id,
            "algorithms_packages": algorithms_packages,
        })

    return results, task_type, algorithms


def _summarize_tasks_algorithm(task_list: list, monitor_by_task: Optional[dict] = None) -> Tuple[List[dict], set]:
    """把设备原始任务列表压成前端展示用摘要，并收集全部算法 id。

    注意：task_list 中 agent_list 的智能体项使用 event_id/event_tag（非 agent_id）；
    小模型任务(single_point_task)的 agent_list 通常为空，其算法名(eventType)在 monitor 里，
    故通过 monitor_by_task（按 task_id 建索引）补齐『关联智能体/算法』列与查看回填用 detail。
    每行同时输出列表页所需的 task_enable（是否启用开关的初值）与 algorithms_label（中文展示串）。
    """
    monitor_by_task = monitor_by_task or []
    all_algorithms: set = set()
    task_list_all = []
    for task in task_list:
        task_agents = []
        # 逐任务重置：算法集合放在循环外会让每个任务的『关联算法』列累积到前面所有任务的算法
        task_algorithms: set = set()
        agent_names: List[str] = []
        task_type = task.get("task_type", "")
        task_id = task.get("task_id", "")
        task_name = task.get("task_name", "")
        task_status = _task_state_label(task)
        device_lists = task.get("device_list", [])
        first_dev = device_lists[0] if device_lists else {}
        device_name = first_dev.get("device_name", "")
        device_id = first_dev.get("device_id", "")

        if task_type == "agent_real_task":
            agent_list = task.get("agent_list", [])
            for a in agent_list:
                event_tag = a.get("event_tag")
                task_algorithms.add(f"AG-{event_tag}")
                if event_tag and event_tag not in agent_names:
                    agent_names.append(event_tag)
                task_agents.append({
                    "agent_id": a.get("event_id", ""),
                    "agent_name": event_tag,
                })
            all_algorithms.update(task_algorithms)

            task_list_all.append({
                "task_type": task_type,
                "task_id": task_id,
                "task_name": task_name,
                "task_status": task_status,
                # 是否启用开关的初值（enable 是设备侧使能标志，与运行态 task_state 相互独立）
                "task_enable": bool(task.get("enable")),
                "camera_device_name": device_name,
                "camera_device_id": device_id,
                "agents_tasks": task_agents,
                "algorithms": list(task_algorithms),
                "algorithms_label": "、".join(agent_names),
                "monitor_tasks": [],
                # 查看回填：纯大模型任务无 monitor，从 task.agent_list 还原多智能体 + 每智能体 ROI
                "detail": task_builders.monitor_to_panel_config(task, None),
            })

    for task in monitor_by_task:
        all_algorithms.update(task.get("algorithms", []))

    task_list_all.extend(monitor_by_task)

    return task_list_all, all_algorithms


def _summarize_tasks(task_list: list, monitor_by_task: list) -> Tuple[List[dict], set]:
    """把设备原始任务列表压成前端展示用摘要，并收集全部算法 id。

    注意：task_list 中 agent_list 的智能体项使用 event_id/event_tag（非 agent_id）；
    小模型任务(single_point_task)的 agent_list 通常为空，其算法名(eventType)在 monitor 里，
    故通过 monitor_by_task（按 task_id 建索引）补齐『关联智能体/算法』列与查看回填用 detail。
    """
    monitor_by_task = monitor_by_task or {}
    summaries = []
    algorithms = set()
    for task in task_list:
        task_status = "error"
        task_id = task.get("task_id", {}) or {}
        task_name = task.get("task_name", {}) or {}
        if(task.get("task_status") == 1):
            task_status = "running"
        agent_list = task.get("agent_list", []) or []
        agent_ids = [a.get("event_id", "") for a in agent_list if a.get("event_id")]
        agent_tags = [a.get("event_tag", "") for a in agent_list  if a.get("event_tag")]
        algorithms.update(agent_ids)
        device_names = [d.get("device_name") for d in task.get("device_list", []) if d.get("device_name")] ## camera name
        device_ids = [d.get("device_id") for d in task.get("device_list", []) if d.get("device_id")]   ## camera id
        category = categorize_task(task)
        mon_entry = monitor_by_task.get(str(task_id)) or {}
        mon = mon_entry.get("monitor")
        algo_name = algorithm_catalog.event_name(mon_entry.get("event_type", "")) if mon_entry else ""

        agent_join = ", ".join(agent_tags) ##  将agenttags 转变成字符串并用,分割

        # 『关联智能体/算法』列：大模型→智能体名(不变)；小模型→小模型算法中文名；小+大→『小模型/智能体』
        if category == "small_task":
            assoc = algo_name
        elif category == "small_and_agent_task":
            assoc = f"{algo_name}/{agent_join}" if algo_name else agent_join
        else:
            assoc = agent_join

        summaries.append(
            {
                "task_id": str(task_id),
                "task_name": task_name,
                "camera_device_names": ", ".join(device_names),
                "camera_device_ids": ", ".join(device_ids),
                "agent_id": ", ".join(agent_ids),
                "agent_name": assoc,
                "task_type": (task.get("task_type") or ""),
                "category": category,
                "task_enable": _task_status(task),
                "task_status": task_status,
                # 查看回填：右侧控制面板可直接展开的真实参数（离线用快照，无需二次请求设备）
                #"detail": task_builders.monitor_to_panel_config(task, mon),
            }
        )
    return summaries, algorithms


class DeviceService:
    @staticmethod
    def build_task_payload(task_obj: dict) -> dict:
        allowed_fields = ["task_id", "task_name", "task_type", "device_list", "enable", "schedule_plan_id", "analysis_interval", "agent_list"]
        payload = {k: task_obj[k] for k in allowed_fields if k in task_obj}
        if "device_list" in payload:
            for dev in payload["device_list"]:
                if "image_extract_frame_interval" in dev:
                    val = dev["image_extract_frame_interval"]
                    # 修复物理设备的特定约束（从设备拉取可能是 0，但下发必须在 1s~10s 之间，单位为 ms）
                    if val < 1000:
                        dev["image_extract_frame_interval"] = 1000
                    elif val > 10000:
                        dev["image_extract_frame_interval"] = 10000
        return payload

    @staticmethod
    async def authed_post(
        client: httpx.AsyncClient, device: DeviceORM, db: Optional[AsyncSession],
        path: str, body: Optional[dict] = None, retry: bool = True,
    ) -> Optional[dict]:
        """带 sessionID 的鉴权 POST，统一了各设备接口的『会话失效自动重登重试』逻辑。

        首次请求非 200 / code≠0（含会话过期）时，用 challenge_login 重登一次并重试。
        成功返回接口 JSON（dict，含 code/message，供调用方读业务错误）；网络/异常返回 None。
        """
        base_url = f"http://{device.ip}:{device.port}"
        if device.session_id:
            client.cookies.set("sessionID", device.session_id)

        async def _post():
            res = await client.post(f"{base_url}{path}", json=body or {})
            return res.json() if res.status_code == 200 else None

        try:
            data = await _post()
            if data is not None and data.get("code") == 0:
                return data
            if retry:
                ok, session_id, _ = await challenge_login(
                    client, base_url, device.username, device.password
                )
                if ok:
                    device.session_id = session_id
                    if db is not None:
                        await db.commit()
                    return await _post()
            return data
        except Exception as e:
            print(f"authed_post error {device.ip}{path}: {e}")
            return None

    @staticmethod
    async def get_device_tasks(client: httpx.AsyncClient, device: DeviceORM, db: Optional[AsyncSession] = None):
        """拉取设备原始任务列表（/intelli_manager/task_list）。会话失效时自动重登。
        成功返回接口 JSON（dict），失败返回 None。"""
        return await DeviceService.authed_post(client, device, db, "/intelli_manager/task_list", TASK_LIST_BODY)

    # ── 任务创建依赖的设备接口封装（均复用 authed_post） ──────────────────
    @staticmethod
    async def get_authorization(client, device, db=None):
        """算法授权文件信息（/intelli_manager/authorization_document）。"""
        #/intelli_manager/alg_warehouse/packet_list
        return await DeviceService.authed_post(
                    client, device, db, "/intelli_manager/alg_warehouse/packet_list", {"offset": 0, "size": 100})
        #return await DeviceService.authed_post(
        #    client, device, db, "/intelli_manager/authorization_document", {"offset": 0, "size": 100})

    @staticmethod
    async def list_alg_warehouses(client, device, db=None):
        """已安装算法仓列表（/intelli_manager/alg_warehouse/packet_list）。"""
        return await DeviceService.authed_post(
            client, device, db, "/intelli_manager/alg_warehouse/packet_list", {"offset": 0, "size": 100})

    @staticmethod
    async def list_alg_cards(client, device, db=None, file_id=None):
        """算法仓卡片能力集（/intelli_manager/alg_warehouse/card_cap），含事件/目标类型。"""
        body = {"offset": 0, "size": 100}
        if file_id is not None:
            body["file_id"] = file_id
        return await DeviceService.authed_post(
            client, device, db, "/intelli_manager/alg_warehouse/card_cap", body)

    @staticmethod
    async def list_algorithm_rows(client, device, db=None) -> Tuple[List[dict], Optional[str]]:
        """拉取设备算法仓 + 卡片能力并整形为算法目录行，返回 (rows, 错误)；离线/失败时 rows=[]、错误非空。

        行形状 {algoCabinName, version, eventType, eventName, targetTypes, description}：
        供【对话草案】propose_deployment 与【面板目录】GET /devices/{id}/algorithms 共用，避免整形逻辑漂移。
        card_cap 无数据时至少按算法仓兜底列出。
        """
        packet = await DeviceService.list_alg_warehouses(client, device, db)
        cards = await DeviceService.list_alg_cards(client, device, db)
        if packet is None:
            return [], f"设备「{device.name}」离线或不可达，无法查询算法仓"
        if packet.get("code") != 0:
            return [], f"查询算法仓失败：{packet.get('message')}"
        warehouses = packet.get("data", {}).get("list", [])
        wh_by_file = {w.get("file_id"): w for w in warehouses if w.get("file_id") is not None}
        rows: List[dict] = []
        card_list = (cards or {}).get("data", {}).get("cards", []) if isinstance(cards, dict) else []
        for c in card_list:
            w = wh_by_file.get(c.get("file_id")) or (warehouses[0] if warehouses else {})
            for at in c.get("alertor_type", []):
                event_type = at.get("alertor_type", "")
                rows.append({
                    "algoCabinName": w.get("alg_name", ""),
                    "version": w.get("alg_version", "V2.0.0"),
                    "eventType": event_type,
                    "eventName": algorithm_catalog.event_name(event_type),  # 英文算法ID → 中文事件名
                    "targetTypes": at.get("target_type", []),
                    "description": w.get("status", ""),
                })
        if not rows:  # card_cap 无数据时至少列出算法仓
            rows = [{"algoCabinName": w.get("alg_name", ""), "version": w.get("alg_version", "V2.0.0"),
                     "eventType": "", "eventName": "", "targetTypes": [], "description": w.get("status", "")}
                    for w in warehouses]
        return rows, None

    @staticmethod
    async def list_agents(client, device, db=None):
        """已有智能体算法列表（/intelli_manager/agent_list）。"""
        return await DeviceService.authed_post(
            client, device, db, "/intelli_manager/agent_list", {"offset": 0, "size": 100})

    @staticmethod
    async def create_agent(client, device, db, body: dict):
        """新建智能体算法（/intelli_manager/agent_item）。"""
        return await DeviceService.authed_post(client, device, db, "/intelli_manager/agent_item", body)

    @staticmethod
    async def create_task(client, device, db, body: dict):
        """创建布控任务（/intelli_manager/task），返回体含 data.task_id。"""
        return await DeviceService.authed_post(client, device, db, "/intelli_manager/task", body)

    @staticmethod
    async def update_task(client, device, db, body: dict):
        """更新已有布控任务（PUT /intelli_manager/task，body 需含 task_id）。
        设备靠 body 里的 task_id 区分更新 vs 新建；参照 task_service 的 Prompt 优化下发用法。
        成功返回接口 JSON（dict，含 code/message），网络/异常返回 None。"""
        base_url = f"http://{device.ip}:{device.port}"
        if device.session_id:
            client.cookies.set("sessionID", device.session_id)
        try:
            res = await client.put(f"{base_url}/intelli_manager/task", json=body or {})
            return res.json() if res.status_code == 200 else None
        except Exception as e:
            print(f"update_task error {device.ip}: {e}")
            return None

    @staticmethod
    async def create_monitor(client, device, db, body: dict):
        """算法仓任务第二步：下发 monitor（/intelli_manager/monitor）。"""
        return await DeviceService.authed_post(client, device, db, "/intelli_manager/monitor", body)

    @staticmethod
    async def deploy_warehouse_task(
        client: httpx.AsyncClient, device: DeviceORM, db: Optional[AsyncSession], *,
        task_name: str,
        channel_device_id: int,
        event_type: str,
        algo_cabin_name: str,
        version: str = "V2.0.0",
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
    ) -> Tuple[bool, str, Optional[str]]:
        """算法仓任务两步下发的共享封装（纯小模型 & 小+大共用）。

        流程：create_task(single_point_task) → 取 data.task_id → create_monitor（带/不带 agent_llm）。
        返回 (成功?, 中文消息, task_id)。部分失败语义：任务已建但 monitor 失败时，
        返回 (False, 孤儿提示, task_id)，让调用方能把 task_id 回传便于排查/清理。
        agent_llm 非空即『小+大』任务，target_expand 仅在该分支生效（见 build_monitor_payload）。
        小模型/小+大为【实时分析】，无分析间隔/抽帧间隔概念（见 build_single_point_task_payload）。
        """
        # 第一步：创建 single_point_task 拿 task_id
        task_payload = task_builders.build_single_point_task_payload(
            task_name, channel_device_id, event_type,
        )
        task_res = await DeviceService.create_task(client, device, db, task_payload)
        if not task_res or task_res.get("code") != 0:
            msg = (task_res or {}).get("message") or "设备不可达或返回错误"
            return False, f"创建任务失败：{msg}", None
        task_id = (task_res.get("data") or {}).get("task_id")
        if not task_id:
            return False, "创建任务成功但未返回 task_id，无法继续下发 monitor", None

        # 第二步：下发 monitor（algo_cabin_name / 阈值 / 目标 / 扩图 / 二次大模型等）
        monitor_payload = task_builders.build_monitor_payload(
            task_id, channel_device_id, event_type, algo_cabin_name,
            version=version, monitor_name=monitor_name, area=area,
            target_types=target_types, threshold=threshold,
            target_max=target_max, target_min=target_min,
            duration=duration, cooldown=cooldown,
            agent_llm=agent_llm, target_expand=target_expand,
        )
        mon_res = await DeviceService.create_monitor(client, device, db, monitor_payload)
        if not mon_res or mon_res.get("code") != 0:
            msg = (mon_res or {}).get("message") or "设备不可达或返回错误"
            # 孤儿：任务已建但 monitor 下发失败，回传 task_id 便于排查/清理
            return False, f"任务已创建(task_id={task_id})但下发 monitor 失败：{msg}", task_id

        return True, f"布控任务创建成功（task_id={task_id}）", task_id

    @staticmethod
    async def deploy_warehouse_task_multi(
        client: httpx.AsyncClient, device: DeviceORM, db: Optional[AsyncSession], *,
        task_name: str,
        channel_device_id: int,
        algorithms: List[dict],
    ) -> Tuple[bool, str, Optional[str]]:
        """算法仓任务【多算法】两步下发：一次提交把 N 条算法布控到一个任务。

        流程：create_task(single_point_task，首算法 eventType 作锚点) → 取 task_id →
        按 algo_cabin_name 分组（保序）→ 每仓把该仓全部规则组装成一条 monitor 下发。
        关键契约：一个 task 关联多条 monitor，各仓【monitor_id 互不相同】，按
        task_builders.monitor_id_for 规律取 int(task_id)*100 + 仓序号(1..N)；
        同仓多算法只调一次 monitor 接口（多条 rulesParams），跨仓则调多次。
        add/update/remove_task_algorithm 定位时靠 labels.algoCabinName 认仓、eventType 认规则；
        同仓 eventType 唯一由上层校验保证。

        每个 algorithm 入参（router 已预解析 I/O 相关字段）：event_type / algo_cabin_name / version /
        target_types / threshold / target_max / target_min / duration / cooldown /
        area（绑定 ROI 或全画面，router 解析）/ agent_llm（仅 combined，router 解析）/ target_expand。
        返回 (成功?, 中文消息, task_id)；建任务后部分仓失败时返回 (False, 孤儿提示, task_id)。
        """
        if not algorithms:
            return False, "未提供任何算法，无法下发任务", None

        # 第一步：创建 single_point_task 拿 task_id（真实规则在各仓 monitor 里）
        task_payload = task_builders.build_single_point_task_payload(
            task_name, channel_device_id, algorithms[0].get("event_type"),
        )
        task_res = await DeviceService.create_task(client, device, db, task_payload)
        if not task_res or task_res.get("code") != 0:
            msg = (task_res or {}).get("message") or "设备不可达或返回错误"
            return False, f"创建任务失败：{msg}", None
        task_id = (task_res.get("data") or {}).get("task_id")
        if not task_id:
            return False, "创建任务成功但未返回 task_id，无法继续下发 monitor", None

        # 按算法仓分组（dict 保序，等价于按首次出现顺序）
        groups: dict = {}
        for algo in algorithms:
            groups.setdefault(algo.get("algo_cabin_name"), []).append(algo)

        # 第二步：逐仓组装 rulesParams → 下发一条 monitor（仓序号 seq 决定各自的 monitor_id）
        failed: List[str] = []
        for seq, (cabin, group) in enumerate(groups.items(), start=1):
            rules = [
                task_builders.build_rule(
                    event_type=algo.get("event_type"),
                    area=algo.get("area"),
                    target_types=algo.get("target_types"),
                    threshold=algo.get("threshold", 0.3),
                    target_max=algo.get("target_max", 1),
                    target_min=algo.get("target_min", 0),
                    duration=algo.get("duration", 3),
                    cooldown=algo.get("cooldown", 600),
                    agent_llm=algo.get("agent_llm"),
                    target_expand=algo.get("target_expand"),
                )
                for algo in group
            ]
            monitor_payload = task_builders.build_warehouse_monitor(
                task_id, channel_device_id, cabin, rules,
                version=group[0].get("version", "V2.0.0"), seq=seq,
            )
            mon_res = await DeviceService.create_monitor(client, device, db, monitor_payload)
            if not mon_res or mon_res.get("code") != 0:
                msg = (mon_res or {}).get("message") or "设备不可达或返回错误"
                failed.append(f"「{cabin}」：{msg}")

        if failed:
            return (False,
                    f"任务已创建(task_id={task_id})但下发 {len(failed)}/{len(groups)} 个算法仓失败："
                    + "；".join(failed), task_id)
        return (True,
                f"布控任务创建成功（task_id={task_id}，{len(groups)} 个算法仓 / {len(algorithms)} 个算法）",
                task_id)

    @staticmethod
    async def locate_task(
        client: httpx.AsyncClient, device: DeviceORM, db: Optional[AsyncSession], task_id
    ) -> Tuple[Optional[dict], Optional[int], Optional[str]]:
        """按 task_id 在设备任务列表中定位任务，返回 (原始任务项, 首通道 device_id, 错误消息)。

        与 agent_tools._locate_device_task 同语义，但放在本模块，供路由层的『编辑保存』复用
        （agent_tools 依赖本模块，反向导入会成环）。
        """
        data = await DeviceService.get_device_tasks(client, device, db)
        if not data or data.get("code") != 0:
            return None, None, f"设备「{device.name}」离线或不可达，无法读取任务列表"
        for t in (data.get("data") or {}).get("list", []) or []:
            if str(t.get("task_id")) == str(task_id):
                dev_list = t.get("device_list") or []
                channel_device_id = (dev_list[0] or {}).get("device_id") if dev_list else None
                return t, channel_device_id, None
        return None, None, f"设备上未找到任务 task_id={task_id}"

    @staticmethod
    async def list_task_monitors(
        client: httpx.AsyncClient, device: DeviceORM, db: Optional[AsyncSession], *,
        task_id, channel_device_id,
    ) -> List[dict]:
        """读取某任务名下的全部 monitor（每个算法仓一条）；失败返回空列表（优雅降级）。"""
        res = await DeviceService.authed_post(
            client, device, db, MONITOR_LIST_PATH,
            {"device_id": channel_device_id, "task_id": task_id})
        return ((res or {}).get("data") or {}).get("param") or []

    @staticmethod
    def _apply_channel(task: dict, channel_device_id, current_channel_id) -> dict:
        """通道变更时只替换 device_list[0].device_id，保留抽帧间隔等设备侧原有字段。"""
        if not channel_device_id or str(channel_device_id) == str(current_channel_id):
            return task
        dev_list = task.get("device_list") or [{}]
        first = dict(dev_list[0] or {})
        first["device_id"] = int(channel_device_id)
        task["device_list"] = [first] + list(dev_list[1:])
        return task

    @staticmethod
    async def update_agent_real_task(
        client: httpx.AsyncClient, device: DeviceORM, db: Optional[AsyncSession], *,
        task_id,
        task_name: str,
        channel_device_id: Optional[int],
        agents: List[dict],
        analysis_interval: int = 5,
    ) -> Tuple[bool, str]:
        """就地更新【纯大模型智能体任务】(agent_real_task)：重建 agent_list + 任务名/分析间隔后 PUT。

        agents 为路由层已富化的项（event_id/event_tag/prompt/alarm_condition/filter_* + area）。
        设备靠 body 里的 task_id 区分更新与新建，故必须带上原 task_id（避免新建出重复任务）。
        enable 沿用设备现值：启用/停用请走 set_task_enable，编辑保存不隐式改变使能状态。
        返回 (成功?, 中文消息)。
        """
        task, cur_channel, err = await DeviceService.locate_task(client, device, db, task_id)
        if err:
            return False, err
        if task.get("task_type") != "agent_real_task":
            return False, f"任务 task_id={task_id} 不是纯大模型智能体任务，无法按智能体任务更新"

        task = dict(task)
        if task_name:
            task["task_name"] = task_name
        task["analysis_interval"] = analysis_interval
        task["agent_list"] = [
            {
                "event_id": a.get("event_id"),
                "event_tag": a.get("event_tag"),
                "agent_config": task_builders.build_agent_config(a, a.get("area")),
            }
            for a in agents
        ]
        DeviceService._apply_channel(task, channel_device_id, cur_channel)

        data = await DeviceService.update_task(client, device, db, DeviceService.build_task_payload(task))
        if data is None:
            return False, f"任务 task_id={task_id} 更新时设备不可达，请重试"
        if data.get("code") != 0:
            return False, f"任务 task_id={task_id} 更新失败：{data.get('message')}"
        return True, f"智能体任务「{task.get('task_name')}」已更新（关联 {len(agents)} 个智能体）"

    @staticmethod
    async def update_warehouse_task_multi(
        client: httpx.AsyncClient, device: DeviceORM, db: Optional[AsyncSession], *,
        task_id,
        task_name: str,
        channel_device_id: Optional[int],
        algorithms: List[dict],
    ) -> Tuple[bool, str]:
        """就地更新【算法仓多算法任务】：任务级 PUT + 按算法仓覆盖重下 monitor。

        设备既无 monitor 更新接口也无删除接口，因此：
        - 保留的仓：用【该仓原 monitor_id】+ 同 algoCabinName 覆盖下发新 rulesParams（整仓替换）；
        - 新增的仓：按 task_builders.next_monitor_id 顺延分配【独立 monitor_id】（与既有仓共用会互相覆盖）；
        - 编辑中被移除的仓：原规则原样重下但 enable=False（停用降级，与 _disable_whole_task 一致）。
        enable 沿用设备现值（启用/停用走 set_task_enable）。返回 (成功?, 中文消息)。
        """
        if not algorithms:
            return False, "未提供任何算法，无法更新任务"
        task, cur_channel, err = await DeviceService.locate_task(client, device, db, task_id)
        if err:
            return False, err
        if task.get("task_type") == "agent_real_task":
            return False, f"任务 task_id={task_id} 为纯大模型智能体任务，无法按算法仓任务更新"
        channel = channel_device_id or cur_channel
        if channel is None:
            return False, f"任务 task_id={task_id} 缺少通道信息，无法更新"

        # ① 先 PUT 任务级字段（名称/通道）；失败即中止，避免只改了 monitor 造成名实不符
        task = dict(task)
        if task_name:
            task["task_name"] = task_name
        DeviceService._apply_channel(task, channel_device_id, cur_channel)
        data = await DeviceService.update_task(client, device, db, DeviceService.build_task_payload(task))
        if data is None:
            return False, f"任务 task_id={task_id} 更新时设备不可达，请重试"
        if data.get("code") != 0:
            return False, f"任务 task_id={task_id} 更新失败：{data.get('message')}"

        # ② 现有 monitor 索引：仓名 → (monitor_id / monitor_name / version / 原规则)
        existing = await DeviceService.list_task_monitors(
            client, device, db, task_id=task_id, channel_device_id=channel)
        index: dict = {}
        for mon in existing:
            common = mon.get("common_param") or {}
            labels = ((common.get("warehouse_v20_param") or {}).get("labels")) or {}
            index[labels.get("algoCabinName")] = {
                "monitor_id": common.get("monitor_id"),
                "monitor_name": common.get("monitor_name"),
                "version": labels.get("version", "V2.0.0"),
                "rules": task_builders._warehouse_rules(mon),
            }

        # ③ 按仓分组覆盖下发（保留仓沿用原 monitor_id，新增仓按规律顺延分配独立 monitor_id）
        groups: dict = {}
        for algo in algorithms:
            groups.setdefault(algo.get("algo_cabin_name"), []).append(algo)
        # 已占用的 monitor（含本轮新分配的），供 next_monitor_id 避让，避免多个新增仓撞同一个 id
        allocated = list(existing)
        failed: List[str] = []
        for cabin, group in groups.items():
            rules = [
                task_builders.build_rule(
                    event_type=algo.get("event_type"),
                    area=algo.get("area"),
                    target_types=algo.get("target_types"),
                    threshold=algo.get("threshold", 0.3),
                    target_max=algo.get("target_max", 1),
                    target_min=algo.get("target_min", 0),
                    duration=algo.get("duration", 3),
                    cooldown=algo.get("cooldown", 600),
                    agent_llm=algo.get("agent_llm"),
                    target_expand=algo.get("target_expand"),
                )
                for algo in group
            ]
            old = index.get(cabin) or {}
            monitor_id = old.get("monitor_id")
            if monitor_id is None:
                monitor_id = task_builders.next_monitor_id(task_id, allocated)
                allocated.append({"common_param": {"monitor_id": monitor_id}})
            monitor_payload = task_builders.build_warehouse_monitor(
                task_id, int(channel), cabin, rules,
                version=group[0].get("version", "V2.0.0"),
                monitor_id=monitor_id,
                monitor_name=old.get("monitor_name"),
            )
            mon_res = await DeviceService.create_monitor(client, device, db, monitor_payload)
            if not mon_res or mon_res.get("code") != 0:
                msg = (mon_res or {}).get("message") or "设备不可达或返回错误"
                failed.append(f"「{cabin}」：{msg}")

        # ④ 编辑中被移除的仓：设备无删除接口，原规则原样重下但置 enable=False
        disabled = 0
        for cabin, old in index.items():
            if not cabin or cabin in groups:
                continue
            payload = task_builders.build_warehouse_monitor(
                task_id, int(channel), cabin, old.get("rules") or [],
                version=old.get("version", "V2.0.0"),
                monitor_id=old.get("monitor_id"),
                monitor_name=old.get("monitor_name"),
                enable=False,
            )
            r = await DeviceService.create_monitor(client, device, db, payload)
            if r and r.get("code") == 0:
                disabled += 1

        if failed:
            return (False,
                    f"任务 task_id={task_id} 已更新名称，但 {len(failed)}/{len(groups)} 个算法仓下发失败："
                    + "；".join(failed))
        extra = f"，停用 {disabled} 个已移除的算法仓" if disabled else ""
        return (True,
                f"布控任务「{task.get('task_name')}」已更新"
                f"（task_id={task_id}，{len(groups)} 个算法仓 / {len(algorithms)} 个算法{extra}）")

    @staticmethod
    async def set_task_enable(
        client: httpx.AsyncClient, device: DeviceORM, db: Optional[AsyncSession], *,
        task_id, enable: bool,
    ) -> Tuple[bool, str]:
        """启用/停用整个任务：任务级 PUT enable + best-effort 同步其名下各算法仓 monitor 的 enable。

        任务级 PUT 是主判据；monitor 同步失败不阻断（原规则保留，仅使能位可能滞后，
        下次编辑保存或再次切换会修正）。返回 (成功?, 中文消息)。
        """
        task, channel, err = await DeviceService.locate_task(client, device, db, task_id)
        if err:
            return False, err
        task = dict(task)
        task["enable"] = bool(enable)
        data = await DeviceService.update_task(client, device, db, DeviceService.build_task_payload(task))
        if data is None:
            return False, f"任务 task_id={task_id} 状态切换时设备不可达，请重试"
        if data.get("code") != 0:
            return False, f"任务 task_id={task_id} 状态切换失败：{data.get('message')}"

        synced = 0
        if task.get("task_type") != "agent_real_task" and channel is not None:
            for mon in await DeviceService.list_task_monitors(
                    client, device, db, task_id=task_id, channel_device_id=channel):
                common = mon.get("common_param") or {}
                labels = ((common.get("warehouse_v20_param") or {}).get("labels")) or {}
                payload = task_builders.build_warehouse_monitor(
                    task_id, int(channel), labels.get("algoCabinName", ""),
                    task_builders._warehouse_rules(mon),
                    version=labels.get("version", "V2.0.0"),
                    monitor_id=common.get("monitor_id"),
                    monitor_name=common.get("monitor_name"),
                    enable=bool(enable),
                )
                r = await DeviceService.create_monitor(client, device, db, payload)
                if r and r.get("code") == 0:
                    synced += 1

        word = "启用" if enable else "停用"
        extra = f"（同步 {synced} 个算法仓）" if synced else ""
        return True, f"任务 task_id={task_id} 已{word}{extra}"

    @staticmethod
    async def list_monitors(client: httpx.AsyncClient, device: DeviceORM, db: Optional[AsyncSession] = None):
        """拉取设备 monitor 列表（用于富化任务摘要里的小模型算法名）。

        MONITOR_LIST_PATH 未在协议文档核实，属 best-effort；authed_post 已对网络/异常返回 None，
        调用方据此优雅降级（关联算法列留空、查看回填仅用任务基础字段），不影响其余功能。
        """
        return await DeviceService.authed_post(client, device, db, MONITOR_LIST_PATH, MONITOR_LIST_BODY)

    @staticmethod
    async def fetch_device_data(
        ip: str, port: str, username: str = "", password: str = "", existing_session_id: str = ""
    ):
        channels: List[dict] = []
        device_tasks: List[dict] = []
        algorithms: set = set()
        algorithms_ability: List[dict] = []
        agents: List[dict] = []
        status = "离线"
        session_id = existing_session_id
        base_url = f"http://{ip}:{port}"

        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                if session_id:
                    client.cookies.set("sessionID", session_id)

                # 有会话则先探测其有效性，无效再重登；无会话直接登录
                needs_login = True
                if session_id:
                    try:
                        res = await client.post(f"{base_url}/device_access/device_config", json={"offset": 0, "size": 1})
                        if res.status_code == 200 and res.json().get("code") == 0:
                            status = "在线"
                            needs_login = False
                    except Exception:
                        status = "离线"
                        needs_login = False  # 网络异常，无需再尝试登录

                if needs_login:
                    ok, new_session, login_status = await challenge_login(client, base_url, username, password)
                    status = login_status
                    if ok:
                        session_id = new_session

                if status == "在线":
                    channels = await DeviceService._fetch_channels(client, base_url, ip)
                    algorithms_ability = await DeviceService._fetch_algorithms_ability(client, base_url, ip)
                    agents = await DeviceService._fetch_agents(client, base_url, ip)
                    device_tasks, algorithms = await DeviceService._fetch_task_summaries(client, base_url, ip)
                    
        except Exception as global_e:
            print(f"Global error in fetch_device_data for {ip}: {global_e}")
            status = "离线"

        return channels, device_tasks, list(algorithms), status, session_id, algorithms_ability, agents 

    @staticmethod
    async def _fetch_channels(client: httpx.AsyncClient, base_url: str, ip: str) -> List[dict]:
        results = []
        try:
            res1 = await client.post(f"{base_url}/device_access/device_state", json={"offset": 0, "size": 100})
            if res1.status_code == 200 and res1.json().get("code") == 0:
                data_list = res1.json().get("data", []) or []
                state_map = {str(item.get("device_id")): item.get("state") for item in data_list}
            #print(f"state_map:{state_map}")
            res = await client.post(f"{base_url}/device_access/device_config", json={"offset": 0, "size": 100})
            if res.status_code == 200 and res.json().get("code") == 0:
                items = res.json().get("data", [])
                for item in items:
                    onlinestatus = "offline"
                    device_id = item.get("device_id")
                    status = state_map.get(str(device_id))  # 直接取值，未匹配到返回 None
                    onlinestatus = "online" if status == 0 else "offline"
                    #print(f"onlinestatus:{onlinestatus}")
                    results.append({
                        "device_id": device_id,
                        "device_name": item.get("device_name"),
                        "proto": item.get("proto"),
                        "rtsp": item.get("rtsp_param", {}).get("url"),
                        "gbid": item.get("gb28181_param", {}).get("DeviceID"),
                        "onlinestatus": onlinestatus,
                    })
                return results;
                #return _parse_channels(res.json().get("data", []))
        except Exception as e:
            print(f"Error fetching channels from {ip}: {e}")
        return []

    @staticmethod
    async def _fetch_task_summaries(client: httpx.AsyncClient, base_url: str, ip: str) -> Tuple[List[dict], set]:
        try:
            res = await client.post(f"{base_url}/intelli_manager/task_list", json=TASK_LIST_BODY)
            if res.status_code == 200 and res.json().get("code") == 0:
                task_list = res.json().get("data", {}).get("list", [])
                monitor_by_task = await DeviceService._fetch_monitor_index(client, base_url, ip,task_list)
                return _summarize_tasks_algorithm(task_list, monitor_by_task)
        except Exception as e:
            print(f"Error fetching tasks from {ip}: {e}")
        return [], set()

    @staticmethod
    async def _fetch_algorithms_ability(client: httpx.AsyncClient, base_url: str, ip: str) ->  List[dict]:
        try:
            res = await client.post(f"{base_url}/intelli_manager/alg_warehouse/packet_list", json=TASK_LIST_BODY)
            if res.status_code == 200 and res.json().get("code") == 0:
                objectalgorithms = res.json().get("data", {})
                return _parse_algorithms(objectalgorithms.get("list", []))
        except Exception as e:
            print(f"Error fetching tasks from {ip}: {e}")
        return []
    
    @staticmethod
    async def _fetch_monitor_index(client: httpx.AsyncClient, base_url: str, ip: str,task_list: list) -> List[dict]:
        """拉取 monitor 列表并按 task_id 建索引；失败/接口不存在时返回空 dict（优雅降级）。
        会话 cookie 已在 fetch_device_data 登录阶段设置到 client 上，此处直接复用。"""
        results : List[dict] = []

        try:
            for task in task_list:
                # 状态三态（正常/异常/未启用）与纯大模型任务共用同一映射
                task_status = _task_state_label(task)
                task_type = task.get("task_type", "") 
                task_id = task.get("task_id", "") 
                #raw_status = task.get("task_state")
                #task_status = STATUS_MAP.get(raw_status, "未知")
                device_lists = task.get("device_list", []) 
                first_dev = device_lists[0] if device_lists else {}
                device_id = first_dev.get("device_id")
                device_name = first_dev.get("device_name")
                if not device_id or not task_id:
                    continue
                # fetch small task 
                monitor_param : List[dict] = []
                algorithms: set = set()
                if task_type == "single_point_task":
                    res = await client.post(f"{base_url}{MONITOR_LIST_PATH}", json={"device_id": device_id, "task_id": task_id})
                    param: List[dict] = []
                    if res.status_code == 200 and res.json().get("code") == 0:
                         param = res.json().get("data", {}).get("param", []) or []
                         monitor_data, task_type ,algorithms = _index_monitors(param)
                         monitor_param.extend(monitor_data)

                    # 『关联智能体/算法』中文列：汇总该任务名下各算法仓的全部规则
                    packages = [pkg for m in monitor_param for pkg in (m.get("algorithms_packages") or [])]
                    results.append({
                        "task_type":task_type,
                        "task_id": task_id,
                        "task_name": task.get("task_name", ""),
                        "task_status":task_status,
                        # 是否启用开关的初值（设备侧 enable 使能标志）
                        "task_enable": bool(task.get("enable")),
                        "camera_device_name": device_name,
                        "camera_device_id": device_id,
                        "monitor_tasks": monitor_param,
                        "algorithms": list(algorithms),
                        "algorithms_label": _algorithms_label(packages),
                        "agents_tasks": [],
                        # 查看回填：把设备任务 + 其全部 monitor/rulesParams 逆映射为面板可展开的多算法真实参数
                        "detail": task_builders.monitors_to_panel_config(task, param),
                    })

            return results
        except Exception as e:
            print(f"Error fetching monitors from {ip}: {e}")
        return []

    @staticmethod
    async def _fetch_agents(client: httpx.AsyncClient, base_url: str, ip: str) -> List[dict]:
        try:
            res = await client.post(f"{base_url}/intelli_manager/agent_list", json={"offset": 0, "size": 100})
            if res.status_code == 200 and res.json().get("code") == 0:
                return _parse_agents(res.json().get("data", {}).get("list", []))
        except Exception as e:
            print(f"Error fetching agents from {ip}: {e}")
        return []
