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
    agents = Column(String, default="[]")  # 设备侧智能体算法快照（JSON 字符串），随设备详情同步

class AlertORM(Base):
    __tablename__ = "alerts"
    id = Column(String, primary_key=True, index=True)
    deviceName = Column(String, index=True)
    alertType = Column(String, index=True)
    time = Column(String)
    # 为 timestamp 创建索引，这是按时间查询和清理 7 天前数据的关键
    timestamp = Column(BigInteger, index=True)
    imageUrl = Column(String, nullable=True)
    remark = Column(String, default="")

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

class LogORM(Base):
    __tablename__ = "logs"
    id = Column(String, primary_key=True, index=True)
    log_id = Column(String, index=True)
    device_name = Column(String, index=True)
    api_path = Column(String)
    parameters = Column(String)
    result = Column(String)
    timestamp = Column(BigInteger, index=True)


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
