from fastapi import APIRouter
import database
from models.schemas import ServicesConfig
from services import alarm_services

router = APIRouter(prefix="/services", tags=["services"])

@router.get("/config", response_model=ServicesConfig)
async def get_services_config():
    # tls 块存在 config.json 的顶层字段里（主服务 :8000 也读它），此处合并返回给前端统一编辑
    return {**(database.current_services_config or {}), "tls": database.tls_config}

@router.post("/config")
async def update_services_config(config: ServicesConfig):
    """保存报警接收（HTTP/WS）配置与 TLS（HTTPS/WSS）开关。

    tls 是【启动期】参数：报警接收两个端口会就地在用新证书重启；
    主服务(:8000) 同样由该开关决定，但已运行的进程需手动重启后端才能生效（日志会提示）。
    """
    payload = config.dict()
    tls = payload.pop("tls", None)
    old_config = dict(database.current_services_config or {})
    old_tls = dict(database.tls_config or {})
    database.current_services_config = payload
    tls_changed = False
    if tls is not None:
        database.tls_config.update(tls)
        tls_changed = any(old_tls.get(k) != database.tls_config.get(k)
                          for k in ("enabled", "cert_file", "key_file"))
    database.save_config()

    if tls_changed:
        # 证书/开关变化：两个报警接收端口都要按新配置重建（uvicorn 的 ssl 参数只能在启动时给定）
        await alarm_services.reload_http_service()
        await alarm_services.reload_ws_service()
        if bool(old_tls.get("enabled")) != bool(database.tls_config.get("enabled")):
            print("[TLS] 主服务(:8000) 的 HTTP/HTTPS 开关已变更，需重启后端进程后生效。")
    else:
        # Check if we need to reload WS
        if old_config.get("ws") != database.current_services_config.get("ws"):
            await alarm_services.reload_ws_service()

        # Check if we need to reload HTTP
        if old_config.get("http") != database.current_services_config.get("http"):
            await alarm_services.reload_http_service()

    return {**database.current_services_config, "tls": database.tls_config}
