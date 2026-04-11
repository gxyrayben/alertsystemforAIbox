# Log Management Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement a log management feature to view and export AI compute box interaction logs with pagination.

**Architecture:** Add a new `LogORM` to the SQLite database, create REST endpoints for pagination and insertion in FastAPI, and build a Svelte component mirroring the existing UI to display the logs with an export-to-CSV feature.

**Tech Stack:** FastAPI, SQLite, Pydantic, Svelte, TailwindCSS.

---

### Task 1: Update Backend Database Models & Schemas

**Files:**
- Modify: `backend/models/orm.py`
- Modify: `backend/models/schemas.py`

- [ ] **Step 1: Add LogORM to database models**

In `backend/models/orm.py`, append the `LogORM` class:

```python
class LogORM(Base):
    __tablename__ = "logs"
    id = Column(String, primary_key=True, index=True)
    log_id = Column(String, index=True)
    device_name = Column(String, index=True)
    api_path = Column(String)
    parameters = Column(String)
    result = Column(String)
    timestamp = Column(BigInteger, index=True)
```

- [ ] **Step 2: Add Log schemas**

In `backend/models/schemas.py`, append the required schemas:

```python
class LogBase(BaseModel):
    log_id: str
    device_name: str
    api_path: str
    parameters: str
    result: str
    timestamp: int

class LogCreate(LogBase):
    pass

class LogResponse(LogBase):
    id: str

    class Config:
        from_attributes = True

class LogListResponse(BaseModel):
    items: List[LogResponse]
    total: int
```

- [ ] **Step 3: Commit**

```bash
git add backend/models/orm.py backend/models/schemas.py
git commit -m "feat(backend): add log database model and schemas"
```

---

### Task 2: Create Backend API Route for Logs

**Files:**
- Create: `backend/routers/logs.py`

- [ ] **Step 1: Create the logs router with endpoints**

Create `backend/routers/logs.py` with the following content:

```python
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from database import SessionLocal
from models.orm import LogORM
from models.schemas import LogResponse, LogCreate, LogListResponse
import uuid
import time

router = APIRouter(prefix="/logs", tags=["logs"])

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@router.get("", response_model=LogListResponse)
def get_logs(page: int = Query(1, ge=1), size: int = Query(15, ge=1, le=100), db: Session = Depends(get_db)):
    skip = (page - 1) * size
    total = db.query(LogORM).count()
    logs = db.query(LogORM).order_by(LogORM.timestamp.desc()).offset(skip).limit(size).all()
    return {"items": logs, "total": total}

@router.post("", response_model=LogResponse)
def create_log(log: LogCreate, db: Session = Depends(get_db)):
    db_log = LogORM(
        id=str(uuid.uuid4()),
        log_id=log.log_id,
        device_name=log.device_name,
        api_path=log.api_path,
        parameters=log.parameters,
        result=log.result,
        timestamp=log.timestamp
    )
    db.add(db_log)
    db.commit()
    db.refresh(db_log)
    return db_log
```

- [ ] **Step 2: Commit**

```bash
git add backend/routers/logs.py
git commit -m "feat(backend): add logs API router"
```

---

### Task 3: Update Backend Router Registration

**Files:**
- Modify: `backend/main.py`

- [ ] **Step 1: Include the logs router in the main app**

In `backend/main.py`, find the router imports and `app.include_router` block, and add `logs.py`.

Modify the imports to include `logs`:
```python
from routers import devices, alerts, services, network, chat, llm, tasks, logs
```

And in the setup section:
```python
app.include_router(logs.router)
```

- [ ] **Step 2: Commit**

```bash
git add backend/main.py
git commit -m "feat(backend): register logs router in main application"
```

---

### Task 4: Update Frontend App and Sidebar

**Files:**
- Modify: `frontend/src/App.svelte`
- Modify: `frontend/src/components/Sidebar.svelte`

- [ ] **Step 1: Add Logs to Sidebar menu**

In `frontend/src/components/Sidebar.svelte`, add the `logs` item between `llm` and `sessions`:

