from datetime import datetime
import json
import os
from models.schemas import Device, Alert

CONFIG_FILE = "config.json"

def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "services_config": {
            "ws": {"enabled": True, "port": "8080", "path": "/api/ws/alarms"},
            "http": {"enabled": True, "port": "80", "path": "/api/http/alarms"}
        },
        "backend_interface_id": None,
        "frontend_interface_id": None,
        "llm_config": {
            "provider": "Google (Gemini API)",
            "model_name": "gemini-2.5-flash-preview-09-2025",
            "base_url": "https://generativelanguage.googleapis.com",
            "api_key": ""
        }
    }

def save_config():
    config_data = {
        "services_config": current_services_config,
        "backend_interface_id": backend_interface_id,
        "frontend_interface_id": frontend_interface_id,
        "llm_config": llm_config
    }
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config_data, f, indent=4)
    except Exception as e:
        print(f"Failed to save config: {e}")

_config = load_config()

current_services_config = _config.get("services_config")
backend_interface_id = _config.get("backend_interface_id") or _config.get("selected_interface_id")
frontend_interface_id = _config.get("frontend_interface_id") or _config.get("selected_interface_id")
llm_config = _config.get("llm_config")

# --- 模拟数据和状态 ---

network_interfaces = [
    {"id": "eth0", "name": "eth0 (默认物理网卡)", "ip": "192.168.1.100", "mac": "00:1B:44:11:3A:B7", "status": "connected"},
    {"id": "eth1", "name": "eth1 (内网数据网卡)", "ip": "10.0.0.5", "mac": "00:1B:44:11:3A:B8", "status": "connected"},
    {"id": "wlan0", "name": "wlan0 (无线网络)", "ip": "192.168.0.50", "mac": "A4:C3:F0:99:81:22", "status": "disconnected"},
    {"id": "docker0", "name": "docker0 (虚拟网桥)", "ip": "172.17.0.1", "mac": "02:42:0E:1B:54:11", "status": "connected"}
]

devices_db = []
alert_types = ['区域入侵', '越界检测', '车辆违停', '人员聚集', '烟火检测']
alerts_db = []
