from sqlalchemy import Column, String, BigInteger
from models.db import Base

class DeviceORM(Base):
    __tablename__ = "devices"
    id = Column(String, primary_key=True, index=True) # 系统内部 ID (UUID)
    device_id = Column(String, unique=True, index=True, nullable=False) # 业务匹配 ID
    name = Column(String, nullable=False)
    ip = Column(String, nullable=False)
    port = Column(String, nullable=False)
    username = Column(String, default="")
    password = Column(String, default="")
    status = Column(String, default="离线")
    session_id = Column(String, default="")
    channels = Column(String, default="[]")
    device_tasks = Column(String, default="[]")
    available_algorithms = Column(String, default="[]")
    algorithms_ability = Column(String, default="[]")
    agents = Column(String, default="[]")  # 设备侧智能体算法快照（JSON 字符串），随设备详情同步

class AlertORM(Base):
    __tablename__ = "alerts"
    id = Column(String, primary_key=True, index=True)
    deviceName = Column(String, index=True)
    alertType = Column(String, index=True)
    time = Column(String)
    # 为 timestamp 创建索引，这是按时间查询和清理 7 天前数据的关键
    timestamp = Column(BigInteger, index=True)
    imageUrl = Column(String, nullable=True)        # 告警大图（整帧）
    imageUrlCrop = Column(String, nullable=True)     # 送检小图（目标裁切），无则为空
    channelid = Column(String, default="", index=True) # 触发通道（device_name），旧数据可能为空
    channelname = Column(String, default="", index=True) # 触发通道（device_name），旧数据可能为空
    remark = Column(String, default="")
    # 告警反馈闭环：'' 待标注 / 'valid' 真实告警 / 'false_positive' 误报
    feedback_status = Column(String, default="", index=True)
    feedback_note = Column(String, default="")        # 标注备注/误报原因
    feedback_time = Column(BigInteger, nullable=True) # 最近一次标注时间（毫秒）
    feedback_submitted = Column(BigInteger, default=0) # 是否已提交后端优化：0 否 / 1 是

class TaskORM(Base):
    __tablename__ = "tasks"
    id = Column(String, primary_key=True, index=True)
    name = Column(String, nullable=False)
    task_type = Column(String, default="警戒分析")
    device_id = Column(String, index=True)
    device_task = Column(String, default="")
    channel = Column(String, default="")
    algorithms = Column(String, default="[]")
    status = Column(String, default="未布控")
    assignee = Column(String, default="")
    priority = Column(String, default="中")
    due_date = Column(BigInteger, nullable=True)
    created_at = Column(BigInteger, nullable=False)
    last_processed_time = Column(BigInteger, default=0)

class TaskTemplateORM(Base):
    """布控任务【参数模板】—— 面板参数快照，可保存 / 套用 / 被智能体引用。

    config 为右侧控制面板 config 的 JSON 字符串快照（前端形状），套用时回填面板；
    task_mode 与面板 taskMode 对齐（smallmodel / agent / combined），event_type 便于按场景归类与匹配报警大图。
    """
    __tablename__ = "task_templates"
    id = Column(String, primary_key=True, index=True)
    name = Column(String, nullable=False)
    task_mode = Column(String, default="smallmodel")
    event_type = Column(String, default="")
    config = Column(String, default="{}")  # 面板 config 快照（JSON 字符串）
    description = Column(String, default="")
    created_at = Column(BigInteger, nullable=False)
    updated_at = Column(BigInteger, index=True, nullable=False)

class LogORM(Base):
    __tablename__ = "logs"
    id = Column(String, primary_key=True, index=True)
    log_id = Column(String, index=True)
    device_name = Column(String, index=True)
    api_path = Column(String)
    parameters = Column(String)
    result = Column(String)
    timestamp = Column(BigInteger, index=True)
    task_name = Column(String, default="")  # 关联的（设备布控）任务名，便于事后定位是哪个任务下发的操作


class FeedbackTaskORM(Base):
    """告警反馈闭环 —— 调优下发运维记录。

    一行 = 一次「提交后端做优化」里，对某个设备布控任务的一次下发结果
    （对应 optimization_service.run_optimization 的一个 group / 一个跳过批次）。
    一次提交（同 batch_id）通常产生多条记录：不同通道任务分别下发。
    """
    __tablename__ = "feedback_tasks"
    id = Column(String, primary_key=True, index=True)
    batch_id = Column(String, index=True)             # 归组同一次提交
    device_name = Column(String, index=True)
    task_name = Column(String, default="")            # 设备布控任务名（跳过批次填设备名/占位）
    channelid = Column(String, default="")              # 该组去重通道，逗号连接
    category = Column(String, default="")             # 大模型任务/小模型任务/小+大任务/-
    case_key = Column(String, default="")             # Case1/Case2/Case3/空
    action = Column(String, default="skipped")        # deployed / skipped
    result = Column(String, default="")               # 结果消息文本
    detail = Column(String, default="")               # 参数变化或 Prompt 摘要
    alerts_snapshot = Column(String, default="[]")    # 该组标注告警快照(JSON 字符串)，供详情翻页
    alert_count = Column(BigInteger, default=0)
    log_id = Column(String, default="")               # 关联 LogORM.log_id，可空
    created_at = Column(BigInteger, index=True)


class ConversationORM(Base):
    __tablename__ = "conversations"
    id = Column(String, primary_key=True, index=True)
    title = Column(String, default="新会话")
    summary = Column(String, default="")  # 本会话滚动记忆/总结，长对话时压缩早期内容并回注为上下文
    created_at = Column(BigInteger, nullable=False)
    updated_at = Column(BigInteger, index=True, nullable=False)


class MessageORM(Base):
    __tablename__ = "messages"
    id = Column(String, primary_key=True, index=True)
    conversation_id = Column(String, index=True, nullable=False)
    role = Column(String, nullable=False)  # user / model
    text = Column(String, default="")
    tables = Column(String, default="")  # 助手回复附带的表格数据（JSON 字符串），用于历史还原
    created_at = Column(BigInteger, index=True, nullable=False)
