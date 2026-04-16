import asyncio
from sqlalchemy import text
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from models.db import engine

async def migrate():
    async with engine.begin() as conn:
        try:
            await conn.execute(text("ALTER TABLE tasks ADD COLUMN last_processed_time BIGINT DEFAULT 0;"))
            print("Migration successful: added last_processed_time")
        except Exception as e:
            if "duplicate column name" in str(e).lower():
                print("Column already exists, skipping.")
            else:
                print(f"Error during migration: {e}")

if __name__ == "__main__":
    asyncio.run(migrate())
