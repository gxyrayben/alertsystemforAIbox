# Task Management Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement a detailed task workflow management feature for the security management platform.

**Architecture:** Backend API in FastAPI (SQLAlchemy + Pydantic). Frontend in Svelte with a main Tasks view and a TaskModal for CRUD operations.

**Tech Stack:** FastAPI, SQLAlchemy, Pydantic, Svelte, Tailwind CSS.

---

### Task 1: Backend Data Models (ORM & Schemas)

**Files:**
- Modify: `backend/models/orm.py`
- Modify: `backend/models/schemas.py`

- [ ] **Step 1: Add TaskORM to ORM models**

```python
# In backend/models/orm.py
# Add underneath AlertORM class

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
```

- [ ] **Step 2: Add Task Schemas to schemas.py**

```python
# In backend/models/schemas.py
from typing import Optional

# Add the following schemas:

class TaskBase(BaseModel):
    name: str
    task_type: str = "区域告警"
    device_id: str
    status: str = "未布控"
    assignee: str = ""
    priority: str = "中"
    due_date: Optional[int] = None

class TaskCreate(TaskBase):
    pass

class TaskUpdate(BaseModel):
    name: Optional[str] = None
    task_type: Optional[str] = None
    device_id: Optional[str] = None
    status: Optional[str] = None
    assignee: Optional[str] = None
    priority: Optional[str] = None
    due_date: Optional[int] = None

class TaskResponse(TaskBase):
    id: str
    created_at: int
    
    class Config:
        from_attributes = True
```

- [ ] **Step 3: Commit**

```bash
git add backend/models/orm.py backend/models/schemas.py
git commit -m "feat: add task database models and schemas"
```

### Task 2: Backend API Endpoints (tasks.py)

**Files:**
- Create: `backend/routers/tasks.py`
- Modify: `backend/main.py`

- [ ] **Step 1: Create tasks router**

```python
# In backend/routers/tasks.py
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import func
from typing import List
import uuid
import time

from models.db import get_db
from models.orm import TaskORM
from models.schemas import TaskCreate, TaskUpdate, TaskResponse

router = APIRouter(prefix="/api/tasks", tags=["tasks"])

@router.get("", response_model=dict)
async def list_tasks(page: int = Query(1, ge=1), size: int = Query(10, ge=1), db: AsyncSession = Depends(get_db)):
    offset = (page - 1) * size
    
    total_query = select(func.count()).select_from(TaskORM)
    total_result = await db.execute(total_query)
    total = total_result.scalar()

    query = select(TaskORM).order_by(TaskORM.created_at.desc()).offset(offset).limit(size)
    result = await db.execute(query)
    tasks = result.scalars().all()
    
    return {"total": total, "tasks": tasks}

@router.post("", response_model=TaskResponse)
async def create_task(task: TaskCreate, db: AsyncSession = Depends(get_db)):
    task_id = f"TASK-{str(uuid.uuid4())[:8].upper()}"
    new_task = TaskORM(
        id=task_id,
        **task.model_dump(),
        created_at=int(time.time() * 1000)
    )
    db.add(new_task)
    await db.commit()
    await db.refresh(new_task)
    return new_task

@router.put("/{task_id}", response_model=TaskResponse)
async def update_task(task_id: str, task_update: TaskUpdate, db: AsyncSession = Depends(get_db)):
    query = select(TaskORM).where(TaskORM.id == task_id)
    result = await db.execute(query)
    task_obj = result.scalars().first()
    if not task_obj:
        raise HTTPException(status_code=404, detail="Task not found")
        
    update_data = task_update.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(task_obj, key, value)
        
    await db.commit()
    await db.refresh(task_obj)
    return task_obj

@router.delete("/{task_id}")
async def delete_task(task_id: str, db: AsyncSession = Depends(get_db)):
    query = select(TaskORM).where(TaskORM.id == task_id)
    result = await db.execute(query)
    task_obj = result.scalars().first()
    if not task_obj:
        raise HTTPException(status_code=404, detail="Task not found")
        
    await db.delete(task_obj)
    await db.commit()
    return {"message": "Task deleted"}
```

- [ ] **Step 2: Register router in main.py**

```python
# In backend/main.py
# Add the import and include_router

from routers import devices, alerts, network, services, chat, llm, tasks

# ... further down where routes are registered ...
app.include_router(tasks.router)
```

- [ ] **Step 3: Commit**

```bash
git add backend/routers/tasks.py backend/main.py
git commit -m "feat: add CRUD endpoints for tasks"
```

### Task 3: Frontend Navigation and Component Scaffolding

