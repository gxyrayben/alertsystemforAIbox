# Automated Prompt Tuning Design Spec

## 1. Overview
This feature implements a continuous background job that automatically tunes the prompt of an algorithm running on an AI security camera. It triggers when a user creates a "Prompt调优" (Prompt Tuning) task in the Task Management module. The background process monitors the stream of alerts from the targeted device and algorithm, gathers batches of 5 recent alerts, and consults an LLM to determine if any are false positives. If so, it updates the prompt on the device automatically.

## 2. Architecture & Database Changes
- **Data Model**: `TaskORM` will receive a new field `last_processed_time` (BigInteger) to record the timestamp of the latest alert that has already been analyzed. By default, this is initialized to the task's creation timestamp.
- **Background Worker**: A global asynchronous scheduling loop using `asyncio` inside the FastAPI `lifespan` event (`backend/main.py`). The loop runs every 60 seconds.

## 3. Workflow Details
1. **Polling Execution**: Every 60 seconds, the background worker queries for all `TaskORM` rows where `task_type == "Prompt调优"` and `status == "布控中"`.
2. **Matching Alerts**: For each active task:
    - Get the device name from `DeviceORM` using `task.device_id`.
    - Extract the target algorithm name from `task.algorithms` (e.g., `algorithms[0]`).
    - Query `AlertORM` for the 5 newest alerts where:
        - `deviceName == <device_name>`
        - `alertType == <algorithm>`
        - `imageUrl IS NOT NULL`
        - `timestamp > task.last_processed_time`
3. **Threshold Check**: If fewer than 5 alerts are found, skip to the next task (wait for more alerts).
4. **Device Interaction**: If 5 alerts are found:
    - Establish a session with the device and fetch the current prompt for the task/algorithm (`GET /intelli_manager/task_list`).
5. **LLM Evaluation**:
    - Encode the 5 alert images in Base64.
    - Submit the 5 images alongside the current prompt to the configured multi-modal LLM.
    - Ask the LLM: "Review these 5 recent alerts. Do they contain false positives? If so, provide an optimized prompt that retains the core instructions while excluding the false positive characteristics."
6. **Prompt Update**:
    - If the LLM indicates `is_false_positive == true` and provides a new prompt, update the task's prompt on the device via `PUT /intelli_manager/task`.
7. **Cursor Update**:
    - Regardless of whether the prompt was updated (as long as the LLM successfully evaluated the batch), update the task's `last_processed_time` to the highest timestamp among the 5 analyzed alerts to prevent re-evaluating them.

## 4. Error Handling
- **Device Offline/Auth Failure**: Skip processing for this task in the current loop. `last_processed_time` remains unchanged.
- **LLM Timeout/Failure**: Log the error and skip. The same 5 alerts will be re-attempted in the next 60-second cycle.
- **Missing Image Files**: If the image file referenced in the database does not exist on disk, filter it out or treat it as a failure (skip to next cycle).

## 5. Security & Performance
- **Database Indexing**: The `AlertORM.timestamp` field is already indexed, allowing efficient querying for `timestamp > last_processed_time`.
- **Concurrent Connections**: Wait times for HTTP and LLM requests should not block the main FastAPI thread; they will be executed asynchronously.

## 6. Implementation Scope
- Update `backend/models/orm.py` and `backend/models/schemas.py`.
- Create the background worker logic in a new file `backend/services/auto_tune_worker.py` or within `backend/main.py`.
- Update task creation logic (`POST /api/tasks`) to set `status` to "布控中" and initialize `last_processed_time` for "Prompt调优" tasks.
- Modify the DB initialization (alembic/migrations or table recreation).