```javascript
        { id: 'llm', icon: 'Cpu', label: '模型配置' },
        { id: 'logs', icon: 'FileText', label: '日志管理' },
        { id: 'sessions', icon: 'MessageSquare', label: '会话管理' }
```

- [ ] **Step 2: Register Logs in App.svelte**

In `frontend/src/App.svelte`:

Import the component (which will be created in the next task):
```javascript
    import Logs from './components/Logs.svelte';
```

Add to `menuTitles`:
```javascript
        'llm': '模型配置',
        'logs': '日志管理',
        'sessions': '会话管理'
```

Add to the conditional rendering block (`<main>`):
```svelte
                {#if activeMenu === 'llm'}
                    <LLMConfig />
                {/if}
                {#if activeMenu === 'logs'}
                    <Logs />
                {/if}
                {#if activeMenu === 'sessions'}
                    <Sessions />
                {/if}
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/App.svelte frontend/src/components/Sidebar.svelte
git commit -m "feat(frontend): add log management to sidebar and app routing"
```

---

### Task 5: Create Frontend Logs Component

**Files:**
- Create: `frontend/src/components/Logs.svelte`

- [ ] **Step 1: Create Logs component UI and logic**

Create `frontend/src/components/Logs.svelte` with:

```svelte
<script>
    import { onMount } from 'svelte';
    import { API_BASE } from '../lib/config.js';

    let logs = [];
    let total = 0;
    let page = 1;
    let size = 15;
    let isLoading = false;

    $: totalPages = Math.ceil(total / size) || 1;
    $: startItem = (page - 1) * size + 1;
    $: endItem = Math.min(page * size, total);

    onMount(() => {
        fetchLogs();
    });

    async function fetchLogs() {
        isLoading = true;
        try {
            const res = await fetch(`${API_BASE}/logs?page=${page}&size=${size}`);
            if (res.ok) {
                const data = await res.json();
                logs = data.items;
                total = data.total;
            }
        } catch (e) {
            console.error(e);
        } finally {
            isLoading = false;
        }
    }

    function prevPage() {
        if (page > 1) {
            page--;
            fetchLogs();
        }
    }

    function nextPage() {
        if (page < totalPages) {
            page++;
            fetchLogs();
        }
    }

    function exportToCsv() {
        if (logs.length === 0) return;

        const headers = ['日志ID', '操作设备', '调用接口', '核心参数', '调用时间', '调用结果'];
        const csvRows = [headers.join(',')];

        logs.forEach(log => {
            const row = [
                log.log_id,
                log.device_name,
                log.api_path,
                // Escape quotes for CSV
                `"${log.parameters.replace(/"/g, '""')}"`,
                formatDate(log.timestamp),
                log.result
            ];
            csvRows.push(row.join(','));
        });

        const csvContent = csvRows.join('\n');
        // Add BOM for Excel UTF-8 support
        const blob = new Blob(['\uFEFF' + csvContent], { type: 'text/csv;charset=utf-8;' });
        const url = URL.createObjectURL(blob);
        const link = document.createElement('a');
        link.setAttribute('href', url);
        link.setAttribute('download', `logs_page_${page}.csv`);
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
    }

    function formatDate(timestamp) {
        const d = new Date(timestamp);
        return `${d.getFullYear()}/${d.getMonth() + 1}/${d.getDate()} ${d.getHours().toString().padStart(2, '0')}:${d.getMinutes().toString().padStart(2, '0')}:${d.getSeconds().toString().padStart(2, '0')}`;
    }

    function truncateParams(params) {
        if (params.length > 50) {
            return params.substring(0, 47) + '...';
        }
        return params;
    }
</script>

