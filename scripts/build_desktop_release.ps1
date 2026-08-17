$ErrorActionPreference = "Stop"
$repo = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$targetTriple = "x86_64-pc-windows-msvc"
$binaryDir = Join-Path $repo "src-tauri\binaries"
$releaseDir = Join-Path $repo "artifacts\release"
New-Item -ItemType Directory -Force -Path $binaryDir, $releaseDir | Out-Null

Push-Location $repo
try {
  & "$repo\.venv\Scripts\python.exe" -m PyInstaller `
    --noconfirm --clean --windowed --onefile `
    --name ai-team-os-sidecar `
    --collect-all langgraph `
    --collect-all langgraph_checkpoint_sqlite `
    --add-data "app\tools\fixtures;app\tools\fixtures" `
    --hidden-import app.api.server `
    app\desktop_sidecar.py
  if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }
  $builtSidecar = Join-Path $repo "dist\ai-team-os-sidecar.exe"
  $bundledSidecar = Join-Path $binaryDir "ai-team-os-sidecar-$targetTriple.exe"
  & (Join-Path $repo "scripts\atomic_deploy_sidecar.ps1") `
    -Source $builtSidecar `
    -Destination $bundledSidecar
  if ($LASTEXITCODE -ne 0) { throw "Sidecar deployment failed" }

  Push-Location (Join-Path $repo "web")
  try { npm run build } finally { Pop-Location }
  if ($LASTEXITCODE -ne 0) { throw "React production build failed" }

  $env:Path = "$env:USERPROFILE\.cargo\bin;$env:Path"
  $portableRoot = Join-Path $env:LOCALAPPDATA "AI-Team-OS-BuildTools"
  $llvmRoot = Get-ChildItem $portableRoot -Directory -Filter "llvm-mingw-*-x86_64" `
    -ErrorAction SilentlyContinue | Sort-Object Name -Descending | Select-Object -First 1
  $sdkRoot = Join-Path $portableRoot "xwin-sdk"
  if (-not (Get-Command link.exe -ErrorAction SilentlyContinue) -and $llvmRoot -and (Test-Path $sdkRoot)) {
    $llvmBin = Join-Path $llvmRoot.FullName "bin"
    $env:AI_TEAM_OS_LLVM_BIN = $llvmBin
    $clangDriver = Join-Path $repo "scripts\clang-cl-portable.cmd"
    $env:Path = "$llvmBin;$env:Path"
    $env:CARGO_TARGET_X86_64_PC_WINDOWS_MSVC_LINKER = Join-Path $llvmBin "lld-link.exe"
    $env:CC_x86_64_pc_windows_msvc = $clangDriver
    $env:CXX_x86_64_pc_windows_msvc = $clangDriver
    $env:CC = $clangDriver
    $env:CXX = $clangDriver
    $env:RC_x86_64_pc_windows_msvc = Join-Path $llvmBin "llvm-rc.exe"
    $env:RC = $env:RC_x86_64_pc_windows_msvc
    $env:LIB = "$(Join-Path $sdkRoot 'crt\lib\x64');$(Join-Path $sdkRoot 'sdk\lib\ucrt\x64');$(Join-Path $sdkRoot 'sdk\lib\um\x64')"
    $env:INCLUDE = "$(Join-Path $sdkRoot 'crt\include');$(Join-Path $sdkRoot 'sdk\include\ucrt');$(Join-Path $sdkRoot 'sdk\include\shared');$(Join-Path $sdkRoot 'sdk\include\um');$(Join-Path $sdkRoot 'sdk\include\winrt')"
  }
  & "$repo\web\node_modules\.bin\tauri.cmd" build --config src-tauri\tauri.conf.json
  if ($LASTEXITCODE -ne 0) { throw "Tauri build failed" }
  $installer = Get-ChildItem "$repo\src-tauri\target\release\bundle\nsis\*.exe" |
    Sort-Object LastWriteTime -Descending | Select-Object -First 1
  if (-not $installer) { throw "NSIS installer not found" }
  $releaseInstaller = Join-Path $releaseDir "AI-Team-OS-x64-Setup.exe"
  Copy-Item -Force $installer.FullName $releaseInstaller
  Copy-Item -Force (Join-Path $repo "docs\releases\RELEASE_NOTES_M6P2.md") `
    (Join-Path $releaseDir "RELEASE_NOTES.md")
  $hash = Get-FileHash $releaseInstaller -Algorithm SHA256
  "$($hash.Hash)  AI-Team-OS-x64-Setup.exe" | Set-Content `
    (Join-Path $releaseDir "SHA256SUMS.txt") -Encoding ascii
  $hash
} finally {
  Pop-Location
}
