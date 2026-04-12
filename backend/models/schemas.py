from pydantic import BaseModel
from typing import List, Optional

class Device(BaseModel):
    id: Optional[str] = None
    device_id: str  # 新增：用于协议匹配的业务 ID
    name: str
    ip: str
    port: str
    username: Optional[str] = ""
    password: Optional[str] = ""
    status: Optional[str] = "离线"

class Alert(BaseModel):
    id: Optional[str] = None
    deviceName: str
    alertType: str
    time: str
    timestamp: int
    imageUrl: Optional[str] = None
    remark: Optional[str] = "暂无备注"

class ChatRequest(BaseModel):
    messages: List[dict]

class AIAnalyzeRequest(BaseModel):
    alert_id: str

class ServiceConfig(BaseModel):
    enabled: bool
    port: str
    path: str
    auth_enabled: Optional[bool] = False
    username: Optional[str] = ""
    password: Optional[str] = ""

class ServicesConfig(BaseModel):
    ws: ServiceConfig
    http: ServiceConfig

class NetworkConfigUpdate(BaseModel):
    backend_interface_id: str
    frontend_interface_id: str

class LLMConfig(BaseModel):
    provider: str
    model_name: str
    base_url: str
    api_key: str

class TaskBase(BaseModel):
    name: str
    task_type: str = "警戒分析"
    device_id: str
    device_task: str = ""
    channel: str = ""
    algorithms: str = "[]"
    status: str = "未布控"
    assignee: str = ""
    priority: str = "中"
    due_date: Optional[int] = None

class TaskCreate(TaskBase):
    pass

class TaskUpdate(BaseModel):
    name: Optional[str] = None
    task_type: Optional[str] = None
    device_id: Optional[str] = None
    device_task: Optional[str] = None
    channel: Optional[str] = None
    algorithms: Optional[str] = None
    status: Optional[str] = None
    assignee: Optional[str] = None
    priority: Optional[str] = None
    due_date: Optional[int] = None

class TaskResponse(TaskBase):
    id: str
    created_at: int
    
    class Config:
        from_attributes = True

class LogBase(BaseModel):
    log_id: str
    device_name: str
    api_path: str
    parameters: str
    result: str
    timestamp: int

class LogCreate(LogBase):
    pass

class LogResponse(LogBase):
    id: str

    class Config:
        from_attributes = True

class LogListResponse(BaseModel):
    items: List[LogResponse]
    total: int
