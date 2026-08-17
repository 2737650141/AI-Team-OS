param(
  [Parameter(Mandatory = $true)][string]$Source,
  [Parameter(Mandatory = $true)][string]$Destination,
  [switch]$Json,
  [ValidateSet("", "TEMP_COPY", "TEMP_SHA", "POST_VERIFY")][string]$SimulateFailure = ""
)

$ErrorActionPreference = "Stop"
$minimumExecutableSize = 1024 * 1024

function Write-DeployResult([object]$Result, [int]$ExitCode) {
  if ($Json) {
    $Result | ConvertTo-Json -Compress
  } elseif ($ExitCode -eq 0) {
    $Result | Format-List
  } else {
    Write-Error "$($Result.deployment_status): $($Result.message)"
  }
  exit $ExitCode
}

function Fail-Deploy([string]$Code, [string]$Message, [string]$TempPath = $null) {
  if ($TempPath -and (Test-Path -LiteralPath $TempPath)) {
    Remove-Item -LiteralPath $TempPath -Force -ErrorAction SilentlyContinue
  }
  Write-DeployResult ([ordered]@{
    deployment_status = $Code
    message = $Message
    source = $Source
    destination = $Destination
  }) 1
}

function Get-Sha256([string]$Path) {
  (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToUpperInvariant()
}

function Assert-PeExecutable([string]$Path, [string]$Label, [string]$TempPath = $null) {
  try {
    $stream = [System.IO.File]::Open($Path, [System.IO.FileMode]::Open, [System.IO.FileAccess]::Read, [System.IO.FileShare]::Read)
    try {
      $buffer = New-Object byte[] 2
      $read = $stream.Read($buffer, 0, 2)
      if ($read -ne 2 -or $buffer[0] -ne 0x4D -or $buffer[1] -ne 0x5A) {
        Fail-Deploy "INVALID_PE" "$Label is not a Windows PE executable" $TempPath
      }
    } finally {
      $stream.Dispose()
    }
  } catch {
    if ($_.Exception.Message -like "*Windows PE executable*") { throw }
    Fail-Deploy "PE_READ_FAILED" "$Label PE sanity check failed: $($_.Exception.Message)" $TempPath
  }
}

$sourceItem = Get-Item -LiteralPath $Source -ErrorAction SilentlyContinue
if (-not $sourceItem) { Fail-Deploy "SOURCE_MISSING" "source sidecar does not exist" }
if ($sourceItem.PSIsContainer) { Fail-Deploy "SOURCE_INVALID" "source sidecar is not a regular file" }
if ($sourceItem.Length -le 0 -or $sourceItem.Length -lt $minimumExecutableSize) {
  Fail-Deploy "SOURCE_INVALID" "source sidecar is empty or too small"
}
try {
  $sourceProbe = [System.IO.File]::Open($sourceItem.FullName, [System.IO.FileMode]::Open, [System.IO.FileAccess]::Read, [System.IO.FileShare]::Read)
  $sourceProbe.Dispose()
} catch {
  Fail-Deploy "SOURCE_UNREADABLE" $_.Exception.Message
}
$sourceSha = Get-Sha256 $sourceItem.FullName
Assert-PeExecutable $sourceItem.FullName "source"

$destinationPath = [System.IO.Path]::GetFullPath($Destination)
$destinationDir = [System.IO.Path]::GetDirectoryName($destinationPath)
if (-not $destinationDir) { Fail-Deploy "DESTINATION_INVALID" "destination directory cannot be resolved" }
New-Item -ItemType Directory -Force -Path $destinationDir | Out-Null

$tempPath = Join-Path $destinationDir ([System.IO.Path]::GetFileName($destinationPath) + ".new")
$backupPath = Join-Path $destinationDir ([System.IO.Path]::GetFileName($destinationPath) + ".bak")
Remove-Item -LiteralPath $tempPath -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath $backupPath -Force -ErrorAction SilentlyContinue

try {
  Copy-Item -LiteralPath $sourceItem.FullName -Destination $tempPath -Force
  if ($SimulateFailure -eq "TEMP_COPY") { throw "simulated temporary copy failure" }
} catch {
  Fail-Deploy "TEMP_COPY_FAILED" $_.Exception.Message $tempPath
}

$tempItem = Get-Item -LiteralPath $tempPath -ErrorAction SilentlyContinue
if (-not $tempItem) { Fail-Deploy "TEMP_COPY_FAILED" "temporary sidecar was not created" $tempPath }
if ($tempItem.Length -ne $sourceItem.Length) {
  Fail-Deploy "TEMP_SIZE_MISMATCH" "temporary size does not match source" $tempPath
}
if ($SimulateFailure -eq "TEMP_SHA") {
  Add-Content -LiteralPath $tempPath -Value "corrupt" -Encoding ascii
  $tempItem = Get-Item -LiteralPath $tempPath
}
$tempSha = Get-Sha256 $tempPath
if ($tempSha -ne $sourceSha) {
  Fail-Deploy "TEMP_SHA_MISMATCH" "temporary SHA256 does not match source" $tempPath
}
Assert-PeExecutable $tempPath "temporary" $tempPath

$hadDestination = Test-Path -LiteralPath $destinationPath
try {
  if ($hadDestination) {
    [System.IO.File]::Replace($tempPath, $destinationPath, $backupPath, $true)
  } else {
    [System.IO.File]::Move($tempPath, $destinationPath)
  }
} catch {
  Fail-Deploy "FILE_LOCKED" $_.Exception.Message $tempPath
}

try {
  $installedItem = Get-Item -LiteralPath $destinationPath -ErrorAction Stop
  $installedSha = Get-Sha256 $destinationPath
  if ($SimulateFailure -eq "POST_VERIFY") { throw "simulated post-verify failure" }
  Assert-PeExecutable $destinationPath "installed"
  if ($installedItem.Length -ne $sourceItem.Length -or $installedSha -ne $sourceSha) {
    throw "installed sidecar verification mismatch"
  }
} catch {
  if ($hadDestination -and (Test-Path -LiteralPath $backupPath)) {
    try {
      [System.IO.File]::Replace($backupPath, $destinationPath, $null, $true)
    } catch {
      Move-Item -LiteralPath $backupPath -Destination $destinationPath -Force -ErrorAction SilentlyContinue
    }
  } elseif (Test-Path -LiteralPath $destinationPath) {
    Remove-Item -LiteralPath $destinationPath -Force -ErrorAction SilentlyContinue
  }
  Fail-Deploy "POST_VERIFY_FAILED" $_.Exception.Message
}

Remove-Item -LiteralPath $backupPath -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath $tempPath -Force -ErrorAction SilentlyContinue

Write-DeployResult ([ordered]@{
  deployment_status = "SUCCESS"
  source = $sourceItem.FullName
  destination = $destinationPath
  source_size = $sourceItem.Length
  installed_size = (Get-Item -LiteralPath $destinationPath).Length
  source_sha256 = $sourceSha
  installed_sha256 = Get-Sha256 $destinationPath
}) 0
