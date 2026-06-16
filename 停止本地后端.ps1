$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$PidFile = Join-Path $Root "backend\uvicorn.pid"

if (!(Test-Path $PidFile)) {
  Write-Host "No backend PID file found." -ForegroundColor Yellow
  exit 0
}

$BackendPid = [int](Get-Content -Path $PidFile -Raw)
$process = Get-Process -Id $BackendPid -ErrorAction SilentlyContinue
if ($null -eq $process) {
  Remove-Item -LiteralPath $PidFile -Force
  Write-Host "Backend process is not running. PID file removed." -ForegroundColor Yellow
  exit 0
}

Stop-Process -Id $BackendPid -Force
Remove-Item -LiteralPath $PidFile -Force
Write-Host "Backend stopped. PID: $BackendPid" -ForegroundColor Green
