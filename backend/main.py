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

from routers import devices, alerts, network, services, chat, llm, tasks, logs
from models.db import engine, Base, AsyncSessionLocal
from models.orm import AlertORM
import services_manager

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
        await conn.execute(text("PRAGMA journal_mode=WAL;"))
        await conn.execute(text("PRAGMA synchronous=NORMAL;"))
        await conn.execute(text("PRAGMA cache_size=-64000;"))
        
    scheduler.add_job(clean_old_alerts, IntervalTrigger(hours=1), id="clean_old_alerts")
    scheduler.start()
    
    # 启动动态的 WS 和 HTTP 报警服务
    await services_manager.init_services()
    
    yield
    
    # 关闭动态服务
    await services_manager.shutdown_services()
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

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