**Files:**
- Modify: `frontend/src/components/Sidebar.svelte`
- Create: `frontend/src/components/Tasks.svelte`
- Modify: `frontend/src/App.svelte`

- [ ] **Step 1: Add Tasks to Sidebar.svelte**

```svelte
// In frontend/src/components/Sidebar.svelte
// Update the menuItems array:

    const menuItems = [
        { id: 'devices', icon: 'Server', label: '设备接入管理' },
        { id: 'tasks', icon: 'ClipboardList', label: '任务管理' },
        { id: 'alerts', icon: 'AlertTriangle', label: '预警管理' },
        { id: 'services', icon: 'Settings', label: '服务管理' },
        { id: 'network', icon: 'Network', label: '网络配置' },
        { id: 'llm', icon: 'Cpu', label: '大模型配置' },
        { id: 'sessions', icon: 'MessageSquare', label: '会话管理' }
    ];
```

- [ ] **Step 2: Scaffold Tasks.svelte**

```svelte
<!-- In frontend/src/components/Tasks.svelte -->
<script>
    export let API_BASE = 'http://localhost:8000';
</script>

<div class="h-full flex flex-col bg-slate-100 p-6 overflow-hidden">
    <h2 class="text-2xl font-bold text-slate-800 mb-6">任务管理</h2>
    <div class="bg-white rounded-xl shadow-sm border border-slate-200 flex-1 flex flex-col">
        <div class="p-4 border-b border-slate-200 flex justify-between items-center">
            <span class="text-slate-600">共找到 0 个任务</span>
            <button class="bg-blue-600 hover:bg-blue-700 text-white px-4 py-2 rounded font-medium flex items-center transition-colors">
                <span class="mr-2">+</span> 新建任务
            </button>
        </div>
        <div class="flex-1 p-8 flex items-center justify-center text-slate-400">
            <!-- Table placeholder -->
            Loading...
        </div>
    </div>
</div>
```

- [ ] **Step 3: Register Tasks in App.svelte**

```svelte
// In frontend/src/App.svelte
// Import Tasks and add it to the view rendering
import Tasks from './components/Tasks.svelte';

// ... inside the <main> block, add an {#if} condition for 'tasks'
        {#if activeMenu === 'devices'}
            <Devices {API_BASE} />
        {:else if activeMenu === 'tasks'}
            <Tasks {API_BASE} />
        {:else if activeMenu === 'alerts'}
```

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/Sidebar.svelte frontend/src/components/Tasks.svelte frontend/src/App.svelte
git commit -m "feat: scaffold Tasks component and add to sidebar"
```

### Task 4: Frontend Task Modal Component

**Files:**
- Create: `frontend/src/components/TaskModal.svelte`

- [ ] **Step 1: Create TaskModal.svelte**

```svelte
<!-- In frontend/src/components/TaskModal.svelte -->
<script>
    import { createEventDispatcher } from 'svelte';
    
    export let task = null; // null means create new
    export let devices = [];
    
    const dispatch = createEventDispatcher();
    
    // Initial state
    let formData = task ? { ...task } : {
        name: '',
        task_type: '区域告警',
        device_id: '',
        status: '未布控',
        assignee: '',
        priority: '中',
        due_date: ''
    };
    
    const taskTypes = ['区域告警', '人员布控', '设备巡检'];
    const statuses = ['未布控', '布控中', '已完成'];
    const priorities = ['高', '中', '低'];
    
    function handleSave() {
        if (!formData.name || !formData.device_id) {
            alert('请填写任务名称和关联设备');
            return;
        }
        dispatch('save', formData);
    }
    
    function handleCancel() {
        dispatch('close');
    }
</script>

