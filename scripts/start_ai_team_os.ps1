# AI Team OS Control Center 一键启动（010 四十六/四十七）
# 用法：右键 → 使用 PowerShell 运行；或 powershell -ExecutionPolicy Bypass -File scripts/start_ai_team_os.ps1
# 仅监听 127.0.0.1；不写系统级配置；无需管理员权限。

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
Write-Host "Demo Mode 无需 API Key；真实模型可在网页 Settings -> Connections 配置。"
Write-Host ""

# 后端（FastAPI）
$Backend = Start-Process -FilePath (Join-Path $Root ".venv\Scripts\python.exe") `
    -ArgumentList "-m", "uvicorn", "app.api.server:app", "--host", "127.0.0.1", "--port", "8000" `
    -WorkingDirectory $Root -PassThru -WindowStyle Hidden

Start-Sleep -Seconds 2

# 前端（Vite dev server）
$Frontend = Start-Process -FilePath "npm" `
    -ArgumentList "run", "dev", "--", "--host", "127.0.0.1" `
    -WorkingDirectory (Join-Path $Root "web") -PassThru -WindowStyle Hidden

Start-Sleep -Seconds 4
Start-Process "http://127.0.0.1:5173"

Write-Host "已启动。关闭本窗口不停止服务；停止方式：" -ForegroundColor Yellow
Write-Host "  Stop-Process -Id $($Backend.Id),$($Frontend.Id)"
Write-Host "按任意键退出脚本（服务保持运行）..."
[void][Console]::ReadKey($true)
