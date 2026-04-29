import asyncio
import uvicorn
import secrets
from fastapi import FastAPI, WebSocket, Request, HTTPException, Depends
from fastapi.security import HTTPBasic, HTTPBasicCredentials
import database
from routers.alerts import receive_http_alarm

http_server_task = None
http_server = None

ws_server_task = None
ws_server = None

security = HTTPBasic()

def check_auth(credentials: HTTPBasicCredentials, service_type: str):
    config = database.current_services_config.get(service_type, {})
    expected_user = config.get("username", "")
    expected_pass = config.get("password", "")
    
    is_user_ok = secrets.compare_digest(credentials.username, expected_user)
    is_pass_ok = secrets.compare_digest(credentials.password, expected_pass)
    
    if not (is_user_ok and is_pass_ok):
        raise HTTPException(
            status_code=401,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Basic"},
        )

async def start_http_service():
    global http_server_task, http_server
    config = database.current_services_config.get("http", {})
    if not config.get("enabled", False):
        return

    app = FastAPI(title="HTTP Alarm Service")
    path = config.get("path", "/api/http/alarms")
    
    # 动态构建依赖项
    dependencies = []
    if config.get("auth_enabled", False):
        dependencies.append(Depends(lambda cred: check_auth(cred, "http")))

    app.post(path, dependencies=dependencies)(receive_http_alarm)
    
    port = int(config.get("port", 80))
    print(f"Starting dynamic HTTP service on port {port} at {path} (Auth: {config.get('auth_enabled')})...")
    
    uvicorn_config = uvicorn.Config(app, host="0.0.0.0", port=port, log_level="info")
    http_server = uvicorn.Server(uvicorn_config)
    
    loop = asyncio.get_running_loop()
    http_server_task = loop.create_task(http_server.serve())

async def stop_http_service():
    global http_server_task, http_server
    if http_server:
        http_server.should_exit = True
        await asyncio.sleep(0.5)
    http_server = None
    http_server_task = None

async def start_ws_service():
    global ws_server_task, ws_server
    config = database.current_services_config.get("ws", {})
    if not config.get("enabled", False):
        return

    app = FastAPI(title="WS Alarm Service")
    path = config.get("path", "/api/ws/alarms")
    
    @app.websocket(path)
    async def websocket_endpoint(websocket: WebSocket):
        # WS 鉴权处理
        if config.get("auth_enabled", False):
            # 简单的 Token 鉴权（由于 WS 握手通常通过 Query 参数或 Header）
            # 这里演示通过 Query 参数鉴权: ?user=xxx&pass=yyy
            user = websocket.query_params.get("user")
            pwd = websocket.query_params.get("pass")
            if user != config.get("username") or pwd != config.get("password"):
                await websocket.close(code=1008) # Policy Violation
                return

        await websocket.accept()
        try:
            while True:
                data = await websocket.receive_text()
                await websocket.send_text(f"ACK: {data}")
        except Exception:
            pass
            
    port = int(config.get("port", 8080))
    print(f"Starting dynamic WS service on port {port} at {path} (Auth: {config.get('auth_enabled')})...")
    
    uvicorn_config = uvicorn.Config(app, host="0.0.0.0", port=port, log_level="info")
    ws_server = uvicorn.Server(uvicorn_config)
    loop = asyncio.get_running_loop()
    ws_server_task = loop.create_task(ws_server.serve())

async def stop_ws_service():
    global ws_server_task, ws_server
    if ws_server:
        ws_server.should_exit = True
        await asyncio.sleep(0.5)
    ws_server = None
    ws_server_task = None

async def reload_http_service():
    await stop_http_service()
    await start_http_service()

async def reload_ws_service():
    await stop_ws_service()
    await start_ws_service()

async def init_services():
    await start_http_service()
    await start_ws_service()

async def shutdown_services():
    await stop_http_service()
    await stop_ws_service()