<div class="fixed inset-0 bg-slate-900/50 backdrop-blur-sm z-50 flex items-center justify-center p-4">
    <div class="bg-white rounded-xl shadow-2xl w-full max-w-xl overflow-hidden flex flex-col max-h-[90vh]">
        <div class="px-6 py-4 border-b border-slate-100 flex justify-between items-center bg-slate-50">
            <h3 class="text-xl font-semibold text-slate-800">{task ? '编辑任务' : '新建任务'}</h3>
            <button on:click={handleCancel} class="text-slate-400 hover:text-slate-600 transition-colors">
                <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path></svg>
            </button>
        </div>
        
        <div class="p-6 overflow-y-auto flex-1 space-y-4">
            <div>
                <label class="block text-sm font-medium text-slate-700 mb-1">任务名称 <span class="text-red-500">*</span></label>
                <input type="text" bind:value={formData.name} class="w-full px-3 py-2 border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500" placeholder="例如：测试安防任务" />
            </div>
            <div class="grid grid-cols-2 gap-4">
                <div>
                    <label class="block text-sm font-medium text-slate-700 mb-1">任务类型 <span class="text-red-500">*</span></label>
                    <select bind:value={formData.task_type} class="w-full px-3 py-2 border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500">
                        {#each taskTypes as type}
                            <option value={type}>{type}</option>
                        {/each}
                    </select>
                </div>
                <div>
                    <label class="block text-sm font-medium text-slate-700 mb-1">关联设备 <span class="text-red-500">*</span></label>
                    <select bind:value={formData.device_id} class="w-full px-3 py-2 border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500">
                        <option value="">请选择设备</option>
                        {#each devices as device}
                            <option value={device.device_id}>{device.name} ({device.device_id})</option>
                        {/each}
                    </select>
                </div>
            </div>
            <div class="grid grid-cols-2 gap-4">
                <div>
                    <label class="block text-sm font-medium text-slate-700 mb-1">任务状态 <span class="text-red-500">*</span></label>
                    <select bind:value={formData.status} class="w-full px-3 py-2 border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500">
                        {#each statuses as status}
                            <option value={status}>{status}</option>
                        {/each}
                    </select>
                </div>
                <div>
                    <label class="block text-sm font-medium text-slate-700 mb-1">优先级</label>
                    <select bind:value={formData.priority} class="w-full px-3 py-2 border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500">
                        {#each priorities as priority}
                            <option value={priority}>{priority}</option>
                        {/each}
                    </select>
                </div>
            </div>
            <div>
                <label class="block text-sm font-medium text-slate-700 mb-1">负责人</label>
                <input type="text" bind:value={formData.assignee} class="w-full px-3 py-2 border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500" placeholder="例如：张三" />
            </div>
        </div>
        
        <div class="px-6 py-4 border-t border-slate-100 flex justify-end gap-3 bg-slate-50">
            <button on:click={handleCancel} class="px-4 py-2 border border-slate-300 rounded-lg text-slate-700 font-medium hover:bg-slate-100 transition-colors">取消</button>
            <button on:click={handleSave} class="px-4 py-2 bg-blue-600 text-white rounded-lg font-medium hover:bg-blue-700 transition-colors shadow-sm">保存</button>
        </div>
    </div>
</div>
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/components/TaskModal.svelte
git commit -m "feat: implement TaskModal component"
```

### Task 5: Frontend Tasks Component Implementation

**Files:**
- Modify: `frontend/src/components/Tasks.svelte`

- [ ] **Step 1: Implement Tasks Logic and API Calls**

```svelte
<!-- In frontend/src/components/Tasks.svelte -->
<!-- Replace entire file content with: -->
<script>
    import { onMount } from 'svelte';
    import Icon from '../lib/Icon.svelte';
    import TaskModal from './TaskModal.svelte';

    export let API_BASE = 'http://localhost:8000';

    let tasks = [];
    let devices = [];
    let total = 0;
    let page = 1;
    const size = 10;

    let showModal = false;
    let editingTask = null;

    onMount(async () => {
        await fetchDevices();
        await fetchTasks();
    });

    async function fetchDevices() {
        try {
            const res = await fetch(`${API_BASE}/api/devices`);
            if (res.ok) {
                devices = await res.json();
            }
        } catch (error) {
            console.error("Failed to fetch devices", error);
        }
    }

    async function fetchTasks() {
        try {
            const res = await fetch(`${API_BASE}/api/tasks?page=${page}&size=${size}`);
            if (res.ok) {
                const data = await res.json();
                tasks = data.tasks;
                total = data.total;
            }
        } catch (error) {
            console.error("Failed to fetch tasks", error);
        }
    }

    function openModal(task = null) {
        editingTask = task;
        showModal = true;
    }

    function closeModal() {
        showModal = false;
        editingTask = null;
    }

    async function saveTask(event) {
        const taskData = event.detail;
        const method = editingTask ? 'PUT' : 'POST';
        const url = editingTask ? `${API_BASE}/api/tasks/${editingTask.id}` : `${API_BASE}/api/tasks`;
        
        try {
            const res = await fetch(url, {
                method,
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(taskData)
            });
            if (res.ok) {
                closeModal();
                fetchTasks();
            } else {
                alert('保存失败');
            }
        } catch (error) {
            alert('网络错误');
        }
    }

    async function deleteTask(taskId) {
        if (!confirm('确定要删除此任务吗？')) return;
        try {
            const res = await fetch(`${API_BASE}/api/tasks/${taskId}`, { method: 'DELETE' });
            if (res.ok) {
                if (tasks.length === 1 && page > 1) page--;
                fetchTasks();
            }
        } catch (error) {
            alert('删除失败');
        }
    }

    function getDeviceName(deviceId) {
        const device = devices.find(d => d.device_id === deviceId);
        return device ? device.name : deviceId;
    }
</script>

<div class="h-full flex flex-col bg-slate-100 p-6 overflow-hidden relative">
    <h2 class="text-2xl font-bold text-slate-800 mb-6">任务管理</h2>
    <div class="bg-white rounded-xl shadow-sm border border-slate-200 flex-1 flex flex-col overflow-hidden">
        <div class="p-4 border-b border-slate-200 flex justify-between items-center bg-slate-50">
            <span class="text-slate-600">共找到 <strong class="text-slate-900">{total}</strong> 个任务</span>
            <button on:click={() => openModal()} class="bg-blue-600 hover:bg-blue-700 text-white px-4 py-2 rounded-lg font-medium flex items-center transition-colors shadow-sm">
                <span class="mr-2 text-lg leading-none">+</span> 新建任务
            </button>
        </div>
        
        <div class="flex-1 overflow-auto">
            <table class="w-full text-left border-collapse">
                <thead>
                    <tr class="bg-slate-50 border-b border-slate-200 text-slate-500 text-sm">
                        <th class="py-3 px-6 font-medium">任务ID</th>
                        <th class="py-3 px-6 font-medium">任务名称</th>
                        <th class="py-3 px-6 font-medium">任务类型</th>
                        <th class="py-3 px-6 font-medium">关联设备</th>
                        <th class="py-3 px-6 font-medium">任务状态</th>
                        <th class="py-3 px-6 font-medium text-right">操作</th>
                    </tr>
                </thead>
                <tbody class="divide-y divide-slate-100 text-slate-700">
                    {#each tasks as task}
                        <tr class="hover:bg-slate-50 transition-colors">
                            <td class="py-3 px-6 font-mono text-xs">{task.id}</td>
                            <td class="py-3 px-6 font-medium">{task.name}</td>
                            <td class="py-3 px-6">{task.task_type}</td>
                            <td class="py-3 px-6">{getDeviceName(task.device_id)}</td>
                            <td class="py-3 px-6">
                                <span class="px-2.5 py-1 text-xs rounded-full font-medium {task.status === '布控中' ? 'bg-green-100 text-green-700' : task.status === '已完成' ? 'bg-blue-100 text-blue-700' : 'bg-slate-100 text-slate-600'}">
                                    {task.status}
                                </span>
                            </td>
                            <td class="py-3 px-6 text-right space-x-3">
                                <button on:click={() => openModal(task)} class="text-blue-500 hover:text-blue-700 transition-colors" title="编辑">
                                    <Icon name="Edit" className="w-5 h-5 inline" />
                                </button>
                                <button on:click={() => deleteTask(task.id)} class="text-red-500 hover:text-red-700 transition-colors" title="删除">
                                    <Icon name="Trash2" className="w-5 h-5 inline" />
                                </button>
                            </td>
                        </tr>
                    {:else}
                        <tr>
                            <td colspan="6" class="py-12 text-center text-slate-400">暂无任务</td>
                        </tr>
                    {/each}
                </tbody>
            </table>
        </div>
        
        <div class="p-4 border-t border-slate-200 flex justify-between items-center bg-slate-50">
            <span class="text-sm text-slate-500">第 <strong>{page}</strong> 页 / 共 <strong>{Math.ceil(total / size) || 1}</strong> 页</span>
            <div class="flex gap-2">
                <button 
                    disabled={page === 1}
                    on:click={() => { page--; fetchTasks(); }}
                    class="p-2 rounded border border-slate-300 text-slate-600 hover:bg-slate-100 disabled:opacity-50 disabled:cursor-not-allowed">
                    <Icon name="ChevronLeft" className="w-4 h-4" />
                </button>
                <button 
                    disabled={page >= Math.ceil(total / size) || total === 0}
                    on:click={() => { page++; fetchTasks(); }}
                    class="p-2 rounded border border-slate-300 text-slate-600 hover:bg-slate-100 disabled:opacity-50 disabled:cursor-not-allowed">
                    <Icon name="ChevronRight" className="w-4 h-4" />
                </button>
            </div>
        </div>
    </div>
</div>

{#if showModal}
    <TaskModal {task={editingTask}} {devices} on:save={saveTask} on:close={closeModal} />
{/if}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/components/Tasks.svelte
git commit -m "feat: complete Tasks list component with fetching and UI"
```