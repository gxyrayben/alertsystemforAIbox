# 盒子操作日志管理功能设计

## 1. 目标与背景
本项目计划支持大模型对接入的 AI 计算盒子任务进行自主优化。为了审计、追踪及排查问题，系统需要一个专门的“日志管理”界面，以记录和展示每次与盒子交互的操作日志（特别是配置更新、状态检查等）。该界面需要与现有的 UI 风格保持一致，并支持分页查看和当前页数据导出。

## 2. 核心功能需求
- **日志列表展示**：分页展示盒子交互操作日志。
- **字段要求**：
  - 日志ID（如：LOG-10027）
  - 操作设备（如：AI计算盒子 10号）
  - 调用接口（如：`/api/v1/task/optimize`）
  - 核心参数（展示 JSON 字符串，超长需截断）
  - 调用时间（格式：`YYYY/M/D HH:mm:ss`）
  - 调用结果（`成功` 或 `失败`）
- **操作互动**：
  - 支持分页控制（上一页、下一页、当前页码展示）。
  - 支持显示总日志数及当前页的条目范围。
  - 支持一键导出“当前页数据”至 CSV 文件。

## 3. 系统架构设计

### 3.1. 数据库模型 (`backend/models/orm.py` 和 `backend/models/schemas.py`)
新增 `LogORM` 模型用于存储日志。
```python
class LogORM(Base):
    __tablename__ = "logs"
    id = Column(String, primary_key=True, index=True) # UUID
    log_id = Column(String, index=True) # LOG-10001
    device_name = Column(String, index=True)
    api_path = Column(String)
    parameters = Column(String)
    result = Column(String) # "成功" | "失败"
    timestamp = Column(BigInteger, index=True) # unix 毫秒级时间戳
```
新增相应的 Pydantic Schema `LogResponse`, `LogCreate`, `LogListResponse`。

### 3.2. 后端 API (`backend/routers/logs.py`)
- `GET /logs`：支持分页查询。参数：`page` (默认 1), `size` (默认 15)。返回包含 `items` (当前页日志列表) 和 `total` (总条数) 的对象。
- `POST /logs`：新增操作日志（为大模型后续调用留出接口）。

### 3.3. 前端界面 (`frontend/src/components/Logs.svelte`)
- **菜单入口**：在 `App.svelte` 和 `Sidebar.svelte` 中新增 `logs` 菜单项（位于“模型配置”和“会话管理”之间），Label为“日志管理”。
- **UI 布局**：
  - **Header**: “系统总共记录了 X 条操作日志”及右侧的绿色“导出当前页数据”按钮。
  - **Table**: 纯 CSS 表格或 Flex/Grid 列表，表头包含对应的 6 个列。样式要求“调用接口”呈现为蓝色，“调用结果”呈现为淡绿色/淡红色背景。
  - **Footer**: 左侧显示“显示第 X 到 Y 条，共 Z 条”，右侧为分页按钮（`<`, `第 X / Y 页`, `>`）。
- **导出逻辑**：纯前端实现，将当前 `logs` 数组转换为 CSV 格式并通过 Blob 对象触发下载。

## 4. 测试与验证策略
- 验证后端能否正常接收和返回分页日志。
- 验证在没有数据时，前端的友好提示。
- 验证分页逻辑计算是否准确。
- 验证导出功能生成的 CSV 文件编码正常（BOM UTF-8），内容符合当前页面的展现。
