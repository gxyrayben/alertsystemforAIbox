<#
  安防综合管理平台 —— Windows 统一启停脚本 (start.ps1)

  用法(在仓库根目录):
    .\start.ps1            # 启动前后端(等同 start)
    .\start.ps1 start      # 启动前后端
    .\start.ps1 stop       # 停止前后端(按端口结束进程)
    .\start.ps1 restart    # 重启
    .\start.ps1 status     # 查看运行状态
    .\start.ps1 logs       # 实时查看 backend.log + frontend.log
    .\start.ps1 setup      # 仅安装依赖(后端 pip + 前端 npm),不启动

  若遇到执行策略拦截,用 start.cmd,或:
    powershell -NoProfile -ExecutionPolicy Bypass -File .\start.ps1 start

  说明:
    - 本机 Python 不在 PATH 上(winget 用户级 3.12),脚本会自动定位全路径;
      也可用环境变量 ALERT_PY 覆盖(指向 python.exe)。
    - 后端从 backend/ 内以 `python -u main.py` 运行,监听 :8000(API)/:8081(HTTP告警)/:8082(WS告警)。
    - 前端从 frontend/ 内以 `npm run dev` 运行(Vite),监听 :5173。前端 API_BASE 指向 :8000,故后端先起。
    - 日志合并写入 logs/backend.log 与 logs/frontend.log;停止/状态一律按端口判定。
#>

param(
    [ValidateSet('start','stop','restart','status','logs','setup')]
    [string]$Action = 'start'
)

# ── 路径与常量 ──────────────────────────────────────────────
$ScriptDir   = Split-Path -Parent $MyInvocation.MyCommand.Path
$BackendDir  = Join-Path $ScriptDir 'backend'
$FrontendDir = Join-Path $ScriptDir 'frontend'
$LogDir      = Join-Path $ScriptDir 'logs'

$BackendPort  = 8000
$FrontendPort = 5173
$IngestPorts  = @(8081, 8082)          # 告警接入 HTTP / WS

$BackendLog  = Join-Path $LogDir 'backend.log'
$FrontendLog = Join-Path $LogDir 'frontend.log'

# ── 彩色输出 ────────────────────────────────────────────────
function Write-Info { param($m) Write-Host "[INFO] $m" -ForegroundColor Cyan }
function Write-Ok   { param($m) Write-Host "[ OK ] $m" -ForegroundColor Green }
function Write-Warn { param($m) Write-Host "[WARN] $m" -ForegroundColor Yellow }
function Write-Err  { param($m) Write-Host "[FAIL] $m" -ForegroundColor Red }

# ── Python 定位 ─────────────────────────────────────────────
function Test-PythonExe {
    param([string]$Exe)
    try {
        $v = & $Exe --version 2>&1
        return ($LASTEXITCODE -eq 0 -and "$v" -match 'Python 3')
    } catch { return $false }
}

