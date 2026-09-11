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


def _index_monitors(monitor_list: list) -> tuple[list, str, set]:
    """把 monitor 列表按其归属的 task_id（字符串）建索引，供任务摘要富化小模型算法信息。

    每项值保留原始 monitor（供 task_builders.monitor_to_panel_config 做逆映射）并预取
    展示所需的 event_type / algo_cabin_name（best-effort，结构缺失时跳过该项，不抛异常）。
    """
    results=[]
    algorithms_packages = []
    algorithms: set = set()
    for mon in monitor_list or []:
        task_type = "small_task"
        common = mon.get("common_param") or {}
        monitor_id = common.get("monitor_id")
        channel_device_id = common.get("channel_id")
        if monitor_id is None:
            continue
        warehouse = common.get("warehouse_v20_param") or {}
        algoCabinName = warehouse.get("labels").get("algoCabinName")
        rules = warehouse.get("rulesParams") or []
        for r in rules:
            agentLLMParam = r.get("extendParams",{}).get("aiotapCustom",{}).get("agentLLMParam",{})
            if(agentLLMParam):
                task_type="small_and_agent_task"
                algorithms.add(f"SM-{r.get("eventType")}-AG-{agentLLMParam.get("event_tag")}")
            else:
                task_type="small_task"
                algorithms.add(f"SM-{r.get("eventType")}")
            algorithms_packages.append({
                "major_type":algoCabinName,
                "minor_type": r.get("eventType"), 
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
        "algorithms_packages":algorithms_packages,
        })

    return results ,task_type, algorithms

def _summarize_tasks_algorithm(task_list: list, monitor_by_task: Optional[dict] = None) -> Tuple[List[dict], set]:
    """把设备原始任务列表压成前端展示用摘要，并收集全部算法 id。

    注意：task_list 中 agent_list 的智能体项使用 event_id/event_tag（非 agent_id）；
    小模型任务(single_point_task)的 agent_list 通常为空，其算法名(eventType)在 monitor 里，
    故通过 monitor_by_task（按 task_id 建索引）补齐『关联智能体/算法』列与查看回填用 detail。
    """
    monitor_by_task = monitor_by_task or []
    algorithms = set()
    STATUS_MAP = {
        0: "未启用",
        1: "正常",
    }
    task_list_all = []
    for task in task_list:
        task_agents = []
        task_status = "未知"
        task_type = task.get("task_type", "")
        task_id = task.get("task_id", "") 
        task_name = task.get("task_name", "") 
        raw_status = task.get("task_state")
        if(raw_status == 0):
            task_status = "未启用"
        if(raw_status == 1):
            task_status = "正常"
            
        #task_status = STATUS_MAP.get(raw_status, "未知")
        device_lists = task.get("device_list", []) 
        first_dev = device_lists[0] if device_lists else {}
        device_name = first_dev.get("device_name","")
        device_id = first_dev.get("device_id","")

        if task_type == "agent_real_task":
            agent_list = task.get("agent_list", [])
            for a in agent_list :
                algorithms.add(f"AG-{a.get("event_tag")}")
                task_agents.append({
                    "agent_id": a.get("event_id", "") ,
                    "agent_name": a.get("event_tag"),
                })

            task_list_all.append({
                "task_type": task_type,
                "task_id": task_id,
                "task_name": task_name,
                "task_status": task_status,
                "camera_device_name": device_name,
                "camera_device_id": device_id,
                "agents_tasks":task_agents,
                "algorithms":list(algorithms),
                "monitor_tasks":[],
            })

    for task in monitor_by_task:
        algorithms.update(task.get("algorithms",[]))

    task_list_all.extend(monitor_by_task)

    return task_list_all, algorithms


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
    async def create_monitor(client, device, db, body: dict):
        """算法仓任务第二步：下发 monitor（/intelli_manager/monitor）。"""
        return await DeviceService.authed_post(client, device, db, "/intelli_manager/monitor", body)

    @staticmethod
    async def list_monitors(client, device, db=None):
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
            print(f"evice_access/device_state {res1.json()}")
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
        # 1. 定义状态码映射字典
        STATUS_MAP = {
            0: "未启用",
            1: "正常",
        }

        try:
            for task in task_list:
                task_status = "未知"
                raw_status = task.get("task_state")
                if(raw_status == 0):
                    task_status = "未启用"
                if(raw_status == 1):
                    task_status = "正常"
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
                    if res.status_code == 200 and res.json().get("code") == 0:
                         monitor_data, task_type ,algorithms = _index_monitors(res.json().get("data", {}).get("param", []))
                         monitor_param.extend(monitor_data)

                    results.append({
                        "task_type":task_type,
                        "task_id": task_id, 
                        "task_name": task.get("task_name", ""), 
                        "task_status":task_status,
                        "camera_device_name": device_name,
                        "camera_device_id": device_id,
                        "monitor_tasks": monitor_param,
                        "algorithms": list(algorithms),
                        "agents_tasks": [],
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
