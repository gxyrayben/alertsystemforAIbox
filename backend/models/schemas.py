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

class SmallModelTaskDeploy(BaseModel):
    """纯小模型（算法仓）任务下发请求体。

    面板/对话下发共用；threshold 为设备 monitor 的单一阈值（前端按 yoloTarget 选好后传入）。
    roiPoints：归一化多边形点 [{x,y}]，为空表示全画面检测。
    小模型/小+大为【实时分析】，无分析间隔/抽帧间隔概念（仅智能体任务有分析间隔）。
    """
    channel_device_id: int
    task_name: str
    event_type: str
    algo_cabin_name: str
    version: str = "V2.0.0"
    target_types: Optional[List[str]] = None
    threshold: float = 0.3
    target_max: int = 1
    target_min: int = 0
    duration: int = 3
    cooldown: int = 600
    roiPoints: List[dict] = []

class CombinedTaskDeploy(SmallModelTaskDeploy):
    """小+大任务下发请求体：在纯小模型基础上追加二次大模型（agentLLMParam）与扩图策略。

    target_expand：扩图策略 {top,bottom,left,right}（仅小+大生效）；
    agent_id 必填，其余智能体字段缺省沿用设备端该智能体自身配置。
    """
    target_expand: Optional[dict] = None
    agent_id: str
    event_tag: str = ""
    alarm_type: str = "freeform"
    prompt: str = ""
    alarm_condition: Optional[str] = None
    filter_enable: bool = False
    filter_keywords: str = ""

class WarehouseAlgorithmItem(BaseModel):
    """一个任务里的【单个算法仓算法】(= monitor 里的一条 rulesParams)。

    kind：'small' 纯小模型 / 'combined' 小+大（挂二次大模型 agentLLMParam）。
    算法身份 = (algo_cabin_name, event_type)；同仓 event_type 不得重复（设备按仓覆盖规则）。
    roiPoints：本算法自己的归一化多边形点 [{x,y}]，为空表示全画面检测（逐算法各自一个 ROI）。
    combined 专用：agent_id 必填，其余智能体字段缺省沿用设备端该智能体自身配置；target_expand 为扩图策略；
    filter_enable/filter_keywords 仅描述型(freeform)智能体有意义，其余下发时强制关闭。
    """
    kind: str = "small"
    event_type: str
    algo_cabin_name: str
    version: str = "V2.0.0"
    target_types: Optional[List[str]] = None
    threshold: float = 0.3
    target_max: int = 1
    target_min: int = 0
    duration: int = 3
    cooldown: int = 600
    roiPoints: List[dict] = []
    # combined 专用
    agent_id: Optional[str] = None
    event_tag: str = ""
    alarm_type: str = "freeform"
    prompt: str = ""
    alarm_condition: Optional[str] = None
    filter_enable: bool = False
    filter_keywords: str = ""
    target_expand: Optional[dict] = None

class WarehouseTaskDeploy(BaseModel):
    """算法仓任务【多算法】统一下发请求体（纯小模型 / 小+大 / 二者混合，一次提交多条算法）。

    一个任务可挂多条算法：同一 algo_cabin_name 组成一条 monitor 的多条 rulesParams，
    跨 algo_cabin_name 则是共享同一 monitor_id 的多条 monitor（详见 device_service.deploy_warehouse_task_multi）。
    小模型/小+大为【实时分析】，无分析间隔/抽帧间隔概念。
    """
    channel_device_id: int
    task_name: str
    algorithms: List[WarehouseAlgorithmItem]


class TaskEnableUpdate(BaseModel):
    """任务列表『是否启用』开关的请求体：切换设备任务的 enable 使能位。"""
    enable: bool


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

class TaskTemplateBase(BaseModel):
    """布控任务参数模板。config 为右侧控制面板 config 的快照（API 层是 dict，ORM 存 JSON 字符串）。"""
    name: str
    task_mode: str = "smallmodel"
    event_type: str = ""
    config: dict = {}
    description: str = ""

class TaskTemplateCreate(TaskTemplateBase):
    pass

class TaskTemplateUpdate(BaseModel):
    name: Optional[str] = None
    task_mode: Optional[str] = None
    event_type: Optional[str] = None
    config: Optional[dict] = None
    description: Optional[str] = None

class TaskTemplateResponse(TaskTemplateBase):
    id: str
    created_at: int
    updated_at: int

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
