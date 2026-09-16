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
        except Exception as e:
            print(f"加载 config.json 失败，使用默认配置: {e}")
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

