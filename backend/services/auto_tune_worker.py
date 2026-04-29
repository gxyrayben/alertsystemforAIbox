import asyncio
from sqlalchemy.future import select
from models.db import AsyncSessionLocal
from models.orm import TaskORM
from services.task_service import perform_auto_tune_workflow

async def run_auto_tune_cycle():
    """
    Background worker cycle that scans for active tuning tasks.
    """
    async with AsyncSessionLocal() as session:
        # Find all active "Prompt调优" tasks
        query = select(TaskORM).where(
            TaskORM.task_type == "Prompt调优",
            TaskORM.status.in_(["布控中", "运行中", "未布控"])
        )
        result = await session.execute(query)
        tasks = result.scalars().all()

        for task in tasks:
            try:
                print(f"[AutoTune Worker] Processing task {task.id} ({task.name})...")
                success, result_data = await perform_auto_tune_workflow(session, task, alert_limit=10)
                if success:
                    print(f"[AutoTune Worker] Task {task.id} success: {result_data}")
                else:
                    print(f"[AutoTune Worker] Task {task.id} skipped: {result_data}")
            except Exception as e:
                print(f"[AutoTune Worker] Error processing task {task.id}: {e}")
