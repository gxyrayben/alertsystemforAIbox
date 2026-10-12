"""临时调试脚本：只读设备上【已被接受】的 monitor 原文，用于对照下发 payload 的字段差异。

只调用 /intelli_manager/monitor_list（只读），不做任何写入；排查完即可删除。
"""
import asyncio
import json

import httpx
from sqlalchemy import select

from models.db import AsyncSessionLocal
from models.orm import DeviceORM
from services.device_service import DeviceService


async def main():
    async with AsyncSessionLocal() as db:
        dev = (await db.execute(select(DeviceORM).where(DeviceORM.name == "Dev01"))).scalar_one()
        async with httpx.AsyncClient(timeout=20) as client:
            for task_id, channel in (("14", 19), ("7", 11)):
                mons = await DeviceService.list_task_monitors(
                    client, dev, db, task_id=task_id, channel_device_id=channel)
                print(f"===== task {task_id} / channel {channel}: {len(mons)} 条 monitor =====")
                print(json.dumps(mons, ensure_ascii=False, indent=1))


asyncio.run(main())