function Resolve-Python {
    $cands = @()
    if ($env:ALERT_PY) { $cands += $env:ALERT_PY }                                    # 1) 环境变量覆盖
    $cands += (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python312\python.exe')     # 2) 本机实测路径
    $root = Join-Path $env:LOCALAPPDATA 'Programs\Python'                              # 3) 其它 3.x
    if (Test-Path $root) {
        Get-ChildItem $root -Directory -ErrorAction SilentlyContinue |
            Where-Object { $_.Name -match '^Python3' } | Sort-Object Name -Descending |
            ForEach-Object { $cands += (Join-Path $_.FullName 'python.exe') }
    }
    $onPath = Get-Command python -ErrorAction SilentlyContinue                         # 4) PATH(排除商店占位符)
    if ($onPath -and $onPath.Source -and ($onPath.Source -notmatch 'WindowsApps')) { $cands += $onPath.Source }

    foreach ($c in ($cands | Select-Object -Unique)) {
        if ($c -and (Test-Path $c) -and (Test-PythonExe -Exe $c)) { return $c }
    }
    return $null
}

# ── 依赖预检 ────────────────────────────────────────────────
function Ensure-BackendDeps {
    param([string]$Py)
    $probe = 'import fastapi,uvicorn,pydantic,sqlalchemy,aiosqlite,httpx,apscheduler,psutil,multipart,websockets'
    & $Py -c $probe 2>&1 | Out-Null
    if ($LASTEXITCODE -eq 0) { return }
    Write-Warn "后端依赖缺失,正在 pip 安装(首次较慢)…"
    & $Py -m pip install --disable-pip-version-check `
        fastapi "uvicorn[standard]" pydantic sqlalchemy aiosqlite httpx apscheduler psutil python-multipart websockets
    if ($LASTEXITCODE -ne 0) { throw "pip 安装后端依赖失败(退出码 $LASTEXITCODE)。" }
    Write-Ok "后端依赖已安装。"
}

function Ensure-FrontendDeps {
    if (-not (Get-Command npm -ErrorAction SilentlyContinue)) { throw "未找到 npm,请先安装 Node.js。" }
    # 仓库自带 node_modules 是 macOS 构建(仅 darwin-arm64、缺 .cmd shim),Windows 上必须重装
    $winEsbuild = Join-Path $FrontendDir 'node_modules\@esbuild\win32-x64'
    $viteCmd    = Join-Path $FrontendDir 'node_modules\.bin\vite.cmd'
    if ((Test-Path $winEsbuild) -and (Test-Path $viteCmd)) { return }
    Write-Warn "前端依赖非 Windows 版本或缺失,正在执行 npm install …"
    Push-Location $FrontendDir
    try {
        & npm install
        if ($LASTEXITCODE -ne 0) { throw "npm install 失败(退出码 $LASTEXITCODE)。" }
    } finally { Pop-Location }
    Write-Ok "前端依赖已安装。"
}

# ── 端口工具(停止/状态一律按端口判定)─────────────────────
function Get-PortPids {
    param([int]$Port)
    try {
        @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction Stop |
            Select-Object -ExpandProperty OwningProcess -Unique)
    } catch { @() }
}

function Test-Port { param([int]$Port) return (@(Get-PortPids -Port $Port).Count -gt 0) }

function Stop-Port {
    param([int]$Port)
    foreach ($procId in @(Get-PortPids -Port $Port)) {
        if ($procId -and $procId -ne 0) {
            try {
                Stop-Process -Id $procId -Force -ErrorAction Stop
                Write-Warn "已结束端口 $Port 上的进程 PID=$procId"
            } catch {
                Write-Warn "无法结束 PID=$procId(端口 $Port):$($_.Exception.Message)"
            }
        }
    }
}

function Wait-Port {
    param([int]$Port, [int]$TimeoutSec = 45)
    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    while ($sw.Elapsed.TotalSeconds -lt $TimeoutSec) {
        if (Test-Port -Port $Port) { return $true }
        Start-Sleep -Milliseconds 500
    }
    return $false
}

function Show-LogTail {
    param([string]$Path, [int]$Lines = 25)
    if (Test-Path $Path) {
        Get-Content -Path $Path -Tail $Lines -ErrorAction SilentlyContinue |
            ForEach-Object { Write-Host "    $_" -ForegroundColor DarkGray }
    }
}

function Get-LanIPv4 {
    try {
        Get-NetIPAddress -AddressFamily IPv4 -ErrorAction Stop |
            Where-Object { $_.IPAddress -notmatch '^(127\.|169\.254\.)' -and $_.PrefixOrigin -ne 'WellKnown' } |
            Select-Object -First 1 -ExpandProperty IPAddress
    } catch { $null }
}

# 在隐藏窗口里后台启动一条命令,stdout+stderr 合并写入日志文件,进程与本脚本解耦(脚本退出后仍运行)
function Start-Detached {
    param([string]$InnerCmd, [string]$LogFile, [string]$WorkDir)
    # cmd /c ""prog" args > "log" 2>&1"  —— 外层双引号被 cmd 剥离,内层引号保护含空格路径
    $argline = '/c "' + $InnerCmd + ' > "' + $LogFile + '" 2>&1"'
    return (Start-Process -FilePath $env:ComSpec -ArgumentList $argline `
                -WorkingDirectory $WorkDir -WindowStyle Hidden -PassThru)
}

# ── 启动 ────────────────────────────────────────────────────
function Start-Backend {
    param([string]$Py)
    if (Test-Port -Port $BackendPort) {
        Write-Warn "后端端口 $BackendPort 已在监听,跳过(如需重启用 restart)。"
        return
    }
    Write-Info "启动后端:python -u main.py (cwd=backend) …"
    $null = Start-Detached -InnerCmd ('"' + $Py + '" -u main.py') -LogFile $BackendLog -WorkDir $BackendDir
    if (Wait-Port -Port $BackendPort -TimeoutSec 45) {
        $listenerPid = (Get-PortPids -Port $BackendPort | Select-Object -First 1)
        Write-Ok "后端已启动 → http://localhost:$BackendPort/docs (PID $listenerPid)"
        foreach ($p in $IngestPorts) {
            if (Test-Port -Port $p) { Write-Ok "告警接入端口 $p 监听中。" }
            else { Write-Warn "告警接入端口 $p 未监听(若 config.json 未启用该服务可忽略)。" }
        }
    } else {
        Write-Err "后端启动失败(${BackendPort} 超时未监听),日志尾部:"
        Show-LogTail -Path $BackendLog
        throw "后端启动失败。"
    }
}

