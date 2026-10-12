# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A security-camera management platform (AI视觉布控优化平台): FastAPI backend + Svelte 4 frontend. The backend acts as a **proxy/orchestrator in front of physical camera "BOX" devices** — it logs into them over HTTP, mirrors their channels/tasks/algorithms into a local SQLite ledger, ingests their alarm push notifications, and runs an LLM agent that can query and deploy detection tasks onto them.

> Note: `README.md` and `GEMINI.md` are stale — they describe an older single-file `backend/main.py`. The real code is split into `routers/` + `services/`. Trust the code, not those docs.

## Commands

Backend (run from **inside `backend/`** — all paths like the DB, `config.json`, and `uploads/` are relative to CWD):
```bash
cd backend
python main.py                 # serves on 0.0.0.0:8000
# or with reload:
python -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```
Dependencies (no requirements.txt): `fastapi uvicorn pydantic sqlalchemy aiosqlite httpx apscheduler psutil`.

Frontend:
```bash
cd frontend
npm install
npm run dev        # Vite dev server — note vite.config.js pins host to 192.168.5.5:5173
npm run build
```

End-to-end simulation (requires the backend already running on :8000, and the alarm ingest ports :8081/:8082 enabled in config):
```bash
python tests/simulate_e2e.py   # spins up a mock camera, pushes alarms, polls logs for auto-tune result
```
There is no unit-test suite or linter configured.

## Backend architecture

Layering is strict — keep it that way:
- **`routers/`** — thin FastAPI endpoints (HTTP concerns only). Registered in `main.py`.
- **`services/`** — all business logic. Routers call services; services never import routers.
- **`models/`** — `orm.py` (SQLAlchemy tables), `schemas.py` (Pydantic), `db.py` (async engine/session).

Key cross-cutting pieces:
- **`database.py`** holds mutable module-level globals (`llm_config`, `current_services_config`, `backend_interface_id`, ...) loaded from `backend/config.json` at import. Routers/services read config via `import database; database.llm_config`. Call `database.save_config()` to persist. **`config.json` is the live runtime config and contains the real LLM API key** — treat it as a secret, don't commit new keys.
- **DB is SQLite with WAL** (`alertsystem.db`). Schema is created by `Base.metadata.create_all` in the `lifespan` hook; **ad-hoc migrations are done there via raw `ALTER TABLE`** (see `main.py` — `messages.tables`, `conversations.summary`, `devices.agents`). Add new columns the same way for backward compat. JSON-typed fields (channels, device_tasks, algorithms, agents) are stored as JSON strings in TEXT columns.
- **Background jobs** (APScheduler, started in `lifespan`): `clean_old_alerts` hourly (deletes alerts + images older than 7 days); `run_auto_tune_cycle` every 60s.
- **Alarm ingestion** (`services/alarm_services.py`) starts **separate HTTP (:8081) and WS (:8082) servers** on their own ports, independent of the main :8000 API, driven by `services_config`. `services/alarm_ingest.py` parses the multipart alarm payload (`global_info` JSON + `alarm_picture_*` images) into an `AlertORM` row; images are saved under `uploads/<date>/<hour>/`.

### Device communication (`services/device_service.py`)
Physical BOX devices use a **SHA256 challenge/response login** (`challenge_login`) yielding a `session_id` cookie, then their `/intelli_manager/*` and `/card_cap/*` HTTP APIs. `apply_device_snapshot` mirrors a device's live channels/tasks/algorithms/agents back into `DeviceORM`. `algorithm_catalog.py` maps Chinese algorithm names ↔ device event-type IDs (devices speak English IDs like `INTRUSION`; UI speaks Chinese).

### LLM layer
- **`services/llm_client.py`** is the single provider-abstraction layer. It normalizes a neutral message format `[{"role", "text", ...}]` to either Gemini (`generateContent`) or OpenAI-compatible (`/chat/completions`) depending on `config["provider"]` containing `"Gemini"`. Use `chat_with_tools()` for tool-calling turns and `complete()` for plain completions. Don't add per-caller provider branching elsewhere.
- **`services/agent_tools.py`** defines `TOOLS` (the tool schemas) and `execute_tool()`. Tools split into local-ledger ops (`list_devices`, `create_task`, ... on `TaskORM`) and live device ops (`get_device_streams`, `list_agents`, `create_*_task`, ... calling device APIs).
- **`services/skills.py`** is the **single source of truth for agent capabilities**. Each skill bundles a name/description/icon + which `TOOLS` it owns + usage guidance. Both the system prompt (`build_skills_prompt()`) and the frontend skills panel (`/skills`) are generated from it — to add a capability, register it here rather than editing the prompt string.
- **Agent loop** lives in `routers/chat.py` `_run_agent()` (max 5 tool-call rounds). It also maintains **rolling conversation memory**: long chats are compressed to the last `HISTORY_KEEP` messages plus a periodically-refreshed `summary` stored on `ConversationORM`.
- **Auto-tune workflow** (`services/task_service.py` `perform_auto_tune_workflow`): for `Prompt调优` tasks, collects unprocessed alarm images for a device/algorithm, sends them to the LLM (`LLMService.optimize_prompt`), and if a false-positive is detected, pushes an optimized prompt back to the device and advances the `last_processed_time` cursor.

## Frontend architecture

