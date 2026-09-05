from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager
import os
import time
from sqlalchemy import text
from sqlalchemy.future import select
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from routers import devices, alerts, network, services, chat, llm, tasks, logs, conversations, feedback
from models.db import engine, Base, AsyncSessionLocal
from models.orm import AlertORM
from services import alarm_services
from services.auto_tune_worker import run_auto_tune_cycle

scheduler = AsyncIOScheduler()

async def clean_old_alerts():
    # 保留 7 天的数据
    cutoff_timestamp = int(time.time() * 1000) - (7 * 24 * 3600 * 1000)
    async with AsyncSessionLocal() as session:
        query = select(AlertORM).where(AlertORM.timestamp < cutoff_timestamp)
        result = await session.execute(query)
        old_alerts = result.scalars().all()
        
        deleted_count = 0
        for alert in old_alerts:
            if alert.imageUrl:
                filepath = f".{alert.imageUrl}"
                if os.path.exists(filepath):
                    try:
                        os.remove(filepath)
                    except Exception as e:
                        print(f"Failed to delete image {filepath}: {e}")
            
            await session.delete(alert)
            deleted_count += 1
            
        if deleted_count > 0:
            await session.commit()
            print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] 自动清理机制：已成功清理 {deleted_count} 条过期预警数据及其图片。")

@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # 兼容旧库：messages 表补充 tables 列（存储助手回复的表格数据用于历史还原）
        cols = [row[1] for row in (await conn.execute(text("PRAGMA table_info(messages)"))).fetchall()]
        if "tables" not in cols:
            await conn.execute(text("ALTER TABLE messages ADD COLUMN tables TEXT DEFAULT ''"))
        # 兼容旧库：conversations 表补充 summary 列（本会话滚动记忆/总结）
        conv_cols = [row[1] for row in (await conn.execute(text("PRAGMA table_info(conversations)"))).fetchall()]
        if "summary" not in conv_cols:
            await conn.execute(text("ALTER TABLE conversations ADD COLUMN summary TEXT DEFAULT ''"))
        # 兼容旧库：devices 表补充 agents 列（设备侧智能体算法快照）
        dev_cols = [row[1] for row in (await conn.execute(text("PRAGMA table_info(devices)"))).fetchall()]
        if "agents" not in dev_cols:
            await conn.execute(text("ALTER TABLE devices ADD COLUMN agents TEXT DEFAULT '[]'"))
        if "algorithms_ability" not in dev_cols:
            await conn.execute(text("ALTER TABLE devices ADD COLUMN algorithms_ability TEXT DEFAULT '[]'"))
        # 兼容旧库：alerts 表补充告警反馈闭环所需列
        alert_cols = [row[1] for row in (await conn.execute(text("PRAGMA table_info(alerts)"))).fetchall()]
        _alert_migrations = {
            "imageUrlCrop": "ALTER TABLE alerts ADD COLUMN imageUrlCrop TEXT",
            "channelid": "ALTER TABLE alerts ADD COLUMN channelid TEXT DEFAULT ''",
            "channelname": "ALTER TABLE alerts ADD COLUMN channelname TEXT DEFAULT ''",
            "feedback_status": "ALTER TABLE alerts ADD COLUMN feedback_status TEXT DEFAULT ''",
            "feedback_note": "ALTER TABLE alerts ADD COLUMN feedback_note TEXT DEFAULT ''",
            "feedback_time": "ALTER TABLE alerts ADD COLUMN feedback_time BIGINT",
            "feedback_submitted": "ALTER TABLE alerts ADD COLUMN feedback_submitted BIGINT DEFAULT 0",
        }
        for col, ddl in _alert_migrations.items():
            if col not in alert_cols:
                await conn.execute(text(ddl))
        # 兼容旧库：logs 表补充 task_name 列（关联下发任务名）
        log_cols = [row[1] for row in (await conn.execute(text("PRAGMA table_info(logs)"))).fetchall()]
        if "task_name" not in log_cols:
            await conn.execute(text("ALTER TABLE logs ADD COLUMN task_name TEXT DEFAULT ''"))
        await conn.execute(text("PRAGMA journal_mode=WAL;"))
        await conn.execute(text("PRAGMA synchronous=NORMAL;"))
        await conn.execute(text("PRAGMA cache_size=-64000;"))
        
    scheduler.add_job(clean_old_alerts, IntervalTrigger(hours=1), id="clean_old_alerts")
    scheduler.add_job(run_auto_tune_cycle, IntervalTrigger(seconds=60), id="run_auto_tune_cycle")
    scheduler.start()
    
    # 启动动态的 WS 和 HTTP 报警服务
    await alarm_services.init_services()
    
    yield
    
    # 关闭动态服务
    await alarm_services.shutdown_services()
    scheduler.shutdown()

app = FastAPI(title="安防综合管理平台 API", lifespan=lifespan)

# 启用 CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

os.makedirs("uploads", exist_ok=True)
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")

# 注册路由
app.include_router(devices.router)
app.include_router(alerts.router)
app.include_router(network.router)
app.include_router(services.router)
app.include_router(chat.router)
app.include_router(llm.router)
app.include_router(tasks.router)
app.include_router(logs.router)
app.include_router(conversations.router)
app.include_router(feedback.router)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
