import httpx
import hashlib
import json
from models.orm import DeviceORM
from sqlalchemy.ext.asyncio import AsyncSession

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
    async def do_login(client: httpx.AsyncClient, device: DeviceORM, db: AsyncSession):
        base_url = f"http://{device.ip}:{device.port}"
        try:
            res = await client.get(f"{base_url}/auth/login/challenge", params={"username": device.username})
            if res.status_code == 200 and res.json().get("code") == 0:
                data = res.json().get("data", {})
                pwd_str = f"{device.password}{data.get('salt','')}{data.get('challenge','')}"
                hashed_pwd = hashlib.sha256(pwd_str.encode('utf-8')).hexdigest()
                login_res = await client.post(f"{base_url}/auth/login", json={
                    "session_id": data.get("session_id"), "username": device.username, "password": hashed_pwd, "aiotap_flag": 1
                })
                if login_res.status_code == 200 and login_res.json().get("code") == 0:
                    device.session_id = data.get("session_id")
                    device.status = "在线"
                    await db.commit()
                    return True
        except Exception as e:
            print(f"Login failed for device {device.name}: {e}")
        return False

    @classmethod
    async def fetch_device_data(cls, ip: str, port: str, username: str = "", password: str = "", existing_session_id: str = ""):
        channels = []
        device_tasks = []
        algorithms = set()
        status = "离线"
        session_id = existing_session_id
        
        try:
            base_url = f"http://{ip}:{port}"
            async with httpx.AsyncClient(timeout=5.0) as client:
                if session_id:
                    client.cookies.set("sessionID", session_id)
                
                async def do_login_internal():
                    nonlocal status, session_id
                    if not username or not password:
                        status = "密码错误"
                        return False
                        
                    try:
                        challenge_res = await client.get(f"{base_url}/auth/login/challenge", params={"username": username})
                        if challenge_res.status_code == 200:
                            c_data = challenge_res.json()
                            if c_data.get("code") == 0:
                                data = c_data.get("data", {})
                                new_session_id = data.get("session_id", "")
                                challenge = data.get("challenge", "")
                                salt = data.get("salt", "")
                                pwd_str = f"{password}{salt}{challenge}"
                                hashed_pwd = hashlib.sha256(pwd_str.encode('utf-8')).hexdigest()
                                
                                login_res = await client.post(f"{base_url}/auth/login", json={
                                    "session_id": new_session_id, "username": username, "password": hashed_pwd, "aiotap_flag": 1
                                })
                                if login_res.status_code == 200 and login_res.json().get("code") == 0:
                                    session_id = new_session_id
                                    client.cookies.set("sessionID", session_id)
                                    status = "在线"
                                    return True
                                else:
                                    status = "密码错误"
                            else:
                                status = "异常"
                        else:
                            status = "离线"
                    except Exception as e:
                        print(f"Error during login process for {ip}: {e}")
                        status = "离线"
                    return False

                if not session_id:
                    await do_login_internal()
                else:
                    try:
                        res = await client.post(f"{base_url}/device_access/device_config", json={"offset": 0, "size": 1})
                        if res.status_code != 200 or res.json().get("code") != 0:
                            await do_login_internal()
                        else:
                            status = "在线"
                    except Exception:
                        status = "离线"
                
                if status == "在线":
                    try:
                        res = await client.post(f"{base_url}/device_access/device_config", json={"offset": 0, "size": 100})
                        if res.status_code == 200 and res.json().get("code") == 0:
                            for item in res.json().get("data", []):
                                channels.append({
                                    "device_id": str(item.get("device_id")),
                                    "device_name": item.get("device_name"),
                                    "proto": item.get("proto"),
                                    "rtsp": item.get("rtsp_param", {}).get("url")
                                })
                    except Exception as e:
                        print(f"Error fetching channels from {ip}: {e}")

                    try:
                        res = await client.post(f"{base_url}/intelli_manager/task_list", json={"offset": 0, "size": 100, "condition": {}})
                        if res.status_code == 200 and res.json().get("code") == 0:
                            for task in res.json().get("data", {}).get("list", []):
                                agent_ids = [agent.get('agent_id', '') for agent in task.get("agent_list", []) if agent.get('agent_id')]
                                for aid in agent_ids: algorithms.add(aid)
                                device_names = [d.get("device_name") for d in task.get("device_list", [])]
                                device_tasks.append({
                                    "task_id": str(task.get("task_id")),
                                    "task_name": task.get("task_name"),
                                    "device_name": ", ".join(device_names),
                                    "agent_id": ", ".join(agent_ids)
                                })
                    except Exception as e:
                        print(f"Error fetching tasks from {ip}: {e}")

        except Exception as global_e:
            print(f"Global error in fetch_device_data for {ip}: {global_e}")
            status = "离线"
                
        return channels, device_tasks, list(algorithms), status, session_id

