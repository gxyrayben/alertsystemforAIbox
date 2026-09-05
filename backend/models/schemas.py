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
    session_id: Optional[str] = ""
    channels: Optional[str] = "[]"
    device_tasks: Optional[str] = "[]"
    available_algorithms: Optional[str] = "[]"
    algorithms_ability: Optional[str] = "[]"
    agents: Optional[str] = "[]"

class AgentCreate(BaseModel):
    """在设备上新建智能体算法的请求体。alarm_type：freeform=描述型，yesno=判断型。"""
    event_id: str
    event_tag: str
    prompt: str
    alarm_type: str = "freeform"
    alarm_condition: Optional[str] = None

class AgentTaskItem(BaseModel):
    """智能体任务(agent_real_task)中关联的单个智能体及其检测区/过滤配置。

    roiPoints：归一化多边形点 [{x,y}]；为空表示全画面检测。
    filter_enable/filter_keywords：仅描述型(freeform)智能体有意义，其余下发时强制关闭。
    """
    event_id: str
    event_tag: str = ""
    alarm_type: str = "freeform"
    prompt: str = ""
    alarm_condition: Optional[str] = None
    filter_enable: bool = False
    filter_keywords: str = ""
    roiPoints: List[dict] = []

class AgentTaskDeploy(BaseModel):
    """纯大模型智能体任务下发请求体（最多关联 4 个智能体）。"""
    channel_device_id: int
    task_name: str
    analysis_interval: int = 5
    agents: List[AgentTaskItem]

class Alert(BaseModel):
    id: Optional[str] = None
    deviceName: str
    alertType: str
    time: str
    timestamp: int
    imageUrl: Optional[str] = None
    imageUrlCrop: Optional[str] = None
    channelid: Optional[str] = ""
    channelname: Optional[str] = ""
    remark: Optional[str] = "暂无备注"
    feedback_status: Optional[str] = ""
    feedback_note: Optional[str] = ""
    feedback_time: Optional[int] = None
    feedback_submitted: Optional[int] = 0

    class Config:
        from_attributes = True

class FeedbackRequest(BaseModel):
    """告警标注请求。status: 'valid' 真实告警 / 'false_positive' 误报。"""
    status: str
    note: Optional[str] = ""

class OptimizationSubmit(BaseModel):
    """提交已标注误报做后端优化。为空则提交全部未提交的已标注误报。"""
    alert_ids: Optional[List[str]] = None


class FeedbackTaskResponse(BaseModel):
    """调优下发运维记录（列表用，不含告警快照明细）。"""
    id: str
    batch_id: str
    device_name: str
    task_name: str = ""
    channelid: str = ""
    category: str = ""
    case_key: str = ""
    action: str
    result: str = ""
    detail: str = ""
    alert_count: int = 0
    log_id: str = ""
    created_at: int

    class Config:
        from_attributes = True


class FeedbackTaskListResponse(BaseModel):
    items: List[FeedbackTaskResponse]
    total: int


class FeedbackTaskDetail(FeedbackTaskResponse):
    """记录详情：附带该次标注告警快照，供前端翻页查看。"""
    alerts: List[dict] = []

class ChatRequest(BaseModel):
    messages: List[dict]
    conversation_id: Optional[str] = None
    device_id: Optional[str] = None

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
    last_processed_time: Optional[int] = None

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
    task_name: Optional[str] = ""

class LogCreate(LogBase):
    pass

class LogResponse(LogBase):
    id: str

    class Config:
        from_attributes = True

class LogListResponse(BaseModel):
    items: List[LogResponse]
    total: int


class MessageResponse(BaseModel):
    id: str
    role: str
    text: str
    tables: List[dict] = []
    created_at: int

    class Config:
        from_attributes = True


class ConversationResponse(BaseModel):
    id: str
    title: str
    summary: str = ""
    created_at: int
    updated_at: int

    class Config:
        from_attributes = True


class ConversationDetail(ConversationResponse):
    messages: List[MessageResponse] = []
