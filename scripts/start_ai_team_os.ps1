# AI Team OS Control Center 一键启动（010 四十六/四十七；010-B 三：健康等待/失败提示）
# 用法：右键 → 使用 PowerShell 运行；或 powershell -ExecutionPolicy Bypass -File scripts/start_ai_team_os.ps1
# 仅监听 127.0.0.1；不写系统级配置；无需管理员权限。
# 注意：本文件必须为 UTF-8 with BOM（PowerShell 5.1 按 ANSI 解析无 BOM UTF-8 会乱码）。

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

# Demo Mode 可无 Key 运行；沙箱项目根可选（示例项目 fixtures/sample-python）
if (-not $env:AI_TEAM_ALLOWED_READ_ROOTS) {
    $env:AI_TEAM_ALLOWED_READ_ROOTS = Join-Path $Root "fixtures"
}

Write-Host "== AI Team OS Control Center ==" -ForegroundColor Cyan
Write-Host "Backend : http://127.0.0.1:8000"
Write-Host "Frontend: http://127.0.0.1:5173"
Write-Host "Demo Mode 无需 API Key；真实模型可在网页 Settings - Connections 配置。"
Write-Host ""

# 010-B 三.1：检查 Python 环境
$Python = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    Write-Host "[错误] 未找到 $Python" -ForegroundColor Red
    Write-Host "请先创建虚拟环境：python -m venv .venv；然后 .venv\Scripts\pip install -r requirements.txt" -ForegroundColor Yellow
    exit 1
}

# 后端（FastAPI）
$Backend = Start-Process -FilePath $Python `
    -ArgumentList "-m", "app.api.server", "--host", "127.0.0.1", "--port", "8000" `
    -WorkingDirectory $Root -PassThru -WindowStyle Hidden

# 前端（Vite dev server；npm.cmd 需经 cmd 包装，Start-Process 直启 npm 会静默失败）
$Frontend = Start-Process -FilePath "cmd.exe" `
    -ArgumentList "/c", "npm run dev -- --host 127.0.0.1" `
    -WorkingDirectory (Join-Path $Root "web") -PassThru -WindowStyle Hidden

# 010-B 三.4：等待服务健康（最多 ~30s）
function Wait-Health($Url, $Name) {
    for ($i = 0; $i -lt 30; $i++) {
        Start-Sleep -Seconds 1
        try {
            $r = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 2
            if ($r.StatusCode -ge 200 -and $r.StatusCode -lt 500) {
                Write-Host "[OK] $Name 就绪：$Url" -ForegroundColor Green
                return $true
            }
        } catch {
            # 未就绪，继续等待
        }
    }
    Write-Host "[错误] $Name 启动超时：$Url" -ForegroundColor Red
    return $false
}

$BackendOk = Wait-Health "http://127.0.0.1:8000/tasks" "Backend"
$FrontendOk = Wait-Health "http://127.0.0.1:5173" "Frontend"

# 010-B 三.6：启动失败时显示可理解错误
if (-not ($BackendOk -and $FrontendOk)) {
    Write-Host "" -ForegroundColor Red
    Write-Host "启动失败。请检查：" -ForegroundColor Red
    Write-Host "  - 端口 8000/5173 是否被占用（netstat -ano | findstr 8000）" -ForegroundColor Yellow
    Write-Host "  - 依赖是否完整：cd web 后执行 npm install" -ForegroundColor Yellow
    exit 1
}

# 010-B 三.5：自动打开默认浏览器
Start-Process "http://127.0.0.1:5173"

Write-Host "已启动。关闭本窗口不停止服务；停止方式：" -ForegroundColor Yellow
Write-Host "  Stop-Process -Id $($Backend.Id),$($Frontend.Id)"
if ([Console]::IsInputRedirected) {
    Start-Sleep -Seconds 2   # 非交互/后台运行：跳过按键等待
} else {
    Write-Host "按任意键退出脚本（服务保持运行）..."
    [void][Console]::ReadKey($true)
}