Svelte 4 + Vite, Tailwind via CDN (no build-time Tailwind), Font Awesome icons.
- **`src/lib/controlStore.js`** — central Svelte store: active tab (`activeMenu`), device list, selected device. Navigation is tab-based via `switchTab`, not a router.
- **`src/lib/api.js`** — all HTTP goes through `apiGet/apiPost/apiPut/apiDelete` against `API_BASE`, which now follows the page protocol (`${window.location.protocol}//${hostname}:8000`, overridable via `window.__API_BASE__`). `apiPost` forwards an `AbortController` signal for cancelable requests (e.g. stopping a running task).
- **`src/App.svelte`** wires `TopNav` + a "基础配置" sidebar to the feature components (`Devices`, `Tasks`, `Alerts`, `Logs`, `Services`, `Network`, `LLMConfig`) and the AI features (`AIControl`, `TaskOps`, `Feedback`, `AgentLibrary`).

## HTTPS / TLS

Everything is HTTP by default; HTTPS is a **config switch**, not a code branch:

- **服务端（入站）**：`backend/config.json` 的 `tls` 块（`enabled` / `cert_file` / `key_file`）是**唯一开关**，主服务 `:8000`（`main.py`）、报警接收 HTTP/WS（`alarm_services.py`）三处共用 —— 统一由 `database.tls_ssl_kwargs()` 判定（证书缺失只告警并回落 HTTP，不会让进程起不来）。前端「服务配置」页可改这个开关：报警接收端口保存即重启，主服务 `:8000` 需重启后端进程。
- **设备侧（出站）**：每台设备自带 `protocol`（http/https，默认 http）与 `tls_verify`（默认 false = **跳过证书校验**，兼容 BOX 自签证书）。所有设备 URL 必须经 `DeviceService.base_url(device)` 拼接，所有设备 HTTP 客户端必须经 `DeviceService.new_client(device, timeout=...)` 创建（verify 策略在工厂里）——**不要在各处自建 `httpx.AsyncClient`**，否则 HTTPS 下自签证书会让调用全部失败。按 ip/port 走的 `fetch_device_data(..., protocol=, tls_verify=)` 同样要传这两个参数。调用公网 LLM 的 `llm_client.py` 不在此列（走系统 CA 校验）。
- **证书**：在 `backend/` 下执行 `python tools/gen_self_signed_cert.py` 生成 `backend/certs/server.crt|key`（优先 openssl，缺则用 cryptography 库），已加入 `.gitignore`。前端 dev server 可选 HTTPS（避免混合内容）：`VITE_HTTPS=1 VITE_CERT=../backend/certs/server.crt VITE_KEY=../backend/certs/server.key npm run dev`。

## 图文互搜（Chinese-CLIP 文搜图 / 以图搜图）

- **模型**：本地 `Chinese-CLIP ViT-B/16`（`OFA-Sys/chinese-clip-vit-base-patch16`），权重放 `backend/models/chinese-clip-vit-base-patch16/`（已 gitignore）。下载：`python tools/download_clip_model.py`（默认走 hf-mirror.com 镜像并跳过重复的 `.pt`，约 720MB）。**huggingface.co 在国内常被墙，必须走镜像**。
- **封装**：`services/clip_service.py` —— 懒加载单例（首次用到才载入，不拖慢启动）、设备自动选择 `cuda → mps(Apple Silicon) → cpu`（Mac/Win 同一套代码）、向量 L2 归一化。注意 **transformers 5.x 的 `get_text_features/get_image_features` 返回 `BaseModelOutputWithPooling`**，特征在 `pooler_output`（512 维），已由 `_extract_features()` 兼容 4.x/5.x 两种返回。
- **索引**：表 `image_embeddings`（一行 = 一张图的一条向量；`kind` 区分 `big` 告警整帧 / `crop` 送检小图）。**非实时建模**：`services/image_index_service.py` 由 APScheduler 每 `image_search.interval_seconds` 秒跑一小批（`per_cycle` 张，编码在线程池里，不阻塞事件循环）；编码失败写 `dim=0` 墓碑行避免反复重试坏图；告警被 7 天清理后由 `prune_orphans()` 清孤儿向量。
- **检索**：`routers/search.py`（`/search/status|text|image|reindex`）。向量池按 kind 常驻内存（`_index_version` 版本号自动失效重建），检索 = 矩阵乘 + top-k，10w 张规模无需 FAISS；过滤条件（设备/通道/类型/时间）先转成允许的 alert_id 集合再做掩码。
- **前端**：`ImageSearch.svelte`（顶部横向导航「图文互搜」，位于「预警管理」之前）。索引状态每 5s 轮询，含进度/失败数/推理设备；支持文搜图与以图搜图、按相似度排序的图片墙、双击看大图。
- **配置**：`config.json` 的 `image_search` 块（enabled / model_dir / device / batch_size / interval_seconds / per_cycle），老配置缺该块会自动与默认值合并。

## Conventions

- Code comments and user-facing strings are in **Chinese**; match that when editing existing files.
- Backend CORS is fully open (`*`) — dev-only.
- Timestamps are **milliseconds since epoch** (`int(time.time() * 1000)`) throughout the DB.
- Design/planning docs for major features live in `docs/superpowers/{plans,specs}/`.

## Code Modification Rules
- **Respect User Edits:** Never revert, overwrite, or roll back user modifications unless explicitly commanded.
- **Incremental Changes Only:** Assume all existing code is the latest single source of truth. Treat differences from legacy implementations as intentional upgrades, not bugs.
- **Diff/Patch First:** When proposing changes to existing files, output only unified diffs or minimum viable updates instead of rewriting full functions or whole files.