function Start-Frontend {
    if (Test-Port -Port $FrontendPort) {
        Write-Warn "前端端口 $FrontendPort 已在监听,跳过。"
        return
    }
    Write-Info "启动前端:npm run dev (cwd=frontend) …"
    $null = Start-Detached -InnerCmd 'npm run dev' -LogFile $FrontendLog -WorkDir $FrontendDir
    if (Wait-Port -Port $FrontendPort -TimeoutSec 60) {
        Write-Ok "前端已启动 → http://localhost:$FrontendPort/"
    } else {
        Write-Err "前端启动失败(${FrontendPort} 超时未监听),日志尾部:"
        Show-LogTail -Path $FrontendLog
        throw "前端启动失败。"
    }
}

# ── 各动作 ──────────────────────────────────────────────────
function Invoke-Start {
    if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Path $LogDir | Out-Null }

    $py = Resolve-Python
    if (-not $py) { throw "未找到可用的 Python 3。请先安装(见 .claude/skills/run-app),或设置环境变量 ALERT_PY 指向 python.exe。" }
    Write-Info "使用 Python:$py"
    if (-not (Get-Command node -ErrorAction SilentlyContinue)) { throw "未找到 Node.js,请先安装。" }

    Ensure-BackendDeps -Py $py
    Ensure-FrontendDeps

    Start-Backend -Py $py          # 后端必须先起(前端 API_BASE 指向 :8000)
    Start-Frontend

    Write-Host ""
    Write-Ok   "全部就绪。"
    Write-Info "前端界面 : http://localhost:$FrontendPort/"
    Write-Info "后端 API : http://localhost:$BackendPort/docs"
    $ip = Get-LanIPv4
    if ($ip) { Write-Info "同网段   : http://${ip}:$FrontendPort/" }
    Write-Info "查看日志 : .\start.ps1 logs    停止 : .\start.ps1 stop"
}

function Invoke-Stop {
    Write-Info "停止前端与后端…"
    foreach ($p in (@($FrontendPort) + $IngestPorts + @($BackendPort))) { Stop-Port -Port $p }
    Write-Ok "已停止。"
}

function Invoke-Status {
    $rows = @(
        @{ Name = '后端 API '; Port = $BackendPort },
        @{ Name = '告警 HTTP'; Port = 8081 },
        @{ Name = '告警 WS  '; Port = 8082 },
        @{ Name = '前端 Vite'; Port = $FrontendPort }
    )
    foreach ($r in $rows) {
        $ids = @(Get-PortPids -Port $r.Port)
        if ($ids.Count -gt 0) {
            $names = ($ids | ForEach-Object { try { (Get-Process -Id $_ -ErrorAction Stop).ProcessName } catch { '?' } }) -join ','
            Write-Ok  ("{0}  运行中  :{1}  (PID {2} / {3})" -f $r.Name, $r.Port, ($ids -join ','), $names)
        } else {
            Write-Warn ("{0}  未运行  :{1}" -f $r.Name, $r.Port)
        }
    }
}

function Invoke-Logs {
    if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Path $LogDir | Out-Null }
    if (-not (Test-Path $BackendLog))  { New-Item -ItemType File -Path $BackendLog  | Out-Null }
    if (-not (Test-Path $FrontendLog)) { New-Item -ItemType File -Path $FrontendLog | Out-Null }
    Write-Info "实时日志(Ctrl-C 退出):backend.log + frontend.log"
    Get-Content -Path $BackendLog, $FrontendLog -Tail 30 -Wait
}

function Invoke-Setup {
    $py = Resolve-Python
    if (-not $py) { throw "未找到可用的 Python 3。请先安装,或设置环境变量 ALERT_PY 指向 python.exe。" }
    Write-Info "使用 Python:$py"
    Ensure-BackendDeps -Py $py
    Ensure-FrontendDeps
    Write-Ok "依赖准备完成。可执行 .\start.ps1 start 启动。"
}

# ── 入口 ────────────────────────────────────────────────────
try {
    switch ($Action) {
        'start'   { Invoke-Start }
        'stop'    { Invoke-Stop }
        'restart' { Invoke-Stop; Write-Host ''; Invoke-Start }
        'status'  { Invoke-Status }
        'logs'    { Invoke-Logs }
        'setup'   { Invoke-Setup }
    }
} catch {
    Write-Err $_.Exception.Message
    exit 1
}