<div class="h-full flex flex-col pt-8 items-center">
    <div class="w-full max-w-6xl bg-white rounded-xl shadow-sm border border-gray-200 flex flex-col h-full overflow-hidden">
        <!-- Header -->
        <div class="px-6 py-5 border-b border-gray-200 flex justify-between items-center bg-gray-50/50 shrink-0">
            <h3 class="text-sm text-gray-600">系统总共记录了 <span class="font-bold text-gray-900">{total}</span> 条操作日志</h3>
            <button on:click={exportToCsv} class="flex items-center px-4 py-2 bg-green-600 hover:bg-green-700 text-white rounded text-sm font-medium transition-colors shadow-sm active:scale-95">
                <svg class="w-4 h-4 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4"></path></svg>
                导出当前页数据
            </button>
        </div>

        <!-- Table -->
        <div class="flex-1 overflow-y-auto">
            <table class="min-w-full divide-y divide-gray-200">
                <thead class="bg-white sticky top-0 z-10 shadow-sm">
                    <tr>
                        <th class="px-6 py-4 text-left text-xs font-semibold text-gray-500 tracking-wider">日志ID</th>
                        <th class="px-6 py-4 text-left text-xs font-semibold text-gray-500 tracking-wider">操作设备</th>
                        <th class="px-6 py-4 text-left text-xs font-semibold text-gray-500 tracking-wider">调用接口</th>
                        <th class="px-6 py-4 text-left text-xs font-semibold text-gray-500 tracking-wider">核心参数</th>
                        <th class="px-6 py-4 text-left text-xs font-semibold text-gray-500 tracking-wider">调用时间</th>
                        <th class="px-6 py-4 text-left text-xs font-semibold text-gray-500 tracking-wider">调用结果</th>
                    </tr>
                </thead>
                <tbody class="bg-white divide-y divide-gray-100">
                    {#if isLoading}
                        <tr><td colspan="6" class="px-6 py-8 text-center text-sm text-gray-500">加载中...</td></tr>
                    {:else if logs.length === 0}
                        <tr><td colspan="6" class="px-6 py-12 text-center text-sm text-gray-500">暂无日志数据</td></tr>
                    {:else}
                        {#each logs as log}
                            <tr class="hover:bg-gray-50 transition-colors">
                                <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-500 font-mono">{log.log_id}</td>
                                <td class="px-6 py-4 whitespace-nowrap text-sm font-medium text-gray-900">{log.device_name}</td>
                                <td class="px-6 py-4 whitespace-nowrap text-sm text-blue-600 font-mono bg-blue-50/30 rounded">{log.api_path}</td>
                                <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-500 font-mono" title={log.parameters}>{truncateParams(log.parameters)}</td>
                                <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-500">{formatDate(log.timestamp)}</td>
                                <td class="px-6 py-4 whitespace-nowrap">
                                    <span class="px-2 inline-flex text-xs leading-5 font-semibold rounded-full {log.result === '成功' ? 'bg-green-100 text-green-800' : 'bg-red-100 text-red-800'}">
                                        {log.result}
                                    </span>
                                </td>
                            </tr>
                        {/each}
                    {/if}
                </tbody>
            </table>
        </div>

        <!-- Pagination -->
        <div class="px-6 py-4 border-t border-gray-200 bg-white flex items-center justify-between shrink-0">
            <div class="text-sm text-gray-500">
                显示第 {total === 0 ? 0 : startItem} 到 {endItem} 条，共 {total} 条
            </div>
            <div class="flex items-center space-x-2">
                <button 
                    on:click={prevPage} 
                    disabled={page === 1}
                    class="p-2 rounded border border-gray-300 text-gray-600 hover:bg-gray-50 disabled:opacity-50 disabled:cursor-not-allowed"
                >
                    <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 19l-7-7 7-7"></path></svg>
                </button>
                <span class="text-sm text-gray-700 px-2">第 {page} / {totalPages} 页</span>
                <button 
                    on:click={nextPage} 
                    disabled={page === totalPages || total === 0}
                    class="p-2 rounded border border-gray-300 text-gray-600 hover:bg-gray-50 disabled:opacity-50 disabled:cursor-not-allowed"
                >
                    <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7"></path></svg>
                </button>
            </div>
        </div>
    </div>
</div>
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/components/Logs.svelte
git commit -m "feat(frontend): create log management component with pagination and export"
```
