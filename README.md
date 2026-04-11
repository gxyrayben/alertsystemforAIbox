# 安防综合管理平台 (Svelte + FastAPI)

本项目基于 `test.html` 的功能和设计，使用 Svelte 作为前端框架，FastAPI 作为后端框架重新开发。

## 项目结构

- `backend/`: FastAPI 后端代码
  - `main.py`: 包含 API 路由、模型和模拟数据逻辑。
- `frontend/`: Svelte 前端代码
  - `src/App.svelte`: 主应用组件。
  - `src/lib/Icon.svelte`: 图标组件。

## 核心功能

1.  **设备接入管理**: 支持设备的列表显示、分页、添加、编辑和删除（CRUD）。
2.  **预警管理**: 
    - 支持按时间、设备名称和预警类型进行检索。
    - **AI 分析**: 调用后端接口模拟 AI 抓拍图像分析，并自动填充备注。
3.  **会话管理**: 提供与 AI 助手的对话界面，支持实时回复模拟。

## 如何运行

### 1. 运行后端 (FastAPI)

确保已安装 `fastapi`, `uvicorn`, `pydantic`：

```bash
pip install fastapi uvicorn pydantic
```

运行服务：

```bash
cd backend
python main.py
```

后端将运行在 `http://localhost:8000`。

### 2. 运行前端 (Svelte)

前端使用 Tailwind CSS 进行样式处理。建议使用 Vite 创建 Svelte 项目并安装相关依赖：

```bash
# 在 frontend 目录下
npm install
npm run dev
```

确保前端访问地址为 `http://localhost:5173`（或根据实际情况调整，并确保后端 CORS 已允许）。

## 技术要点

- **Svelte 响应式**: 使用 Svelte 的 `$` 语法处理分页计算，使用 `bind:value` 实现双向绑定。
- **FastAPI 异步**: 后端接口采用 `async def`，模拟了 AI 处理的延迟效果。
- **CORS 支持**: 后端已配置中间件，允许跨域请求。
- **模块化**: 图标逻辑从主文件抽离，增强了代码可读性。
