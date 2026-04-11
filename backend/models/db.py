from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.orm import declarative_base

DB_FILE = "alertsystem.db"
DB_URL = f"sqlite+aiosqlite:///{DB_FILE}"

# 创建异步引擎
engine = create_async_engine(
    DB_URL,
    echo=False,
    # 允许不同线程访问，因为 FastAPI 可能会用多个 worker/线程
    connect_args={"check_same_thread": False}
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine, autoflush=False, expire_on_commit=False
)

Base = declarative_base()

async def get_db():
    async with AsyncSessionLocal() as session:
        yield session
