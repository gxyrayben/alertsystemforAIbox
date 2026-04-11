# Task Management Feature Design

## Objective
Implement a new "任务管理" (Task Management) feature for the AlertSystem, allowing users to track, assign, and manage security-related tasks based on the provided UI mockup.

## Architecture
- **Backend**: FastAPI with SQLAlchemy (ORM) & Pydantic (Schemas).
- **Frontend**: Svelte components using Tailwind CSS for styling, split into a main table view and a modal for creation/editing.

## Data Model (Backend)

### `TaskORM` (SQLAlchemy)
Table Name: `tasks`
- `id`: String (UUID or specific format like TASK-1000), Primary Key, Index
- `name`: String (Task Name, e.g., "测试安防任务 1")
- `task_type`: String (Task Type, e.g., "区域告警", "人员布控", "设备巡检")
- `device_id`: String (Related Device ID, links to `DeviceORM.device_id`)
- `status`: String (Task Status, using security terminology: "未布控", "布控中", "已完成")
- `assignee`: String (Assignee name - hidden in main table but editable)
- `priority`: String (Priority: "高", "中", "低" - hidden in main table but editable)
- `due_date`: BigInteger (Timestamp - hidden in main table but editable)
- `created_at`: BigInteger (Timestamp)

### Pydantic Schemas (`backend/models/schemas.py`)
- `TaskBase`: Base schema containing `name`, `task_type`, `device_id`, `status`, `assignee`, `priority`, `due_date`.
- `TaskCreate`: Schema for creating a task.
- `TaskUpdate`: Schema for updating a task (all fields optional).
- `TaskResponse`: Schema representing the returned task, including `id` and `created_at`.

## API Endpoints (`backend/routers/tasks.py`)
- `GET /api/tasks`: List tasks with pagination (e.g., `?page=1&size=10`).
- `POST /api/tasks`: Create a new task.
- `PUT /api/tasks/{task_id}`: Update an existing task.
- `DELETE /api/tasks/{task_id}`: Delete a task.

*(Remember to include `tasks` router in `backend/main.py`)*

## Frontend UI (Svelte)

### Navigation (`Sidebar.svelte`)
- Add a new menu item: `{ id: 'tasks', icon: 'ClipboardList', label: '任务管理' }`.

### `Tasks.svelte` (Main View Component)
- **Header**: Title "任务管理".
- **Action Bar**: Displays total task count ("共找到 XX 个任务") and a primary blue button "+ 新建任务".
- **Data Table**:
  - Columns: 任务ID (Task ID), 任务名称 (Task Name), 任务类型 (Task Type), 关联设备 (Related Device), 任务状态 (Task Status with colored badges), 操作 (Actions).
  - Actions: Edit icon (blue), Delete icon (red).
- **Footer**: Pagination controls ("第 1 页 / 共 X 页", Prev `<` / Next `>`).
- **State Management**: Handles fetching from `/api/tasks` and controls the visibility of the modal.

### `TaskModal.svelte` (Form Component)
- Receives a `task` object as a prop (null for creation, populated for editing).
- **Form Fields**:
  - 任务名称 (Task Name) - Text Input
  - 任务类型 (Task Type) - Select ("区域告警", "人员布控", "设备巡检")
  - 关联设备 (Related Device) - Select (fetched from `/api/devices`)
  - 任务状态 (Task Status) - Select ("未布控", "布控中", "已完成")
  - 负责人 (Assignee) - Text Input
  - 优先级 (Priority) - Select ("高", "中", "低")
  - 截止时间 (Due Date) - Date Picker / Text Input
- **Actions**: "取消" (Cancel) and "保存" (Save). Emits `save` and `close` events to parent `Tasks.svelte`.

## Error Handling & Validation
- **Backend**: Return standard HTTP 404 for missing tasks on update/delete. Ensure robust JSON parsing.
- **Frontend**: Validate required fields (name, type, status) before emitting the save event. Show simple `alert()` for errors.

## Testing Strategy
- Verify creating a task shows it immediately in the table.
- Verify editing a task updates the backend and reflects changes in the UI.
- Verify pagination works when task count exceeds page size.
- Verify deleting a task removes it.