---
name: run-app
description: 启动本安防综合管理平台(FastAPI 后端 + Svelte 前端)并冒烟验证。当被要求 run/start/跑起来/启动这个项目、或需要在真实应用里确认改动生效时使用。已在 Windows 上实测。
---

# 启动安防综合管理平台(Windows 实测流程)

本仓库最初在 **macOS** 上开发,拷到 Windows 后有两个坑必须先处理。
`start.sh` 只适用于 Mac/Linux(依赖 `lsof`/`nohup`/`python3`),**Windows 上不要用**。

后端 = FastAPI(:8000 主 API,+ :8081 HTTP 告警接入,+ :8082 WS 告警接入)。
前端 = Svelte 4 + Vite(:5173)。前端 `src/lib/api.js` 里 `API_BASE=http://localhost:8000`,所以后端必须先起。

---

## 0. 一次性环境准备(仅首次 / 依赖缺失时)

### Python(后端)
本机通常**没有** Python,且商店占位符会冒充 `python`。用 winget 装用户级 Python 3.12:

```powershell
winget install --id Python.Python.3.12 -e --source winget --scope user `
  --accept-package-agreements --accept-source-agreements --disable-interactivity
```

装完后 **Python 不在 PATH 上**,后续一律用全路径。先固定一个变量:

```powershell
$py = "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"   # 实际解析为 ...\Users\<你>\AppData\Local\Programs\Python\Python312\python.exe
& $py --version   # 应输出 Python 3.12.x
```

装后端依赖(**没有 requirements.txt**;这一行比 CLAUDE.md 的列表多了 `python-multipart` 和 `websockets`,否则 :8081/:8082 会起不来):

```powershell
& $py -m pip install fastapi "uvicorn[standard]" pydantic sqlalchemy aiosqlite httpx apscheduler psutil python-multipart websockets
```

### 前端依赖(必须在 Windows 上重装)
仓库自带的 `node_modules` 是 Mac 构建(只有 `@esbuild/darwin-arm64`、缺 `.cmd` shim),
直接 `npm run dev` 会报 `'vite' 不是内部或外部命令`。在 Windows 上重装即可修复:

```powershell
cd frontend; npm install; cd ..
```

验证修复成功:`frontend\node_modules\.bin\vite.cmd` 存在,且 `frontend\node_modules\@esbuild\win32-x64\` 存在。

---

## 1. 启动后端(从 backend/ 目录,路径都相对 CWD)

```powershell
$py = "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"
Set-Location backend
& $py main.py     # 建议后台运行
```

就绪标志(日志):`Application startup complete` + `Uvicorn running on http://0.0.0.0:8000`(以及 :8081/:8082 各一条)。
DB 表 / 迁移在 lifespan 钩子里自动建;告警接入服务由 `config.json` 的 `services_config` 驱动。

## 2. 启动前端

```powershell
cd frontend
npm run dev       # Vite → http://localhost:5173/
```

## 3. 冒烟验证(两个都起来后)

```bash
curl -s -o /dev/null -w "backend  /docs -> %{http_code}\n" http://localhost:8000/docs   # 期望 200
curl -s -o /dev/null -w "backend  /devices -> %{http_code}\n" http://localhost:8000/devices  # 期望 200,返回 JSON 设备数组
curl -s -o /dev/null -w "frontend / -> %{http_code}\n" http://localhost:5173/            # 期望 200
```

浏览器打开 http://localhost:5173/ 应看到「AI视觉布控优化系统」界面。四个端口都应在 LISTENING:5173 / 8000 / 8081 / 8082。

## 4. 停止

结束对应的后台进程即可;或按端口杀:

```powershell
foreach ($p in 8000,8081,8082,5173) {
  Get-NetTCPConnection -LocalPort $p -State Listen -ErrorAction SilentlyContinue |
    ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }
}
```

---

## 排错速查
- `'vite' 不是内部或外部命令` → 前端 `node_modules` 是 Mac 版,`cd frontend; npm install` 重装。
- 后端 `ModuleNotFoundError: python_multipart` / WS 端点报错 → 漏装 `python-multipart` / `websockets`(见 §0)。
- `python` 弹出应用商店 / 找不到 → 用 §0 的 `$py` 全路径,别依赖 PATH。
- 端口被占 → 先执行 §4 停止,再重启。
