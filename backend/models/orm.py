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
    task_type = Column(String, default="区域告警")
    device_id = Column(String, index=True)
    status = Column(String, default="未布控")
    assignee = Column(String, default="")
    priority = Column(String, default="中")
    due_date = Column(BigInteger, nullable=True)
    created_at = Column(BigInteger, nullable=False)
