from datetime import datetime
import json
import os
from models.schemas import Device, Alert

CONFIG_FILE = "config.json"

# 服务端 TLS（HTTPS/WSS）默认配置：enabled=False 时主服务与报警接收端口都仍走 HTTP/WS。
# cert_file/key_file 相对 backend/ 工作目录（与 uploads/ 同口径），也可写绝对路径。
DEFAULT_TLS_CONFIG = {
    "enabled": False,
    "cert_file": "certs/server.crt",
    "key_file": "certs/server.key",
}

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
        "tls": dict(DEFAULT_TLS_CONFIG),
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
        "tls": tls_config,
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
# 服务端 TLS：与默认值合并，保证老 config.json（无 tls 字段）也能取到 cert/key 默认路径
tls_config = {**DEFAULT_TLS_CONFIG, **(_config.get("tls") or {})}
backend_interface_id = _config.get("backend_interface_id") or _config.get("selected_interface_id")
frontend_interface_id = _config.get("frontend_interface_id") or _config.get("selected_interface_id")
llm_config = _config.get("llm_config")


def tls_ssl_kwargs() -> dict:
    """uvicorn 的 SSL 启动参数：tls.enabled 且证书齐备时返回 {ssl_certfile, ssl_keyfile}，否则 {}（回落 HTTP）。

    主服务(:8000) 与报警接收(HTTP/WS) 共用这一份判定，保证"二选一开关"语义一致。
    证书缺失时只告警、不抛异常：服务仍能以 HTTP 正常启动，避免整个进程起不来。
    """
    if not tls_config.get("enabled"):
        return {}
    cert = (tls_config.get("cert_file") or "").strip()
    key = (tls_config.get("key_file") or "").strip()
    missing = [p for p in (cert, key) if not p or not os.path.exists(p)]
    if missing:
        print(f"[TLS] 已启用 HTTPS，但证书文件不存在：{missing} —— 本次回落 HTTP。"
              f"可执行 `python tools/gen_self_signed_cert.py` 生成自签证书。")
        return {}
    return {"ssl_certfile": cert, "ssl_keyfile": key}


